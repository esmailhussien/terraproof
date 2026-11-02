"""Deterministic derivation of every verification-heldout-s0b case output.

Usage:
    python derive.py <cache-dir> <out-dir>

For each case id below, builds the delivered artifact(s) under
<out-dir>/outputs/<case-id>/ and prints a JSON map of the numbers each case
builder produced (sorted keys, rounded to 6 decimals). Runs with the same
cache are byte-identical.

For wrong cases the delivered artifact embeds the practitioner's mistake only;
the facts in cases.json describe the deliverable as it was claimed (the honest
computation). This module never imports terraproof.
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
FT_PER_M = 3.280839895013123

S2_SCL_A = "s2/wa_SCL.tif"
S2_SCL_B = "s2/wb_SCL.tif"
S2_SCL_C = "s2/wc_SCL.tif"
S2_B03 = "s2/wa_B03.tif"
S2_B08 = "s2/wa_B08.tif"
S2_B02 = "s2/wa_B02.tif"
COP_NORWAY = "copdem/norway_win.tif"
COP_MATTERHORN = "copdem/matterhorn_win.tif"
DEP3_LA = "usgs3dep/USGS_13_n33w118_win.tif"
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
    "mask_s2_w_reject_snow_wa",
    "mask_s2_w_fill_kept_valid_wb",
    "mask_s2_w_reject_water_wa",
    "mask_s2_c_standard_rule_wa",
    "mask_s2_c_snow_valid_wa",
    "mask_s2_c_standard_rule_wc",
    "mask_s2_c_water_veg_only_wa",
    "mask_s2_c_wedge_all_invalid_wb",
    # Reprojected slopes (6 wrong, 6 correct)
    "slope_rs_w_degrees_as_lengths_matterhorn_sw",
    "slope_rs_w_latitude_ignored_norway_sw",
    "slope_rs_w_degrees_labelled_percent_matterhorn_ws",
    "slope_rs_w_feet_over_metres_norway_ws",
    "slope_rs_w_mercator_spacing_norway_ws",
    "slope_rs_w_spacing_as_feet_matterhorn_ws",
    "slope_rs_c_norway_bilinear_pct_sw",
    "slope_rs_c_matterhorn_cubic_deg_sw",
    "slope_rs_c_norway_bilinear_deg_polar_ws",
    "slope_rs_c_matterhorn_average_pct_ws",
    "slope_rs_c_norway_groundmetres_bilinear_pct_mercator_ws",
    "slope_rs_c_norway_nearest_deg_ws",
    # Multi-value reports (6 wrong, 6 correct)
    "report_w_fill_averaged_in_la",
    "report_w_zeros_evicted_la",
    "report_w_area_in_degrees_new_zealand",
    "report_w_share_over_all_cells_scl_wa",
    "report_w_nir_taken_from_green",
    "report_w_blue_offset_applied_twice",
    "report_c_la_multi",
    "report_c_la_zero_kept",
    "report_c_new_zealand_multi",
    "report_c_scl_class_list_wa",
    "report_c_bands_multi_wa",
    "report_c_norway_multi",
    "report_c_edge_qa_counts_wc",
    # Same-grid slopes (3 wrong, 3 correct)
    "slope_sg_w_mercator_metres_norway",
    "slope_sg_w_feet_over_metres_matterhorn",
    "slope_sg_w_degrees_labelled_percent_matterhorn",
    "slope_sg_c_norway_pct",
    "slope_sg_c_matterhorn_deg",
    "slope_sg_c_matterhorn_pct",
    # Plain (4 correct)
    "plain_norway_elevation_multi",
    "plain_ndvi_wa",
    "plain_blue_reflectance_snow_wa",
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


def _res_y_x(prof: dict):
    t = prof["transform"]
    return abs(t.e), abs(t.a)


def _mid_lat(prof: dict, rows: int) -> float:
    res_y, _ = _res_y_x(prof)
    return prof["transform"].f - (rows / 2.0) * res_y


def _geo_step(prof: dict, rows: int, mode: str):
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
    return dx_m, dy_m, lat


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


# ------------------------------------------------------- slope chain specs
# (source, order, resampling, target_crs, res_m, values_unit, label_unit, error)
# For wrong cases, `error` is applied to the delivered artifact only; the
# facts in cases.json describe the same chain honestly.
RS_SPECS = {
    "slope_rs_w_degrees_as_lengths_matterhorn_sw":
        (COP_MATTERHORN, "slope_then_warp", "bilinear", "EPSG:32632", 30.0,
         "percent", "percent", "degrees_as_metres"),
    "slope_rs_w_latitude_ignored_norway_sw":
        (COP_NORWAY, "slope_then_warp", "cubic", "EPSG:32633", 50.0,
         "percent", "percent", "metres_no_cos"),
    "slope_rs_w_degrees_labelled_percent_matterhorn_ws":
        (COP_MATTERHORN, "warp_then_slope", "average", "EPSG:32632", 60.0,
         "degrees", "percent", "label_swap"),
    "slope_rs_w_feet_over_metres_norway_ws":
        (COP_NORWAY, "warp_then_slope", "average", "EPSG:3413", 30.0,
         "percent", "percent", "feet_values"),
    "slope_rs_w_mercator_spacing_norway_ws":
        (COP_NORWAY, "warp_then_slope", "bilinear", "EPSG:3857", 30.0,
         "percent", "percent", "mercator_spacing"),
    "slope_rs_w_spacing_as_feet_matterhorn_ws":
        (COP_MATTERHORN, "warp_then_slope", "bilinear", "EPSG:32632", 30.0,
         "percent", "percent", "spacing_scales_to_feet"),
    "slope_rs_c_norway_bilinear_pct_sw":
        (COP_NORWAY, "slope_then_warp", "bilinear", "EPSG:32633", 50.0,
         "percent", "percent", None),
    "slope_rs_c_matterhorn_cubic_deg_sw":
        (COP_MATTERHORN, "slope_then_warp", "cubic", "EPSG:32632", 50.0,
         "degrees", "degrees", None),
    "slope_rs_c_norway_bilinear_deg_polar_ws":
        (COP_NORWAY, "warp_then_slope", "bilinear", "EPSG:3413", 30.0,
         "degrees", "degrees", None),
    "slope_rs_c_matterhorn_average_pct_ws":
        (COP_MATTERHORN, "warp_then_slope", "average", "EPSG:32632", 60.0,
         "percent", "percent", None),
    "slope_rs_c_norway_groundmetres_bilinear_pct_mercator_ws":
        (COP_NORWAY, "warp_then_slope", "bilinear", "EPSG:3857", 30.0,
         "percent", "percent", "mercator_reduced_honest"),
    "slope_rs_c_norway_nearest_deg_ws":
        (COP_NORWAY, "warp_then_slope", "nearest", "EPSG:32633", 40.0,
         "degrees", "degrees", None),
}


def _rs_chain(cache: Path, case_id: str):
    rel, order, method, crs, res, values_unit, _label, error = RS_SPECS[case_id]
    z, prof = read_tif(cache, rel)
    if order == "slope_then_warp":
        mode = (error if error in ("degrees_as_metres", "metres_no_cos")
                else "metres_lat_aware")
        dx_m, dy_m, _ = _geo_step(prof, z.shape[0], mode)
        step = _to_unit(_mag(z, dx_m, dy_m), values_unit)
        warped, t = _warp(step, prof, rel, cache, crs, res, method)
        return warped, t
    warped_dem, t = _warp(z, prof, rel, cache, crs, res, method)
    valid = ~np.isnan(warped_dem)
    zf = np.where(valid, warped_dem, 0.0)
    dx_m = dy_m = res
    if error == "feet_values":
        zf = zf * FT_PER_M
    elif error == "mercator_spacing":
        pass                                   # grid metres kept as if ground metres
    elif error == "mercator_reduced_honest":
        _, _, lat = _geo_step(prof, z.shape[0], "metres_lat_aware")
        dx_m = dy_m = res * math.cos(math.radians(lat))
    elif error == "spacing_scales_to_feet":
        dx_m = dy_m = res * FT_PER_M
    mag = _mag(zf, dx_m, dy_m)
    vals = _to_unit(mag, values_unit)
    return np.where(valid, vals, np.nan), t


def _truth_honest_rs(cache: Path, case_id: str) -> float:
    """Mean of the chain exactly as its facts describe it."""
    rel, order, method, crs, res, _v, label_unit, _e = RS_SPECS[case_id]
    z, prof = read_tif(cache, rel)
    if order == "slope_then_warp":
        dx_m, dy_m, _ = _geo_step(prof, z.shape[0], "metres_lat_aware")
        step = _to_unit(_mag(z, dx_m, dy_m), label_unit)
        warped, _ = _warp(step, prof, rel, cache, crs, res, method)
        return float(warped[~np.isnan(warped)].mean())
    warped_dem, _ = _warp(z, prof, rel, cache, crs, res, method)
    valid = ~np.isnan(warped_dem)
    zf = np.where(valid, warped_dem, 0.0)
    dx_m = dy_m = res
    if crs == "EPSG:3857":
        _, _, lat = _geo_step(prof, z.shape[0], "metres_lat_aware")
        dx_m = dy_m = res * math.cos(math.radians(lat))
    mag = _mag(zf, dx_m, dy_m)
    return float(_to_unit(mag, label_unit)[valid].mean())


def _build_reprojected_slope(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    rel, order, method, crs, res, values_unit, label_unit, error = RS_SPECS[case_id]
    warped, t = _rs_chain(cache, case_id)
    valid = ~np.isnan(warped)
    got = write_tif(dest / "slope.tif", np.where(valid, warped, -9999.0),
                    {"crs": crs, "transform": t}, dtype="float32",
                    nodata=-9999.0)
    sel = got[got != -9999.0]
    delivered_mean = float(sel.mean(dtype=np.float64))
    write_json(dest / "summary.json", {
        "mean_slope": r6(delivered_mean), "labelled_unit": label_unit,
        "valid_pixel_count": int(sel.size),
    })
    result = {"mean_slope": r6(delivered_mean), "labelled_unit": label_unit,
              "valid_pixel_count": int(sel.size)}
    if case_id.startswith("slope_rs_w"):
        truth = _truth_honest_rs(cache, case_id)
        result["truth_mean"] = r6(truth)
        result["mismatch_factor"] = r6(delivered_mean / truth)
    return result


# ---------------------------------------------------------- same-grid slopes


SG_SPECS = {
    "slope_sg_w_mercator_metres_norway": (COP_NORWAY, "metres_no_cos"),
    "slope_sg_w_feet_over_metres_matterhorn": (COP_MATTERHORN, "feet_values"),
    "slope_sg_w_degrees_labelled_percent_matterhorn": (COP_MATTERHORN, "pct_labelled_deg"),
    "slope_sg_c_norway_pct": (COP_NORWAY, None),
    "slope_sg_c_matterhorn_deg": (COP_MATTERHORN, None),
    "slope_sg_c_matterhorn_pct": (COP_MATTERHORN, None),
}


def _build_samegrid_slope(cache: Path, out: Path, case_id: str) -> dict:
    rel, error = SG_SPECS[case_id]
    dest = out / "outputs" / case_id
    z, prof = read_tif(cache, rel)
    dx_m, dy_m, lat = _geo_step(prof, z.shape[0], "metres_lat_aware")
    if error == "metres_no_cos":
        dx_m, dy_m, _ = _geo_step(prof, z.shape[0], "metres_no_cos")
        vals = _to_unit(_mag(z, dx_m, dy_m), "percent")
        label_unit = "percent"
    elif error == "feet_values":
        vals = _to_unit(_mag(z * FT_PER_M, dx_m, dy_m), "percent")
        label_unit = "percent"
    elif error == "pct_labelled_deg":
        vals = _to_unit(_mag(z, dx_m, dy_m), "percent")
        label_unit = "degrees"
    else:
        unit = "percent" if case_id.endswith("_pct") else "degrees"
        vals = _to_unit(_mag(z, dx_m, dy_m), unit)
        label_unit = unit
    prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
    got = write_tif(dest / "slope.tif", vals, prof2, dtype="float32")
    delivered = float(got.mean(dtype=np.float64))
    write_json(dest / "summary.json", {"mean_slope": r6(delivered),
                                       "labelled_unit": label_unit})
    result = {"mean_slope": r6(delivered), "labelled_unit": label_unit}
    if case_id.startswith("slope_sg_w"):
        tdx, tdy, _ = _geo_step(prof, z.shape[0], "metres_lat_aware")
        truth_unit = ("degrees" if "degrees_labelled_percent" in case_id
                      else "percent")
        truth = float(_to_unit(_mag(z, tdx, tdy), truth_unit).mean())
        result["truth_mean"] = r6(truth)
        result["mismatch_factor"] = r6(delivered / truth)
    return result


# -------------------------------------------------------------------- masks


MASK_SPECS = {
    "mask_s2_w_reject_only_medium_clouds_wa": (S2_SCL_A, "~8", "land_or_snow"),
    "mask_s2_w_reject_only_shadow_wa": (S2_SCL_A, "~3", "land_or_snow"),
    "mask_s2_w_reject_snow_wa": (S2_SCL_A, "no11", "land_or_snow"),
    "mask_s2_w_fill_kept_valid_wb": (S2_SCL_B, "all", "standard"),
    "mask_s2_w_reject_water_wa": (S2_SCL_A, "no6", "land_or_snow"),
    "mask_s2_c_standard_rule_wa": (S2_SCL_A, "in4567", "standard"),
    "mask_s2_c_snow_valid_wa": (S2_SCL_A, "in4567plus11", "land_or_snow"),
    "mask_s2_c_standard_rule_wc": (S2_SCL_C, "in4567", "standard"),
    "mask_s2_c_water_veg_only_wa": (S2_SCL_A, "in456", "water_veg"),
    "mask_s2_c_wedge_all_invalid_wb": (S2_SCL_B, "in4567", "standard"),
}


def _rule_mask(scl: np.ndarray, which: str) -> np.ndarray:
    return {
        "standard": np.isin(scl, [4, 5, 6, 7]),
        "land_or_snow": np.isin(scl, [4, 5, 6, 7, 11]),
        "water_veg": np.isin(scl, [4, 5, 6]),
    }[which]


def _delivered_mask(scl: np.ndarray, how: str) -> np.ndarray:
    return {
        "~8": ~np.isin(scl, [8]),
        "~3": ~np.isin(scl, [3]),
        "no11": ~np.isin(scl, [11]),
        "no6": ~np.isin(scl, [6]),
        "all": np.ones(scl.shape, dtype=bool),
        "in4567": np.isin(scl, [4, 5, 6, 7]),
        "in4567plus11": np.isin(scl, [4, 5, 6, 7, 11]),
        "in456": np.isin(scl, [4, 5, 6]),
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


# ------------------------------------------------------------------ reports


def _geod_area_km2_perim_km(geom):
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


def _la_stats(cache: Path):
    z, _ = read_tif(cache, DEP3_LA)
    valid = z != DEP3_FILL
    sel = z[valid]
    return z, valid, sel


def _norway_stats(cache: Path):
    z, _ = read_tif(cache, COP_NORWAY)
    valid = z != DEP3_FILL
    sel = z[valid]
    return z, valid, sel


def _nz_vectors(cache: Path):
    geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
    feats = geo["features"]
    nz = next(f for f in feats if f["properties"].get("NAME") == "New Zealand")
    geom = shape(nz["geometry"])
    area_km2, perim_km = _geod_area_km2_perim_km(geom)
    return feats, geom, r6(area_km2), r6(perim_km)


def _scl_list_report(cache: Path, rel: str, wrong: bool):
    scl, _ = read_tif(cache, rel)
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
    honest = {e["class"]: r6(int((scl == e["class"]).sum()) / valid_n)
              for e in entries}
    bad = [e for e in entries if e["share_of_valid"] != honest[e["class"]]]
    return {"per_class": entries, "valid_pixel_count": valid_n}, valid_n, \
        (bad[0] if bad else None), honest


def _band_stats(cache: Path):
    b03, _ = read_tif(cache, S2_B03)
    b08, _ = read_tif(cache, S2_B08)
    b02, _ = read_tif(cache, S2_B02)
    ok_all = (b03 != 0) & (b08 != 0) & (b02 != 0)
    r3 = b03.astype(np.float64) * SCALE
    r8 = b08.astype(np.float64) * SCALE
    r2 = b02.astype(np.float64) * SCALE
    green = r6(r3[ok_all].mean())
    nir = r6(r8[ok_all].mean())
    blue = r6(r2[ok_all].mean())
    ndvi = r6(((r8 - r3) / np.maximum(r8 + r3, 1e-12))[ok_all].mean())
    return green, nir, blue, ndvi


def _edge_qa_counts(cache: Path):
    scl, _ = read_tif(cache, S2_SCL_C)
    rule = np.isin(scl, [4, 5, 6, 7, 11])
    return {
        "by_qa": {
            "fill": int((scl == 0).sum()),
            "cloud_medium_or_high": int(((scl == 8) | (scl == 9)).sum()),
            "water": int((scl == 6).sum()),
        },
        "valid_share": r6(float(rule.sum()) / scl.size),
    }


def _build_report(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id in ("report_w_fill_averaged_in_la", "report_c_la_multi"):
        wrong = case_id.startswith("report_w")
        z, valid, sel = _la_stats(cache)
        mean_val = z.mean(dtype=np.float64) if wrong else sel.mean()
        report = {
            "extremes": {
                "mean_elevation_m": r6(mean_val),
                "max_elevation_m": r6(sel.max()),
                "min_elevation_m": r6(sel.min()),
            },
            "usable_pixel_count": int(valid.sum()),
            "usable_share": r6(float(valid.sum()) / z.size),
        }
        write_json(dest / "report.json", report)
        truth_mean = float(sel.mean())
        delivered_mean = float(report["extremes"]["mean_elevation_m"])
        return {
            "delivered_mean_elevation_m": r6(delivered_mean),
            "truth_mean_elevation_m": r6(truth_mean),
            "usable_share": report["usable_share"],
            "max_elevation_m": report["extremes"]["max_elevation_m"],
            "mismatch_factor_abs": (r6(abs(delivered_mean - truth_mean) / truth_mean)
                                    if wrong else 0.0),
        }
    if case_id in ("report_w_zeros_evicted_la", "report_c_la_zero_kept"):
        wrong = case_id.startswith("report_w")
        z, valid, sel = _la_stats(cache)
        usable = int((valid & (z != 0)).sum()) if wrong else int(valid.sum())
        report = {
            "extremes": {
                "mean_elevation_m": r6(sel.mean()),
                "max_elevation_m": r6(sel.max()),
            },
            "usable_pixel_count": usable,
            "zero_height_valid_count": int((sel == 0).sum()),
        }
        write_json(dest / "report.json", report)
        return {
            "delivered_usable_pixel_count": usable,
            "truth_usable_pixel_count": int(valid.sum()),
            "evicted_zero_height_pixels": int(valid.sum()) - usable,
            "zero_height_valid_count": report["zero_height_valid_count"],
            "mean_elevation_m": report["extremes"]["mean_elevation_m"],
        }
    if case_id in ("report_w_area_in_degrees_new_zealand",
                   "report_c_new_zealand_multi"):
        wrong = case_id.startswith("report_w")
        feats, geom, area_km2, perim_km = _nz_vectors(cache)
        report = {
            "feature_count": len(feats),
            "new_zealand": {
                "area_sq_km": round(float(geom.area), 6) if wrong else area_km2,
                "boundary_perimeter_km": perim_km,
            },
        }
        write_json(dest / "report.json", report)
        return {
            "feature_count": len(feats),
            "delivered_area_sq_km": report["new_zealand"]["area_sq_km"],
            "truth_area_sq_km": area_km2,
            "perimeter_km": perim_km,
            "area_mismatch_factor": (r6(area_km2 /
                                        report["new_zealand"]["area_sq_km"])
                                     if wrong else 1.0),
        }
    if case_id in ("report_w_share_over_all_cells_scl_wa",
                   "report_c_scl_class_list_wa"):
        wrong = case_id.startswith("report_w")
        report, valid_n, bad, honest = _scl_list_report(cache, S2_SCL_A, wrong)
        write_json(dest / "report.json", report)
        return {
            "valid_pixel_count": valid_n,
            "bad_class": (bad["class"] if bad else None),
            "bad_share_delivered": (bad["share_of_valid"] if bad else None),
            "bad_share_honest": (honest[bad["class"]] if bad else None),
            "share_mismatch_ratio": (r6(honest[bad["class"]] /
                                        bad["share_of_valid"]) if bad else 1.0),
        }
    if case_id == "report_w_nir_taken_from_green":
        green, nir, _blue, ndvi = _band_stats(cache)
        report = {
            "bands": {
                "green_B03": {"mean_reflectance": green},
                "nir_B08": {"mean_reflectance": green},
            },
            "ndvi_mean_over_valid": ndvi,
        }
        write_json(dest / "report.json", report)
        return {
            "green_mean_reflectance": green,
            "delivered_nir_mean_reflectance": green,
            "truth_nir_mean_reflectance": nir,
            "ndvi_mean_over_valid": ndvi,
            "nir_over_green": r6(nir / green),
        }
    if case_id == "report_w_blue_offset_applied_twice":
        green, nir, blue, ndvi = _band_stats(cache)
        b02, _ = read_tif(cache, S2_B02)
        okb = b02 != 0
        blue_wrong = r6(((b02.astype(np.float64) - 1000.0) * SCALE)[okb].mean())
        report = {
            "bands": {
                "green_B03": {"mean_reflectance": green},
                "nir_B08": {"mean_reflectance": nir},
                "blue_B02": {"mean_reflectance": blue_wrong},
            },
            "ndvi_mean_over_valid": ndvi,
        }
        write_json(dest / "report.json", report)
        return {
            "green_mean_reflectance": green,
            "nir_mean_reflectance": nir,
            "delivered_blue_mean_reflectance": blue_wrong,
            "truth_blue_mean_reflectance": blue,
            "ndvi_mean_over_valid": ndvi,
            "blue_shortfall_abs": r6(abs(blue - blue_wrong)),
        }
    if case_id == "report_c_bands_multi_wa":
        green, nir, blue, ndvi = _band_stats(cache)
        report = {
            "bands": {
                "green_B03": {"mean_reflectance": green},
                "nir_B08": {"mean_reflectance": nir},
                "blue_B02": {"mean_reflectance": blue},
            },
            "ndvi_mean_over_valid": ndvi,
        }
        write_json(dest / "report.json", report)
        return {
            "green_mean_reflectance": green,
            "nir_mean_reflectance": nir,
            "blue_mean_reflectance": blue,
            "ndvi_mean_over_valid": ndvi,
            "ndvi_over_green": r6(ndvi / green),
        }
    if case_id == "report_c_norway_multi":
        z, valid, sel = _norway_stats(cache)
        report = {
            "extremes": {
                "mean_elevation_m": r6(sel.mean()),
                "max_elevation_m": r6(sel.max()),
                "min_elevation_m": r6(sel.min()),
            },
            "usable_share": r6(float(valid.sum()) / z.size),
            "zero_height_valid_count": int((sel == 0).sum()),
        }
        write_json(dest / "report.json", report)
        return dict(report)
    if case_id == "report_c_edge_qa_counts_wc":
        report = _edge_qa_counts(cache)
        write_json(dest / "report.json", report)
        return dict(report)
    raise KeyError(case_id)


# ------------------------------------------------------------------- plain


def _build_plain(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "plain_norway_elevation_multi":
        z, _ = read_tif(cache, COP_NORWAY)
        sel = z.astype(np.float64)
        report = {"mean_elevation_m": r6(sel.mean()),
                  "min_elevation_m": r6(sel.min()),
                  "max_elevation_m": r6(sel.max())}
        write_json(dest / "report.json", report)
        return dict(report)
    if case_id == "plain_ndvi_wa":
        b03, prof = read_tif(cache, S2_B03)
        b08, _ = read_tif(cache, S2_B08)
        scl, _ = read_tif(cache, S2_SCL_A)
        r3 = b03.astype(np.float64) * SCALE
        r8 = b08.astype(np.float64) * SCALE
        ndvi = (r8 - r3) / np.maximum(r8 + r3, 1e-12)
        ok = (b03 != 0) & (b08 != 0)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "ndvi_map.tif", np.where(ok, ndvi, -9999.0), prof2,
                  dtype="float32", nodata=-9999.0)
        t10 = s10(scl)
        result = {"ndvi_mean_over_valid": r6(ndvi[ok].mean()),
                  "ndvi_class_6_mean": r6(ndvi[t10 == 6].mean())}
        write_json(dest / "summary.json", result)
        return result
    if case_id == "plain_blue_reflectance_snow_wa":
        b02, _ = read_tif(cache, S2_B02)
        scl, _ = read_tif(cache, S2_SCL_A)
        t10 = s10(scl)
        truth = float((b02.astype(np.float64) * SCALE)[t10 == 11].mean())
        write_json(dest / "summary.json", {"mean_blue_reflectance_snow": r6(truth)})
        return {"mean_blue_reflectance_snow": r6(truth)}
    if case_id == "plain_feature_count_ne":
        feats, _g, _a, _p = _nz_vectors(cache)
        write_json(dest / "summary.json", {"feature_count": len(feats)})
        return {"feature_count": len(feats)}
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
