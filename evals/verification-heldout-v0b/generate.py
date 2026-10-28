"""Deterministic generator for Terraproof Phase 7 held-out verification cases (V0b).

Generates synthetic source datasets and deliverables for 48 held-out cases across
6 families:
1. metric_in_geographic_coords (8 cases: 4 wrong, 4 correct)
2. qa_masking (8 cases: 4 wrong, 4 correct)
3. terrain_slope_unlabeled (8 cases: 4 wrong, 4 correct)
4. vertical_datums_and_units (8 cases: 4 wrong, 4 correct)
5. nodata_and_scale_regression (8 cases: 4 wrong, 4 correct)
6. plain (8 cases: 0 wrong, 8 correct)

All rasters are written as tiled GeoTIFFs with overviews and declared nodata.
Uses only numpy, rasterio, pyproj, shapely, pyogrio, and standard library.
Never imports terraproof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pyogrio.raw
import pyproj
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, Polygon


def sha256_file(path: Path) -> str:
    """Compute hex SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def write_tiled_raster(
    path: Path,
    data: np.ndarray,
    crs: str,
    transform: rasterio.Affine,
    nodata: float | int | None = None,
    dtype: str | None = None,
    build_ovr: bool = True,
) -> None:
    """Deterministically write a 2D numpy array as a tiled GeoTIFF with overviews."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if dtype is None:
        dtype = str(data.dtype)
    height, width = data.shape

    kwargs: Dict[str, Any] = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": dtype,
        "crs": crs,
        "transform": transform,
        "tiled": True,
        "blockxsize": 64,
        "blockysize": 64,
    }
    if nodata is not None:
        kwargs["nodata"] = nodata

    with rasterio.open(path, "w", **kwargs) as ds:
        ds.write(data.astype(dtype), 1)
        if build_ovr and height >= 32 and width >= 32:
            ds.build_overviews([2, 4], Resampling.nearest)


def write_vector_geojson(
    path: Path,
    geoms: List[Any],
    field_data: Dict[str, List[Any]],
    geom_type: str,
    crs: str = "EPSG:4326",
) -> None:
    """Deterministically write vector features to GeoJSON using pyogrio.raw."""
    path.parent.mkdir(parents=True, exist_ok=True)
    layer_name = path.stem
    wkb_geoms = np.array([g.wkb for g in geoms], dtype=object)
    fields = list(field_data.keys())
    arrays = [np.array(field_data[f]) for f in fields]
    pyogrio.raw.write(
        str(path),
        wkb_geoms,
        arrays,
        fields,
        geometry_type=geom_type,
        crs=crs,
        driver="GeoJSON",
        layer=layer_name,
    )


def generate_all(out_dir: Path) -> Dict[str, str]:
    """Generate all 48 verification cases into out_dir deterministically."""
    np.random.seed(42)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: Dict[str, str] = {}

    def track(rel_path: str) -> None:
        p = out_dir / rel_path
        if not p.is_file():
            raise FileNotFoundError(f"Expected generated file not found: {p}")
        manifest[rel_path] = sha256_file(p)

    # =========================================================================
    # Family 1: Metric values delivered in geographic coordinates (8 cases)
    # =========================================================================

    # Case 1: heldout-v0b-geom-01-wrong (Highland estate: planar deg2 area stored as area_m2)
    p1 = Polygon([(-4.120, 57.000), (-4.100, 57.000), (-4.100, 57.0125), (-4.120, 57.0125), (-4.120, 57.000)])
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-01-wrong/sources/highland_estate.geojson",
        [p1],
        {"estate_id": ["EST-SCOT-01"]},
        "Polygon",
        "EPSG:4326",
    )
    # Wrong: computed planar area = 0.020 * 0.0125 = 0.00025 sq deg, labeled as area_m2
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-01-wrong/output/highland_estate_measured.geojson",
        [p1],
        {"estate_id": ["EST-SCOT-01"], "area_m2": [0.00025]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-01-wrong/sources/highland_estate.geojson")
    track("heldout-v0b-geom-01-wrong/output/highland_estate_measured.geojson")

    # Case 2: heldout-v0b-geom-02-wrong (Arctic river: 500m buffer using isotropic 0.00449 deg circle at 68 N)
    line2 = LineString([(18.00, 68.00), (18.05, 68.00), (18.10, 68.00)])
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-02-wrong/sources/arctic_river.geojson",
        [line2],
        {"river_id": ["ARCTIC-CHAR-02"]},
        "LineString",
        "EPSG:4326",
    )
    # Wrong: buffered in degrees with isotropic radius 0.00449 deg (width reaches 1334.5 m)
    wrong_buf2 = line2.buffer(0.00449)
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-02-wrong/output/arctic_river_buffer.geojson",
        [wrong_buf2],
        {"river_id": ["ARCTIC-CHAR-02"], "buffer_dist_m": [500.0]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-02-wrong/sources/arctic_river.geojson")
    track("heldout-v0b-geom-02-wrong/output/arctic_river_buffer.geojson")

    # Case 3: heldout-v0b-geom-03-wrong (Germany road length: Euclidean deg * 111319.5 ignoring cos 50)
    line3 = LineString([(10.00, 50.00), (10.10, 50.00)])
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-03-wrong/sources/germany_corridor.geojson",
        [line3],
        {"corridor_id": ["CORR-DE-A7"]},
        "LineString",
        "EPSG:4326",
    )
    # Wrong: 0.1 deg * 111319.5 = 11132.0 m
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-03-wrong/output/germany_corridor_measured.geojson",
        [line3],
        {"corridor_id": ["CORR-DE-A7"], "length_m": [11132.0]},
        "LineString",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-03-wrong/sources/germany_corridor.geojson")
    track("heldout-v0b-geom-03-wrong/output/germany_corridor_measured.geojson")

    # Case 4: heldout-v0b-geom-04-wrong (NZ powerline: buffer(100.0) executed in degree space)
    line4 = LineString([(170.00, -44.00), (170.05, -44.02), (170.10, -44.05)])
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-04-wrong/sources/nz_powerline.geojson",
        [line4],
        {"line_id": ["NZ-GRID-HV44"]},
        "LineString",
        "EPSG:4326",
    )
    wrong_buf4 = line4.buffer(100.0)  # 100 degrees wide!
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-04-wrong/output/nz_powerline_buffer.geojson",
        [wrong_buf4],
        {"line_id": ["NZ-GRID-HV44"], "buffer_dist_m": [100.0]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-04-wrong/sources/nz_powerline.geojson")
    track("heldout-v0b-geom-04-wrong/output/nz_powerline_buffer.geojson")

    # Case 5: heldout-v0b-geom-05-correct (Alberta compartment: geodesic area in m2 delivered in EPSG:4326)
    p5 = Polygon([(-115.00, 54.00), (-114.96, 54.00), (-114.96, 54.03), (-115.00, 54.03), (-115.00, 54.00)])
    geod5 = pyproj.Geod(ellps="WGS84")
    true_area5 = abs(float(geod5.geometry_area_perimeter(p5)[0]))
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-05-correct/sources/alberta_compartment.geojson",
        [p5],
        {"compartment_id": ["AB-COMP-88"]},
        "Polygon",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-05-correct/output/alberta_compartment_measured.geojson",
        [p5],
        {"compartment_id": ["AB-COMP-88"], "area_m2": [round(true_area5, 1)]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-05-correct/sources/alberta_compartment.geojson")
    track("heldout-v0b-geom-05-correct/output/alberta_compartment_measured.geojson")

    # Case 6: heldout-v0b-geom-06-correct (Iceland skerry: uniform 250m metric buffer delivered in EPSG:4326)
    trans6_to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32627", always_xy=True)
    trans6_to_wgs = pyproj.Transformer.from_crs("EPSG:32627", "EPSG:4326", always_xy=True)
    coords_wgs6 = [(-18.50, 65.00), (-18.46, 65.02), (-18.42, 65.05)]
    line6 = LineString(coords_wgs6)
    coords_utm6 = [trans6_to_utm.transform(x, y) for x, y in coords_wgs6]
    buf6_utm = LineString(coords_utm6).buffer(250.0)  # exact 250m in UTM 27N
    ext_wgs6 = [trans6_to_wgs.transform(x, y) for x, y in buf6_utm.exterior.coords]
    buf6_wgs = Polygon(ext_wgs6)
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-06-correct/sources/iceland_skerry.geojson",
        [line6],
        {"skerry_id": ["IS-SANCT-09"]},
        "LineString",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-06-correct/output/iceland_skerry_buffer.geojson",
        [buf6_wgs],
        {"skerry_id": ["IS-SANCT-09"], "buffer_dist_m": [250.0]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-06-correct/sources/iceland_skerry.geojson")
    track("heldout-v0b-geom-06-correct/output/iceland_skerry_buffer.geojson")

    # Case 7: heldout-v0b-geom-07-correct (Chile railway: geodesic length in m delivered in EPSG:4326)
    coords7 = [(-70.50, -33.00), (-70.20, -33.25), (-69.80, -33.50)]
    line7 = LineString(coords7)
    geod7 = pyproj.Geod(ellps="WGS84")
    true_len7 = float(geod7.geometry_length(line7))
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-07-correct/sources/chile_railway.geojson",
        [line7],
        {"rail_id": ["CL-MINING-07"]},
        "LineString",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-07-correct/output/chile_railway_measured.geojson",
        [line7],
        {"rail_id": ["CL-MINING-07"], "length_m": [round(true_len7, 1)]},
        "LineString",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-07-correct/sources/chile_railway.geojson")
    track("heldout-v0b-geom-07-correct/output/chile_railway_measured.geojson")

    # Case 8: heldout-v0b-geom-08-correct (Alaska pipeline: uniform 1000m buffer delivered in EPSG:4326)
    trans8_to_alb = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3338", always_xy=True)
    trans8_to_wgs = pyproj.Transformer.from_crs("EPSG:3338", "EPSG:4326", always_xy=True)
    coords_wgs8 = [(-146.00, 61.00), (-145.90, 61.05), (-145.80, 61.10)]
    line8 = LineString(coords_wgs8)
    coords_alb8 = [trans8_to_alb.transform(x, y) for x, y in coords_wgs8]
    buf8_alb = LineString(coords_alb8).buffer(1000.0)  # exact 1000m in Alaska Albers
    ext_wgs8 = [trans8_to_wgs.transform(x, y) for x, y in buf8_alb.exterior.coords]
    buf8_wgs = Polygon(ext_wgs8)
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-08-correct/sources/alaska_pipe_centerline.geojson",
        [line8],
        {"pipe_id": ["AK-TAPS-61"]},
        "LineString",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-geom-08-correct/output/alaska_pipe_buffer.geojson",
        [buf8_wgs],
        {"pipe_id": ["AK-TAPS-61"], "buffer_dist_m": [1000.0]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-v0b-geom-08-correct/sources/alaska_pipe_centerline.geojson")
    track("heldout-v0b-geom-08-correct/output/alaska_pipe_buffer.geojson")

    # =========================================================================
    # Family 2: QA Masking, both directions (8 cases)
    # =========================================================================

    # Case 9: heldout-v0b-qa-01-wrong (Ukraine wheat NDVI: omitted QA masking)
    t9 = from_origin(500000.0, 5400000.0, 10.0, 10.0)
    y9, x9 = np.mgrid[0:128, 0:128]
    ndvi9 = 0.58 + 0.18 * np.sin(x9 / 12.0)
    scl9 = np.full((128, 128), 4, dtype=np.uint8)  # vegetation
    scl9[x9 < 35] = 5  # bare soil
    scl9[(x9 > 80) & (y9 < 45)] = 8  # medium cloud
    scl9[(x9 > 95) & (y9 < 35)] = 9  # high cloud
    scl9[(x9 > 85) & (y9 >= 45) & (y9 < 60)] = 3  # cloud shadow
    ndvi9[scl9 == 8] = 0.15
    ndvi9[scl9 == 9] = 0.22
    ndvi9[scl9 == 3] = 0.08
    # Wrong: delivered unmasked
    write_tiled_raster(out_dir / "heldout-v0b-qa-01-wrong/sources/ukraine_raw_ndvi.tif", ndvi9.astype(np.float32), "EPSG:32636", t9, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-01-wrong/sources/ukraine_scl.tif", scl9, "EPSG:32636", t9, nodata=0, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-01-wrong/output/ukraine_masked_ndvi.tif", ndvi9.astype(np.float32), "EPSG:32636", t9, nodata=-9999.0)
    track("heldout-v0b-qa-01-wrong/sources/ukraine_raw_ndvi.tif")
    track("heldout-v0b-qa-01-wrong/sources/ukraine_scl.tif")
    track("heldout-v0b-qa-01-wrong/output/ukraine_masked_ndvi.tif")

    # Case 10: heldout-v0b-qa-02-wrong (Minnesota lakes: over-masked, dropped clear water class 6)
    t10 = from_origin(450000.0, 5100000.0, 30.0, 30.0)
    y10, x10 = np.mgrid[0:128, 0:128]
    ndwi10 = -0.25 + 0.10 * np.sin(x10 / 15.0)
    qa10 = np.full((128, 128), 4, dtype=np.uint8)  # clear land
    water_mask10 = ((x10 - 64)**2 + (y10 - 64)**2) < 900
    qa10[water_mask10] = 6  # clear water
    ndwi10[water_mask10] = 0.65
    qa10[(x10 < 20) & (y10 < 20)] = 8  # cloud
    # Wrong: kept only class 4, dropped clear water class 6
    wrong_ndwi10 = np.full((128, 128), -9999.0, dtype=np.float32)
    wrong_ndwi10[qa10 == 4] = ndwi10[qa10 == 4]
    write_tiled_raster(out_dir / "heldout-v0b-qa-02-wrong/sources/minnesota_ndwi.tif", ndwi10.astype(np.float32), "EPSG:32615", t10, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-02-wrong/sources/minnesota_qa.tif", qa10, "EPSG:32615", t10, nodata=0, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-02-wrong/output/minnesota_ndwi_masked.tif", wrong_ndwi10, "EPSG:32615", t10, nodata=-9999.0)
    track("heldout-v0b-qa-02-wrong/sources/minnesota_ndwi.tif")
    track("heldout-v0b-qa-02-wrong/sources/minnesota_qa.tif")
    track("heldout-v0b-qa-02-wrong/output/minnesota_ndwi_masked.tif")

    # Case 11: heldout-v0b-qa-03-wrong (Pyrenees snow: over-masked, dropped snow class 11)
    t11 = from_origin(350000.0, 4700000.0, 20.0, 20.0)
    y11, x11 = np.mgrid[0:128, 0:128]
    ndsi11 = 0.85 - 0.05 * np.cos(x11 / 10.0)
    scl11 = np.full((128, 128), 11, dtype=np.uint8)  # snow
    scl11[x11 > 90] = 5  # bare rock
    ndsi11[x11 > 90] = 0.12
    scl11[(x11 < 30) & (y11 < 30)] = 8  # cloud
    # Wrong: kept only class 5, dropped snow class 11
    wrong_ndsi11 = np.full((128, 128), -9999.0, dtype=np.float32)
    wrong_ndsi11[scl11 == 5] = ndsi11[scl11 == 5]
    write_tiled_raster(out_dir / "heldout-v0b-qa-03-wrong/sources/pyrenees_snow_ndsi.tif", ndsi11.astype(np.float32), "EPSG:32631", t11, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-03-wrong/sources/pyrenees_scl.tif", scl11, "EPSG:32631", t11, nodata=0, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-03-wrong/output/pyrenees_snow_masked.tif", wrong_ndsi11, "EPSG:32631", t11, nodata=-9999.0)
    track("heldout-v0b-qa-03-wrong/sources/pyrenees_snow_ndsi.tif")
    track("heldout-v0b-qa-03-wrong/sources/pyrenees_scl.tif")
    track("heldout-v0b-qa-03-wrong/output/pyrenees_snow_masked.tif")

    # Case 12: heldout-v0b-qa-04-wrong (Rockies snow fraction: kept cloudy pixels bit 0 == 1)
    t12 = from_origin(500000.0, 4400000.0, 500.0, 500.0)
    y12, x12 = np.mgrid[0:128, 0:128]
    snow_frac12 = 0.70 + 0.15 * np.sin(x12 / 10.0)
    qc12 = np.zeros((128, 128), dtype=np.uint8)
    cloud_mask12 = (x12 >= 40) & (x12 <= 75) & (y12 >= 20) & (y12 <= 65)
    qc12[cloud_mask12] = 1  # cloud bit 0 set
    snow_frac12[cloud_mask12] = 0.45
    # Wrong: delivered unmasked
    write_tiled_raster(out_dir / "heldout-v0b-qa-04-wrong/sources/rockies_snow_fraction.tif", snow_frac12.astype(np.float32), "EPSG:32613", t12, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-04-wrong/sources/rockies_qc_bits.tif", qc12, "EPSG:32613", t12, nodata=255, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-04-wrong/output/rockies_snow_fraction_clean.tif", snow_frac12.astype(np.float32), "EPSG:32613", t12, nodata=-9999.0)
    track("heldout-v0b-qa-04-wrong/sources/rockies_snow_fraction.tif")
    track("heldout-v0b-qa-04-wrong/sources/rockies_qc_bits.tif")
    track("heldout-v0b-qa-04-wrong/output/rockies_snow_fraction_clean.tif")

    # Case 13: heldout-v0b-qa-05-correct (Thessaly NDVI: SCL masked + sensor swath nodata gap preserved)
    t13 = from_origin(300000.0, 4400000.0, 10.0, 10.0)
    y13, x13 = np.mgrid[0:128, 0:128]
    ndvi13 = 0.62 + 0.12 * np.sin(y13 / 10.0)
    scl13 = np.full((128, 128), 4, dtype=np.uint8)  # vegetation
    scl13[x13 < 40] = 5  # bare soil
    scl13[(x13 > 90) & (y13 < 40)] = 8  # cloud
    scl13[(x13 > 85) & (y13 >= 40) & (y13 < 55)] = 3  # shadow
    # Source nodata swath gap across corner:
    swath_gap13 = (x13 + y13) < 45
    ndvi13[swath_gap13] = -9999.0
    # Correct output: masks invalid SCL classes AND preserves source swath gap as nodata
    correct_ndvi13 = ndvi13.copy().astype(np.float32)
    invalid_scl13 = np.isin(scl13, [3, 8, 9])
    correct_ndvi13[invalid_scl13] = -9999.0
    write_tiled_raster(out_dir / "heldout-v0b-qa-05-correct/sources/thessaly_raw_ndvi.tif", ndvi13.astype(np.float32), "EPSG:32634", t13, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-05-correct/sources/thessaly_scl.tif", scl13, "EPSG:32634", t13, nodata=0, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-05-correct/output/thessaly_masked_ndvi.tif", correct_ndvi13, "EPSG:32634", t13, nodata=-9999.0)
    track("heldout-v0b-qa-05-correct/sources/thessaly_raw_ndvi.tif")
    track("heldout-v0b-qa-05-correct/sources/thessaly_scl.tif")
    track("heldout-v0b-qa-05-correct/output/thessaly_masked_ndvi.tif")

    # Case 14: heldout-v0b-qa-06-correct (Everglades NDVI: clear water with legitimate negative NDVI preserved)
    t14 = from_origin(520000.0, 2850000.0, 30.0, 30.0)
    y14, x14 = np.mgrid[0:128, 0:128]
    ndvi14 = 0.50 + 0.15 * np.cos(x14 / 12.0)
    scl14 = np.full((128, 128), 4, dtype=np.uint8)
    water_mask14 = (x14 >= 30) & (x14 <= 70) & (y14 >= 40) & (y14 <= 85)
    scl14[water_mask14] = 6  # water
    ndvi14[water_mask14] = -0.28  # legitimate negative NDVI
    scl14[(x14 < 25) & (y14 < 25)] = 8  # cloud
    correct_ndvi14 = ndvi14.copy().astype(np.float32)
    correct_ndvi14[scl14 == 8] = -9999.0
    write_tiled_raster(out_dir / "heldout-v0b-qa-06-correct/sources/everglades_raw_ndvi.tif", ndvi14.astype(np.float32), "EPSG:32617", t14, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-06-correct/sources/everglades_scl.tif", scl14, "EPSG:32617", t14, nodata=0, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-06-correct/output/everglades_masked_ndvi.tif", correct_ndvi14, "EPSG:32617", t14, nodata=-9999.0)
    track("heldout-v0b-qa-06-correct/sources/everglades_raw_ndvi.tif")
    track("heldout-v0b-qa-06-correct/sources/everglades_scl.tif")
    track("heldout-v0b-qa-06-correct/output/everglades_masked_ndvi.tif")

    # Case 15: heldout-v0b-qa-07-correct (Alps snow NDSI: snow class 11 preserved, clouds masked)
    t15 = from_origin(450000.0, 5100000.0, 20.0, 20.0)
    y15, x15 = np.mgrid[0:128, 0:128]
    ndsi15 = 0.82 + 0.04 * np.sin(x15 / 8.0)
    scl15 = np.full((128, 128), 11, dtype=np.uint8)  # snow
    scl15[x15 > 90] = 5  # bare rock
    ndsi15[x15 > 90] = 0.15
    scl15[(x15 < 30) & (y15 < 35)] = 8  # cloud
    correct_ndsi15 = ndsi15.copy().astype(np.float32)
    correct_ndsi15[scl15 == 8] = -9999.0
    write_tiled_raster(out_dir / "heldout-v0b-qa-07-correct/sources/alps_snow_ndsi.tif", ndsi15.astype(np.float32), "EPSG:32632", t15, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-07-correct/sources/alps_scl.tif", scl15, "EPSG:32632", t15, nodata=0, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-qa-07-correct/output/alps_snow_clean.tif", correct_ndsi15, "EPSG:32632", t15, nodata=-9999.0)
    track("heldout-v0b-qa-07-correct/sources/alps_snow_ndsi.tif")
    track("heldout-v0b-qa-07-correct/sources/alps_scl.tif")
    track("heldout-v0b-qa-07-correct/output/alps_snow_clean.tif")

    # Case 16: heldout-v0b-qa-08-correct (Death Valley TIRS: cloud masked, scan border nodata + >335K preserved)
    t16 = from_origin(510000.0, 4020000.0, 30.0, 30.0)
    y16, x16 = np.mgrid[0:128, 0:128]
    tirs16 = 333.0 + 4.0 * np.sin(x16 / 10.0)
    qa16 = np.zeros((128, 128), dtype=np.uint16)
    qa16[(x16 < 30) & (y16 < 30)] = 8  # cloud bit 3
    # Instrument scan border nodata along top:
    border16 = y16 < 10
    tirs16[border16] = -9999.0
    correct_tirs16 = tirs16.copy().astype(np.float32)
    correct_tirs16[(qa16 & (1 << 3)) != 0] = -9999.0
    write_tiled_raster(out_dir / "heldout-v0b-qa-08-correct/sources/death_valley_tirs.tif", tirs16.astype(np.float32), "EPSG:32611", t16, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-qa-08-correct/sources/death_valley_qa.tif", qa16, "EPSG:32611", t16, nodata=0, dtype="uint16")
    write_tiled_raster(out_dir / "heldout-v0b-qa-08-correct/output/death_valley_tirs_clean.tif", correct_tirs16, "EPSG:32611", t16, nodata=-9999.0)
    track("heldout-v0b-qa-08-correct/sources/death_valley_tirs.tif")
    track("heldout-v0b-qa-08-correct/sources/death_valley_qa.tif")
    track("heldout-v0b-qa-08-correct/output/death_valley_tirs_clean.tif")

    # =========================================================================
    # Family 3: Terrain slope from DEMs without unit labels (8 cases)
    # =========================================================================

    # Case 17: heldout-v0b-slope-01-wrong (Japan Alps DEM in EPSG:4326: degree dx=0.001 treated as metres)
    t17 = from_origin(137.5, 36.5, 0.001, 0.001)
    y17, x17 = np.mgrid[0:128, 0:128]
    z17 = 2200.0 + 350.0 * np.sin(x17 / 10.0) + 250.0 * np.cos(y17 / 10.0)
    dz_dx_wrong17 = np.gradient(z17, 0.001, axis=1)
    dz_dy_wrong17 = np.gradient(z17, 0.001, axis=0)
    slope_wrong17 = np.degrees(np.arctan(np.sqrt(dz_dx_wrong17**2 + dz_dy_wrong17**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-01-wrong/sources/japan_dem_deg.tif", z17.astype(np.float32), "EPSG:4326", t17, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-01-wrong/output/japan_slope_deg.tif", slope_wrong17.astype(np.float32), "EPSG:4326", t17, nodata=-9999.0)
    track("heldout-v0b-slope-01-wrong/sources/japan_dem_deg.tif")
    track("heldout-v0b-slope-01-wrong/output/japan_slope_deg.tif")

    # Case 18: heldout-v0b-slope-02-wrong (Colorado Rockies DEM in UTM: declared feet treated as metres)
    t18 = from_origin(450000.0, 4350000.0, 10.0, 10.0)
    y18, x18 = np.mgrid[0:128, 0:128]
    z_ft18 = 9500.0 + 1200.0 * np.sin(x18 / 12.0) + 800.0 * np.cos(y18 / 12.0)
    # Wrong: treated feet as metres against 10m grid:
    dz_dx_wrong18 = np.gradient(z_ft18, 10.0, axis=1)
    dz_dy_wrong18 = np.gradient(z_ft18, 10.0, axis=0)
    slope_wrong18 = np.degrees(np.arctan(np.sqrt(dz_dx_wrong18**2 + dz_dy_wrong18**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-02-wrong/sources/colorado_dtm_ft.tif", z_ft18.astype(np.float32), "EPSG:32613", t18, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-02-wrong/output/colorado_slope_deg.tif", slope_wrong18.astype(np.float32), "EPSG:32613", t18, nodata=-9999.0)
    track("heldout-v0b-slope-02-wrong/sources/colorado_dtm_ft.tif")
    track("heldout-v0b-slope-02-wrong/output/colorado_slope_deg.tif")

    # Case 19: heldout-v0b-slope-03-wrong (Norway fjord DEM in EPSG:4326: ignored cos 62)
    t19 = from_origin(6.5, 62.5, 0.0005, 0.0005)
    y19, x19 = np.mgrid[0:128, 0:128]
    z19 = 650.0 + 400.0 * np.sin(x19 / 10.0) + 200.0 * np.cos(y19 / 10.0)
    # Wrong: used dx = dy = 0.0005 * 111320 (equatorial)
    dx_wrong19 = 0.0005 * 111320.0
    dz_dx_wrong19 = np.gradient(z19, dx_wrong19, axis=1)
    dz_dy_wrong19 = np.gradient(z19, dx_wrong19, axis=0)
    slope_wrong19 = np.degrees(np.arctan(np.sqrt(dz_dx_wrong19**2 + dz_dy_wrong19**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-03-wrong/sources/norway_fjord_dem.tif", z19.astype(np.float32), "EPSG:4326", t19, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-03-wrong/output/norway_fjord_slope.tif", slope_wrong19.astype(np.float32), "EPSG:4326", t19, nodata=-9999.0)
    track("heldout-v0b-slope-03-wrong/sources/norway_fjord_dem.tif")
    track("heldout-v0b-slope-03-wrong/output/norway_fjord_slope.tif")

    # Case 20: heldout-v0b-slope-04-wrong (Appalachian DEM in EPSG:4326: feet and degrees both ignored)
    t20 = from_origin(-81.5, 38.5, 0.0005, 0.0005)
    y20, x20 = np.mgrid[0:128, 0:128]
    z_ft20 = 2400.0 + 500.0 * np.sin(x20 / 12.0)
    dz_dx_wrong20 = np.gradient(z_ft20, 0.0005, axis=1)
    dz_dy_wrong20 = np.gradient(z_ft20, 0.0005, axis=0)
    slope_wrong20 = np.degrees(np.arctan(np.sqrt(dz_dx_wrong20**2 + dz_dy_wrong20**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-04-wrong/sources/appalachian_dem_ft.tif", z_ft20.astype(np.float32), "EPSG:4326", t20, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-04-wrong/output/appalachian_slope_deg.tif", slope_wrong20.astype(np.float32), "EPSG:4326", t20, nodata=-9999.0)
    track("heldout-v0b-slope-04-wrong/sources/appalachian_dem_ft.tif")
    track("heldout-v0b-slope-04-wrong/output/appalachian_slope_deg.tif")

    # Case 21: heldout-v0b-slope-05-correct (Apennines DEM in EPSG:4326: metric scaled dx=82.72m, dy=111.32m)
    t21 = from_origin(13.5, 42.5, 0.001, 0.001)
    y21, x21 = np.mgrid[0:128, 0:128]
    z21 = 1400.0 + 350.0 * np.sin(x21 / 10.0) + 250.0 * np.cos(y21 / 10.0)
    dx_m21 = 0.001 * 111320.0 * math.cos(math.radians(42.0))  # 82.72 m
    dy_m21 = 0.001 * 111320.0                                 # 111.32 m
    dz_dx21 = np.gradient(z21, dx_m21, axis=1)
    dz_dy21 = np.gradient(z21, dy_m21, axis=0)
    slope21 = np.degrees(np.arctan(np.sqrt(dz_dx21**2 + dz_dy21**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-05-correct/sources/apennines_dem_deg.tif", z21.astype(np.float32), "EPSG:4326", t21, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-05-correct/output/apennines_slope_deg.tif", slope21.astype(np.float32), "EPSG:4326", t21, nodata=-9999.0)
    track("heldout-v0b-slope-05-correct/sources/apennines_dem_deg.tif")
    track("heldout-v0b-slope-05-correct/output/apennines_slope_deg.tif")

    # Case 22: heldout-v0b-slope-06-correct (Sierra Nevada in UTM: vertical feet converted to metres against 30m grid)
    t22 = from_origin(320000.0, 4150000.0, 30.0, 30.0)
    y22, x22 = np.mgrid[0:128, 0:128]
    z_ft22 = 8200.0 + 1500.0 * np.sin(x22 / 12.0) + 900.0 * np.cos(y22 / 12.0)
    z_m22 = z_ft22 * 0.3048
    dz_dx22 = np.gradient(z_m22, 30.0, axis=1)
    dz_dy22 = np.gradient(z_m22, 30.0, axis=0)
    slope22 = np.degrees(np.arctan(np.sqrt(dz_dx22**2 + dz_dy22**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-06-correct/sources/sierra_nevada_dtm_ft.tif", z_ft22.astype(np.float32), "EPSG:32611", t22, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-06-correct/output/sierra_nevada_slope_deg.tif", slope22.astype(np.float32), "EPSG:32611", t22, nodata=-9999.0)
    track("heldout-v0b-slope-06-correct/sources/sierra_nevada_dtm_ft.tif")
    track("heldout-v0b-slope-06-correct/output/sierra_nevada_slope_deg.tif")

    # Case 23: heldout-v0b-slope-07-correct (Kenai DEM in EPSG:4326: scaled by cos 60 = 0.5000)
    t23 = from_origin(-150.0, 60.5, 0.0008, 0.0008)
    y23, x23 = np.mgrid[0:128, 0:128]
    z23 = 1100.0 + 450.0 * np.sin(x23 / 10.0) + 300.0 * np.cos(y23 / 10.0)
    dx_m23 = 0.0008 * 111320.0 * math.cos(math.radians(60.0))  # 44.53 m
    dy_m23 = 0.0008 * 111320.0                                 # 89.06 m
    dz_dx23 = np.gradient(z23, dx_m23, axis=1)
    dz_dy23 = np.gradient(z23, dy_m23, axis=0)
    slope23 = np.degrees(np.arctan(np.sqrt(dz_dx23**2 + dz_dy23**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-07-correct/sources/kenai_dem_deg.tif", z23.astype(np.float32), "EPSG:4326", t23, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-07-correct/output/kenai_slope_deg.tif", slope23.astype(np.float32), "EPSG:4326", t23, nodata=-9999.0)
    track("heldout-v0b-slope-07-correct/sources/kenai_dem_deg.tif")
    track("heldout-v0b-slope-07-correct/output/kenai_slope_deg.tif")

    # Case 24: heldout-v0b-slope-08-correct (Mt. Rainier in State Plane ft: dx=dy=30.48m, vertical m)
    t24 = from_origin(1200000.0, 500000.0, 100.0, 100.0)
    y24, x24 = np.mgrid[0:128, 0:128]
    z_m24 = 3400.0 + 800.0 * np.sin(x24 / 15.0) + 400.0 * np.cos(y24 / 15.0)
    # Horizontal grid is 100 ft = 30.48 m
    dz_dx24 = np.gradient(z_m24, 30.48, axis=1)
    dz_dy24 = np.gradient(z_m24, 30.48, axis=0)
    slope24 = np.degrees(np.arctan(np.sqrt(dz_dx24**2 + dz_dy24**2)))
    write_tiled_raster(out_dir / "heldout-v0b-slope-08-correct/sources/rainier_dem_m.tif", z_m24.astype(np.float32), "EPSG:2927", t24, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-slope-08-correct/output/rainier_slope_deg.tif", slope24.astype(np.float32), "EPSG:2927", t24, nodata=-9999.0)
    track("heldout-v0b-slope-08-correct/sources/rainier_dem_m.tif")
    track("heldout-v0b-slope-08-correct/output/rainier_slope_deg.tif")

    # =========================================================================
    # Family 4: Vertical datums and unusual units (8 cases)
    # =========================================================================

    # Case 25: heldout-v0b-datum-01-wrong (Everglades: inverted geoid h + N instead of h - N)
    t25 = from_origin(500000.0, 2850000.0, 20.0, 20.0)
    y25, x25 = np.mgrid[0:128, 0:128]
    h25 = -25.0 + 4.0 * np.sin(x25 / 15.0)
    n25_const = -28.4
    wrong_H25 = h25 + n25_const  # inverted!
    write_tiled_raster(out_dir / "heldout-v0b-datum-01-wrong/sources/everglades_ellips_h.tif", h25.astype(np.float32), "EPSG:32617", t25, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-01-wrong/output/everglades_ortho_h.tif", wrong_H25.astype(np.float32), "EPSG:32617", t25, nodata=-9999.0)
    track("heldout-v0b-datum-01-wrong/sources/everglades_ellips_h.tif")
    track("heldout-v0b-datum-01-wrong/output/everglades_ortho_h.tif")

    # Case 26: heldout-v0b-datum-02-wrong (Boston Harbor: soundings positive-down kept as positive elevation)
    t26 = from_origin(330000.0, 4680000.0, 5.0, 5.0)
    y26, x26 = np.mgrid[0:128, 0:128]
    depths26 = 16.0 + 6.0 * np.sin(x26 / 15.0)  # positive down
    # Wrong: delivered positive depths as elevation
    write_tiled_raster(out_dir / "heldout-v0b-datum-02-wrong/sources/boston_soundings_down.tif", depths26.astype(np.float32), "EPSG:32619", t26, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-02-wrong/output/boston_elevation_up.tif", depths26.astype(np.float32), "EPSG:32619", t26, nodata=-9999.0)
    track("heldout-v0b-datum-02-wrong/sources/boston_soundings_down.tif")
    track("heldout-v0b-datum-02-wrong/output/boston_elevation_up.tif")

    # Case 27: heldout-v0b-datum-03-wrong (Bering Sea: fathoms converted with 0.3048 instead of 1.8288)
    t27 = from_origin(500000.0, 6200000.0, 100.0, 100.0)
    y27, x27 = np.mgrid[0:128, 0:128]
    fath27 = -60.0 + 30.0 * np.sin(x27 / 15.0)
    wrong_m27 = fath27 * 0.3048  # used foot factor!
    write_tiled_raster(out_dir / "heldout-v0b-datum-03-wrong/sources/bering_shelf_fathoms.tif", fath27.astype(np.float32), "EPSG:32602", t27, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-03-wrong/output/bering_shelf_metres.tif", wrong_m27.astype(np.float32), "EPSG:32602", t27, nodata=-9999.0)
    track("heldout-v0b-datum-03-wrong/sources/bering_shelf_fathoms.tif")
    track("heldout-v0b-datum-03-wrong/output/bering_shelf_metres.tif")

    # Case 28: heldout-v0b-datum-04-wrong (Houston: omitted geoid grid N ~ -27.2m)
    t28 = from_origin(270000.0, 3290000.0, 10.0, 10.0)
    y28, x28 = np.mgrid[0:128, 0:128]
    h28 = 5.0 + 15.0 * np.sin(x28 / 15.0)
    n28 = -27.2 + 0.3 * np.cos(y28 / 20.0)
    # Wrong: delivered raw ellipsoidal h
    write_tiled_raster(out_dir / "heldout-v0b-datum-04-wrong/sources/houston_ellips_h.tif", h28.astype(np.float32), "EPSG:32615", t28, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-04-wrong/sources/houston_geoid18_n.tif", n28.astype(np.float32), "EPSG:32615", t28, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-04-wrong/output/houston_ortho_h.tif", h28.astype(np.float32), "EPSG:32615", t28, nodata=-9999.0)
    track("heldout-v0b-datum-04-wrong/sources/houston_ellips_h.tif")
    track("heldout-v0b-datum-04-wrong/sources/houston_geoid18_n.tif")
    track("heldout-v0b-datum-04-wrong/output/houston_ortho_h.tif")

    # Case 29: heldout-v0b-datum-05-correct (SF Bay: soundings positive-down correctly inverted to negative elevation)
    t29 = from_origin(550000.0, 4180000.0, 5.0, 5.0)
    y29, x29 = np.mgrid[0:128, 0:128]
    depths29 = 20.0 + 12.0 * np.sin(x29 / 15.0)
    elev29 = -depths29
    write_tiled_raster(out_dir / "heldout-v0b-datum-05-correct/sources/sf_bay_soundings_down.tif", depths29.astype(np.float32), "EPSG:32610", t29, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-05-correct/output/sf_bay_elevation_up.tif", elev29.astype(np.float32), "EPSG:32610", t29, nodata=-9999.0)
    track("heldout-v0b-datum-05-correct/sources/sf_bay_soundings_down.tif")
    track("heldout-v0b-datum-05-correct/output/sf_bay_elevation_up.tif")

    # Case 30: heldout-v0b-datum-06-correct (Mississippi Delta: 2D GEOID18 grid applied H = h - N)
    t30 = from_origin(750000.0, 3250000.0, 10.0, 10.0)
    y30, x30 = np.mgrid[0:128, 0:128]
    n30 = -27.0 + 0.5 * np.sin(x30 / 20.0) + 0.3 * np.cos(y30 / 20.0)
    true_H30 = 8.0 + 6.0 * np.sin(x30 / 12.0)
    h30 = true_H30 + n30
    correct_H30 = h30 - n30
    write_tiled_raster(out_dir / "heldout-v0b-datum-06-correct/sources/delta_ellips_h.tif", h30.astype(np.float32), "EPSG:32616", t30, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-06-correct/sources/delta_geoid18_n.tif", n30.astype(np.float32), "EPSG:32616", t30, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-06-correct/output/delta_ortho_h.tif", correct_H30.astype(np.float32), "EPSG:32616", t30, nodata=-9999.0)
    track("heldout-v0b-datum-06-correct/sources/delta_ellips_h.tif")
    track("heldout-v0b-datum-06-correct/sources/delta_geoid18_n.tif")
    track("heldout-v0b-datum-06-correct/output/delta_ortho_h.tif")

    # Case 31: heldout-v0b-datum-07-correct (North Sea: fathoms converted to negative elevation m * 1.8288)
    t31 = from_origin(450000.0, 6300000.0, 25.0, 25.0)
    y31, x31 = np.mgrid[0:128, 0:128]
    fath31 = -45.0 + 25.0 * np.sin(x31 / 15.0)
    m31 = fath31 * 1.8288
    write_tiled_raster(out_dir / "heldout-v0b-datum-07-correct/sources/north_sea_fathoms.tif", fath31.astype(np.float32), "EPSG:32631", t31, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-07-correct/output/north_sea_metres.tif", m31.astype(np.float32), "EPSG:32631", t31, nodata=-9999.0)
    track("heldout-v0b-datum-07-correct/sources/north_sea_fathoms.tif")
    track("heldout-v0b-datum-07-correct/output/north_sea_metres.tif")

    # Case 32: heldout-v0b-datum-08-correct (Puerto Rico: US survey feet converted to metres * 1200/3937)
    t32 = from_origin(200000.0, 250000.0, 5.0, 5.0)
    y32, x32 = np.mgrid[0:128, 0:128]
    us_ft32 = 65.0 + 35.0 * np.sin(x32 / 12.0)
    m32 = us_ft32 * (1200.0 / 3937.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-08-correct/sources/pr_highway_us_ft.tif", us_ft32.astype(np.float32), "EPSG:32161", t32, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-datum-08-correct/output/pr_highway_metres.tif", m32.astype(np.float32), "EPSG:32161", t32, nodata=-9999.0)
    track("heldout-v0b-datum-08-correct/sources/pr_highway_us_ft.tif")
    track("heldout-v0b-datum-08-correct/output/pr_highway_metres.tif")

    # =========================================================================
    # Family 5: Nodata stored as zero, and scale and offset (8 cases)
    # =========================================================================

    # Case 33: heldout-v0b-reg-01-wrong (Windfarm bathymetry: fill 0 kept in depth statistics)
    t33 = from_origin(300000.0, 4550000.0, 10.0, 10.0)
    y33, x33 = np.mgrid[0:128, 0:128]
    bathy33 = np.zeros((128, 128), dtype=np.float32)  # fill 0
    marine33 = (x33 >= 35) & (x33 <= 85) & (y33 >= 20) & (y33 <= 100)
    bathy33[marine33] = -32.4 + 6.0 * np.sin(x33[marine33] / 10.0)
    # Source has nodata=0.0; wrong deliverable treated 0 as valid depth (nodata=-9999.0):
    write_tiled_raster(out_dir / "heldout-v0b-reg-01-wrong/sources/windfarm_bathymetry_raw.tif", bathy33, "EPSG:32619", t33, nodata=0.0)
    write_tiled_raster(out_dir / "heldout-v0b-reg-01-wrong/output/windfarm_valid_bathymetry.tif", bathy33, "EPSG:32619", t33, nodata=-9999.0)
    track("heldout-v0b-reg-01-wrong/sources/windfarm_bathymetry_raw.tif")
    track("heldout-v0b-reg-01-wrong/output/windfarm_valid_bathymetry.tif")

    # Case 34: heldout-v0b-reg-02-wrong (Death Valley DEM: genuine 0.0m sea level pixels evicted)
    t34 = from_origin(510000.0, 4000000.0, 30.0, 30.0)
    y34, x34 = np.mgrid[0:128, 0:128]
    dem34 = (x34.astype(np.float32) - 45.0) * 2.5
    # Tidal base level strip at x in [42, 46] is exactly 0.0 m (384 pixels)
    dem34[(x34 >= 42) & (x34 <= 46)] = 0.0
    dem34[y34 < 12] = -9999.0
    wrong_dem34 = dem34.copy()
    wrong_dem34[wrong_dem34 == -9999.0] = -9999.0
    wrong_dem34[wrong_dem34 == 0.0] = -9999.0  # false eviction of 0.0!
    write_tiled_raster(out_dir / "heldout-v0b-reg-02-wrong/sources/death_valley_dem.tif", dem34, "EPSG:32611", t34, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-reg-02-wrong/output/death_valley_clean_dem.tif", wrong_dem34, "EPSG:32611", t34, nodata=-9999.0)
    track("heldout-v0b-reg-02-wrong/sources/death_valley_dem.tif")
    track("heldout-v0b-reg-02-wrong/output/death_valley_clean_dem.tif")

    # Case 35: heldout-v0b-reg-03-wrong (MODIS B1 Red uint16: unscaled raw integers)
    t35 = from_origin(600000.0, 4200000.0, 250.0, 250.0)
    y35, x35 = np.mgrid[0:128, 0:128]
    true_ref35 = 0.325 + 0.15 * np.sin(x35 / 12.0)
    raw_dn35 = np.round(true_ref35 / 0.0001).astype(np.uint16)
    write_tiled_raster(out_dir / "heldout-v0b-reg-03-wrong/sources/modis_b1_raw_uint16.tif", raw_dn35, "EPSG:32614", t35, nodata=65535, dtype="uint16")
    write_tiled_raster(out_dir / "heldout-v0b-reg-03-wrong/output/modis_b1_reflectance.tif", raw_dn35.astype(np.float32), "EPSG:32614", t35, nodata=-9999.0)
    track("heldout-v0b-reg-03-wrong/sources/modis_b1_raw_uint16.tif")
    track("heldout-v0b-reg-03-wrong/output/modis_b1_reflectance.tif")

    # Case 36: heldout-v0b-reg-04-wrong (SLSTR LST int16: offset sign inverted)
    t36 = from_origin(450000.0, 4100000.0, 1000.0, 1000.0)
    y36, x36 = np.mgrid[0:128, 0:128]
    true_lst36 = 301.15 + 5.0 * np.sin(x36 / 15.0)
    raw_lst36 = np.round((true_lst36 - 273.15) / 0.01).astype(np.int16)
    wrong_lst36 = raw_lst36.astype(np.float32) * 0.01 - 273.15  # sign inverted!
    write_tiled_raster(out_dir / "heldout-v0b-reg-04-wrong/sources/slstr_lst_raw_int16.tif", raw_lst36, "EPSG:32630", t36, nodata=-32768, dtype="int16")
    write_tiled_raster(out_dir / "heldout-v0b-reg-04-wrong/output/slstr_lst_kelvin.tif", wrong_lst36, "EPSG:32630", t36, nodata=-9999.0)
    track("heldout-v0b-reg-04-wrong/sources/slstr_lst_raw_int16.tif")
    track("heldout-v0b-reg-04-wrong/output/slstr_lst_kelvin.tif")

    # Case 37: heldout-v0b-reg-05-correct (Belize reef: fill zero masked to nodata)
    t37 = from_origin(350000.0, 1900000.0, 10.0, 10.0)
    y37, x37 = np.mgrid[0:128, 0:128]
    bathy37 = np.zeros((128, 128), dtype=np.float32)
    lagoon37 = ((x37 - 64)**2 + (y37 - 64)**2) < 1600
    bathy37[lagoon37] = -18.0 + 8.0 * np.sin(x37[lagoon37] / 8.0)
    clean_bathy37 = np.full((128, 128), -9999.0, dtype=np.float32)
    clean_bathy37[lagoon37] = bathy37[lagoon37]
    write_tiled_raster(out_dir / "heldout-v0b-reg-05-correct/sources/belize_reef_raw.tif", bathy37, "EPSG:32616", t37, nodata=0.0)
    write_tiled_raster(out_dir / "heldout-v0b-reg-05-correct/output/belize_reef_clean.tif", clean_bathy37, "EPSG:32616", t37, nodata=-9999.0)
    track("heldout-v0b-reg-05-correct/sources/belize_reef_raw.tif")
    track("heldout-v0b-reg-05-correct/output/belize_reef_clean.tif")

    # Case 38: heldout-v0b-reg-06-correct (Namib rain: genuine 0.0mm dry days preserved, -999 masked)
    t38 = from_origin(400000.0, 7400000.0, 2000.0, 2000.0)
    y38, x38 = np.mgrid[0:128, 0:128]
    rain38 = np.zeros((128, 128), dtype=np.float32)  # genuine 0.0 mm
    rain_cells38 = (x38 > 75) & (y38 > 75)
    rain38[rain_cells38] = 4.5 + 2.5 * np.sin(x38[rain_cells38] / 5.0)
    rain38[x38 < 25] = -999.0  # nodata
    clean_rain38 = rain38.copy()
    clean_rain38[clean_rain38 == -999.0] = -9999.0
    write_tiled_raster(out_dir / "heldout-v0b-reg-06-correct/sources/namib_rain_raw.tif", rain38, "EPSG:32733", t38, nodata=-999.0)
    write_tiled_raster(out_dir / "heldout-v0b-reg-06-correct/output/namib_rain_clean.tif", clean_rain38, "EPSG:32733", t38, nodata=-9999.0)
    track("heldout-v0b-reg-06-correct/sources/namib_rain_raw.tif")
    track("heldout-v0b-reg-06-correct/output/namib_rain_clean.tif")

    # Case 39: heldout-v0b-reg-07-correct (Landsat 9 B3 Green uint16 unpacked)
    t39 = from_origin(620000.0, 4200000.0, 30.0, 30.0)
    y39, x39 = np.mgrid[0:128, 0:128]
    true_b3_39 = 0.22 + 0.12 * np.cos(x39 / 10.0)
    raw_b3_39 = np.round((true_b3_39 + 0.2) / 0.0000275).astype(np.uint16)
    clean_b3_39 = raw_b3_39.astype(np.float32) * 0.0000275 - 0.2
    write_tiled_raster(out_dir / "heldout-v0b-reg-07-correct/sources/landsat9_b3_raw_uint16.tif", raw_b3_39, "EPSG:32614", t39, nodata=0, dtype="uint16")
    write_tiled_raster(out_dir / "heldout-v0b-reg-07-correct/output/landsat9_b3_reflectance.tif", clean_b3_39, "EPSG:32614", t39, nodata=-9999.0)
    track("heldout-v0b-reg-07-correct/sources/landsat9_b3_raw_uint16.tif")
    track("heldout-v0b-reg-07-correct/output/landsat9_b3_reflectance.tif")

    # Case 40: heldout-v0b-reg-08-correct (ERA5 Siberia T2m int16 unpacked DN * 0.002 + 250.0)
    t40 = from_origin(500000.0, 6900000.0, 10000.0, 10000.0)
    y40, x40 = np.mgrid[0:128, 0:128]
    true_t40 = 238.0 + 5.0 * np.sin(x40 / 12.0)
    raw_t40 = np.round((true_t40 - 250.0) / 0.002).astype(np.int16)
    clean_t40 = raw_t40.astype(np.float32) * 0.002 + 250.0
    write_tiled_raster(out_dir / "heldout-v0b-reg-08-correct/sources/siberia_t2m_raw_int16.tif", raw_t40, "EPSG:32645", t40, nodata=-32768, dtype="int16")
    write_tiled_raster(out_dir / "heldout-v0b-reg-08-correct/output/siberia_t2m_kelvin.tif", clean_t40, "EPSG:32645", t40, nodata=-9999.0)
    track("heldout-v0b-reg-08-correct/sources/siberia_t2m_raw_int16.tif")
    track("heldout-v0b-reg-08-correct/output/siberia_t2m_kelvin.tif")

    # =========================================================================
    # Family 6: Plain correct outputs (8 cases)
    # =========================================================================

    # Case 41: heldout-v0b-plain-01-correct (Bavaria DEM in UTM Zone 32N)
    t41 = from_origin(680000.0, 5320000.0, 25.0, 25.0)
    y41, x41 = np.mgrid[0:128, 0:128]
    dem41 = 450.0 + 280.0 * np.sin(x41 / 15.0) + 120.0 * np.cos(y41 / 15.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-01-correct/sources/bavaria_dem_utm32.tif", dem41.astype(np.float32), "EPSG:32632", t41, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-01-correct/output/bavaria_dem_delivered.tif", dem41.astype(np.float32), "EPSG:32632", t41, nodata=-9999.0)
    track("heldout-v0b-plain-01-correct/sources/bavaria_dem_utm32.tif")
    track("heldout-v0b-plain-01-correct/output/bavaria_dem_delivered.tif")

    # Case 42: heldout-v0b-plain-02-correct (Corridor NDVI in UTM Zone 18N)
    t42 = from_origin(350000.0, 4200000.0, 10.0, 10.0)
    y42, x42 = np.mgrid[0:128, 0:128]
    ndvi42 = 0.45 + 0.30 * np.sin(x42 / 12.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-02-correct/sources/corridor_ndvi_raw.tif", ndvi42.astype(np.float32), "EPSG:32618", t42, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-02-correct/output/corridor_ndvi_delivered.tif", ndvi42.astype(np.float32), "EPSG:32618", t42, nodata=-9999.0)
    track("heldout-v0b-plain-02-correct/sources/corridor_ndvi_raw.tif")
    track("heldout-v0b-plain-02-correct/output/corridor_ndvi_delivered.tif")

    # Case 43: heldout-v0b-plain-03-correct (Paris LST in UTM Zone 31N)
    t43 = from_origin(440000.0, 5410000.0, 100.0, 100.0)
    y43, x43 = np.mgrid[0:128, 0:128]
    lst43 = 298.0 + 8.0 * np.cos(x43 / 15.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-03-correct/sources/paris_lst_raw.tif", lst43.astype(np.float32), "EPSG:32631", t43, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-03-correct/output/paris_lst_delivered.tif", lst43.astype(np.float32), "EPSG:32631", t43, nodata=-9999.0)
    track("heldout-v0b-plain-03-correct/sources/paris_lst_raw.tif")
    track("heldout-v0b-plain-03-correct/output/paris_lst_delivered.tif")

    # Case 44: heldout-v0b-plain-04-correct (London CHM in British National Grid)
    t44 = from_origin(530000.0, 180000.0, 5.0, 5.0)
    y44, x44 = np.mgrid[0:128, 0:128]
    chm44 = 12.0 + 10.0 * np.sin(x44 / 10.0)
    chm44[x44 < 20] = 0.0  # roads
    write_tiled_raster(out_dir / "heldout-v0b-plain-04-correct/sources/london_chm_raw.tif", chm44.astype(np.float32), "EPSG:27700", t44, nodata=-9999.0)
    write_tiled_raster(out_dir / "heldout-v0b-plain-04-correct/output/london_chm_delivered.tif", chm44.astype(np.float32), "EPSG:27700", t44, nodata=-9999.0)
    track("heldout-v0b-plain-04-correct/sources/london_chm_raw.tif")
    track("heldout-v0b-plain-04-correct/output/london_chm_delivered.tif")

    # Case 45: heldout-v0b-plain-05-correct (Seattle building footprints GeoJSON in UTM Zone 10N)
    bldg_poly = Polygon([(550000.0, 5270000.0), (550050.0, 5270000.0), (550050.0, 5270080.0), (550000.0, 5270080.0), (550000.0, 5270000.0)])
    write_vector_geojson(
        out_dir / "heldout-v0b-plain-05-correct/sources/seattle_buildings_raw.geojson",
        [bldg_poly],
        {"building_id": ["BLDG-SEA-01"], "height_m": [24.5]},
        "Polygon",
        "EPSG:32610",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-plain-05-correct/output/seattle_buildings_delivered.geojson",
        [bldg_poly],
        {"building_id": ["BLDG-SEA-01"], "height_m": [24.5]},
        "Polygon",
        "EPSG:32610",
    )
    track("heldout-v0b-plain-05-correct/sources/seattle_buildings_raw.geojson")
    track("heldout-v0b-plain-05-correct/output/seattle_buildings_delivered.geojson")

    # Case 46: heldout-v0b-plain-06-correct (Danube reaches GeoJSON LineString in UTM Zone 33N)
    reach_line = LineString([(400000.0, 5300000.0), (405000.0, 5302000.0), (410000.0, 5305000.0)])
    write_vector_geojson(
        out_dir / "heldout-v0b-plain-06-correct/sources/danube_reaches_raw.geojson",
        [reach_line],
        {"reach_id": ["DANUBE-R-102"], "stream_order": [4]},
        "LineString",
        "EPSG:32633",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-plain-06-correct/output/danube_reaches_delivered.geojson",
        [reach_line],
        {"reach_id": ["DANUBE-R-102"], "stream_order": [4]},
        "LineString",
        "EPSG:32633",
    )
    track("heldout-v0b-plain-06-correct/sources/danube_reaches_raw.geojson")
    track("heldout-v0b-plain-06-correct/output/danube_reaches_delivered.geojson")

    # Case 47: heldout-v0b-plain-07-correct (Air stations GeoJSON Point in EPSG:4326)
    pts = [Point(2.35, 48.85), Point(2.40, 48.87)]
    write_vector_geojson(
        out_dir / "heldout-v0b-plain-07-correct/sources/air_stations_raw.geojson",
        pts,
        {"station_id": ["STA-01", "STA-02"], "pm25_ugm3": [12.4, 15.8]},
        "Point",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-v0b-plain-07-correct/output/air_stations_delivered.geojson",
        pts,
        {"station_id": ["STA-01", "STA-02"], "pm25_ugm3": [12.4, 15.8]},
        "Point",
        "EPSG:4326",
    )
    track("heldout-v0b-plain-07-correct/sources/air_stations_raw.geojson")
    track("heldout-v0b-plain-07-correct/output/air_stations_delivered.geojson")

    # Case 48: heldout-v0b-plain-08-correct (Illinois Land Cover categorical uint8 GeoTIFF in EPSG:32616)
    t48 = from_origin(400000.0, 4400000.0, 30.0, 30.0)
    y48, x48 = np.mgrid[0:128, 0:128]
    lc48 = np.full((128, 128), 3, dtype=np.uint8)  # Cropland
    lc48[x48 < 30] = 2  # Forest
    lc48[(x48 > 90) & (y48 > 90)] = 4  # Urban
    lc48[((x48 - 64)**2 + (y48 - 64)**2) < 400] = 1  # Water
    write_tiled_raster(out_dir / "heldout-v0b-plain-08-correct/sources/illinois_landcover_raw.tif", lc48, "EPSG:32616", t48, nodata=255, dtype="uint8")
    write_tiled_raster(out_dir / "heldout-v0b-plain-08-correct/output/illinois_landcover_delivered.tif", lc48, "EPSG:32616", t48, nodata=255, dtype="uint8")
    track("heldout-v0b-plain-08-correct/sources/illinois_landcover_raw.tif")
    track("heldout-v0b-plain-08-correct/output/illinois_landcover_delivered.tif")

    # Write manifest.json
    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic generator for Terraproof held-out cases V0b.")
    parser.add_argument("outdir", type=str, help="Output directory where cases will be generated.")
    args = parser.parse_args()

    out_dir = Path(args.outdir)
    print(f"Generating held-out cases V0b into: {out_dir}")
    manifest = generate_all(out_dir)
    print(f"Successfully generated {len(manifest)} files across 48 verification cases.")
    print(f"Manifest written to: {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
