#!/usr/bin/env python
"""Deterministic derivation of every case's delivered outputs from cache.

Usage:
    python derive.py <cache-dir> <out-dir>

For each case id below, builds the delivered artifact(s) under
<out-dir>/outputs/<case-id>/ and prints a JSON map of the numbers each case
builder produced to stdout (sorted keys, rounded to 6 decimals). Runs with the
same cache are byte-identical.
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

SCALE = 1e-4            # reflectance scale as found in the STAC item
DEP3_FILL = -999999.0
R_EARTH_M = 6378137.0

# ESA Sentinel-2 L2A scene classification (SCL); class meanings are documented
# in the ESA Sentinel-2 product guide, not inside the fetched files.
QA60_BITS = (1 << 10) | (1 << 11)

S2_B03 = "s2/wa_B03.tif"
S2_B11 = "s2/wa_B11.tif"
S2_SCL = "s2/wa_SCL.tif"
S2_WB_SCL = "s2/wb_SCL.tif"
S2_WB_B03 = "s2/wb_B03.tif"
COP_NEPAL = "copdem/n28e084_win.tif"
COP_SVALBARD = "copdem/n78e016_win.tif"
DEP3_DELTA = "usgs3dep/USGS_13_n31w091_win.tif"
DEP3_KAUAI = "usgs3dep/USGS_13_n22w159_win.tif"
NE_COUNTRIES = "naturalearth/ne_110m_admin_0_countries.geojson"

CASES = [
    # QA masking (4 wrong)
    "qa_masking_wrong_cloud_medium_kept_wa",
    "qa_masking_wrong_qa60_bits_mixed_wa",
    "qa_masking_wrong_water_masked_wa",
    "qa_masking_wrong_shadow_kept_wa",
    # QA masking (4 correct)
    "qa_masking_correct_standard_wa",
    "qa_masking_correct_snow_valid_wa",
    "qa_masking_correct_water_veg_only_wa",
    "qa_masking_correct_wedge_nodata_wb",
    # Scale, offset and fill (3 wrong)
    "scale_wrong_raw_packed_wa_b03",
    "scale_wrong_offset_sign_flipped_wa_b03",
    "scale_wrong_fill_decoded_as_data_wb_b03",
    # Scale, offset and fill (3 correct)
    "scale_correct_standard_decode_wa_b03",
    "scale_correct_swir_decode_wa_b11",
    "scale_correct_wedge_all_fill_wb_b03",
    # Elevation units and slope (3 wrong)
    "elevation_wrong_unit_ignored_kauai",
    "elevation_wrong_degrees_as_metres_nepal",
    "elevation_wrong_latitude_ignored_svalbard",
    # Elevation units and slope (3 correct)
    "elevation_correct_slope_metres_nepal",
    "elevation_correct_3dep_metres_delta",
    "elevation_correct_svalbard_projected_slope",
    # Nodata (2 wrong)
    "nodata_wrong_fill_averaged_in_kauai",
    "nodata_wrong_real_zeros_evicted_kauai",
    # Nodata (2 correct)
    "nodata_correct_fill_excluded_mean_kauai",
    "nodata_correct_delta_zeros_kept",
    # Delivered metric values (3 wrong)
    "metrics_wrong_area_degrees_sq_km",
    "metrics_wrong_buffer_degrees_100km",
    "metrics_wrong_perimeter_degrees_km",
    # Delivered metric values (2 correct)
    "metrics_correct_area_geodesic",
    "metrics_correct_buffer_geodesic_100km",
    "metrics_correct_perimeter_geodesic",
    # Plain (4 correct)
    "plain_mean_elevation_nepal",
    "plain_ndvi_window_a",
    "plain_blue_reflectance_snow_wa",
    "plain_ne_feature_count",
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


# ---------------------------------------------------------------- QA masking


def _build_qa(cache: Path, out: Path, case_id: str) -> dict:
    if case_id == "qa_masking_correct_wedge_nodata_wb":
        scl, prof = read_tif(cache, S2_WB_SCL)
        kept = np.isin(scl, [4, 5, 6, 7])
        rule = kept
    else:
        scl, prof = read_tif(cache, S2_SCL)
        rule = {
            "qa_masking_wrong_cloud_medium_kept_wa": np.isin(scl, [4, 5, 6, 7, 11]),
            "qa_masking_wrong_qa60_bits_mixed_wa": np.isin(scl, [4, 5, 6, 7, 11]),
            "qa_masking_wrong_water_masked_wa": np.isin(scl, [4, 5, 6, 7, 11]),
            "qa_masking_wrong_shadow_kept_wa": np.isin(scl, [4, 5, 6, 7, 11]),
            "qa_masking_correct_standard_wa": np.isin(scl, [4, 5, 6, 7]),
            "qa_masking_correct_snow_valid_wa": np.isin(scl, [4, 5, 6, 7, 11]),
            "qa_masking_correct_water_veg_only_wa": np.isin(scl, [4, 5, 6]),
        }[case_id]
        kept = {
            "qa_masking_wrong_cloud_medium_kept_wa": ~np.isin(scl, [8]),
            "qa_masking_wrong_qa60_bits_mixed_wa":
                ((1 << scl.astype(np.int64)) & QA60_BITS) == 0,
            "qa_masking_wrong_water_masked_wa": ~np.isin(scl, [6]),
            "qa_masking_wrong_shadow_kept_wa": ~np.isin(scl, [3]),
            "qa_masking_correct_standard_wa": np.isin(scl, [4, 5, 6, 7]),
            "qa_masking_correct_snow_valid_wa": np.isin(scl, [4, 5, 6, 7, 11]),
            "qa_masking_correct_water_veg_only_wa": np.isin(scl, [4, 5, 6]),
        }[case_id]
    prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
    write_tif(out / "outputs" / case_id / "validity_mask.tif",
              kept.astype("uint8"), prof2, dtype="uint8")
    total = int(kept.size)
    kept_cnt = int(kept.sum())
    wrong_lumps = int((kept & ~rule).sum())
    evicted = int((~kept & rule).sum())
    if case_id == "qa_masking_wrong_water_masked_wa":
        badly = evicted
    else:
        badly = wrong_lumps
    return {
        "valid_pixel_count": kept_cnt,
        "valid_pixel_fraction": r6(kept_cnt / total),
        "invalid_pixel_count": total - kept_cnt,
        "badly_classified_pixel_count": badly,
    }


# ------------------------------------------------- scale, offset and fill


def _decode(arr: np.ndarray) -> np.ndarray:
    return arr.astype(np.float64) * SCALE


def _build_scale(cache: Path, out: Path, case_id: str) -> dict:
    if case_id in ("scale_correct_wedge_all_fill_wb_b03",
                   "scale_wrong_fill_decoded_as_data_wb_b03"):
        dn, prof = read_tif(cache, S2_WB_B03)
    elif case_id == "scale_correct_swir_decode_wa_b11":
        dn, prof = read_tif(cache, S2_B11)
    else:
        dn, prof = read_tif(cache, S2_B03)
    prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
    dest = out / "outputs" / case_id
    if case_id == "scale_wrong_raw_packed_wa_b03":
        write_tif(dest / "reflectance.tif", dn.astype(np.float64), prof2,
                  dtype="float64")
        truth_mean = float(_decode(dn[dn != 0]).mean())
        ratio = float(dn.mean(dtype=np.float64)) / truth_mean
        return {"mean_reflectance": r6(float(dn.mean(dtype=np.float64))),
                "delivered_over_truth_mean_reflectance": r6(ratio)}
    if case_id == "scale_wrong_offset_sign_flipped_wa_b03":
        decoded = (dn.astype(np.float64) + 1000.0) * SCALE
        write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float64")
        truth_mean = float(_decode(dn[dn != 0]).mean())
        excess = float(decoded.mean(dtype=np.float64)) - truth_mean
        return {"mean_reflectance": r6(float(decoded.mean())),
                "excess_mean_reflectance": r6(excess)}
    if case_id == "scale_wrong_fill_decoded_as_data_wb_b03":
        decoded = _decode(dn)
        write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float32")
        return {
            "mean_reflectance": r6(float(decoded.mean())),
            "valid_pixel_fraction": 1.0,
            "valid_pixel_count": int(dn.size),
        }
    if case_id == "scale_correct_standard_decode_wa_b03":
        filled = dn == 0
        decoded = _decode(dn)
        write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float32")
        return {
            "mean_reflectance": r6(float(decoded[~filled].mean())),
            "fill_pixel_count": int(filled.sum()),
        }
    if case_id == "scale_correct_swir_decode_wa_b11":
        filled = dn == 0
        decoded = _decode(dn)
        write_tif(dest / "reflectance.tif", decoded, prof2, dtype="float32")
        return {
            "mean_reflectance": r6(float(decoded[~filled].mean())),
            "fill_pixel_count": int(filled.sum()),
        }
    if case_id == "scale_correct_wedge_all_fill_wb_b03":
        filled = dn == 0
        decoded = _decode(dn)
        write_tif(dest / "validity_mask.tif", (~filled).astype("uint8"), prof2,
                  dtype="uint8")
        return {
            "valid_pixel_count": int((~filled).sum()),
            "mean_reflectance": r6(float(decoded[~filled].mean())) if (~filled).any() else None,
        }
    raise KeyError(case_id)


# --------------------------------------------------- elevation units & slope


def _slope_pct(z: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    zy, zx = np.gradient(z.astype(np.float64), dy_m, dx_m)
    return 100.0 * np.hypot(zx, zy)


def _slope_deg(z: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    zy, zx = np.gradient(z.astype(np.float64), dy_m, dx_m)
    return np.degrees(np.arctan2(np.hypot(zx, zy), 1.0))


def _mid_lat(prof: dict, rows: int) -> float:
    res_y = abs(prof["transform"].e)
    return prof["transform"].f - (rows / 2.0) * res_y


def _metres_per_deg(res_deg_x: float, res_deg_y: float, lat_mid: float):
    dy_m = res_deg_y * R_EARTH_M * math.pi / 180.0
    dx_m = res_deg_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat_mid))
    return dx_m, dy_m


def _build_elevation(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "elevation_correct_3dep_metres_delta":
        z, prof = read_tif(cache, DEP3_DELTA)
        sel = z[z != DEP3_FILL]
        write_json(dest / "elevation_summary.json", {
            "elevation_unit": "m",
            "mean_elevation_m": r6(float(sel.mean())),
            "min_elevation_m": r6(float(sel.min())),
            "max_elevation_m": r6(float(sel.max())),
            "valid_pixel_count": int(sel.size),
        })
        return {"mean_elevation_m": r6(float(sel.mean())),
                "valid_pixel_count": int(sel.size)}
    if case_id == "elevation_wrong_unit_ignored_kauai":
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
    if case_id == "elevation_correct_slope_metres_nepal":
        z, prof = read_tif(cache, COP_NEPAL)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
        dx_m, dy_m = _metres_per_deg(res_x, res_y, _mid_lat(prof, z.shape[0]))
        slope = _slope_pct(z, dx_m, dy_m)
        write_tif(dest / "slope_percent.tif", slope, prof2, dtype="float32")
        return {"mean_slope_percent": r6(float(slope.mean()))}
    if case_id == "elevation_wrong_degrees_as_metres_nepal":
        z, prof = read_tif(cache, COP_NEPAL)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
        wrong = _slope_pct(z, res_x, res_y)
        write_tif(dest / "slope_percent.tif", wrong, prof2, dtype="float32")
        dx_m, dy_m = _metres_per_deg(res_x, res_y, _mid_lat(prof, z.shape[0]))
        truth = _slope_pct(z, dx_m, dy_m)
        return {
            "delivered_mean_slope_percent": r6(float(wrong.mean())),
            "mismatch_factor": r6(float(wrong.mean() / truth.mean())),
        }
    if case_id == "elevation_wrong_latitude_ignored_svalbard":
        z, prof = read_tif(cache, COP_SVALBARD)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        res_x, res_y = abs(prof["transform"].a), abs(prof["transform"].e)
        dx_m_wrong = res_x * R_EARTH_M * math.pi / 180.0
        dy_m = res_y * R_EARTH_M * math.pi / 180.0
        wrong = _slope_pct(z, dx_m_wrong, dy_m)
        write_tif(dest / "slope_percent.tif", wrong, prof2, dtype="float32")
        dx_m_true, _ = _metres_per_deg(res_x, res_y, _mid_lat(prof, z.shape[0]))
        truth = _slope_pct(z, dx_m_true, dy_m)
        return {
            "delivered_mean_slope_percent": r6(float(wrong.mean())),
            "mismatch_factor": r6(float(wrong.mean() / truth.mean())),
        }
    if case_id == "elevation_correct_svalbard_projected_slope":
        z, prof = read_tif(cache, COP_SVALBARD)
        with rasterio.open(cache / COP_SVALBARD) as src:
            t, new_w, new_h = calculate_default_transform(
                src.crs, "EPSG:32633", src.width, src.height, *src.bounds,
                resolution=30.0)
        dst_w, dst_h = int(new_w), int(new_h)
        dst = np.full((dst_h, dst_w), np.nan, dtype=np.float64)
        reproject(source=z, destination=dst,
                  src_transform=prof["transform"], src_crs=prof["crs"],
                  dst_transform=t, dst_crs="EPSG:32633",
                  src_nodata=prof["nodata"], dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
        valid = ~np.isnan(dst)
        if int(valid.sum()) < 100:
            raise RuntimeError("projected Svalbard window produced too few cells")
        z_filled = np.where(valid, dst, 0.0)
        slope = np.where(valid, _slope_deg(z_filled, 30.0, 30.0), -9999.0)
        prof_out = {"crs": "EPSG:32633", "transform": t}
        outarr = write_tif(dest / "slope_deg.tif", slope, prof_out,
                           dtype="float32", nodata=-9999.0)
        sel = outarr[outarr != -9999.0]
        return {"mean_slope_degrees": r6(float(sel.mean(dtype=np.float64)))}
    raise KeyError(case_id)


# -------------------------------------------------------------------- nodata


def _build_nodata(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "nodata_wrong_fill_averaged_in_kauai":
        z, prof = read_tif(cache, DEP3_KAUAI)
        sel_all = z.astype("float64")
        sel_valid = z[z != DEP3_FILL].astype("float64")
        write_json(dest / "delivered_mean_including_fill.json", {
            "mean_elevation_m_including_fill": r6(float(sel_all.mean())),
        })
        delivered = float(sel_all.mean())
        truth = float(sel_valid.mean())
        return {
            "delivered_mean_elevation_m_including_fill": r6(delivered),
            "truth_mean_elevation_m_excluding_fill": r6(truth),
            "mismatch_factor_abs": r6(abs(delivered - truth) / truth),
        }
    if case_id == "nodata_wrong_real_zeros_evicted_kauai":
        z, prof = read_tif(cache, DEP3_KAUAI)
        valid_truth = z != DEP3_FILL
        delivered = (z != DEP3_FILL) & (z != 0)
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "validity_mask.tif", delivered.astype("uint8"),
                  prof2, dtype="uint8")
        return {"wrongly_evicted_zero_height_pixels":
                int((valid_truth & ~delivered).sum())}
    if case_id == "nodata_correct_fill_excluded_mean_kauai":
        z, prof = read_tif(cache, DEP3_KAUAI)
        valid = z != DEP3_FILL
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "validity_mask.tif", valid.astype("uint8"), prof2,
                  dtype="uint8")
        sel = z[valid]
        return {
            "mean_elevation_m_excluding_fill": r6(float(sel.mean())),
            "valid_pixel_count": int(sel.size),
            "zero_m_pixel_count_in_valid": int((sel == 0).sum()),
        }
    if case_id == "nodata_correct_delta_zeros_kept":
        z, prof = read_tif(cache, DEP3_DELTA)
        valid = z != DEP3_FILL
        prof2 = {"crs": prof["crs"], "transform": prof["transform"]}
        write_tif(dest / "validity_mask.tif", valid.astype("uint8"), prof2,
                  dtype="uint8")
        sel = z[valid]
        return {
            "valid_pixel_count": int(sel.size),
            "zero_m_pixel_count_in_valid": int((sel == 0).sum()),
        }
    raise KeyError(case_id)


# ------------------------------------------------------------ metric values


def _geod_area_km2(geom) -> float:
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    total = []
    for p in polys:
        lons, lats = np.array(p.exterior.coords).T
        area, _ = geod.polygon_area_perimeter(lons, lats)
        total.append(abs(area))
        for ring in p.interiors:
            lons, lats = np.array(ring.coords).T
            area, _ = geod.polygon_area_perimeter(lons, lats)
            total.append(-abs(area))
    return abs(sum(total)) / 1e6


def _geod_perimeter_km(geom) -> float:
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    total = 0.0
    for p in polys:
        lons, lats = np.array(p.exterior.coords).T
        _, _, dist = geod.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
        total += float(np.sum(dist))
    return total / 1000.0


def _single_ring_multipolygon(geom) -> "MultiPolygonLike":
    if geom.geom_type == "MultiPolygon":
        return geom
    from shapely.geometry import MultiPolygon
    return MultiPolygon([geom])


def _build_metrics(cache: Path, out: Path, case_id: str) -> dict:
    geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))

    def feature(name: str) -> dict:
        for f in geo["features"]:
            if f["properties"].get("NAME") == name:
                return f
        raise KeyError(name)

    dest = out / "outputs" / case_id
    if case_id == "metrics_wrong_area_degrees_sq_km":
        feat = feature("Iceland")
        geom = shape(feat["geometry"])
        deg2 = float(geom.area)
        committed = round(deg2, 6)
        truth = _geod_area_km2(_single_ring_multipolygon(geom))
        write_json(dest / "iceland_area_wrong.geojson", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NAME": "Iceland", "area_sq_km": committed},
                "geometry": feat["geometry"],
            }],
        })
        return {
            "delivered_area_sq_km": committed,
            "truth_area_sq_km": r6(truth),
            "mismatch_factor": r6(truth / committed),
        }
    if case_id == "metrics_correct_area_geodesic":
        feat = feature("Iceland")
        geom = shape(feat["geometry"])
        km2 = _geod_area_km2(_single_ring_multipolygon(geom))
        write_json(dest / "iceland_area_correct.geojson", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NAME": "Iceland", "area_sq_km": round(km2, 4)},
                "geometry": feat["geometry"],
            }],
        })
        return {"area_sq_km": round(km2, 4)}
    if case_id == "metrics_wrong_buffer_degrees_100km":
        feat = feature("Iceland")
        geom = shape(feat["geometry"])
        buf = geom.buffer(1.0)
        deg2 = float(buf.area)
        write_json(dest / "iceland_buffer_wrong.geojson", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NAME": "Iceland", "buffer_km": 100.0,
                               "buffer_area_sq_km": round(deg2, 6)},
                "geometry": mapping(buf),
            }],
        })
        truth = _geod_area_km2(_single_ring_multipolygon(buf))
        return {
            "delivered_buffer_area_sq_km": round(deg2, 6),
            "truth_buffer_area_sq_km_at_100km": r6(truth),
            "mismatch_factor": r6(truth / round(deg2, 6)),
        }
    if case_id == "metrics_correct_buffer_geodesic_100km":
        feat = feature("Iceland")
        geom = shape(feat["geometry"])
        c = geom.centroid
        ae = CRS.from_proj4(
            f"+proj=aeqd +lat_0={c.y!r} +lon_0={c.x!r} +datum=WGS84 +units=m "
            "+no_defs")
        fwd = Transformer.from_crs("EPSG:4326", ae, always_xy=True)
        back = Transformer.from_crs(ae, "EPSG:4326", always_xy=True)
        geom_m = shp_transform(lambda x, y, z=None: fwd.transform(x, y), geom)
        buf_m = geom_m.buffer(100_000.0)
        buf_ll = shp_transform(lambda x, y, z=None: back.transform(x, y), buf_m)
        area_km2 = _geod_area_km2(_single_ring_multipolygon(buf_ll))
        write_json(dest / "iceland_buffer_correct.geojson", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NAME": "Iceland", "buffer_km": 100.0,
                               "buffer_area_sq_km": round(area_km2, 4)},
                "geometry": mapping(buf_ll),
            }],
        })
        return {"buffer_area_sq_km": round(area_km2, 4)}
    if case_id == "metrics_wrong_perimeter_degrees_km":
        feat = feature("Switzerland")
        geom = shape(feat["geometry"])
        deg_len = float(geom.length)
        committed = round(deg_len, 6)
        truth = _geod_perimeter_km(geom)
        write_json(dest / "switzerland_perimeter_wrong.geojson", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NAME": "Switzerland",
                               "boundary_perimeter_km": committed},
                "geometry": feat["geometry"],
            }],
        })
        return {
            "delivered_boundary_perimeter_km": committed,
            "truth_boundary_perimeter_km": r6(truth),
            "mismatch_factor": r6(truth / committed),
        }
    if case_id == "metrics_correct_perimeter_geodesic":
        feat = feature("Switzerland")
        geom = shape(feat["geometry"])
        km = _geod_perimeter_km(geom)
        write_json(dest / "switzerland_perimeter_correct.geojson", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NAME": "Switzerland",
                               "boundary_perimeter_km": round(km, 4)},
                "geometry": feat["geometry"],
            }],
        })
        return {"boundary_perimeter_km": round(km, 4)}
    raise KeyError(case_id)


# --------------------------------------------------------------------- plain


def _build_plain(cache: Path, out: Path, case_id: str) -> dict:
    dest = out / "outputs" / case_id
    if case_id == "plain_mean_elevation_nepal":
        z, prof = read_tif(cache, COP_NEPAL)
        sel = z.astype(np.float64)
        write_json(dest / "elevation_summary.json", {
            "mean_elevation_m": r6(sel.mean()),
            "min_elevation_m": r6(sel.min()),
            "max_elevation_m": r6(sel.max()),
            "elevation_unit": "m",
        })
        return {"mean_elevation_m": r6(sel.mean())}
    if case_id == "plain_ndvi_window_a":
        b03, prof = read_tif(cache, S2_B03)
        b08, _prof8 = read_tif(cache, "s2/wa_B08.tif")
        scl, _prof_s = read_tif(cache, S2_SCL)
        r3 = _decode(b03)
        r8 = _decode(b08)
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
        write_json(dest / "ndvi_summary.json", result)
        return result
    if case_id == "plain_blue_reflectance_snow_wa":
        b02, _prof = read_tif(cache, "s2/wa_B02.tif")
        scl, _prof_s = read_tif(cache, S2_SCL)
        s10 = np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)
        m = s10 == 11
        r2 = _decode(b02)
        write_json(dest / "blue_reflectance_summary.json", {
            "mean_blue_reflectance_snow": r6(float(r2[m].mean())),
            "scale_as_found": 1e-4,
        })
        return {"mean_blue_reflectance_snow": r6(float(r2[m].mean()))}
    if case_id == "plain_ne_feature_count":
        geo = json.loads((cache / NE_COUNTRIES).read_text(encoding="utf-8"))
        write_json(dest / "feature_count.json", {"feature_count": len(geo["features"])})
        return {"feature_count": len(geo["features"])}
    raise KeyError(case_id)


def build_case(cache: Path, out: Path, case_id: str) -> dict:
    if case_id.startswith("qa_"):
        return _build_qa(cache, out, case_id)
    if case_id.startswith("scale_"):
        return _build_scale(cache, out, case_id)
    if case_id.startswith("elevation_"):
        return _build_elevation(cache, out, case_id)
    if case_id.startswith("nodata_"):
        return _build_nodata(cache, out, case_id)
    if case_id.startswith("metrics_"):
        return _build_metrics(cache, out, case_id)
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
