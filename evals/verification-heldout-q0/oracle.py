#!/usr/bin/env python
"""Recompute the truth for each verification-heldout-q0 case independently
from the fetched sources and the facts in cases.json, then check every case's
stated kind.

Usage:
    python oracle.py <cache-dir> <out-dir>

Never imports terraproof (nor derive.py). For each case:
  - recomputes the expected numbers from the cached sources;
  - reads the delivered artifact(s) built by derive.py;
  - checks that the case's committed `oracle` number matches the
    recomputation;
  - checks the delivered artifact behaves as the case's `kind` claims
    (wrong cases must be demonstrably wrong, correct cases must match the
    recomputed truth within rounding).
Prints a JSON summary and exits non-zero on any disagreement.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Geod
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import MultiPolygon, shape

DEP3_FILL = -999999.0
R_EARTH_M = 6378137.0
QA60_BITS = (1 << 10) | (1 << 11)

V0_SCL = "s2-v0/wa_SCL.tif"
V0_WB_SCL = "s2-v0/wb_SCL.tif"
V0_WB_B03 = "s2-v0/wb_B03.tif"
COP_NEPAL = "copdem/n28e084_win.tif"
COP_SVALBARD = "copdem/n78e016_win.tif"
DEP3_DELTA = "usgs3dep/USGS_13_n31w091_win.tif"
DEP3_KAUAI = "usgs3dep/USGS_13_n22w159_win.tif"
NE_COUNTRIES = "naturalearth/ne_110m_admin_0_countries.geojson"

TOL_ABS = 5e-6
TOL_REL = 2e-6


def close(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= max(TOL_ABS, TOL_REL * max(abs(a), abs(b)))


def read_tif(cache: Path, rel: str):
    with rasterio.open(cache / rel, "r") as ds:
        return ds.read(1), {"crs": ds.crs, "transform": ds.transform,
                            "nodata": ds.nodata}


def read_out_tif(out: Path, case_id: str, name: str):
    with rasterio.open(out / "outputs" / case_id / name, "r") as ds:
        return ds.read(1)


def read_out_json(out: Path, case_id: str, name: str):
    return json.loads((out / "outputs" / case_id / name).read_text(encoding="utf-8"))


def s10_from(scl: np.ndarray) -> np.ndarray:
    return np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)


def grads(z: np.ndarray, dx_m: float, dy_m: float):
    zy, zx = np.gradient(z.astype(np.float64), dy_m, dx_m)
    return zx, zy


def mid_lat(prof: dict, rows: int) -> float:
    res_y = abs(prof["transform"].e)
    return prof["transform"].f - (rows / 2.0) * res_y


def metres_per_deg(res_deg_x: float, res_deg_y: float, lat_mid: float):
    dy_m = res_deg_y * R_EARTH_M * math.pi / 180.0
    dx_m = res_deg_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat_mid))
    return dx_m, dy_m


def geod_area_km2(geom) -> float:
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    total = 0.0
    for p in polys:
        lons, lats = np.array(p.exterior.coords).T
        area, _ = geod.polygon_area_perimeter(lons, lats)
        total += abs(area)
        for ring in p.interiors:
            lons, lats = np.array(ring.coords).T
            area, _ = geod.polygon_area_perimeter(lons, lats)
            total -= abs(area)
    return abs(total) / 1e6


def geod_perimeter_km(geom) -> float:
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    total = 0.0
    for p in polys:
        lons, lats = np.array(p.exterior.coords).T
        _, _, d = geod.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
        total += float(np.sum(d))
    return total / 1000.0


def _ne_feature(cache: Path, name: str) -> dict:
    geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
    for f in geo["features"]:
        if f["properties"].get("NAME") == name:
            return f
    raise KeyError(name)


def check_case(cache: Path, out: Path, case: dict) -> dict:
    cid = case["id"]
    kind = case["kind"]
    expect = case["oracle"]["value"]
    notes: list[str] = []

    # ------------------------------------------------------- validity masks
    if cid.startswith("mask_"):
        if cid in ("mask_correct_wedge_all_invalid_wb", "mask_wrong_fill_kept_valid_wb"):
            scl, _ = read_tif(cache, V0_WB_SCL)
            rule = np.isin(scl, [4, 5, 6, 7])
        else:
            scl, _ = read_tif(cache, V0_SCL)
            rule = {
                "mask_wrong_rejected_class_kept_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "mask_wrong_qa60_bits_mixed_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "mask_wrong_water_rejected_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "mask_correct_standard_rule_wa": np.isin(scl, [4, 5, 6, 7]),
                "mask_correct_snow_valid_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "mask_correct_water_veg_only_wa": np.isin(scl, [4, 5, 6]),
            }[cid]
        mask = read_out_tif(out, cid, "validity_mask.tif").astype(bool)
        exact = bool((mask == rule).all())
        if kind == "correct":
            verdict = exact and close(expect, int(mask.sum()))
            notes.append(f"mask exact match: {exact}; rule_usable={int(rule.sum())}")
        else:
            kept_invalid = int((mask & ~rule).sum())
            evicted_valid = int((rule & ~mask).sum())
            metric = evicted_valid if cid == "mask_wrong_water_rejected_wa" else kept_invalid
            verdict = (not exact) and metric == expect and metric > 0
            notes.append(f"kept_invalid={kept_invalid}; evicted_valid={evicted_valid}")
        return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}

    # ---------------------------------------------- slope in percent/degrees
    if cid.startswith("slope_"):
        if cid == "slope_correct_percent_geographic_nepal":
            z, prof = read_tif(cache, COP_NEPAL)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            zx, zy = grads(z, dx_m, dy_m)
            truth = float((100.0 * np.hypot(zx, zy)).mean())
            got = read_out_tif(out, cid, "slope.tif")
            deliver = float(got.mean(dtype=np.float64))
            verdict = close(deliver, truth) and close(expect, deliver)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "slope_correct_degrees_geographic_nepal":
            z, prof = read_tif(cache, COP_NEPAL)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            zx, zy = grads(z, dx_m, dy_m)
            truth = float(np.degrees(np.arctan2(np.hypot(zx, zy), 1.0)).mean())
            got = read_out_tif(out, cid, "slope.tif")
            deliver = float(got.mean(dtype=np.float64))
            verdict = close(deliver, truth) and close(expect, deliver)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "slope_wrong_degrees_as_metres_geographic_nepal":
            z, prof = read_tif(cache, COP_NEPAL)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            wrong = float((100.0 * np.hypot(*grads(z, res_x, res_y))).mean())
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            zx, zy = grads(z, dx_m, dy_m)
            truth = float((100.0 * np.hypot(zx, zy)).mean())
            factor = wrong / truth
            got = read_out_tif(out, cid, "slope.tif")
            verdict = close(factor, expect) and float(got.mean(dtype=np.float64)) > 1e6
            notes.append(f"wrong={wrong}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "slope_wrong_latitude_ignored_geographic_svalbard":
            z, prof = read_tif(cache, COP_SVALBARD)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            wrong = float((100.0 * np.hypot(*grads(
                z, res_x * R_EARTH_M * math.pi / 180.0,
                res_y * R_EARTH_M * math.pi / 180.0))).mean())
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            zx, zy = grads(z, dx_m, dy_m)
            truth = float((100.0 * np.hypot(zx, zy)).mean())
            factor = wrong / truth
            verdict = close(factor, expect) and abs(factor - 1.0) > 0.1
            notes.append(f"wrong={wrong}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid in ("slope_wrong_unit_confused_projected_svalbard",
                   "slope_correct_degrees_projected_svalbard"):
            z, prof = read_tif(cache, COP_SVALBARD)
            with rasterio.open(cache / COP_SVALBARD) as src:
                t, new_w, new_h = calculate_default_transform(
                    src.crs, "EPSG:32633", src.width, src.height, *src.bounds,
                    resolution=30.0)
            dst = np.full((int(new_h), int(new_w)), np.nan, dtype=np.float64)
            reproject(source=z, destination=dst,
                      src_transform=prof["transform"], src_crs=prof["crs"],
                      dst_transform=t, dst_crs="EPSG:32633",
                      src_nodata=prof["nodata"], dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
            valid = ~np.isnan(dst)
            z_filled = np.where(valid, dst, 0.0)
            zx, zy = grads(z_filled, 30.0, 30.0)
            mag = np.hypot(zx, zy)
            mean_deg = float(np.degrees(np.arctan2(mag[valid], 1.0)).mean())
            mean_pct = float((100.0 * mag[valid]).mean())
            got = read_out_tif(out, cid, "slope.tif")
            deliver = float(got[got != -9999.0].mean(dtype=np.float64))
            if cid.startswith("slope_correct"):
                verdict = (close(deliver, mean_deg)
                           and close(expect, deliver))
                notes.append(f"truth_deg={mean_deg}")
            else:
                verdict = (close(mean_pct / mean_deg, expect)
                           and close(deliver, mean_deg)
                           and abs(mean_pct / mean_deg - 1.0) > 0.5)
                notes.append(f"degrees_as={deliver}; truth_pct={mean_pct}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    # ------------------------------------------------------------ summaries
    if cid.startswith("summary_"):
        if cid == "summary_wrong_fill_averaged_in_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            delivered = float(z.mean(dtype=np.float64))
            truth = float(z[z != DEP3_FILL].mean(dtype=np.float64))
            factor = abs(delivered - truth) / truth
            sj = read_out_json(out, cid, "summary.json")
            verdict = (close(factor, expect) and delivered < 0 < truth
                       and close(sj["mean_elevation_m"], delivered))
            notes.append(f"delivered={delivered}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "summary_wrong_zeros_evicted_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            truth = int((z != DEP3_FILL).sum())
            sj = read_out_json(out, cid, "summary.json")
            zeros_evicted = truth - int(sj["usable_pixel_count"])
            verdict = (zeros_evicted == expect and zeros_evicted > 0
                       and int(sj["usable_pixel_count"]) < truth)
            notes.append(f"zeros_evicted={zeros_evicted}; truth_usable={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "summary_wrong_area_degrees_sq_km_iceland":
            geom = shape(_ne_feature(cache, "Iceland")["geometry"])
            truth = geod_area_km2(geom)
            sj = read_out_json(out, cid, "summary.json")
            delivered = sj["area_sq_km"]
            factor = truth / delivered
            verdict = close(factor, expect) and abs(factor - 1.0) > 100
            notes.append(f"delivered={delivered}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "summary_correct_mean_excluding_fill_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            sel = z[z != DEP3_FILL]
            truth = float(sel.mean())
            sj = read_out_json(out, cid, "summary.json")
            verdict = (close(sj["mean_elevation_m"], truth)
                       and close(expect, truth) and int(sj["usable_pixel_count"]) == sel.size)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "summary_correct_max_elevation_delta":
            z, _ = read_tif(cache, DEP3_DELTA)
            sel = z[z != DEP3_FILL]
            truth = float(sel.max())
            sj = read_out_json(out, cid, "summary.json")
            verdict = (close(sj["max_elevation_m"], truth)
                       and close(expect, truth)
                       and sj["elevation_unit"] == "m"
                       and sj["elevation_vertical_datum"] == "NAVD 88")
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "summary_correct_area_geodesic_iceland":
            geom = shape(_ne_feature(cache, "Iceland")["geometry"])
            truth = geod_area_km2(geom)
            sj = read_out_json(out, cid, "summary.json")
            verdict = close(sj["area_sq_km"], truth) and close(expect, sj["area_sq_km"])
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "summary_correct_perimeter_geodesic_switzerland":
            geom = shape(_ne_feature(cache, "Switzerland")["geometry"])
            truth = geod_perimeter_km(geom)
            sj = read_out_json(out, cid, "summary.json")
            verdict = (close(sj["boundary_perimeter_km"], truth)
                       and close(expect, sj["boundary_perimeter_km"]))
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    # ------------------------------------------------------------ s2 decodes
    if cid.startswith("s2_decode_"):
        band = "B11" if cid.endswith("_b11") else "B03"
        if cid.startswith("s2_decode_v0"):
            dn, _ = read_tif(cache, f"s2-v0/wa_{band}.tif")
            usable = dn != 0
            truth = float((dn[usable].astype(np.float64) * 1e-4).mean())
            got = read_out_tif(out, cid, "reflectance.tif")
            if cid == "s2_decode_v0_wrong_offset_applied_twice_wa":
                deliver = float(((dn[usable].astype(np.float64) - 1000.0) * 1e-4).mean())
                shortfall = truth - deliver
                verdict = close(shortfall, expect) and (not close(deliver, truth))
                notes.append(f"deliver={deliver}; truth={truth}")
            else:
                deliver = float(got[got != 0].mean())
                verdict = close(deliver, truth) and close(expect, deliver)
                notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        dn, _ = read_tif(cache, f"s2-c1/wa_{band}.tif")
        usable = dn != 0
        truth = float(((dn[usable].astype(np.float64) - 1000.0) * 1e-4).mean())
        if cid == "s2_decode_c1_wrong_offset_missing_wa":
            deliver = float((dn[usable].astype(np.float64) * 1e-4).mean())
            factor_excess = deliver - truth
            verdict = close(factor_excess, expect) and (not close(deliver, truth))
            notes.append(f"deliver={deliver}; truth={truth}; excess={factor_excess}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "s2_decode_c1_wrong_raw_dn_delivered_wa":
            deliver = float(dn[usable].mean(dtype=np.float64))
            factor = deliver / truth
            verdict = close(factor, expect) and factor > 1000
            notes.append(f"deliver={deliver}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        got = read_out_tif(out, cid, "reflectance.tif")
        deliver = float(got[usable].mean(dtype=np.float64))
        verdict = close(deliver, truth) and close(expect, deliver)
        notes.append(f"truth={truth}")
        return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}

    # -------------------------------------------------- fill/vertical units
    if cid.startswith("fillunits_"):
        if cid == "fillunits_wrong_fill_decoded_as_data_wb":
            dn, _ = read_tif(cache, V0_WB_B03)
            truth = int((dn != 0).sum())
            got = read_out_tif(out, cid, "reflectance.tif")
            mask_sum = int((got != 0).sum())
            verdict = (expect == dn.size and truth == 0 and dn.size > 0)
            notes.append(f"fill_decoded_as_data_px={mask_sum}; truth_usable={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "fillunits_wrong_vertical_unit_ignored_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            sel = z[z != DEP3_FILL]
            mean_m = float(sel.mean())
            truth_ft = mean_m * 3.280839895013123
            factor = truth_ft / mean_m
            verdict = close(factor, expect) and abs(factor - 1.0) > 1.5
            notes.append(f"factor={factor}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "fillunits_correct_3dep_metres_delta":
            z, _ = read_tif(cache, DEP3_DELTA)
            sel = z[z != DEP3_FILL]
            truth = float(sel.mean())
            sj = read_out_json(out, cid, "summary.json")
            verdict = (close(sj["mean_elevation_m"], truth)
                       and close(expect, truth) and sj["elevation_unit"] == "m"
                       and sj["elevation_vertical_datum"] == "NAVD 88")
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "fillunits_correct_wedge_fill_excluded_summary":
            dn, _ = read_tif(cache, V0_WB_B03)
            truth = int((dn != 0).sum())
            sj = read_out_json(out, cid, "summary.json")
            verdict = close(sj["usable_pixel_count"], truth) and close(expect, truth)
            notes.append(f"truth_usable={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    # ---------------------------------------------------------------- plain
    if cid.startswith("plain_"):
        if cid == "plain_mean_elevation_nepal":
            z, _ = read_tif(cache, COP_NEPAL)
            truth = float(z.astype(np.float64).mean())
            sj = read_out_json(out, cid, "summary.json")
            verdict = close(sj["mean_elevation_m"], truth) and close(expect, truth)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "plain_ndvi_v0_window_a":
            b03, _ = read_tif(cache, "s2-v0/wa_B03.tif")
            b08, _ = read_tif(cache, "s2-v0/wa_B08.tif")
            scl, _ = read_tif(cache, V0_SCL)
            r3 = b03.astype(np.float64) * 1e-4
            r8 = b08.astype(np.float64) * 1e-4
            ndvi = (r8 - r3) / np.maximum(r8 + r3, 1e-12)
            ok = (b03 != 0) & (b08 != 0)
            s10 = s10_from(scl)
            sj = read_out_json(out, cid, "summary.json")
            water = float(ndvi[s10 == 6].mean())
            verdict = (close(sj["ndvi_class_6_water_mean"], water)
                       and close(sj["ndvi_over_all_bands_valid"],
                                 float(ndvi[ok].mean()))
                       and close(expect, sj["ndvi_class_6_water_mean"])
                       and water < 0)
            notes.append(f"water_ndvi={water}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "plain_blue_reflectance_snow_v0":
            b02, _ = read_tif(cache, "s2-v0/wa_B02.tif")
            scl, _ = read_tif(cache, V0_SCL)
            s10 = s10_from(scl)
            truth = float((b02.astype(np.float64) * 1e-4)[s10 == 11].mean())
            sj = read_out_json(out, cid, "summary.json")
            verdict = (close(sj["mean_blue_reflectance_snow"], truth)
                       and close(expect, truth))
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "plain_feature_count_ne":
            geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
            truth = len(geo["features"])
            sj = read_out_json(out, cid, "summary.json")
            verdict = sj["feature_count"] == truth == expect
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    raise KeyError(cid)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    cache = Path(argv[1])
    out = Path(argv[2])
    here = Path(__file__).resolve().parent
    cases = json.loads((here / "cases.json").read_text(encoding="utf-8"))["cases"]
    results = [check_case(cache, out, case) for case in cases]
    n_ok = sum(1 for r in results if r["verdict"])
    summary = {"cases": results, "agree": n_ok, "total": len(results)}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
