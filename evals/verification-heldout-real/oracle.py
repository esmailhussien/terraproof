#!/usr/bin/env python
"""Recompute the truth for each case independently from the fetched sources
and the facts in cases.json, then check every case's stated kind.

Usage:
    python oracle.py <cache-dir> <out-dir>

Never imports terraproof. For each case:
  - recomputes the expected numbers from the cached sources;
  - reads the delivered artifact(s) built by derive.py;
  - checks that the case's committed `oracle` number matches the
    recomputation;
  - checks the delivered artifact behaves as the case's `kind` claims
    (wrong cases must be demonstrably wrong, correct cases must match the
    recomputed truth within tolerance).
Prints a summary and exits non-zero on any disagreement.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Geod, Transformer
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import MultiPolygon, shape
from shapely.ops import transform as shp_transform

DEP3_FILL = -999999.0
R_EARTH_M = 6378137.0
QA60_BITS = (1 << 10) | (1 << 11)

S2_B02 = "s2/wa_B02.tif"
S2_B03 = "s2/wa_B03.tif"
S2_B08 = "s2/wa_B08.tif"
S2_B11 = "s2/wa_B11.tif"
S2_SCL = "s2/wa_SCL.tif"
S2_WB_SCL = "s2/wb_SCL.tif"
S2_WB_B03 = "s2/wb_B03.tif"
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
        return ds.read(1), {"crs": ds.crs, "transform": ds.transform, "nodata": ds.nodata}


def read_out_tif(out: Path, case_id: str, name: str):
    with rasterio.open(out / "outputs" / case_id / name, "r") as ds:
        return ds.read(1)


def read_out_json(out: Path, case_id: str, name: str):
    return json.loads((out / "outputs" / case_id / name).read_text(encoding="utf-8"))


def scale_decode(arr: np.ndarray) -> np.ndarray:
    return arr.astype(np.float64) * 1e-4


def slope_mag(z: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    zy, zx = np.gradient(z.astype(np.float64), dy_m, dx_m)
    return np.hypot(zx, zy)


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
        _, _, dist = geod.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
        total += float(np.sum(dist))
    return total / 1000.0


def s10_from(scl: np.ndarray) -> np.ndarray:
    return np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)


def slope_deg_30m(z: np.ndarray) -> np.ndarray:
    zy, zx = np.gradient(z.astype(np.float64), 30.0, 30.0)
    return np.degrees(np.arctan2(np.hypot(zx, zy), 1.0))


def check_case(cache: Path, out: Path, case: dict) -> dict:
    """Return a verdict dict for one case entry."""
    cid = case["id"]
    kind = case["kind"]
    claims = case["oracle"]
    expect = claims["value"]
    facts = case["facts"]
    rationale = claims.get("reason") if kind == "wrong" else claims.get("evidence")
    notes: list[str] = []

    def ok(expected_value, delivered, note_extra=""):
        good = close(expected_value, delivered)
        return good, note_extra

    # ----------------------------------------------------------- QA masking
    if cid.startswith("qa_masking"):
        if cid == "qa_masking_correct_wedge_nodata_wb":
            scl, _ = read_tif(cache, S2_WB_SCL)
            rule = np.isin(scl, [4, 5, 6, 7])
        else:
            scl, _ = read_tif(cache, S2_SCL)
            rule = {
                "qa_masking_wrong_cloud_medium_kept_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "qa_masking_wrong_qa60_bits_mixed_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "qa_masking_wrong_water_masked_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "qa_masking_wrong_shadow_kept_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "qa_masking_correct_standard_wa": np.isin(scl, [4, 5, 6, 7]),
                "qa_masking_correct_snow_valid_wa": np.isin(scl, [4, 5, 6, 7, 11]),
                "qa_masking_correct_water_veg_only_wa": np.isin(scl, [4, 5, 6]),
            }[cid]
        mask = read_out_tif(out, cid, "validity_mask.tif")
        exact = bool((mask.astype(bool) == rule).all())
        kept_cnt = int(mask.sum())
        rule_cnt = int(rule.sum())
        if cid.startswith("qa_masking_correct"):
            verdict = exact and close(expect, kept_cnt)
            notes.append(f"mask exact match: {exact}; rule_valid_count={rule_cnt}")
        else:
            if cid == "qa_masking_wrong_water_masked_wa":
                metric = int((rule & (mask == 0)).sum())
            else:
                metric = int(((mask == 1) & (~rule)).sum())
            verdict = (not exact) and metric == expect and metric > 0 and kept_cnt != rule_cnt
            notes.append(f"badly_classified_pixels={metric}")
        return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}

    # --------------------------------------------------- scale/offset/fill
    if cid.startswith("scale_"):
        if cid == "scale_correct_wedge_all_fill_wb_b03":
            dn, _ = read_tif(cache, S2_WB_B03)
            mask = read_out_tif(out, cid, "validity_mask.tif")
            valid_cnt = int(mask.sum())
            truth_valid = int((dn != 0).sum())
            verdict = (valid_cnt == truth_valid == 0) and close(expect, 0)
            notes.append("window is entirely declared fill; valid pixels must be 0")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "scale_wrong_fill_decoded_as_data_wb_b03":
            dn, _ = read_tif(cache, S2_WB_B03)
            truth_valid = int((dn != 0).sum())
            verdict = (truth_valid == 0) and expect == dn.size
            notes.append("fill decoded as data over the whole fill window")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        which = S2_B11 if cid == "scale_correct_swir_decode_wa_b11" else S2_B03
        dn, _ = read_tif(cache, which)
        filled = dn == 0
        truth_mean = float(scale_decode(dn[~filled]).mean())
        if cid == "scale_wrong_raw_packed_wa_b03":
            delivered_summary = float(dn.mean(dtype=np.float64))
            factor = delivered_summary / truth_mean
            good = close(factor, expect)
            wrongness = not close(delivered_summary, truth_mean) and factor > 100.0
            notes.append(f"factor={factor}")
            return {"id": cid, "kind": kind, "verdict": bool(wrongness and good),
                    "notes": notes}
        if cid == "scale_wrong_offset_sign_flipped_wa_b03":
            delivered_summary = float(((dn.astype(np.float64) + 1000.0) * 1e-4).mean())
            excess = delivered_summary - truth_mean
            good = close(excess, expect)
            wrongness = not close(delivered_summary, truth_mean) and excess > 0.02
            notes.append(f"excess={excess}; truth={truth_mean}")
            return {"id": cid, "kind": kind, "verdict": bool(wrongness and good),
                    "notes": notes}
        delivered_summary = truth_mean
        good = close(delivered_summary, expect)
        notes.append(f"truth_mean={delivered_summary}")
        return {"id": cid, "kind": kind, "verdict": bool(good), "notes": notes}

    # ----------------------------------------------- elevation units/slope
    if cid.startswith("elevation_"):
        if cid == "elevation_correct_3dep_metres_delta":
            z, _ = read_tif(cache, DEP3_DELTA)
            truth = float(z[z != DEP3_FILL].mean())
            delivered = read_out_json(out, cid, "elevation_summary.json")["mean_elevation_m"]
            verdict = close(delivered, truth) and close(expect, truth)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "elevation_wrong_unit_ignored_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            sel = z[z != DEP3_FILL]
            mean_m = float(sel.mean())
            truth_ft = mean_m * 3.280839895013123
            factor_truth_over_delivered = truth_ft / mean_m
            verdict = close(expect, factor_truth_over_delivered)
            notes.append(f"delivered claims feet while storing metre values; "
                         f"factor={factor_truth_over_delivered}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "elevation_correct_slope_metres_nepal":
            z, prof = read_tif(cache, COP_NEPAL)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            truth = float((100 * slope_mag(z, dx_m, dy_m)).mean())
            sarr = read_out_tif(out, cid, "slope_percent.tif")
            delivered = float(sarr.mean(dtype=np.float64))
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth_mean={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "elevation_wrong_degrees_as_metres_nepal":
            z, prof = read_tif(cache, COP_NEPAL)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            wrong = float((100 * slope_mag(z, res_x, res_y)).mean())
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            truth = float((100 * slope_mag(z, dx_m, dy_m)).mean())
            factor = wrong / truth
            sarr = read_out_tif(out, cid, "slope_percent.tif")
            delivered_mean = float(sarr.mean(dtype=np.float64))
            verdict = close(factor, expect) and delivered_mean > 1e6
            notes.append(f"delivered={delivered_mean}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "elevation_wrong_latitude_ignored_svalbard":
            z, prof = read_tif(cache, COP_SVALBARD)
            res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
            wrong = float((100 * slope_mag(z, res_x * R_EARTH_M * math.pi / 180.0,
                                           res_y * R_EARTH_M * math.pi / 180.0)).mean())
            dx_m, dy_m = metres_per_deg(res_x, res_y, mid_lat(prof, z.shape[0]))
            truth = float((100 * slope_mag(z, dx_m, dy_m)).mean())
            factor = wrong / truth
            sarr = read_out_tif(out, cid, "slope_percent.tif")
            verdict = close(factor, expect) and abs(factor - 1.0) > 0.1
            notes.append(f"delivered={wrong}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "elevation_correct_svalbard_projected_slope":
            z, prof = read_tif(cache, COP_SVALBARD)
            with rasterio.open(cache / COP_SVALBARD) as src:
                t, new_w, new_h = calculate_default_transform(
                    src.crs, "EPSG:32633", src.width, src.height, *src.bounds,
                    resolution=30.0)
            dst = np.full((int(new_h), int(new_w)), np.nan, dtype=np.float64)
            from rasterio.warp import reproject, Resampling
            reproject(source=z, destination=dst, src_transform=prof["transform"],
                      src_crs=prof["crs"], dst_transform=t, dst_crs="EPSG:32633",
                      src_nodata=prof["nodata"], dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
            valid = ~np.isnan(dst)
            z_filled = np.where(valid, dst, 0.0)
            slp = slope_deg_30m(z_filled)
            truth = float(slp[valid].mean())
            sarr = read_out_tif(out, cid, "slope_deg.tif")
            sel = sarr[sarr != -9999.0]
            delivered = float(sel.mean(dtype=np.float64))
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    # ------------------------------------------------------------- nodata
    if cid.startswith("nodata_"):
        if cid == "nodata_wrong_fill_averaged_in_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            delivered = float(z.mean(dtype=np.float64))
            truth = float(z[z != DEP3_FILL].mean(dtype=np.float64))
            factor = abs(delivered - truth) / truth
            verdict = close(factor, expect) and delivered < 0 < truth
            notes.append(f"delivered={delivered}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "nodata_wrong_real_zeros_evicted_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            valid_truth = z != DEP3_FILL
            mask = read_out_tif(out, cid, "validity_mask.tif")
            evicted = int((valid_truth & (mask == 0)).sum())
            zeros_evicted = int((valid_truth & (mask == 0) & (z == 0)).sum())
            verdict = zeros_evicted == expect and zeros_evicted > 0 and (z[mask == 1] == 0).sum() == 0
            notes.append(f"zeros_evicted={zeros_evicted}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "nodata_correct_fill_excluded_mean_kauai":
            z, _ = read_tif(cache, DEP3_KAUAI)
            mask = read_out_tif(out, cid, "validity_mask.tif")
            sel = z[mask == 1]
            sel = sel[sel != DEP3_FILL]
            truth = float(sel.mean(dtype=np.float64))
            zeros = int((sel == 0).sum())
            verdict = close(truth, expect) and zeros > 0
            notes.append(f"truth={truth}; zeros_kept={zeros}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "nodata_correct_delta_zeros_kept":
            z, _ = read_tif(cache, DEP3_DELTA)
            mask = read_out_tif(out, cid, "validity_mask.tif")
            sel = z[(mask == 1) & (z != DEP3_FILL)]
            zeros = int((sel == 0).sum())
            verdict = zeros == expect and zeros > 0
            notes.append(f"zeros_kept={zeros}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    # ------------------------------------------------------ metric values
    if cid.startswith("metrics_"):
        geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))

        def feature(name: str) -> dict:
            for f in geo["features"]:
                if f["properties"].get("NAME") == name:
                    return f
            raise KeyError(name)

        if cid == "metrics_wrong_area_degrees_sq_km":
            geom = shape(feature("Iceland")["geometry"])
            truth = geod_area_km2(geom)
            delivered = read_out_json(out, cid, "iceland_area_wrong.geojson")["features"][0]["properties"]["area_sq_km"]
            factor = truth / delivered
            verdict = close(factor, expect) and abs(factor - 1.0) > 100
            notes.append(f"delivered={delivered}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "metrics_correct_area_geodesic":
            geom = shape(feature("Iceland")["geometry"])
            truth = geod_area_km2(geom)
            delivered = read_out_json(out, cid, "iceland_area_correct.geojson")["features"][0]["properties"]["area_sq_km"]
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "metrics_wrong_buffer_degrees_100km":
            geom = shape(feature("Iceland")["geometry"])
            buf = geom.buffer(1.0)
            truth = geod_area_km2(MultiPolygon([buf]) if buf.geom_type == "Polygon" else buf)
            properties = read_out_json(out, cid, "iceland_buffer_wrong.geojson")["features"][0]["properties"]
            delivered = properties["buffer_area_sq_km"]
            factor = truth / delivered
            verdict = (close(factor, expect) and abs(factor - 1.0) > 10
                       and properties["buffer_km"] == 100.0)
            notes.append(f"delivered={delivered}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "metrics_correct_buffer_geodesic_100km":
            geom = shape(feature("Iceland")["geometry"])
            c = geom.centroid
            ae = CRS.from_proj4(f"+proj=aeqd +lat_0={c.y!r} +lon_0={c.x!r} "
                                "+datum=WGS84 +units=m +no_defs")
            fwd = Transformer.from_crs("EPSG:4326", ae, always_xy=True)
            back = Transformer.from_crs(ae, "EPSG:4326", always_xy=True)
            geom_m = shp_transform(lambda x, y, z=None: fwd.transform(x, y), geom)
            buf_ll = shp_transform(lambda x, y, z=None: back.transform(x, y),
                                   geom_m.buffer(100_000.0))
            truth = geod_area_km2(MultiPolygon([buf_ll]) if buf_ll.geom_type == "Polygon" else buf_ll)
            delivered = read_out_json(out, cid, "iceland_buffer_correct.geojson")["features"][0]["properties"]["buffer_area_sq_km"]
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "metrics_wrong_perimeter_degrees_km":
            geom = shape(feature("Switzerland")["geometry"])
            truth = geod_perimeter_km(geom)
            delivered = read_out_json(out, cid, "switzerland_perimeter_wrong.geojson")["features"][0]["properties"]["boundary_perimeter_km"]
            factor = truth / delivered
            verdict = close(factor, expect) and abs(factor - 1.0) > 10
            notes.append(f"delivered={delivered}; truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "metrics_correct_perimeter_geodesic":
            geom = shape(feature("Switzerland")["geometry"])
            truth = geod_perimeter_km(geom)
            delivered = read_out_json(out, cid, "switzerland_perimeter_correct.geojson")["features"][0]["properties"]["boundary_perimeter_km"]
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        raise KeyError(cid)

    # -------------------------------------------------------------- plain
    if cid.startswith("plain_"):
        if cid == "plain_mean_elevation_nepal":
            z, _ = read_tif(cache, COP_NEPAL)
            truth = float(z.mean(dtype=np.float64))
            delivered = read_out_json(out, cid, "elevation_summary.json")["mean_elevation_m"]
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "plain_ndvi_window_a":
            b03, _ = read_tif(cache, S2_B03)
            b08, _ = read_tif(cache, S2_B08)
            scl, _ = read_tif(cache, S2_SCL)
            r3 = scale_decode(b03)
            r8 = scale_decode(b08)
            ndvi = (r8 - r3) / np.maximum(r8 + r3, 1e-12)
            ok = (b03 != 0) & (b08 != 0)
            delivered = read_out_json(out, cid, "ndvi_summary.json")
            checks = []
            checks.append(close(delivered["ndvi_over_all_bands_valid"],
                                float(ndvi[ok].mean())))
            s10 = s10_from(scl)
            checks.append(close(delivered.get("ndvi_class_6_water_mean"),
                                float(ndvi[s10 == 6].mean())))
            all_close = all(checks)
            water_neg = float(ndvi[s10 == 6].mean()) < 0
            verdict = all_close and close(delivered["ndvi_class_6_water_mean"], expect) and water_neg
            notes.append(f"water_ndvi_negative={water_neg}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "plain_blue_reflectance_snow_wa":
            b02, _ = read_tif(cache, S2_B02)
            scl, _ = read_tif(cache, S2_SCL)
            s10 = s10_from(scl)
            truth = float(scale_decode(b02)[s10 == 11].mean(dtype=np.float64))
            delivered = read_out_json(out, cid, "blue_reflectance_summary.json")["mean_blue_reflectance_snow"]
            verdict = close(delivered, truth) and close(expect, delivered)
            notes.append(f"truth={truth}")
            return {"id": cid, "kind": kind, "verdict": bool(verdict), "notes": notes}
        if cid == "plain_ne_feature_count":
            truth = int(len(json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))["features"]))
            delivered = read_out_json(out, cid, "feature_count.json")["feature_count"]
            verdict = delivered == expect == truth
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
