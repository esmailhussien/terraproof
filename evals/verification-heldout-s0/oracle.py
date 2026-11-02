#!/usr/bin/env python
"""Recompute the truth for every verification-heldout-s0 case independently
from the fetched sources and the facts in cases.json, then check each case's
stated kind.

Usage:
    python oracle.py <cache-dir> <out-dir>

Never imports terraproof and never imports derive.py. For each case it
recomputes the truth from the cached sources, reads the delivered artifact(s),
checks the case's committed `oracle` number against the recomputation, and
checks that the artifact behaves as its `kind` claims. For reprojected slopes
it recomputes the declared chain (order, target, resolution, resampling) and
compares means within tolerance. Prints a JSON summary; exits non-zero on any
disagreement.
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
SCALE = 1e-4
QA60_BITS = (1 << 10) | (1 << 11)  # unused; kept for parity of documentation

V0_SCL = "s2/wa_SCL.tif"
V0_WB = "s2/wb_SCL.tif"
V0_WC = "s2/wc_SCL.tif"
COP_NEPAL = "copdem/nepal_win.tif"
COP_SVALBARD = "copdem/svalbard_win.tif"
COP_ALPS = "copdem/alps_win.tif"
DEP3_DELTA = "usgs3dep/USGS_13_n31w091_win.tif"
DEP3_KAUAI = "usgs3dep/USGS_13_n22w159_win.tif"
NE = "naturalearth/ne_110m_admin_0_countries.geojson"

TOL_ABS = 5e-6
TOL_REL = 2e-6

RESAMPLINGS = {
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
    "nearest": Resampling.nearest,
}

RS_CHAINS = {
    "slope_rs_w_degrees_as_lengths_nepal_sw":
        (COP_NEPAL, "slope_then_warp", "bilinear", "EPSG:32645", 50.0,
         "percent", "percent", "degrees_as_metres"),
    "slope_rs_w_latitude_ignored_svalbard_sw":
        (COP_SVALBARD, "slope_then_warp", "cubic", "EPSG:32633", 50.0,
         "percent", "percent", "metres_no_cos"),
    "slope_rs_w_degrees_labelled_percent_nepal_ws":
        (COP_NEPAL, "warp_then_slope", "bilinear", "EPSG:32645", 50.0,
         "degrees", "percent", None),
    "slope_rs_w_feet_over_metres_alps_ws":
        (COP_ALPS, "warp_then_slope", "average", "EPSG:32632", 30.0,
         "percent", "percent", "feet_values"),
    "slope_rs_w_mercator_spacing_svalbard_ws":
        (COP_SVALBARD, "warp_then_slope", "bilinear", "EPSG:3857", 500.0,
         "percent", "percent", "mercator_spacing"),
    "slope_rs_w_percent_labelled_degrees_alps_sw":
        (COP_ALPS, "slope_then_warp", "nearest", "EPSG:32632", 50.0,
         "percent", "degrees", None),
    "slope_rs_c_nepal_bilinear_pct_sw":
        (COP_NEPAL, "slope_then_warp", "bilinear", "EPSG:32645", 50.0,
         "percent", "percent", None),
    "slope_rs_c_svalbard_cubic_pct_sw":
        (COP_SVALBARD, "slope_then_warp", "cubic", "EPSG:32633", 50.0,
         "percent", "percent", None),
    "slope_rs_c_svalbard_bilinear_deg_ws":
        (COP_SVALBARD, "warp_then_slope", "bilinear", "EPSG:32633", 30.0,
         "degrees", "degrees", None),
    "slope_rs_c_nepal_average_pct_ws":
        (COP_NEPAL, "warp_then_slope", "average", "EPSG:32645", 60.0,
         "percent", "percent", None),
    "slope_rs_c_alps_nearest_deg_ws":
        (COP_ALPS, "warp_then_slope", "nearest", "EPSG:32632", 30.0,
         "degrees", "degrees", None),
    "slope_rs_c_alps_average_deg_sw":
        (COP_ALPS, "slope_then_warp", "average", "EPSG:32632", 50.0,
         "degrees", "degrees", None),
}


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
    rel = rel[len("cache/"):] if rel.startswith("cache/") else rel
    with rasterio.open(cache / rel, "r") as ds:
        return ds.read(1), {"crs": ds.crs, "transform": ds.transform,
                            "nodata": ds.nodata}


def read_out_tif(out: Path, case_id: str, name: str):
    with rasterio.open(out / "outputs" / case_id / name, "r") as ds:
        return ds.read(1)


def read_out_json(out: Path, case_id: str, name: str):
    return json.loads((out / "outputs" / case_id / name).read_text(encoding="utf-8"))


def geo_step(prof: dict, rows: int, mode: str):
    res_y, res_x = abs(prof["transform"].e), abs(prof["transform"].a)
    lat = prof["transform"].f - (rows / 2.0) * res_y
    dy = res_y * R_EARTH_M * math.pi / 180.0
    if mode == "metres_lat_aware":
        dx = res_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat))
    elif mode == "metres_no_cos":
        dx = res_x * R_EARTH_M * math.pi / 180.0
    else:
        dx, dy = res_x, res_y
    return dx, dy, lat


def mag_of(z, dx, dy):
    zy, zx = np.gradient(z.astype(np.float64), dy, dx)
    return np.hypot(zx, zy)


def to_unit(mag, unit):
    return 100.0 * mag if unit == "percent" else np.degrees(np.arctan2(mag, 1.0))


def warp_arr(arr, prof, cache_rel, cache, crs, res, method):
    with rasterio.open(cache / cache_rel) as src:
        t, w, h = calculate_default_transform(src.crs, crs, src.width,
                                              src.height, *src.bounds,
                                              resolution=res)
    dst = np.full((int(h), int(w)), np.nan, dtype=np.float64)
    reproject(source=arr, destination=dst, src_transform=prof["transform"],
              src_crs=prof["crs"], dst_transform=t, dst_crs=crs,
              src_nodata=prof["nodata"], dst_nodata=np.nan,
              resampling=RESAMPLINGS[method])
    return dst


def s10(scl):
    return np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)


def geod_area_perim(geom):
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    area = perim = 0.0
    for p in polys:
        lons, lats = np.array(p.exterior.coords).T
        a, per = geod.polygon_area_perimeter(lons, lats)
        area += abs(a)
        perim += abs(per)
        for ring in p.interiors:
            lons, lats = np.array(ring.coords).T
            a, _ = geod.polygon_area_perimeter(lons, lats)
            area -= abs(a)
    return area / 1e6, perim / 1000.0


def rs_recompute(cache: Path, case_id: str, honest: bool):
    rel, order, method, crs, res, values_unit, label_unit, error = RS_CHAINS[case_id]
    z, prof = read_tif(cache, rel)
    unit = label_unit if honest else values_unit
    if order == "slope_then_warp":
        mode = ("metres_lat_aware" if honest else
                (error if error in ("degrees_as_metres", "metres_no_cos")
                 else "metres_lat_aware"))
        dx, dy, _ = geo_step(prof, z.shape[0], mode)
        step = to_unit(mag_of(z, dx, dy), unit)
        out = warp_arr(step, prof, rel, cache, crs, res, method)
        return float(out[~np.isnan(out)].mean())
    wd = warp_arr(z, prof, rel, cache, crs, res, method)
    valid = ~np.isnan(wd)
    zf = np.where(valid, wd, 0.0)
    if error == "feet_values" and not honest:
        zf = zf * 3.280839895013123
    dx = dy = res
    if error == "mercator_spacing" and honest:
        _, _, lat = geo_step(prof, z.shape[0], "metres_lat_aware")
        dx = dy = res * math.cos(math.radians(lat))
    vals = to_unit(mag_of(zf, dx, dy), unit)[valid]
    return float(vals.mean())


def verdict(cid, kind, ok, notes):
    return {"id": cid, "kind": kind, "verdict": bool(ok), "notes": notes}


def check_case(cache: Path, out: Path, case: dict) -> dict:
    cid = case["id"]
    kind = case["kind"]
    expect = case["oracle"]["value"]

    # ---- masks ----------------------------------------------------------
    if cid.startswith("mask_"):
        rel = case["facts"]["pixel_qa_window"]["path"]
        scl, _ = read_tif(cache, rel)
        rule = np.isin(scl, case["facts"]["pixel_qa_valid_classes"])
        mask = read_out_tif(out, cid, "validity_mask.tif").astype(bool)
        sj = read_out_json(out, cid, "summary.json")
        exact = bool((mask == rule).all())
        if kind == "correct":
            return verdict(cid, kind, exact and close(expect, int(mask.sum()))
                           and int(sj["usable_pixel_count"]) == int(mask.sum()),
                           [f"exact={exact}; usable={int(mask.sum())}"])
        kept_invalid = int((mask & ~rule).sum())
        evicted = int((rule & ~mask).sum())
        metric = {
            "count_of_documented_invalid_pixels_kept_usable": kept_invalid,
            "count_of_documented_valid_pixels_evicted": evicted,
        }[case["oracle"]["value_metric"]]
        return verdict(cid, kind, (not exact) and metric == int(expect)
                       and metric > 0 and int(sj["usable_pixel_count"]) == int(mask.sum()),
                       [f"kept_invalid={kept_invalid}; evicted={evicted}"])

    # ---- reprojected slopes --------------------------------------------
    if cid.startswith("slope_rs_"):
        delivered = rs_recompute(cache, cid, honest=False)
        truth = rs_recompute(cache, cid, honest=True)
        got = read_out_tif(out, cid, "slope.tif")
        dmean = float(got[got != -9999.0].astype(np.float64).mean())
        sj = read_out_json(out, cid, "summary.json")
        if kind == "correct":
            return verdict(cid, kind, close(dmean, delivered)
                           and close(dmean, truth) and close(expect, dmean)
                           and close(sj["mean_slope"], dmean),
                           [f"chain={dmean}; close_to_truth={close(dmean, truth)}"])
        factor = dmean / truth
        return verdict(cid, kind, close(factor, expect)
                       and close(dmean, delivered)
                       and abs(factor - 1.0) > 0.05
                       and not close(dmean, truth),
                       [f"delivered={dmean}; truth={truth}; factor={factor}"])

    # ---- same-grid slopes ----------------------------------------------
    if cid.startswith("slope_sg_"):
        facts = case["facts"]
        rel = facts["source_dem"]["path"]
        z, prof = read_tif(cache, rel)
        mode = "metres_lat_aware"
        dx, dy, _ = geo_step(prof, z.shape[0], mode)
        unit = facts["slope_unit"]
        mag = mag_of(z, dx, dy)
        truth = float(to_unit(mag, unit).mean())
        got = read_out_tif(out, cid, "slope.tif")
        dmean = float(got.astype(np.float64).mean())
        if kind == "correct":
            return verdict(cid, kind, close(dmean, truth) and close(expect, truth),
                           [f"truth={truth}"])
        factor = dmean / truth
        return verdict(cid, kind, close(factor, expect)
                       and abs(factor - 1.0) > 0.05 and not close(dmean, truth),
                       [f"delivered={dmean}; truth={truth}; factor={factor}"])

    # ---- multi-value reports --------------------------------------------
    if cid.startswith("report_"):
        rep = read_out_json(out, cid, "report.json")
        checks = []
        truths = {}
        if "kauai" in cid:
            z, _ = read_tif(cache, DEP3_KAUAI)
            valid = z != DEP3_FILL
            truths["extremes.mean_elevation_m"] = float(z[valid].mean())
            truths["extremes.max_elevation_m"] = float(z[valid].max())
            truths["extremes.min_elevation_m"] = float(z[valid].min())
            truths["usable_pixel_count"] = int(valid.sum())
            truths["usable_share"] = float(valid.sum()) / z.size
        elif "delta" in cid:
            z, _ = read_tif(cache, DEP3_DELTA)
            valid = z != DEP3_FILL
            truths["extremes.mean_elevation_m"] = float(z[valid].mean())
            truths["extremes.max_elevation_m"] = float(z[valid].max())
            truths["usable_pixel_count"] = int(valid.sum())
            truths["zero_height_valid_count"] = int((z[valid] == 0).sum())
        elif "vector" in cid:
            geo = json.loads((cache / NE).read_text(encoding="utf-8"))
            feats = geo["features"]
            by = {f["properties"].get("NAME"): f for f in feats}
            a_km2, p_km = geod_area_perim(shape(by["Iceland"]["geometry"]))
            _, sw_km = geod_area_perim(shape(by["Switzerland"]["geometry"]))
            truths["feature_count"] = len(feats)
            truths["iceland.area_sq_km"] = a_km2
            truths["switzerland.boundary_perimeter_km"] = sw_km
        elif "scl_class_list" in cid or "one_share_over_all_cells" in cid:
            scl, _ = read_tif(cache, V0_WC)
            rule = np.isin(scl, [4, 5, 6, 7, 11])
            valid_n = int(rule.sum())
            truths["valid_pixel_count"] = valid_n
            for e in rep["per_class"]:
                n = int((scl == e["class"]).sum())
                truths[f"per_class[{e['class']}].pixel_count"] = n
                truths[f"per_class[{e['class']}].share_of_valid"] = n / valid_n
        elif "bands" in cid or "nir_taken_from_green" in cid:
            b03, _ = read_tif(cache, "s2/wa_B03.tif")
            b08, _ = read_tif(cache, "s2/wa_B08.tif")
            r3 = b03.astype(np.float64) * SCALE
            r8 = b08.astype(np.float64) * SCALE
            ok = (b03 != 0) & (b08 != 0)
            truths["bands.green_B03.mean_reflectance"] = float(r3[ok].mean())
            truths["bands.nir_B08.mean_reflectance"] = float(r8[ok].mean())
            truths["ndvi_mean_over_valid"] = float(
                ((r8 - r3) / np.maximum(r8 + r3, 1e-12))[ok].mean())

        def get(path):
            obj = rep
            for part in path.split("."):
                if part.startswith("per_class["):
                    cls = int(part.split("[")[1].rstrip("]"))
                    obj = next(e for e in obj["per_class"] if e["class"] == cls)
                    continue
                obj = obj[part]
            return obj

        bad = []
        for key, tval in truths.items():
            val = get(key)
            if isinstance(tval, float):
                okk = close(val, tval)
            else:
                okk = val == tval
            if not okk:
                bad.append(key)
        if kind == "correct":
            return verdict(cid, kind, not bad
                           and any(close(expect, t) for t in truths.values()),
                           [f"all {len(truths)} numbers match"])
        if len(bad) != 1:
            return verdict(cid, kind, False, [f"wrong_keys={bad}"])
        d = float(get(bad[0]))
        t = float(truths[bad[0]])
        metric_name = case["oracle"]["value_metric"]
        metric = {
            "mismatch_factor_abs_fill_averaged_in": abs(d - t) / t,
            "evicted_zero_height_pixels": t - d,
            "area_degrees_mismatch_factor": t / d,
            "share_ratio_honest_over_delivered": t / d,
            "nir_mean_over_green_mean": t / d,
        }[metric_name]
        return verdict(cid, kind, close(metric, expect),
                       [f"bad_key={bad[0]}; metric={metric}"])

    # ---- plain -----------------------------------------------------------
    if cid.startswith("plain_"):
        if cid == "plain_nepal_elevation_multi":
            z, _ = read_tif(cache, COP_NEPAL)
            sj = read_out_json(out, cid, "report.json")
            ok = (close(sj["mean_elevation_m"], float(z.mean(dtype=np.float64)))
                  and close(sj["min_elevation_m"], float(z.min()))
                  and close(sj["max_elevation_m"], float(z.max()))
                  and close(expect, sj["mean_elevation_m"]))
            return verdict(cid, kind, ok, ["multi stats match"])
        if cid == "plain_ndvi_v0_window_a":
            b03, _ = read_tif(cache, "s2/wa_B03.tif")
            b08, _ = read_tif(cache, "s2/wa_B08.tif")
            scl, _ = read_tif(cache, V0_SCL)
            r3 = b03.astype(np.float64) * SCALE
            r8 = b08.astype(np.float64) * SCALE
            ndvi = (r8 - r3) / np.maximum(r8 + r3, 1e-12)
            okm = (b03 != 0) & (b08 != 0)
            sj = read_out_json(out, cid, "summary.json")
            water = float(ndvi[s10(scl) == 6].mean())
            ok = (close(sj["ndvi_mean_over_valid"], float(ndvi[okm].mean()))
                  and close(sj["ndvi_class_6_mean"], water)
                  and close(expect, water) and water < 0)
            return verdict(cid, kind, ok, [f"water={water}"])
        if cid == "plain_blue_reflectance_snow_v0":
            b02, _ = read_tif(cache, "s2/wa_B02.tif")
            scl, _ = read_tif(cache, V0_SCL)
            truth = float((b02.astype(np.float64) * SCALE)[s10(scl) == 11].mean())
            sj = read_out_json(out, cid, "summary.json")
            return verdict(cid, kind, close(sj["mean_blue_reflectance_snow"], truth)
                           and close(expect, truth), [f"truth={truth}"])
        if cid == "plain_feature_count_ne":
            geo = json.loads((cache / NE).read_text(encoding="utf-8"))
            truth = len(geo["features"])
            sj = read_out_json(out, cid, "summary.json")
            return verdict(cid, kind, sj["feature_count"] == truth == int(expect),
                           [f"truth={truth}"])

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
    print(json.dumps({"cases": results, "agree": n_ok, "total": len(results)},
                     indent=2, sort_keys=True))
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
