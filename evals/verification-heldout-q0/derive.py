#!/usr/bin/env python
"""Deterministic derivation of every verification-heldout-q0 case output.

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
from pyproj import CRS, Geod, Transformer
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import transform as shp_transform

SCALE = 1e-4
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

CASES = [
    # Validity masks (4 wrong, 4 correct) - v0 scene
    "mask_wrong_rejected_class_kept_wa",
    "mask_wrong_qa60_bits_mixed_wa",
    "mask_wrong_water_rejected_wa",
    "mask_wrong_fill_kept_valid_wb",
    "mask_correct_standard_rule_wa",
    "mask_correct_snow_valid_wa",
    "mask_correct_water_veg_only_wa",
    "mask_correct_wedge_all_invalid_wb",
    # Slope in percent and degrees (3 wrong, 3 correct)
    "slope_wrong_degrees_as_metres_geographic_nepal",
    "slope_wrong_latitude_ignored_geographic_svalbard",
    "slope_wrong_unit_confused_projected_svalbard",
    "slope_correct_percent_geographic_nepal",
    "slope_correct_degrees_geographic_nepal",
    "slope_correct_degrees_projected_svalbard",
    # Summary reports (3 wrong, 4 correct)
    "summary_wrong_fill_averaged_in_kauai",
    "summary_wrong_zeros_evicted_kauai",
    "summary_wrong_area_degrees_sq_km_iceland",
    "summary_correct_mean_excluding_fill_kauai",
    "summary_correct_max_elevation_delta",
    "summary_correct_area_geodesic_iceland",
    "summary_correct_perimeter_geodesic_switzerland",
    # Sentinel-2 decodes, two distributions (3 wrong, 4 correct)
    "s2_decode_v0_wrong_offset_applied_twice_wa",
    "s2_decode_v0_correct_scale_only_wa_b03",
    "s2_decode_v0_correct_scale_only_wa_b11",
    "s2_decode_c1_wrong_offset_missing_wa",
    "s2_decode_c1_wrong_raw_dn_delivered_wa",
    "s2_decode_c1_correct_offset_subtracted_wa_b03",
    "s2_decode_c1_correct_offset_subtracted_wa_b11",
    # Fill and vertical units (2 wrong, 2 correct)
    "fillunits_wrong_fill_decoded_as_data_wb",
    "fillunits_wrong_vertical_unit_ignored_kauai",
    "fillunits_correct_3dep_metres_delta",
    "fillunits_correct_wedge_fill_excluded_summary",
    # Plain (4 correct)
    "plain_mean_elevation_nepal",
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
        dest,
        mode="w",
        driver="GTiff",
        tiled=True,
        blockxsize=512,
        blockysize=512,
        compress="deflate",
        predictor=2,
        dtype=dtype,
        crs=prof["crs"],
        transform=prof["transform"],
        nodata=nodata,
        width=out.shape[1],
        height=out.shape[0],
        count=1,
    ) as dst:
        dst.write(out, 1)
    with rasterio.open(dest, mode="r+") as dst:
        dst.build_overviews([2, 4])
    return out


def write_json(dest: Path, obj: dict) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


# ------------------------------------------------------------- validity masks


def _mask_rule(cache: Path, case_id: str):
    if case_id == "mask_correct_wedge_all_invalid_wb" or case_id == "mask_wrong_fill_kept_valid_wb":
        scl, prof = read_tif(cache, V0_WB_SCL)
        rule = np.isin(scl, [4, 5, 6, 7])
        delivered = np.ones_like(scl, dtype=bool) if case_id == "mask_wrong_fill_kept_valid_wb" else rule
        return delivered, rule, prof
    scl, prof = read_tif(cache, V0_SCL)
    rule = {
        "mask_wrong_rejected_class_kept_wa": np.isin(scl, [4, 5, 6, 7, 11]),
        "mask_wrong_qa60_bits_mixed_wa": np.isin(scl, [4, 5, 6, 7, 11]),
        "mask_wrong_water_rejected_wa": np.isin(scl, [4, 5, 6, 7, 11]),
        "mask_correct_standard_rule_wa": np.isin(scl, [4, 5, 6, 7]),
        "mask_correct_snow_valid_wa": np.isin(scl, [4, 5, 6, 7, 11]),
        "mask_correct_water_veg_only_wa": np.isin(scl, [4, 5, 6]),
    }[case_id]
    delivered = {
        "mask_wrong_rejected_class_kept_wa": ~np.isin(scl, [8]),
        "mask_wrong_qa60_bits_mixed_wa": ((1 << scl.astype(np.int64)) & QA60_BITS) == 0,
        "mask_wrong_water_rejected_wa": ~np.isin(scl, [6]),
        "mask_correct_standard_rule_wa": np.isin(scl, [4, 5, 6, 7]),
        "mask_correct_snow_valid_wa": np.isin(scl, [4, 5, 6, 7, 11]),
        "mask_correct_water_veg_only_wa": np.isin(scl, [4, 5, 6]),
    }[case_id]
    return delivered, rule, prof


def _build_mask(cache: Path, out: Path, case_id: str) -> dict:
    delivered, rule, prof = _mask_rule(cache, case_id)
    prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
    write_tif(out / "outputs" / case_id / "validity_mask.tif",
              delivered.astype("uint8"), prof2, dtype="uint8")
    kept = int(delivered.sum())
    total = int(delivered.size)
    result = {
        "usable_pixel_count": kept,
        "usable_fraction": r6(kept / total),
        "invalid_pixel_count": total - kept,
    }
    if case_id.startswith("mask_wrong"):
        result["kept_invalid_pixel_count"] = int((delivered & ~rule).sum())
        result["evicted_valid_pixel_count"] = int((rule & ~delivered).sum())
    return result


# ------------------------------------------------- slope in percent/degrees


def _grads(z: np.ndarray, dx_m: float, dy_m: float):
    zy, zx = np.gradient(z.astype(np.float64), dy_m, dx_m)
    return zx, zy


def _mid_lat(prof: dict, rows: int) -> float:
    res_y = abs(prof["transform"].e)
    return prof["transform"].f - (rows / 2.0) * res_y


def _metres_per_deg(res_deg_x: float, res_deg_y: float, lat_mid: float):
    dy_m = res_deg_y * R_EARTH_M * math.pi / 180.0
    dx_m = res_deg_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat_mid))
    return dx_m, dy_m


def _build_slope(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id in ("slope_correct_percent_geographic_nepal",
                   "slope_correct_degrees_geographic_nepal",
                   "slope_wrong_degrees_as_metres_geographic_nepal"):
        z, prof = read_tif(cache, COP_NEPAL)
        res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
        dx_m, dy_m = _metres_per_deg(res_x, res_y, _mid_lat(prof, z.shape[0]))
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        if case_id == "slope_correct_percent_geographic_nepal":
            zx, zy = _grads(z, dx_m, dy_m)
            val = 100.0 * np.hypot(zx, zy)
            write_tif(dest / "slope.tif", val, prof2, dtype="float32")
            return {"mean_slope_percent": r6(float(val.mean())), "slope_unit": "percent"}
        if case_id == "slope_correct_degrees_geographic_nepal":
            zx, zy = _grads(z, dx_m, dy_m)
            val = np.degrees(np.arctan2(np.hypot(zx, zy), 1.0))
            write_tif(dest / "slope.tif", val, prof2, dtype="float32")
            return {"mean_slope_degrees": r6(float(val.mean())), "slope_unit": "degrees"}
        # wrong: degree spacings used directly as metre lengths
        zx_d, zy_d = _grads(z, res_x, res_y)
        wrong = 100.0 * np.hypot(zx_d, zy_d)
        write_tif(dest / "slope.tif", wrong, prof2, dtype="float32")
        zx, zy = _grads(z, dx_m, dy_m)
        truth = float((100.0 * np.hypot(zx, zy)).mean())
        return {
            "mean_slope_percent": r6(float(wrong.mean())),
            "mismatch_factor": r6(float(wrong.mean()) / truth),
        }
    if case_id == "slope_wrong_latitude_ignored_geographic_svalbard":
        z, prof = read_tif(cache, COP_SVALBARD)
        res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
        dx_m_wrong = res_x * R_EARTH_M * math.pi / 180.0
        dy_m = res_y * R_EARTH_M * math.pi / 180.0
        zx, zy = _grads(z, dx_m_wrong, dy_m)
        wrong = 100.0 * np.hypot(zx, zy)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "slope.tif", wrong, prof2, dtype="float32")
        dx_m_true, _ = _metres_per_deg(res_x, res_y, _mid_lat(prof, z.shape[0]))
        zx_t, zy_t = _grads(z, dx_m_true, dy_m)
        truth = float((100.0 * np.hypot(zx_t, zy_t)).mean())
        return {
            "mean_slope_percent": r6(float(wrong.mean())),
            "mismatch_factor": r6(float(wrong.mean()) / truth),
        }
    if case_id in ("slope_wrong_unit_confused_projected_svalbard",
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
        zx, zy = _grads(z_filled, 30.0, 30.0)
        mag = np.hypot(zx, zy)
        prof_out = {"crs": "EPSG:32633", "transform": t}
        name = "slope.tif"
        if case_id == "slope_correct_degrees_projected_svalbard":
            val = np.where(valid, np.degrees(np.arctan2(mag, 1.0)), -9999.0)
            got = write_tif(dest / name, val, prof_out, dtype="float32",
                            nodata=-9999.0)
            sel = got[got != -9999.0]
            return {"mean_slope_degrees": r6(float(sel.mean(dtype=np.float64))),
                    "slope_unit": "degrees"}
        # wrong: degrees values delivered under the percent label on the same grid
        val = np.where(valid, np.degrees(np.arctan2(mag, 1.0)), -9999.0)
        got = write_tif(dest / name, val, prof_out, dtype="float32", nodata=-9999.0)
        sel = got[got != -9999.0]
        mean_deg = float(sel.mean(dtype=np.float64))
        truth_pct = float((100.0 * mag[valid]).mean())
        return {
            "mean_slope_percent": r6(mean_deg),
            "truth_mean_slope_percent": r6(truth_pct),
            "mismatch_factor": r6(truth_pct / mean_deg),
        }
    raise KeyError(case_id)


# --------------------------------------------------------------- summaries


def _build_summary(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "summary_wrong_fill_averaged_in_kauai":
        z, _ = read_tif(cache, DEP3_KAUAI)
        delivered = float(z.mean(dtype=np.float64))
        truth = float(z[z != DEP3_FILL].mean(dtype=np.float64))
        write_json(dest / "summary.json", {
            "mean_elevation_m": r6(delivered),
            "elevation_unit": "m",
        })
        return {
            "delivered_mean_elevation_m": r6(delivered),
            "truth_mean_elevation_m": r6(truth),
            "mismatch_factor_abs": r6(abs(delivered - truth) / truth),
        }
    if case_id == "summary_wrong_zeros_evicted_kauai":
        z, _ = read_tif(cache, DEP3_KAUAI)
        usable = (z != DEP3_FILL) & (z != 0)
        write_json(dest / "summary.json", {
            "usable_pixel_count": int(usable.sum()),
        })
        truth = int((z != DEP3_FILL).sum())
        return {
            "delivered_usable_pixel_count": int(usable.sum()),
            "truth_usable_pixel_count": truth,
            "evicted_zero_height_pixels": int(truth - int(usable.sum())),
        }
    if case_id == "summary_wrong_area_degrees_sq_km_iceland":
        geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
        feat = next(f for f in geo["features"] if f["properties"].get("NAME") == "Iceland")
        geom = shape(feat["geometry"])
        deg2 = float(geom.area)
        committed = round(deg2, 6)
        polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
        geod = Geod(ellps="WGS84")
        truth = 0.0
        for p in polys:
            lons, lats = np.array(p.exterior.coords).T
            area, _ = geod.polygon_area_perimeter(lons, lats)
            truth += abs(area)
            for ring in p.interiors:
                lons, lats = np.array(ring.coords).T
                area, _ = geod.polygon_area_perimeter(lons, lats)
                truth -= abs(area)
        truth = abs(truth) / 1e6
        write_json(dest / "summary.json", {
            "quantity": "country_area",
            "area_sq_km": committed,
        })
        return {
            "delivered_area_sq_km": committed,
            "truth_area_sq_km": r6(truth),
            "mismatch_factor": r6(truth / committed),
        }
    if case_id == "summary_correct_mean_excluding_fill_kauai":
        z, _ = read_tif(cache, DEP3_KAUAI)
        sel = z[z != DEP3_FILL]
        write_json(dest / "summary.json", {
            "mean_elevation_m": r6(float(sel.mean())),
            "usable_pixel_count": int(sel.size),
        })
        return {"mean_elevation_m": r6(float(sel.mean())),
                "usable_pixel_count": int(sel.size)}
    if case_id == "summary_correct_max_elevation_delta":
        z, _ = read_tif(cache, DEP3_DELTA)
        sel = z[z != DEP3_FILL]
        write_json(dest / "summary.json", {
            "max_elevation_m": r6(float(sel.max())),
            "elevation_unit": "m",
            "elevation_vertical_datum": "NAVD 88",
        })
        return {"max_elevation_m": r6(float(sel.max())),
                "min_elevation_m": r6(float(sel.min()))}
    if case_id in ("summary_correct_area_geodesic_iceland",
                   "summary_correct_perimeter_geodesic_switzerland"):
        geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
        name = "Iceland" if case_id.endswith("iceland") else "Switzerland"
        feat = next(f for f in geo["features"] if f["properties"].get("NAME") == name)
        geom = shape(feat["geometry"])
        geod = Geod(ellps="WGS84")
        if case_id.endswith("iceland"):
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
            value_km2 = abs(total) / 1e6
            write_json(dest / "summary.json", {
                "quantity": "country_area",
                "area_sq_km": round(value_km2, 4),
            })
            return {"area_sq_km": round(value_km2, 4)}
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        total = 0.0
        for p in polys:
            lons, lats = np.array(p.exterior.coords).T
            _, _, d = geod.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
            total += float(np.sum(d))
        value_km = total / 1000.0
        write_json(dest / "summary.json", {
            "quantity": "boundary_perimeter",
            "boundary_perimeter_km": round(value_km, 4),
        })
        return {"boundary_perimeter_km": round(value_km, 4)}
    raise KeyError(case_id)


# ------------------------------------------------------------- s2 decodes


def _v0_band(cache: Path, band: str):
    arr, prof = read_tif(cache, f"s2-v0/wa_{band}.tif")
    return arr, prof


def _c1_band(cache: Path, band: str):
    arr, prof = read_tif(cache, f"s2-c1/wa_{band}.tif")
    return arr, prof


def _build_s2_decode(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    band = "B11" if case_id.endswith("_b11") else "B03"
    if case_id.startswith("s2_decode_v0"):
        dn, prof = _v0_band(cache, band)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        usable = dn != 0
        truth_mean = float((dn[usable].astype(np.float64) * SCALE).mean())
        if case_id == "s2_decode_v0_wrong_offset_applied_twice_wa":
            decoded = (dn.astype(np.float64) - 1000.0) * SCALE
            write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float64")
            shortfall = truth_mean - float(decoded[usable].mean())
            return {"mean_reflectance_delivered": r6(float(decoded[usable].mean())),
                    "shortfall_mean_reflectance": r6(shortfall)}
        val = dn.astype(np.float64) * SCALE
        write_tif(dest / "reflectance.tif", val, prof2, dtype="float32")
        return {"mean_reflectance": r6(truth_mean),
                "fill_pixel_count": int((dn == 0).sum())}
    if case_id.startswith("s2_decode_c1"):
        dn, prof = _c1_band(cache, band)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        usable = dn != 0
        truth_mean = float(((dn[usable].astype(np.float64) - 1000.0) * SCALE).mean())
        if case_id == "s2_decode_c1_wrong_offset_missing_wa":
            decoded = dn.astype(np.float64) * SCALE
            write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float64")
            excess = float(decoded[usable].mean()) - truth_mean
            return {"mean_reflectance_delivered": r6(float(decoded[usable].mean())),
                    "excess_mean_reflectance": r6(excess)}
        if case_id == "s2_decode_c1_wrong_raw_dn_delivered_wa":
            write_tif(dest / "reflectance.tif", dn.astype(np.float64), prof2,
                      dtype="float64")
            raw_mean = float(dn[usable].mean(dtype=np.float64))
            return {"mean_reflectance_delivered": r6(raw_mean),
                    "delivered_over_truth": r6(raw_mean / truth_mean)}
        decoded = (dn.astype(np.float64) - 1000.0) * SCALE
        write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float32")
        return {"mean_reflectance": r6(truth_mean),
                "fill_pixel_count": int((dn == 0).sum())}
    raise KeyError(case_id)


# --------------------------------------------------- fill and vertical units


def _build_fillunits(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "fillunits_wrong_fill_decoded_as_data_wb":
        dn, prof = read_tif(cache, V0_WB_B03)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        decoded = dn.astype(np.float64) * SCALE
        write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float32")
        write_json(dest / "summary.json", {
            "usable_pixel_fraction": 1.0,
            "mean_reflectance": r6(float(decoded.mean())),
        })
        return {"falsely_usable_pixel_count": int(dn.size),
                "truth_usable_pixel_count": int((dn != 0).sum())}
    if case_id == "fillunits_wrong_vertical_unit_ignored_kauai":
        z, prof = read_tif(cache, DEP3_KAUAI)
        sel = z[z != DEP3_FILL]
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "elevation_delivered.tif", z.astype("float64"), prof2,
                  dtype="float64")
        mean_m = float(sel.mean())
        mean_ft_truth = mean_m * 3.280839895013123
        return {
            "delivered_mean_elevation_ft": r6(mean_m),
            "truth_mean_elevation_ft": r6(mean_ft_truth),
            "mismatch_factor": r6(mean_ft_truth / mean_m),
        }
    if case_id == "fillunits_correct_3dep_metres_delta":
        z, _ = read_tif(cache, DEP3_DELTA)
        sel = z[z != DEP3_FILL]
        write_json(dest / "summary.json", {
            "mean_elevation_m": r6(float(sel.mean())),
            "elevation_unit": "m",
            "elevation_vertical_datum": "NAVD 88",
            "usable_pixel_count": int(sel.size),
        })
        return {"mean_elevation_m": r6(float(sel.mean())),
                "usable_pixel_count": int(sel.size)}
    if case_id == "fillunits_correct_wedge_fill_excluded_summary":
        dn, _ = read_tif(cache, V0_WB_B03)
        usable = dn != 0
        write_json(dest / "summary.json", {
            "usable_pixel_count": int(usable.sum()),
            "mean_reflectance": None if not usable.any() else r6(float((dn[usable].astype(np.float64) * SCALE).mean())),
        })
        return {"usable_pixel_count": int(usable.sum())}
    raise KeyError(case_id)


# -------------------------------------------------------------------- plain


def _build_plain(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "plain_mean_elevation_nepal":
        z, _ = read_tif(cache, COP_NEPAL)
        sel = z.astype(np.float64)
        write_json(dest / "summary.json", {
            "mean_elevation_m": r6(sel.mean()),
            "min_elevation_m": r6(sel.min()),
            "max_elevation_m": r6(sel.max()),
            "elevation_unit": "m",
        })
        return {"mean_elevation_m": r6(sel.mean())}
    if case_id == "plain_ndvi_v0_window_a":
        b03, prof = read_tif(cache, "s2-v0/wa_B03.tif")
        b08, _p = read_tif(cache, "s2-v0/wa_B08.tif")
        scl, _ps = read_tif(cache, V0_SCL)
        r3 = b03.astype(np.float64) * SCALE
        r8 = b08.astype(np.float64) * SCALE
        ndvi = (r8 - r3) / np.maximum(r8 + r3, 1e-12)
        ok = (b03 != 0) & (b08 != 0)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "ndvi_map.tif", np.where(ok, ndvi, -9999.0), prof2,
                  dtype="float32", nodata=-9999.0)
        s10 = np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)
        result = {"ndvi_over_all_bands_valid": r6(ndvi[ok].mean())}
        for cls, key in ((4, "ndvi_class_4_vegetation_mean"),
                         (6, "ndvi_class_6_water_mean"),
                         (11, "ndvi_class_11_snow_mean")):
            result[key] = r6(ndvi[s10 == cls].mean())
        write_json(dest / "summary.json", result)
        return result
    if case_id == "plain_blue_reflectance_snow_v0":
        b02, _ = read_tif(cache, "s2-v0/wa_B02.tif")
        scl, _ps = read_tif(cache, V0_SCL)
        s10 = np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)
        m = s10 == 11
        r2 = b02.astype(np.float64) * SCALE
        write_json(dest / "summary.json", {
            "mean_blue_reflectance_snow": r6(float(r2[m].mean())),
        })
        return {"mean_blue_reflectance_snow": r6(float(r2[m].mean()))}
    if case_id == "plain_feature_count_ne":
        geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
        write_json(dest / "summary.json", {"feature_count": len(geo["features"])})
        return {"feature_count": len(geo["features"])}
    raise KeyError(case_id)


def build_case(cache: Path, out: Path, case_id: str) -> dict:
    if case_id.startswith("mask_"):
        return _build_mask(cache, out, case_id)
    if case_id.startswith("slope_"):
        return _build_slope(cache, out, case_id)
    if case_id.startswith("summary_"):
        return _build_summary(cache, out, case_id)
    if case_id.startswith("s2_decode_"):
        return _build_s2_decode(cache, out, case_id)
    if case_id.startswith("fillunits_"):
        return _build_fillunits(cache, out, case_id)
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
