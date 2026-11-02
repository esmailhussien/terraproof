#!/usr/bin/env python
"""Deterministic derivation of every verification-heldout-s0 case output.

Usage:
    python derive.py <cache-dir> <out-dir>

For each case id below, builds the delivered artifact(s) under
<out-dir>/outputs/<case-id>/ and prints a JSON map of the numbers each case
builder produced (sorted keys, rounded to 6 decimals). Runs with the same
cache are byte-identical.
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

SCALE = 1e-4
DEP3_FILL = -999999.0
R_EARTH_M = 6378137.0

V0_SCL = "s2/wa_SCL.tif"
V0_WC_SCL = "s2/wc_SCL.tif"
COP_NEPAL = "copdem/nepal_win.tif"
COP_SVALBARD = "copdem/svalbard_win.tif"
COP_ALPS = "copdem/alps_win.tif"
DEP3_DELTA = "usgs3dep/USGS_13_n31w091_win.tif"
DEP3_KAUAI = "usgs3dep/USGS_13_n22w159_win.tif"
NE_COUNTRIES = "naturalearth/ne_110m_admin_0_countries.geojson"

RESAMPLINGS = {
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
    "nearest": Resampling.nearest,
}

CASES = [
    # QA validity masks (5 wrong, 5 correct)
    "mask_s2_w_reject_only_medium_clouds_wa",
    "mask_s2_w_reject_only_shadow_wa",
    "mask_s2_w_reject_water_wc",
    "mask_s2_w_reject_snow_wa",
    "mask_s2_w_fill_kept_valid_wb",
    "mask_s2_c_standard_rule_wa",
    "mask_s2_c_snow_valid_wa",
    "mask_s2_c_water_veg_only_wc",
    "mask_s2_c_standard_rule_wc",
    "mask_s2_c_vegetation_bare_only_wa",
    # Reprojected slopes (6 wrong, 6 correct)
    "slope_rs_w_degrees_as_lengths_nepal_sw",
    "slope_rs_w_latitude_ignored_svalbard_sw",
    "slope_rs_w_degrees_labelled_percent_nepal_ws",
    "slope_rs_w_feet_over_metres_alps_ws",
    "slope_rs_w_mercator_spacing_svalbard_ws",
    "slope_rs_w_percent_labelled_degrees_alps_sw",
    "slope_rs_c_nepal_bilinear_pct_sw",
    "slope_rs_c_svalbard_cubic_pct_sw",
    "slope_rs_c_svalbard_bilinear_deg_ws",
    "slope_rs_c_nepal_average_pct_ws",
    "slope_rs_c_alps_nearest_deg_ws",
    "slope_rs_c_alps_average_deg_sw",
    # Multi-value reports (5 wrong, 5 correct)
    "report_w_fill_averaged_in_kauai",
    "report_w_zeros_evicted_delta",
    "report_w_area_in_degrees_vector",
    "report_w_one_share_over_all_cells_scl_wc",
    "report_w_nir_taken_from_green_v0",
    "report_c_kauai_multi",
    "report_c_delta_multi",
    "report_c_vector_multi",
    "report_c_scl_class_list_wc",
    "report_c_bands_multi_v0",
    # Same-grid geographic slopes (3 wrong, 3 correct)
    "slope_sg_w_latitude_ignored_svalbard",
    "slope_sg_w_degrees_as_lengths_alps",
    "slope_sg_w_feet_over_metres_nepal",
    "slope_sg_c_nepal_pct",
    "slope_sg_c_svalbard_deg",
    "slope_sg_c_alps_pct",
    # Plain (4 correct)
    "plain_nepal_elevation_multi",
    "plain_ndvi_v0_window_a",
    "plain_blue_reflectance_snow_v0",
    "plain_feature_count_ne",
]


def r6(x) -> float:
    return round(float(x), 6)


def read_tif(cache: Path, rel: str):
    with rasterio.open(cache / rel, "r") as ds:
        arr = ds.read(1)
        return arr, {"crs": ds.crs, "transform": ds.transform, "nodata": ds.nodata}


def write_tif(dest: Path, arr: np.ndarray, prof: dict, *, dtype="float32",
              nodata=None) -> np.ndarray:
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = np.ascontiguousarray(arr.astype(dtype))
    with rasterio.open(
        dest, mode="w", driver="GTiff", tiled=True, blockxsize=512,
        blockysize=512, compress="deflate", predictor=2, dtype=dtype,
        crs=prof["crs"], transform=prof["transform"], nodata=nodata,
        width=out.shape[1], height=out.shape[0], count=1,
    ) as dst:
        dst.write(out, 1)
    with rasterio.open(dest, mode="r+") as dst:
        dst.build_overviews([2, 4])
    return out


def write_json(dest: Path, obj: dict) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def s10(scl: np.ndarray) -> np.ndarray:
    return np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)


# ------------------------------------------------------------------- masks


MASK_SPECS = {
    "mask_s2_w_reject_only_medium_clouds_wa": ("s2/wa_SCL.tif", "~8", "land_or_snow"),
    "mask_s2_w_reject_only_shadow_wa": ("s2/wa_SCL.tif", "~3", "land_or_snow"),
    "mask_s2_w_reject_water_wc": ("s2/wc_SCL.tif", "no6", "land_or_snow"),
    "mask_s2_w_reject_snow_wa": ("s2/wa_SCL.tif", "no11", "land_or_snow"),
    "mask_s2_w_fill_kept_valid_wb": ("s2/wb_SCL.tif", "all", "standard"),
    "mask_s2_c_standard_rule_wa": ("s2/wa_SCL.tif", "in4567", "standard"),
    "mask_s2_c_snow_valid_wa": ("s2/wa_SCL.tif", "in4567plus11", "land_or_snow"),
    "mask_s2_c_water_veg_only_wc": ("s2/wc_SCL.tif", "in456", "water_veg"),
    "mask_s2_c_standard_rule_wc": ("s2/wc_SCL.tif", "in4567", "standard"),
    "mask_s2_c_vegetation_bare_only_wa": ("s2/wa_SCL.tif", "in45", "vegetation_bare"),
}


def _rule_mask(scl: np.ndarray, which: str) -> np.ndarray:
    return {
        "standard": np.isin(scl, [4, 5, 6, 7]),
        "land_or_snow": np.isin(scl, [4, 5, 6, 7, 11]),
        "water_veg": np.isin(scl, [4, 5, 6]),
        "vegetation_bare": np.isin(scl, [4, 5]),
    }[which]


def _delivered_mask(scl: np.ndarray, how: str) -> np.ndarray:
    return {
        "~8": ~np.isin(scl, [8]),
        "~3": ~np.isin(scl, [3]),
        "no6": ~np.isin(scl, [6]),
        "no11": ~np.isin(scl, [11]),
        "all": np.ones(scl.shape, dtype=bool),
        "in4567": np.isin(scl, [4, 5, 6, 7]),
        "in4567plus11": np.isin(scl, [4, 5, 6, 7, 11]),
        "in456": np.isin(scl, [4, 5, 6]),
        "in45": np.isin(scl, [4, 5]),
    }[how]


def _build_mask(cache: Path, out: Path, case_id: str) -> dict:
    rel, how, rule_key = MASK_SPECS[case_id]
    scl, prof = read_tif(cache, rel)
    delivered = _delivered_mask(scl, how)
    rule = _rule_mask(scl, rule_key)
    prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
    dest = out / "outputs" / case_id
    write_tif(dest / "validity_mask.tif", delivered.astype("uint8"), prof2,
              dtype="uint8")
    kept = int(delivered.sum())
    total = int(delivered.size)
    summary = {
        "usable_pixel_count": kept,
        "usable_fraction": r6(kept / total),
        "invalid_pixel_count": total - kept,
    }
    if case_id.startswith("mask_s2_w"):
        summary["kept_invalid_pixel_count"] = int((delivered & ~rule).sum())
        summary["evicted_valid_pixel_count"] = int((rule & ~delivered).sum())
    write_json(dest / "summary.json", summary)
    return summary


# ---------------------------------------------------------- slope geometry


def _res_y_x(prof: dict):
    t = prof["transform"]
    return abs(t.e), abs(t.a)


def _mid_lat(prof: dict, rows: int) -> float:
    res_y, _ = _res_y_x(prof)
    return prof["transform"].f - (rows / 2.0) * res_y


def _geo_step(prof: dict, rows: int, mode: str):
    """(dx_m, dy_m) for the source geographic grid under three assumptions."""
    res_y, res_x = _res_y_x(prof)
    lat = _mid_lat(prof, rows)
    dy_m = res_y * R_EARTH_M * math.pi / 180.0
    if mode == "metres_lat_aware":
        dx_m = res_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat))
    elif mode == "metres_no_cos":
        dx_m = res_x * R_EARTH_M * math.pi / 180.0
    elif mode == "degrees_as_metres":
        dx_m, dy_m = res_x, res_y
    else:
        raise ValueError(mode)
    return dx_m, dy_m


def _mag(z: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    zy, zx = np.gradient(z.astype(np.float64), dy_m, dx_m)
    return np.hypot(zx, zy)


def _to_unit(mag: np.ndarray, unit: str) -> np.ndarray:
    if unit == "percent":
        return 100.0 * mag
    if unit == "degrees":
        return np.degrees(np.arctan2(mag, 1.0))
    raise ValueError(unit)


def _warp(arr: np.ndarray, prof: dict, cache_rel: str, cache: Path,
          target_crs: str, res_m: float, method: str):
    with rasterio.open(cache / cache_rel) as src:
        t, w, h = calculate_default_transform(src.crs, target_crs, src.width,
                                              src.height, *src.bounds,
                                              resolution=res_m)
    dst = np.full((int(h), int(w)), np.nan, dtype=np.float64)
    reproject(source=arr, destination=dst, src_transform=prof["transform"],
              src_crs=prof["crs"], dst_transform=t, dst_crs=target_crs,
              src_nodata=prof["nodata"], dst_nodata=np.nan,
              resampling=RESAMPLINGS[method])
    return dst, t


# Reprojected-slope chains: each spec is
# (source, order, resampling, target_crs, res_m, values_unit, label_unit, error)
RS_SPECS = {
    # wrong cases
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
    # correct cases
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


def _rs_chain(cache: Path, case_id: str) -> tuple[np.ndarray, dict]:
    """Build the delivered slope array + its warp profile for a case."""
    rel, order, method, crs, res, values_unit, _label, error = RS_SPECS[case_id]
    z, prof = read_tif(cache, rel)
    if order == "slope_then_warp":
        dx_m, dy_m = _geo_step(prof, z.shape[0],
                               error if error in ("degrees_as_metres", "metres_no_cos")
                               else "metres_lat_aware")
        step = _to_unit(_mag(z, dx_m, dy_m), values_unit)
        warped, t = _warp(step, prof, rel, cache, crs, res, method)
    else:
        warped_dem, t = _warp(z, prof, rel, cache, crs, res, method)
        valid = ~np.isnan(warped_dem)
        zf = np.where(valid, warped_dem, 0.0)
        if error == "feet_values":
            zf = zf * 3.280839895013123
        mag = _mag(zf, res, res)
        step = _to_unit(mag, values_unit)
        warped = np.where(valid, step, np.nan)
    return warped, t


def _build_reprojected_slope(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    rel, order, method, crs, res, values_unit, label_unit, error = RS_SPECS[case_id]
    warped, t = _rs_chain(cache, case_id)
    valid = ~np.isnan(warped)
    out_arr = np.where(valid, warped, -9999.0).astype("float32")
    prof2 = {"crs": crs, "transform": t}
    got = write_tif(dest / "slope.tif", out_arr, prof2, dtype="float32",
                    nodata=-9999.0)
    sel = got[got != -9999.0]
    delivered_mean = float(sel.mean(dtype=np.float64))
    write_json(dest / "summary.json", {
        "mean_slope": r6(delivered_mean),
        "labelled_unit": label_unit,
        "valid_pixel_count": int(sel.size),
    })
    result = {"mean_slope": r6(delivered_mean), "labelled_unit": label_unit,
              "valid_pixel_count": int(sel.size)}
    if case_id.startswith("slope_rs_w"):
        truth = _rs_truth_honest(cache, case_id)
        result["truth_mean"] = r6(truth)
        result["mismatch_factor"] = r6(delivered_mean / truth)
    return result


def _rs_truth_honest(cache: Path, case_id: str) -> float:
    """Mean slope of the same chain with only the flagged error fixed."""
    rel, order, method, crs, res, values_unit, label_unit, error = RS_SPECS[case_id]
    z, prof = read_tif(cache, rel)
    if order == "slope_then_warp":
        dx_m, dy_m = _geo_step(prof, z.shape[0], "metres_lat_aware")
        mag = _mag(z, dx_m, dy_m)
        # a unit label swap is fixed by honouring the label; a geodesy error
        # is fixed by the lat-aware metre step (the label is then correct).
        truth_unit = label_unit if values_unit != label_unit else "percent"
        step = _to_unit(mag, truth_unit)
        warped, _ = _warp(step, prof, rel, cache, crs, res, method)
        return float(warped[~np.isnan(warped)].mean())
    # warp_then_slope: the honest grid is the same warped DEM, the honest
    # spacing is ground metres, and elevations are the source's metres.
    warped_dem, _ = _warp(z, prof, rel, cache, crs, res, method)
    valid = ~np.isnan(warped_dem)
    zf = np.where(valid, warped_dem, 0.0)
    if error == "mercator_spacing":
        scale = math.cos(math.radians(_mid_lat(prof, z.shape[0])))
        mag = _mag(zf, res * scale, res * scale)
    else:
        mag = _mag(zf, res, res)
    truth_unit = label_unit if values_unit != label_unit else "percent"
    vals = _to_unit(mag, truth_unit)
    return float(vals[valid].mean())


# ------------------------------------------------------------- same-grid


SG_SPECS = {
    "slope_sg_w_latitude_ignored_svalbard": (COP_SVALBARD, "percent", "metres_no_cos"),
    "slope_sg_w_degrees_as_lengths_alps": (COP_ALPS, "percent", "degrees_as_metres"),
    "slope_sg_w_feet_over_metres_nepal": (COP_NEPAL, "percent", "feet_values"),
    "slope_sg_c_nepal_pct": (COP_NEPAL, "percent", None),
    "slope_sg_c_svalbard_deg": (COP_SVALBARD, "degrees", None),
    "slope_sg_c_alps_pct": (COP_ALPS, "percent", None),
}


def _build_samegrid_slope(cache: Path, out: Path, case_id: str) -> dict:
    rel, unit, error = SG_SPECS[case_id]
    dest = out / "outputs" / case_id
    z, prof = read_tif(cache, rel)
    dx_m, dy_m = _geo_step(prof, z.shape[0],
                           error if error in ("metres_no_cos", "degrees_as_metres")
                           else "metres_lat_aware")
    if error == "feet_values":
        z = z * 3.280839895013123
    vals = _to_unit(_mag(z, dx_m, dy_m), unit)
    prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
    got = write_tif(dest / "slope.tif", vals, prof2, dtype="float32")
    delivered = float(got.mean(dtype=np.float64))
    write_json(dest / "summary.json", {"mean_slope": r6(delivered),
                                       "labelled_unit": unit})
    result = {"mean_slope": r6(delivered), "labelled_unit": unit}
    if case_id.startswith("slope_sg_w"):
        tz = read_tif(cache, rel)[0]
        tdx, tdy = _geo_step(prof, tz.shape[0], "metres_lat_aware")
        truth = float(_to_unit(_mag(tz, tdx, tdy), unit).mean())
        result["truth_mean"] = r6(truth)
        result["mismatch_factor"] = r6(delivered / truth)
    return result


# ----------------------------------------------------------- multi reports


def _geod_area_km2_perim_km(geom):
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    area = 0.0
    perim = 0.0
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


def _kauai_report(cache: Path, wrong: bool) -> dict:
    z, _ = read_tif(cache, DEP3_KAUAI)
    valid = z != DEP3_FILL
    sel = z[valid]
    mean_valid = r6(sel.mean())
    mean_all = r6(z.mean(dtype=np.float64))
    report = {
        "extremes": {
            "mean_elevation_m": mean_all if wrong else mean_valid,
            "max_elevation_m": r6(sel.max()),
            "min_elevation_m": r6(sel.min()),
        },
        "usable_pixel_count": int(valid.sum()),
        "usable_share": r6(float(valid.sum()) / z.size),
    }
    return report, mean_valid, mean_all


def _delta_report(cache: Path, wrong: bool) -> dict:
    z, _ = read_tif(cache, DEP3_DELTA)
    valid = z != DEP3_FILL
    sel = z[valid]
    usable = int((valid & (z != 0)).sum()) if wrong else int(valid.sum())
    report = {
        "extremes": {
            "mean_elevation_m": r6(sel.mean()),
            "max_elevation_m": r6(sel.max()),
        },
        "usable_pixel_count": usable,
        "zero_height_valid_count": int((sel == 0).sum()),
    }
    return report, int(valid.sum()), usable


def _vector_report(cache: Path, wrong: bool) -> dict:
    geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
    feats = geo["features"]
    by = {f["properties"].get("NAME"): f for f in feats}
    ice = shape(by["Iceland"]["geometry"])
    swi = shape(by["Switzerland"]["geometry"])
    area_geo_km2, _ = _geod_area_km2_perim_km(ice)
    _, peri_geo_km = _geod_area_km2_perim_km(swi)
    report = {
        "feature_count": len(feats),
        "iceland": {"area_sq_km": (round(float(ice.area), 6) if wrong
                                   else round(area_geo_km2, 4))},
        "switzerland": {"boundary_perimeter_km": round(peri_geo_km, 4)},
    }
    return report, r6(area_geo_km2), r6(peri_geo_km), len(feats)


def _scl_list_report(cache: Path, wrong: bool) -> dict:
    scl, _ = read_tif(cache, V0_WC_SCL)
    rule = np.isin(scl, [4, 5, 6, 7, 11])
    valid_n = int(rule.sum())
    classes = sorted(int(c) for c in np.unique(scl) if c in (4, 5, 6, 7, 11))
    bad_index = 2 if len(classes) > 2 else 0
    entries = []
    for i, cl in enumerate(classes):
        n = int((scl == cl).sum())
        share = r6(n / valid_n)
        if wrong and i == bad_index:
            share = r6(n / scl.size)
        entries.append({"class": cl, "pixel_count": n, "share_of_valid": share})
    report = {"per_class": entries, "valid_pixel_count": valid_n}
    honest = {e["class"]: r6(int((scl == e["class"]).sum()) / valid_n)
              for e in entries}
    bad = [e for e in entries if e["share_of_valid"] != honest[e["class"]]]
    return report, valid_n, (bad[0] if bad else None), honest


def _bands_report(cache: Path, wrong: bool) -> dict:
    b03, _ = read_tif(cache, "s2/wa_B03.tif")
    b08, _ = read_tif(cache, "s2/wa_B08.tif")
    green = b03.astype(np.float64) * SCALE
    nir = b08.astype(np.float64) * SCALE
    ok = (b03 != 0) & (b08 != 0)
    g_mean = r6(green[ok].mean())
    n_mean = r6(nir[ok].mean())
    ndvi_mean = r6(((nir - green) / np.maximum(nir + green, 1e-12))[ok].mean())
    report = {
        "bands": {
            "green_B03": {"mean_reflectance": g_mean},
            "nir_B08": {"mean_reflectance": g_mean if wrong else n_mean},
        },
        "ndvi_mean_over_valid": ndvi_mean,
    }
    return report, g_mean, n_mean, ndvi_mean


def _build_report(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id in ("report_w_fill_averaged_in_kauai", "report_c_kauai_multi"):
        wrong = case_id.startswith("report_w")
        report, mean_valid, mean_all = _kauai_report(cache, wrong)
        write_json(dest / "report.json", report)
        return {
            "usable_share": report["usable_share"],
            "delivered_mean": mean_all if wrong else mean_valid,
            "truth_mean": mean_valid,
            "mismatch_factor_abs": (r6(abs(mean_all - mean_valid) / mean_valid)
                                    if wrong else 0.0),
            "max_elevation_m": report["extremes"]["max_elevation_m"],
        }
    if case_id in ("report_w_zeros_evicted_delta", "report_c_delta_multi"):
        wrong = case_id.startswith("report_w")
        report, truth_usable, usable = _delta_report(cache, wrong)
        write_json(dest / "report.json", report)
        return {
            "delivered_usable_pixel_count": usable,
            "truth_usable_pixel_count": truth_usable,
            "evicted_zero_height_pixels": truth_usable - usable,
            "mean_elevation_m": report["extremes"]["mean_elevation_m"],
        }
    if case_id in ("report_w_area_in_degrees_vector", "report_c_vector_multi"):
        wrong = case_id.startswith("report_w")
        report, area_km2, peri_km, n_feat = _vector_report(cache, wrong)
        write_json(dest / "report.json", report)
        return {
            "feature_count": n_feat,
            "delivered_area_sq_km": report["iceland"]["area_sq_km"],
            "truth_area_sq_km": area_km2,
            "perimeter_km": peri_km,
            "area_mismatch_factor": (r6(area_km2 / report["iceland"]["area_sq_km"])
                                     if wrong else 1.0),
        }
    if case_id in ("report_w_one_share_over_all_cells_scl_wc",
                   "report_c_scl_class_list_wc"):
        wrong = case_id.startswith("report_w")
        report, valid_n, bad, honest = _scl_list_report(cache, wrong)
        write_json(dest / "report.json", report)
        return {
            "valid_pixel_count": valid_n,
            "bad_class": (bad["class"] if bad else None),
            "bad_share_delivered": (bad["share_of_valid"] if bad else None),
            "bad_share_honest": (honest[bad["class"]] if bad else None),
            "share_mismatch_ratio": (r6(honest[bad["class"]] /
                                        bad["share_of_valid"]) if bad else 1.0),
        }
    if case_id in ("report_w_nir_taken_from_green_v0", "report_c_bands_multi_v0"):
        wrong = case_id.startswith("report_w")
        report, g_mean, n_mean, ndvi_mean = _bands_report(cache, wrong)
        write_json(dest / "report.json", report)
        return {
            "green_mean_reflectance": g_mean,
            "delivered_nir_mean_reflectance": report["bands"]["nir_B08"]["mean_reflectance"],
            "truth_nir_mean_reflectance": n_mean,
            "ndvi_mean_over_valid": ndvi_mean,
            "nir_over_green": (r6(n_mean / g_mean) if wrong else 1.0),
        }
    raise KeyError(case_id)


# ------------------------------------------------------------------- plain


def _build_plain(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "plain_nepal_elevation_multi":
        z, _ = read_tif(cache, COP_NEPAL)
        sel = z.astype(np.float64)
        report = {"mean_elevation_m": r6(sel.mean()),
                  "min_elevation_m": r6(sel.min()),
                  "max_elevation_m": r6(sel.max())}
        write_json(dest / "report.json", report)
        return dict(report)
    if case_id == "plain_ndvi_v0_window_a":
        b03, prof = read_tif(cache, "s2/wa_B03.tif")
        b08, _ = read_tif(cache, "s2/wa_B08.tif")
        scl, _ = read_tif(cache, V0_SCL)
        r3 = b03.astype(np.float64) * SCALE
        r8 = b08.astype(np.float64) * SCALE
        ndvi = (r8 - r3) / np.maximum(r8 + r3, 1e-12)
        ok = (b03 != 0) & (b08 != 0)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "ndvi_map.tif", np.where(ok, ndvi, -9999.0), prof2,
                  dtype="float32", nodata=-9999.0)
        t10 = s10(scl)
        result = {"ndvi_mean_over_valid": r6(ndvi[ok].mean()),
                  "ndvi_class_4_mean": r6(ndvi[t10 == 4].mean()),
                  "ndvi_class_6_mean": r6(ndvi[t10 == 6].mean())}
        write_json(dest / "summary.json", result)
        return result
    if case_id == "plain_blue_reflectance_snow_v0":
        b02, _ = read_tif(cache, "s2/wa_B02.tif")
        scl, _ = read_tif(cache, V0_SCL)
        t10 = s10(scl)
        truth = float((b02.astype(np.float64) * SCALE)[t10 == 11].mean())
        write_json(dest / "summary.json", {"mean_blue_reflectance_snow": r6(truth)})
        return {"mean_blue_reflectance_snow": r6(truth)}
    if case_id == "plain_feature_count_ne":
        geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
        write_json(dest / "summary.json", {"feature_count": len(geo["features"])})
        return {"feature_count": len(geo["features"])}
    raise KeyError(case_id)


def build_case(cache: Path, out: Path, case_id: str) -> dict:
    if case_id.startswith("mask_"):
        return _build_mask(cache, out, case_id)
    if case_id.startswith("slope_rs_"):
        return _build_reprojected_slope(cache, out, case_id)
    if case_id.startswith("slope_sg_"):
        return _build_samegrid_slope(cache, out, case_id)
    if case_id.startswith("report_"):
        return _build_report(cache, out, case_id)
    if case_id.startswith("plain_"):
        return _build_plain(cache, out, case_id)
    raise KeyError(case_id)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    cache = Path(argv[1])
    out = Path(argv[2])
    summary = {}
    for case_id in CASES:
        summary[case_id] = build_case(cache, out, case_id)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
