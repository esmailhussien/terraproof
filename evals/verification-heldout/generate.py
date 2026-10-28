"""Deterministic generator for Terraproof Phase 7 held-out verification cases (V0).

Generates synthetic source datasets and deliverables for 40 held-out cases across
5 trap families (vertical units, QA masking, scale & offset, nodata as zero,
geographic metric work).

Deterministic: seeded with fixed RNG, uses only numpy, rasterio, pyproj, shapely,
pyogrio, and standard library. Never imports terraproof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pyogrio.raw
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Polygon, mapping
import pyproj


def sha256_file(path: Path) -> str:
    """Compute hex SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def write_raster(
    path: Path,
    data: np.ndarray,
    crs: str,
    transform: rasterio.Affine,
    nodata: float | int | None = None,
    dtype: str | None = None,
) -> None:
    """Deterministically write a 2D numpy array as a GeoTIFF."""
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
    }
    if nodata is not None:
        kwargs["nodata"] = nodata

    with rasterio.open(path, "w", **kwargs) as ds:
        ds.write(data.astype(dtype), 1)


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
    """Generate all 40 verification cases into out_dir deterministically."""
    np.random.seed(42)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, str] = {}

    def track(rel_path: str) -> None:
        p = out_dir / rel_path
        if not p.is_file():
            raise FileNotFoundError(f"Expected generated file not found: {p}")
        manifest[rel_path] = sha256_file(p)

    # =========================================================================
    # Family 1: Vertical units (8 cases)
    # =========================================================================

    # Case 1: heldout-vert-01-wrong (Post m - Baseline ft without conversion)
    t1 = from_origin(500000.0, 5200000.0, 2.0, 2.0)
    y1, x1 = np.mgrid[0:60, 0:60]
    base_ft_1 = 150.0 + 20.0 * np.sin(x1 / 10.0) + 10.0 * np.cos(y1 / 10.0)
    post_m_1 = (base_ft_1 * 0.3048) - 0.22  # slight erosion of -0.22 m
    wrong_diff_1 = post_m_1 - base_ft_1     # subtracted feet directly
    write_raster(out_dir / "heldout-vert-01-wrong/sources/baseline_dtm_ft.tif", base_ft_1.astype(np.float32), "EPSG:32610", t1)
    write_raster(out_dir / "heldout-vert-01-wrong/sources/post_storm_dtm_m.tif", post_m_1.astype(np.float32), "EPSG:32610", t1)
    write_raster(out_dir / "heldout-vert-01-wrong/output/elevation_change_m.tif", wrong_diff_1.astype(np.float32), "EPSG:32610", t1)
    track("heldout-vert-01-wrong/sources/baseline_dtm_ft.tif")
    track("heldout-vert-01-wrong/sources/post_storm_dtm_m.tif")
    track("heldout-vert-01-wrong/output/elevation_change_m.tif")

    # Case 2: heldout-vert-02-wrong (Feet DTM multiplied by 3.28084 instead of 0.3048)
    t2 = from_origin(600000.0, 5100000.0, 10.0, 10.0)
    y2, x2 = np.mgrid[0:50, 0:50]
    dtm_ft_2 = 5500.0 + 800.0 * np.sin(x2 / 8.0) + 600.0 * np.cos(y2 / 8.0)
    wrong_dtm_m_2 = dtm_ft_2 * 3.28084
    write_raster(out_dir / "heldout-vert-02-wrong/sources/cascade_raw_dtm_ft.tif", dtm_ft_2.astype(np.float32), "EPSG:32610", t2)
    write_raster(out_dir / "heldout-vert-02-wrong/output/cascade_metric_dtm.tif", wrong_dtm_m_2.astype(np.float32), "EPSG:32610", t2)
    track("heldout-vert-02-wrong/sources/cascade_raw_dtm_ft.tif")
    track("heldout-vert-02-wrong/output/cascade_metric_dtm.tif")

    # Case 3: heldout-vert-03-wrong (Ellipsoidal h delivered raw without geoid N=-31.5)
    t3 = from_origin(350000.0, 3900000.0, 5.0, 5.0)
    y3, x3 = np.mgrid[0:70, 0:70]
    h_ellips_3 = -10.0 + 15.0 * np.sin(x3 / 12.0) + 5.0 * np.cos(y3 / 12.0)
    # Delivered without adding 31.5 m:
    write_raster(out_dir / "heldout-vert-03-wrong/sources/ellipsoidal_dem_m.tif", h_ellips_3.astype(np.float32), "EPSG:32618", t3)
    write_raster(out_dir / "heldout-vert-03-wrong/output/orthometric_navd88_dem.tif", h_ellips_3.astype(np.float32), "EPSG:32618", t3)
    track("heldout-vert-03-wrong/sources/ellipsoidal_dem_m.tif")
    track("heldout-vert-03-wrong/output/orthometric_navd88_dem.tif")

    # Case 4: heldout-vert-04-wrong (Canopy DSM m - DTM ft without conversion)
    t4 = from_origin(450000.0, 4800000.0, 1.0, 1.0)
    y4, x4 = np.mgrid[0:60, 0:60]
    dsm_m_4 = 245.0 + 10.0 * np.sin(x4 / 10.0) + 5.0 * np.cos(y4 / 10.0)
    true_dtm_m_4 = dsm_m_4 - (20.0 + 5.0 * np.sin((x4 + y4) / 15.0))
    dtm_ft_4 = true_dtm_m_4 / 0.3048
    wrong_chm_4 = dsm_m_4 - dtm_ft_4
    write_raster(out_dir / "heldout-vert-04-wrong/sources/canopy_dsm_m.tif", dsm_m_4.astype(np.float32), "EPSG:32610", t4)
    write_raster(out_dir / "heldout-vert-04-wrong/sources/bare_earth_dtm_ft.tif", dtm_ft_4.astype(np.float32), "EPSG:32610", t4)
    write_raster(out_dir / "heldout-vert-04-wrong/output/canopy_height_m.tif", wrong_chm_4.astype(np.float32), "EPSG:32610", t4)
    track("heldout-vert-04-wrong/sources/canopy_dsm_m.tif")
    track("heldout-vert-04-wrong/sources/bare_earth_dtm_ft.tif")
    track("heldout-vert-04-wrong/output/canopy_height_m.tif")

    # Case 5: heldout-vert-05-correct (Post m - (Pre ft * 0.3048))
    t5 = from_origin(540000.0, 5260000.0, 5.0, 5.0)
    y5, x5 = np.mgrid[0:60, 0:60]
    pre_ft_5 = 30.0 + 10.0 * np.sin(x5 / 10.0)
    post_m_5 = (pre_ft_5 * 0.3048) + 1.50
    correct_change_5 = post_m_5 - (pre_ft_5 * 0.3048)
    write_raster(out_dir / "heldout-vert-05-correct/sources/pre_dredge_ft.tif", pre_ft_5.astype(np.float32), "EPSG:32610", t5)
    write_raster(out_dir / "heldout-vert-05-correct/sources/post_dredge_m.tif", post_m_5.astype(np.float32), "EPSG:32610", t5)
    write_raster(out_dir / "heldout-vert-05-correct/output/dredge_change_m.tif", correct_change_5.astype(np.float32), "EPSG:32610", t5)
    track("heldout-vert-05-correct/sources/pre_dredge_ft.tif")
    track("heldout-vert-05-correct/sources/post_dredge_m.tif")
    track("heldout-vert-05-correct/output/dredge_change_m.tif")

    # Case 6: heldout-vert-06-correct (Alps elevation ft * 0.3048)
    t6 = from_origin(450000.0, 5150000.0, 25.0, 25.0)
    y6, x6 = np.mgrid[0:50, 0:50]
    alps_ft_6 = 10000.0 + 3500.0 * np.sin(x6 / 8.0) + 1000.0 * np.cos(y6 / 8.0)
    alps_m_6 = alps_ft_6 * 0.3048
    write_raster(out_dir / "heldout-vert-06-correct/sources/alps_elevation_ft.tif", alps_ft_6.astype(np.float32), "EPSG:2056", t6)
    write_raster(out_dir / "heldout-vert-06-correct/output/alps_elevation_m.tif", alps_m_6.astype(np.float32), "EPSG:2056", t6)
    track("heldout-vert-06-correct/sources/alps_elevation_ft.tif")
    track("heldout-vert-06-correct/output/alps_elevation_m.tif")

    # Case 7: heldout-vert-07-correct (H = h - N)
    t7 = from_origin(400000.0, 4100000.0, 10.0, 10.0)
    y7, x7 = np.mgrid[0:60, 0:60]
    n_geoid_7 = -32.4 + 0.3 * np.sin(x7 / 15.0) + 0.2 * np.cos(y7 / 15.0)
    true_H_7 = 5.0 + 4.0 * np.sin(x7 / 10.0) + 3.0 * np.cos(y7 / 10.0)
    h_ellips_7 = true_H_7 + n_geoid_7
    ortho_H_7 = h_ellips_7 - n_geoid_7
    write_raster(out_dir / "heldout-vert-07-correct/sources/chesapeake_ellipsoidal_h_m.tif", h_ellips_7.astype(np.float32), "EPSG:32618", t7)
    write_raster(out_dir / "heldout-vert-07-correct/sources/geoid18_undulation_n_m.tif", n_geoid_7.astype(np.float32), "EPSG:32618", t7)
    write_raster(out_dir / "heldout-vert-07-correct/output/chesapeake_orthometric_h_m.tif", ortho_H_7.astype(np.float32), "EPSG:32618", t7)
    track("heldout-vert-07-correct/sources/chesapeake_ellipsoidal_h_m.tif")
    track("heldout-vert-07-correct/sources/geoid18_undulation_n_m.tif")
    track("heldout-vert-07-correct/output/chesapeake_orthometric_h_m.tif")

    # Case 8: heldout-vert-08-correct (Fathoms * 1.8288)
    t8 = from_origin(500000.0, 4850000.0, 20.0, 20.0)
    y8, x8 = np.mgrid[0:50, 0:50]
    fath_8 = -25.0 + 15.0 * np.sin(x8 / 10.0)
    m_8 = fath_8 * 1.8288
    write_raster(out_dir / "heldout-vert-08-correct/sources/maine_bathymetry_fathoms.tif", fath_8.astype(np.float32), "EPSG:32619", t8)
    write_raster(out_dir / "heldout-vert-08-correct/output/maine_bathymetry_m.tif", m_8.astype(np.float32), "EPSG:32619", t8)
    track("heldout-vert-08-correct/sources/maine_bathymetry_fathoms.tif")
    track("heldout-vert-08-correct/output/maine_bathymetry_m.tif")

    # =========================================================================
    # Family 2: QA Masking (8 cases)
    # =========================================================================

    # Case 9: heldout-qa-01-wrong (Omitted SCL QA mask entirely)
    t9 = from_origin(600000.0, 4300000.0, 10.0, 10.0)
    y9, x9 = np.mgrid[0:64, 0:64]
    ndvi_raw_9 = 0.55 + 0.20 * np.sin(x9 / 8.0)
    scl_9 = np.full((64, 64), 4, dtype=np.uint8)  # default vegetation
    scl_9[x9 < 20] = 5  # bare soil
    scl_9[(x9 > 40) & (y9 < 25)] = 8  # medium cloud
    scl_9[(x9 > 48) & (y9 < 20)] = 9  # high cloud
    scl_9[(x9 > 42) & (y9 >= 25) & (y9 < 32)] = 3  # cloud shadow
    ndvi_raw_9[scl_9 == 8] = 0.18
    ndvi_raw_9[scl_9 == 9] = 0.22
    ndvi_raw_9[scl_9 == 3] = 0.08
    # Wrong output did not mask any pixels
    write_raster(out_dir / "heldout-qa-01-wrong/sources/kansas_raw_ndvi.tif", ndvi_raw_9.astype(np.float32), "EPSG:32614", t9)
    write_raster(out_dir / "heldout-qa-01-wrong/sources/kansas_scl.tif", scl_9, "EPSG:32614", t9)
    write_raster(out_dir / "heldout-qa-01-wrong/output/kansas_masked_ndvi.tif", ndvi_raw_9.astype(np.float32), "EPSG:32614", t9)
    track("heldout-qa-01-wrong/sources/kansas_raw_ndvi.tif")
    track("heldout-qa-01-wrong/sources/kansas_scl.tif")
    track("heldout-qa-01-wrong/output/kansas_masked_ndvi.tif")

    # Case 10: heldout-qa-02-wrong (Inverted QA bitmask)
    t10 = from_origin(500000.0, 5800000.0, 30.0, 30.0)
    y10, x10 = np.mgrid[0:64, 0:64]
    nbr_10 = 0.60 - 0.25 * np.sin(x10 / 12.0)
    qa_10 = np.zeros((64, 64), dtype=np.uint16)
    # Set cloud bit 3 (8) and shadow bit 4 (16) on ~24%
    qa_10[(x10 > 35) & (y10 > 35)] = 8
    qa_10[(x10 > 45) & (y10 > 25) & (y10 <= 35)] = 16
    qa_10[(x10 <= 15) & (y10 > 45)] = 2  # dilated cloud bit 1
    # Erroneous output keeps cloudy pixels, masks clear forest pixels to NaN:
    invalid_mask_10 = (qa_10 & 0b00011010) != 0
    wrong_nbr_10 = np.full((64, 64), np.nan, dtype=np.float32)
    wrong_nbr_10[invalid_mask_10] = nbr_10[invalid_mask_10]  # inverted!
    write_raster(out_dir / "heldout-qa-02-wrong/sources/bc_fire_nbr.tif", nbr_10.astype(np.float32), "EPSG:32610", t10)
    write_raster(out_dir / "heldout-qa-02-wrong/sources/bc_qa_pixel.tif", qa_10, "EPSG:32610", t10)
    write_raster(out_dir / "heldout-qa-02-wrong/output/bc_fire_nbr_filtered.tif", wrong_nbr_10, "EPSG:32610", t10, nodata=np.nan)
    track("heldout-qa-02-wrong/sources/bc_fire_nbr.tif")
    track("heldout-qa-02-wrong/sources/bc_qa_pixel.tif")
    track("heldout-qa-02-wrong/output/bc_fire_nbr_filtered.tif")

    # Case 11: heldout-qa-03-wrong (Failed to mask QC bits 0-1 == 2)
    t11 = from_origin(400000.0, 4400000.0, 1000.0, 1000.0)
    y11, x11 = np.mgrid[0:60, 0:60]
    lst_11 = 312.0 + 5.0 * np.sin(x11 / 10.0)
    qc_11 = np.zeros((60, 60), dtype=np.uint8)
    qc_11[(x11 >= 20) & (x11 <= 32) & (y11 >= 15) & (y11 <= 30)] = 2  # cloud
    lst_11[qc_11 == 2] = 232.0  # cold cloud top
    # Wrong deliverable delivered unmasked:
    write_raster(out_dir / "heldout-qa-03-wrong/sources/iberia_lst_k.tif", lst_11.astype(np.float32), "EPSG:32630", t11)
    write_raster(out_dir / "heldout-qa-03-wrong/sources/iberia_qc.tif", qc_11, "EPSG:32630", t11)
    write_raster(out_dir / "heldout-qa-03-wrong/output/iberia_lst_clean.tif", lst_11.astype(np.float32), "EPSG:32630", t11)
    track("heldout-qa-03-wrong/sources/iberia_lst_k.tif")
    track("heldout-qa-03-wrong/sources/iberia_qc.tif")
    track("heldout-qa-03-wrong/output/iberia_lst_clean.tif")

    # Case 12: heldout-qa-04-wrong (Over-masked clear water class 2)
    t12 = from_origin(550000.0, 2800000.0, 3.0, 3.0)
    y12, x12 = np.mgrid[0:60, 0:60]
    ndwi_12 = -0.20 + 0.10 * np.sin(x12 / 8.0)
    udm2_12 = np.full((60, 60), 1, dtype=np.uint8)  # clear land
    # Sloughs: water class 2
    water_mask_12 = (y12 >= 20) & (y12 <= 35) & (x12 >= 15)
    udm2_12[water_mask_12] = 2
    ndwi_12[water_mask_12] = 0.65
    # Cloud class 3
    udm2_12[(x12 < 12) & (y12 < 12)] = 3
    # Wrong output kept only class 1:
    wrong_ndwi_12 = np.full((60, 60), np.nan, dtype=np.float32)
    wrong_ndwi_12[udm2_12 == 1] = ndwi_12[udm2_12 == 1]
    write_raster(out_dir / "heldout-qa-04-wrong/sources/everglades_ndwi.tif", ndwi_12.astype(np.float32), "EPSG:32617", t12)
    write_raster(out_dir / "heldout-qa-04-wrong/sources/everglades_udm2.tif", udm2_12, "EPSG:32617", t12)
    write_raster(out_dir / "heldout-qa-04-wrong/output/everglades_ndwi_masked.tif", wrong_ndwi_12, "EPSG:32617", t12, nodata=np.nan)
    track("heldout-qa-04-wrong/sources/everglades_ndwi.tif")
    track("heldout-qa-04-wrong/sources/everglades_udm2.tif")
    track("heldout-qa-04-wrong/output/everglades_ndwi_masked.tif")

    # Case 13: heldout-qa-05-correct (SCL masking keeping 4, 5, 6, 7 including negative NDVI water)
    t13 = from_origin(320000.0, 3400000.0, 10.0, 10.0)
    y13, x13 = np.mgrid[0:64, 0:64]
    ndvi_13 = 0.65 - 0.20 * np.cos(y13 / 10.0)
    scl_13 = np.full((64, 64), 4, dtype=np.uint8)  # vegetation
    scl_13[x13 < 15] = 5  # bare soil
    water_mask_13 = (y13 > 45) & (x13 > 30)
    scl_13[water_mask_13] = 6  # water
    ndvi_13[water_mask_13] = -0.28  # genuine negative NDVI
    scl_13[(x13 > 50) & (y13 < 20)] = 8  # cloud
    scl_13[(x13 > 45) & (y13 >= 20) & (y13 < 28)] = 3  # shadow
    correct_ndvi_13 = np.full((64, 64), np.nan, dtype=np.float32)
    valid_mask_13 = np.isin(scl_13, [4, 5, 6, 7])
    correct_ndvi_13[valid_mask_13] = ndvi_13[valid_mask_13]
    write_raster(out_dir / "heldout-qa-05-correct/sources/nile_raw_ndvi.tif", ndvi_13.astype(np.float32), "EPSG:32636", t13)
    write_raster(out_dir / "heldout-qa-05-correct/sources/nile_scl.tif", scl_13, "EPSG:32636", t13)
    write_raster(out_dir / "heldout-qa-05-correct/output/nile_masked_ndvi.tif", correct_ndvi_13, "EPSG:32636", t13, nodata=np.nan)
    track("heldout-qa-05-correct/sources/nile_raw_ndvi.tif")
    track("heldout-qa-05-correct/sources/nile_scl.tif")
    track("heldout-qa-05-correct/output/nile_masked_ndvi.tif")

    # Case 14: heldout-qa-06-correct (Hot desert >335K preserved, QA bits 0, 3, 4 masked)
    t14 = from_origin(510000.0, 4020000.0, 30.0, 30.0)
    y14, x14 = np.mgrid[0:60, 0:60]
    b10_14 = 332.0 + 5.0 * np.sin(x14 / 8.0)
    qa_14 = np.zeros((60, 60), dtype=np.uint16)
    qa_14[(x14 < 15) & (y14 < 15)] = 8  # cloud bit 3
    qa_14[(x14 < 15) & (y14 >= 15) & (y14 < 25)] = 16  # shadow bit 4
    correct_b10_14 = np.full((60, 60), np.nan, dtype=np.float32)
    valid_14 = (qa_14 & ((1 << 0) | (1 << 3) | (1 << 4))) == 0
    correct_b10_14[valid_14] = b10_14[valid_14]
    write_raster(out_dir / "heldout-qa-06-correct/sources/death_valley_b10_k.tif", b10_14.astype(np.float32), "EPSG:32611", t14)
    write_raster(out_dir / "heldout-qa-06-correct/sources/death_valley_qa_pixel.tif", qa_14, "EPSG:32611", t14)
    write_raster(out_dir / "heldout-qa-06-correct/output/death_valley_b10_masked.tif", correct_b10_14, "EPSG:32611", t14, nodata=np.nan)
    track("heldout-qa-06-correct/sources/death_valley_b10_k.tif")
    track("heldout-qa-06-correct/sources/death_valley_qa_pixel.tif")
    track("heldout-qa-06-correct/output/death_valley_b10_masked.tif")

    # Case 15: heldout-qa-07-correct (Greenland NDSI preserves snow 11 and rock 5, masks cloud 8, 9, 3)
    t15 = from_origin(500000.0, 7500000.0, 20.0, 20.0)
    y15, x15 = np.mgrid[0:60, 0:60]
    ndsi_15 = 0.82 + 0.05 * np.sin(x15 / 10.0)
    scl_15 = np.full((60, 60), 11, dtype=np.uint8)  # snow/ice
    scl_15[x15 > 45] = 5  # bare rock
    ndsi_15[x15 > 45] = 0.15
    scl_15[(x15 < 20) & (y15 < 20)] = 8  # cloud
    scl_15[(x15 < 20) & (y15 >= 20) & (y15 < 26)] = 3  # shadow
    correct_ndsi_15 = np.full((60, 60), np.nan, dtype=np.float32)
    valid_15 = np.isin(scl_15, [5, 11])
    correct_ndsi_15[valid_15] = ndsi_15[valid_15]
    write_raster(out_dir / "heldout-qa-07-correct/sources/greenland_ndsi.tif", ndsi_15.astype(np.float32), "EPSG:32624", t15)
    write_raster(out_dir / "heldout-qa-07-correct/sources/greenland_scl.tif", scl_15, "EPSG:32624", t15)
    write_raster(out_dir / "heldout-qa-07-correct/output/greenland_ndsi_masked.tif", correct_ndsi_15, "EPSG:32624", t15, nodata=np.nan)
    track("heldout-qa-07-correct/sources/greenland_ndsi.tif")
    track("heldout-qa-07-correct/sources/greenland_scl.tif")
    track("heldout-qa-07-correct/output/greenland_ndsi_masked.tif")

    # Case 16: heldout-qa-08-correct (VIIRS DNB: zero radiance in clear rural areas preserved, flag 1 masked)
    t16 = from_origin(450000.0, 4500000.0, 500.0, 500.0)
    y16, x16 = np.mgrid[0:60, 0:60]
    rad_16 = np.zeros((60, 60), dtype=np.float32)
    # Town lights
    rad_16[(x16 > 35) & (y16 > 35)] = 25.0 + 10.0 * np.sin((x16[(x16 > 35) & (y16 > 35)]) / 3.0)
    # Clear rural fields have genuine 0.0 radiance
    qf_16 = np.zeros((60, 60), dtype=np.uint8)
    qf_16[(x16 < 15) & (y16 < 25)] = 1  # cloud/stray light
    correct_rad_16 = np.full((60, 60), np.nan, dtype=np.float32)
    correct_rad_16[qf_16 == 0] = rad_16[qf_16 == 0]
    write_raster(out_dir / "heldout-qa-08-correct/sources/viirs_dnb_radiance.tif", rad_16, "EPSG:32615", t16)
    write_raster(out_dir / "heldout-qa-08-correct/sources/viirs_quality_flag.tif", qf_16, "EPSG:32615", t16)
    write_raster(out_dir / "heldout-qa-08-correct/output/viirs_dnb_clean.tif", correct_rad_16, "EPSG:32615", t16, nodata=np.nan)
    track("heldout-qa-08-correct/sources/viirs_dnb_radiance.tif")
    track("heldout-qa-08-correct/sources/viirs_quality_flag.tif")
    track("heldout-qa-08-correct/output/viirs_dnb_clean.tif")

    # =========================================================================
    # Family 3: Scale and Offset (8 cases)
    # =========================================================================

    # Case 17: heldout-scale-01-wrong (Unscaled raw uint16 delivered)
    t17 = from_origin(650000.0, 4150000.0, 30.0, 30.0)
    y17, x17 = np.mgrid[0:60, 0:60]
    # Physical reflectance ~0.05 to 0.55
    true_ref_17 = 0.28 + 0.18 * np.sin(x17 / 8.0)
    raw_dn_17 = np.round((true_ref_17 + 0.2) / 0.0000275).astype(np.uint16)
    # Delivered raw without scaling:
    write_raster(out_dir / "heldout-scale-01-wrong/sources/landsat9_b4_raw_uint16.tif", raw_dn_17, "EPSG:32614", t17)
    write_raster(out_dir / "heldout-scale-01-wrong/output/landsat9_b4_reflectance.tif", raw_dn_17.astype(np.float32), "EPSG:32614", t17)
    track("heldout-scale-01-wrong/sources/landsat9_b4_raw_uint16.tif")
    track("heldout-scale-01-wrong/output/landsat9_b4_reflectance.tif")

    # Case 18: heldout-scale-02-wrong (Scale applied twice: DN * 0.02 * 0.02)
    t18 = from_origin(500000.0, 4200000.0, 1000.0, 1000.0)
    y18, x18 = np.mgrid[0:60, 0:60]
    true_lst_18 = 298.0 + 8.0 * np.sin(x18 / 10.0)
    raw_lst_18 = np.round(true_lst_18 / 0.02).astype(np.uint16)
    wrong_lst_18 = (raw_lst_18.astype(np.float32) * 0.02) * 0.02
    write_raster(out_dir / "heldout-scale-02-wrong/sources/mod11a1_raw_lst_uint16.tif", raw_lst_18, "EPSG:32632", t18)
    write_raster(out_dir / "heldout-scale-02-wrong/output/mod11a1_unpacked_lst.tif", wrong_lst_18, "EPSG:32632", t18)
    track("heldout-scale-02-wrong/sources/mod11a1_raw_lst_uint16.tif")
    track("heldout-scale-02-wrong/output/mod11a1_unpacked_lst.tif")

    # Case 19: heldout-scale-03-wrong (Offset subtracted instead of added: DN * 0.01 - 273.15)
    t19 = from_origin(400000.0, 3600000.0, 1000.0, 1000.0)
    y19, x19 = np.mgrid[0:60, 0:60]
    true_sst_19 = 292.5 + 4.0 * np.sin(y19 / 8.0)
    raw_sst_19 = np.round((true_sst_19 - 273.15) / 0.01).astype(np.int16)
    wrong_sst_19 = raw_sst_19.astype(np.float32) * 0.01 - 273.15  # sign flipped!
    write_raster(out_dir / "heldout-scale-03-wrong/sources/slstr_sst_raw_int16.tif", raw_sst_19, "EPSG:32629", t19)
    write_raster(out_dir / "heldout-scale-03-wrong/output/slstr_sst_kelvin.tif", wrong_sst_19, "EPSG:32629", t19)
    track("heldout-scale-03-wrong/sources/slstr_sst_raw_int16.tif")
    track("heldout-scale-03-wrong/output/slstr_sst_kelvin.tif")

    # Case 20: heldout-scale-04-wrong (Divided by scale: DN / 0.0001)
    t20 = from_origin(550000.0, 4300000.0, 9000.0, 9000.0)
    y20, x20 = np.mgrid[0:50, 0:50]
    true_sm_20 = 0.28 + 0.10 * np.sin(x20 / 7.0)
    raw_sm_20 = np.round(true_sm_20 / 0.0001).astype(np.uint16)
    wrong_sm_20 = raw_sm_20.astype(np.float32) / 0.0001
    write_raster(out_dir / "heldout-scale-04-wrong/sources/smap_sm_raw_uint16.tif", raw_sm_20, "EPSG:32614", t20)
    write_raster(out_dir / "heldout-scale-04-wrong/output/smap_sm_m3_m3.tif", wrong_sm_20, "EPSG:32614", t20)
    track("heldout-scale-04-wrong/sources/smap_sm_raw_uint16.tif")
    track("heldout-scale-04-wrong/output/smap_sm_m3_m3.tif")

    # Case 21: heldout-scale-05-correct (Landsat 8 B5 unpacked correctly)
    t21 = from_origin(620000.0, 4200000.0, 30.0, 30.0)
    y21, x21 = np.mgrid[0:60, 0:60]
    true_b5_21 = 0.35 + 0.15 * np.cos(x21 / 8.0)
    raw_b5_21 = np.round((true_b5_21 + 0.2) / 0.0000275).astype(np.uint16)
    correct_b5_21 = raw_b5_21.astype(np.float32) * 0.0000275 - 0.2
    write_raster(out_dir / "heldout-scale-05-correct/sources/landsat8_b5_raw_uint16.tif", raw_b5_21, "EPSG:32614", t21)
    write_raster(out_dir / "heldout-scale-05-correct/output/landsat8_b5_reflectance.tif", correct_b5_21, "EPSG:32614", t21)
    track("heldout-scale-05-correct/sources/landsat8_b5_raw_uint16.tif")
    track("heldout-scale-05-correct/output/landsat8_b5_reflectance.tif")

    # Case 22: heldout-scale-06-correct (ERA5 T2m unpacked: DN * 0.002 + 260.0)
    t22 = from_origin(500000.0, 6800000.0, 10000.0, 10000.0)
    y22, x22 = np.mgrid[0:50, 0:50]
    true_t2m_22 = 248.0 + 3.0 * np.sin(x22 / 8.0)
    raw_t2m_22 = np.round((true_t2m_22 - 260.0) / 0.002).astype(np.int16)
    correct_t2m_22 = raw_t2m_22.astype(np.float32) * 0.002 + 260.0
    write_raster(out_dir / "heldout-scale-06-correct/sources/era5_t2m_raw_int16.tif", raw_t2m_22, "EPSG:32633", t22)
    write_raster(out_dir / "heldout-scale-06-correct/output/era5_t2m_kelvin.tif", correct_t2m_22, "EPSG:32633", t22)
    track("heldout-scale-06-correct/sources/era5_t2m_raw_int16.tif")
    track("heldout-scale-06-correct/output/era5_t2m_kelvin.tif")

    # Case 23: heldout-scale-07-correct (GPCC precip anomaly: DN * 0.1 - 50.0)
    t23 = from_origin(450000.0, 4800000.0, 25000.0, 25000.0)
    y23, x23 = np.mgrid[0:50, 0:50]
    true_anom_23 = 10.0 + 55.0 * np.sin(x23 / 7.0)  # ranges from -45 to +65
    raw_anom_23 = np.round((true_anom_23 + 50.0) / 0.1).astype(np.int16)
    correct_anom_23 = raw_anom_23.astype(np.float32) * 0.1 - 50.0
    write_raster(out_dir / "heldout-scale-07-correct/sources/gpcc_precip_raw_int16.tif", raw_anom_23, "EPSG:32632", t23)
    write_raster(out_dir / "heldout-scale-07-correct/output/gpcc_precip_anomaly_mm.tif", correct_anom_23, "EPSG:32632", t23)
    track("heldout-scale-07-correct/sources/gpcc_precip_raw_int16.tif")
    track("heldout-scale-07-correct/output/gpcc_precip_anomaly_mm.tif")

    # Case 24: heldout-scale-08-correct (GEDI uint8 unpacked: DN * 0.25)
    t24 = from_origin(500000.0, 100000.0, 25.0, 25.0)
    y24, x24 = np.mgrid[0:60, 0:60]
    true_chm_24 = 30.0 + 20.0 * np.sin(x24 / 9.0)
    true_chm_24[x24 < 10] = 0.0  # river clearing
    raw_chm_24 = np.round(true_chm_24 / 0.25).astype(np.uint8)
    correct_chm_24 = raw_chm_24.astype(np.float32) * 0.25
    write_raster(out_dir / "heldout-scale-08-correct/sources/gedi_chm_raw_uint8.tif", raw_chm_24, "EPSG:32632", t24)
    write_raster(out_dir / "heldout-scale-08-correct/output/gedi_chm_metres.tif", correct_chm_24, "EPSG:32632", t24)
    track("heldout-scale-08-correct/sources/gedi_chm_raw_uint8.tif")
    track("heldout-scale-08-correct/output/gedi_chm_metres.tif")

    # =========================================================================
    # Family 4: Nodata Stored as Zero (8 cases)
    # =========================================================================

    # Case 25: heldout-nodata-01-wrong (Harbor bathymetry: fill 0 kept as valid depth)
    t25 = from_origin(500000.0, 4800000.0, 5.0, 5.0)
    y25, x25 = np.mgrid[0:60, 0:60]
    bathy_25 = np.zeros((60, 60), dtype=np.float32)  # default fill 0
    channel_25 = (x25 >= 15) & (x25 <= 35)
    bathy_25[channel_25] = -18.25 + 4.0 * np.sin(y25[channel_25] / 8.0)
    # Deliverable erroneously kept 0 as valid depth:
    write_raster(out_dir / "heldout-nodata-01-wrong/sources/harbor_bathymetry_raw.tif", bathy_25, "EPSG:32619", t25)
    write_raster(out_dir / "heldout-nodata-01-wrong/output/harbor_valid_bathymetry.tif", bathy_25, "EPSG:32619", t25)
    track("heldout-nodata-01-wrong/sources/harbor_bathymetry_raw.tif")
    track("heldout-nodata-01-wrong/output/harbor_valid_bathymetry.tif")

    # Case 26: heldout-nodata-02-wrong (Coastal 0.0m contours evicted as nodata)
    t26 = from_origin(560000.0, 3670000.0, 30.0, 30.0)
    y26, x26 = np.mgrid[0:60, 0:60]
    dem_26 = (x26.astype(np.float32) - 20.0) * 3.0  # -60 to +117 m
    # Tidal flat / shoreline at sea level is exactly 0.0 m (columns 18 to 21)
    dem_26[(x26 >= 18) & (x26 <= 21)] = 0.0
    # Outside border is -9999.0
    dem_26[y26 < 5] = -9999.0
    # Erroneous output evicted 0.0 m pixels as NaN:
    wrong_dem_26 = dem_26.copy()
    wrong_dem_26[wrong_dem_26 == -9999.0] = np.nan
    wrong_dem_26[wrong_dem_26 == 0.0] = np.nan  # false eviction of legitimate sea level!
    write_raster(out_dir / "heldout-nodata-02-wrong/sources/salton_sea_dem.tif", dem_26, "EPSG:32611", t26, nodata=-9999.0)
    write_raster(out_dir / "heldout-nodata-02-wrong/output/salton_sea_clean_dem.tif", wrong_dem_26, "EPSG:32611", t26, nodata=np.nan)
    track("heldout-nodata-02-wrong/sources/salton_sea_dem.tif")
    track("heldout-nodata-02-wrong/output/salton_sea_clean_dem.tif")

    # Case 27: heldout-nodata-03-wrong (InSAR swath border 0s kept)
    t27 = from_origin(420000.0, 4100000.0, 20.0, 20.0)
    y27, x27 = np.mgrid[0:60, 0:60]
    insar_27 = np.zeros((60, 60), dtype=np.float32)
    swath_27 = (x27 >= 20) & (x27 <= 40)
    insar_27[swath_27] = 0.68 + 0.12 * np.sin(y27[swath_27] / 10.0)
    write_raster(out_dir / "heldout-nodata-03-wrong/sources/insar_coherence_raw.tif", insar_27, "EPSG:32611", t27)
    write_raster(out_dir / "heldout-nodata-03-wrong/output/insar_coherence_masked.tif", insar_27, "EPSG:32611", t27)
    track("heldout-nodata-03-wrong/sources/insar_coherence_raw.tif")
    track("heldout-nodata-03-wrong/output/insar_coherence_masked.tif")

    # Case 28: heldout-nodata-04-wrong (Hail crop loss: unsurveyed 0s treated as 0% damage)
    t28 = from_origin(450000.0, 4650000.0, 1000.0, 1000.0)
    y28, x28 = np.mgrid[0:50, 0:50]
    hail_28 = np.zeros((50, 50), dtype=np.float32)
    storm_28 = (x28 >= 15) & (x28 <= 28) & (y28 >= 10) & (y28 <= 35)
    hail_28[storm_28] = 54.2 + 20.0 * np.sin(x28[storm_28] / 5.0)
    write_raster(out_dir / "heldout-nodata-04-wrong/sources/iowa_hail_damage_raw.tif", hail_28, "EPSG:32615", t28)
    write_raster(out_dir / "heldout-nodata-04-wrong/output/iowa_hail_damage_clean.tif", hail_28, "EPSG:32615", t28)
    track("heldout-nodata-04-wrong/sources/iowa_hail_damage_raw.tif")
    track("heldout-nodata-04-wrong/output/iowa_hail_damage_clean.tif")

    # Case 29: heldout-nodata-05-correct (St. Helena ocean 0 masked to NaN)
    t29 = from_origin(500000.0, 8200000.0, 30.0, 30.0)
    y29, x29 = np.mgrid[0:60, 0:60]
    dem_29 = np.zeros((60, 60), dtype=np.float32)
    island_29 = ((x29 - 30)**2 + (y29 - 30)**2) < 225
    dem_29[island_29] = 200.0 + 350.0 * np.cos(np.sqrt((x29[island_29] - 30)**2 + (y29[island_29] - 30)**2) / 4.0)
    correct_dem_29 = np.full((60, 60), np.nan, dtype=np.float32)
    correct_dem_29[island_29] = dem_29[island_29]
    write_raster(out_dir / "heldout-nodata-05-correct/sources/st_helena_dem_raw.tif", dem_29, "EPSG:32728", t29)
    write_raster(out_dir / "heldout-nodata-05-correct/output/st_helena_dem_masked.tif", correct_dem_29, "EPSG:32728", t29, nodata=np.nan)
    track("heldout-nodata-05-correct/sources/st_helena_dem_raw.tif")
    track("heldout-nodata-05-correct/output/st_helena_dem_masked.tif")

    # Case 30: heldout-nodata-06-correct (Flevoland: -9999 nodata masked, 0.0m preserved)
    t30 = from_origin(150000.0, 500000.0, 10.0, 10.0)
    y30, x30 = np.mgrid[0:60, 0:60]
    dem_30 = -3.5 + (x30.astype(np.float32) / 60.0) * 15.0
    # Dike along x=14 has exact 0.0 m elevation
    dem_30[:, 14] = 0.0
    # True nodata outside polder boundary
    dem_30[y30 < 6] = -9999.0
    correct_dem_30 = dem_30.copy()
    correct_dem_30[correct_dem_30 == -9999.0] = np.nan
    write_raster(out_dir / "heldout-nodata-06-correct/sources/flevoland_polder_dem.tif", dem_30, "EPSG:28992", t30, nodata=-9999.0)
    write_raster(out_dir / "heldout-nodata-06-correct/output/flevoland_polder_clean.tif", correct_dem_30, "EPSG:28992", t30, nodata=np.nan)
    track("heldout-nodata-06-correct/sources/flevoland_polder_dem.tif")
    track("heldout-nodata-06-correct/output/flevoland_polder_clean.tif")

    # Case 31: heldout-nodata-07-correct (Congo forest change: 255 masked, 0 and 1 preserved)
    t31 = from_origin(500000.0, 100000.0, 30.0, 30.0)
    y31, x31 = np.mgrid[0:50, 0:50]
    change_31 = np.zeros((50, 50), dtype=np.uint8)  # stable forest 0
    change_31[(x31 > 30) & (y31 > 30) & (x31 < 36)] = 1  # forest loss
    change_31[y31 < 10] = 255  # persistent cloud / nodata
    correct_change_31 = change_31.astype(np.float32)
    correct_change_31[change_31 == 255] = np.nan
    write_raster(out_dir / "heldout-nodata-07-correct/sources/congo_forest_change.tif", change_31, "EPSG:32633", t31, nodata=255)
    write_raster(out_dir / "heldout-nodata-07-correct/output/congo_forest_change_clean.tif", correct_change_31, "EPSG:32633", t31, nodata=np.nan)
    track("heldout-nodata-07-correct/sources/congo_forest_change.tif")
    track("heldout-nodata-07-correct/output/congo_forest_change_clean.tif")

    # Case 32: heldout-nodata-08-correct (Atacama rain: -999 masked, genuine 0.0mm preserved)
    t32 = from_origin(400000.0, 7400000.0, 1000.0, 1000.0)
    y32, x32 = np.mgrid[0:50, 0:50]
    rain_32 = np.zeros((50, 50), dtype=np.float32)  # genuine 0.0 mm rain
    rain_32[(x32 > 35) & (y32 > 35)] = 5.0 + 3.0 * np.sin(x32[(x32 > 35) & (y32 > 35)] / 2.0)
    rain_32[x32 < 10] = -999.0  # unmonitored nodata
    correct_rain_32 = rain_32.copy()
    correct_rain_32[correct_rain_32 == -999.0] = np.nan
    write_raster(out_dir / "heldout-nodata-08-correct/sources/atacama_daily_rain.tif", rain_32, "EPSG:32719", t32, nodata=-999.0)
    write_raster(out_dir / "heldout-nodata-08-correct/output/atacama_daily_rain_clean.tif", correct_rain_32, "EPSG:32719", t32, nodata=np.nan)
    track("heldout-nodata-08-correct/sources/atacama_daily_rain.tif")
    track("heldout-nodata-08-correct/output/atacama_daily_rain_clean.tif")

    # =========================================================================
    # Family 5: Geographic Metric Work (8 cases)
    # =========================================================================

    # Case 33: heldout-geom-01-wrong (Highland parcel area: planar deg2 stored as area_sqm)
    p33 = Polygon([(-4.215, 57.500), (-4.200, 57.500), (-4.200, 57.510), (-4.215, 57.510), (-4.215, 57.500)])
    write_vector_geojson(
        out_dir / "heldout-geom-01-wrong/sources/highland_parcels.geojson",
        [p33],
        {"parcel_id": ["HP-101"]},
        "Polygon",
        "EPSG:4326",
    )
    # Wrong: computed planar area = 0.015 * 0.010 = 0.00015
    write_vector_geojson(
        out_dir / "heldout-geom-01-wrong/output/highland_parcels_measured.geojson",
        [p33],
        {"parcel_id": ["HP-101"], "area_sqm": [0.00015]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-geom-01-wrong/sources/highland_parcels.geojson")
    track("heldout-geom-01-wrong/output/highland_parcels_measured.geojson")

    # Case 34: heldout-geom-02-wrong (Alaska stream 500m buffer: 0.00898 deg circular buffer)
    line34 = LineString([(-150.00, 60.00), (-149.95, 60.00), (-149.90, 60.00)])
    write_vector_geojson(
        out_dir / "heldout-geom-02-wrong/sources/alaska_salmon_stream.geojson",
        [line34],
        {"stream_id": ["AK-SAL-01"]},
        "LineString",
        "EPSG:4326",
    )
    # Wrong: buffered in degrees with isotropic radius 0.00898 deg (north-south 1000m)
    wrong_buf34 = line34.buffer(0.00898)
    write_vector_geojson(
        out_dir / "heldout-geom-02-wrong/output/alaska_stream_buffer.geojson",
        [wrong_buf34],
        {"stream_id": ["AK-SAL-01"], "buffer_dist_m": [500.0]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-geom-02-wrong/sources/alaska_salmon_stream.geojson")
    track("heldout-geom-02-wrong/output/alaska_stream_buffer.geojson")

    # Case 35: heldout-geom-03-wrong (France highway length: deg * 111319.5 ignoring cos(45))
    line35 = LineString([(2.00, 45.00), (2.10, 45.00)])
    write_vector_geojson(
        out_dir / "heldout-geom-03-wrong/sources/france_highway.geojson",
        [line35],
        {"route_ref": ["A89-E70"]},
        "LineString",
        "EPSG:4326",
    )
    # Wrong: 0.1 deg * 111319.5 = 11132.0 m
    write_vector_geojson(
        out_dir / "heldout-geom-03-wrong/output/france_highway_measured.geojson",
        [line35],
        {"route_ref": ["A89-E70"], "length_m": [11132.0]},
        "LineString",
        "EPSG:4326",
    )
    track("heldout-geom-03-wrong/sources/france_highway.geojson")
    track("heldout-geom-03-wrong/output/france_highway_measured.geojson")

    # Case 36: heldout-geom-04-wrong (Andes slope: computed with dx=0.001 deg as metres)
    t36 = from_origin(-70.0, -30.0, 0.001, 0.001)
    y36, x36 = np.mgrid[0:50, 0:50]
    z36 = 2500.0 + 300.0 * np.sin(x36 / 5.0) + 200.0 * np.cos(y36 / 5.0)
    # Erroneous slope in degrees: arctan(dz / 0.001) in degrees ~ 89.9 deg
    dz_dx_wrong = np.gradient(z36, 0.001, axis=1)
    dz_dy_wrong = np.gradient(z36, 0.001, axis=0)
    slope_wrong_rad = np.arctan(np.sqrt(dz_dx_wrong**2 + dz_dy_wrong**2))
    slope_wrong_deg = np.degrees(slope_wrong_rad)
    write_raster(out_dir / "heldout-geom-04-wrong/sources/andes_elevation_deg.tif", z36.astype(np.float32), "EPSG:4326", t36)
    write_raster(out_dir / "heldout-geom-04-wrong/output/andes_slope_degrees.tif", slope_wrong_deg.astype(np.float32), "EPSG:4326", t36)
    track("heldout-geom-04-wrong/sources/andes_elevation_deg.tif")
    track("heldout-geom-04-wrong/output/andes_slope_degrees.tif")

    # Case 37: heldout-geom-05-correct (Sweden reserve: area in m2 via EPSG:3006 projection)
    p37 = Polygon([(18.000, 65.000), (18.040, 65.000), (18.040, 65.025), (18.000, 65.025), (18.000, 65.000)])
    geod37 = pyproj.Geod(ellps="WGS84")
    true_area_37 = abs(geod37.geometry_area_perimeter(p37)[0])
    write_vector_geojson(
        out_dir / "heldout-geom-05-correct/sources/sweden_reserve.geojson",
        [p37],
        {"reserve_id": ["SW-RES-44"]},
        "Polygon",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-geom-05-correct/output/sweden_reserve_measured.geojson",
        [p37],
        {"reserve_id": ["SW-RES-44"], "area_sqm": [round(true_area_37, 1)]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-geom-05-correct/sources/sweden_reserve.geojson")
    track("heldout-geom-05-correct/output/sweden_reserve_measured.geojson")

    # Case 38: heldout-geom-06-correct (California pipeline 250m buffer in EPSG:32611)
    trans38_to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32611", always_xy=True)
    trans38_to_wgs = pyproj.Transformer.from_crs("EPSG:32611", "EPSG:4326", always_xy=True)
    coords_wgs38 = [(-117.50, 34.00), (-117.48, 34.02), (-117.45, 34.05)]
    line38 = LineString(coords_wgs38)
    coords_utm38 = [trans38_to_utm.transform(x, y) for x, y in coords_wgs38]
    line38_utm = LineString(coords_utm38)
    buf38_utm = line38_utm.buffer(250.0)  # exact 250m buffer in UTM
    # Reproject buffer back to WGS84 for deliverable
    exterior_wgs = [trans38_to_wgs.transform(x, y) for x, y in buf38_utm.exterior.coords]
    buf38_wgs = Polygon(exterior_wgs)
    write_vector_geojson(
        out_dir / "heldout-geom-06-correct/sources/california_pipeline.geojson",
        [line38],
        {"pipeline_id": ["CA-GAS-250"]},
        "LineString",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-geom-06-correct/output/california_pipeline_buffer.geojson",
        [buf38_wgs],
        {"pipeline_id": ["CA-GAS-250"], "buffer_dist_m": [250.0]},
        "Polygon",
        "EPSG:4326",
    )
    track("heldout-geom-06-correct/sources/california_pipeline.geojson")
    track("heldout-geom-06-correct/output/california_pipeline_buffer.geojson")

    # Case 39: heldout-geom-07-correct (Baltic cable: geodesic length in metres via Geod)
    coords39 = [(19.00, 58.00), (19.50, 58.20), (20.20, 58.50)]
    line39 = LineString(coords39)
    geod39 = pyproj.Geod(ellps="WGS84")
    true_len_39 = geod39.geometry_length(line39)
    write_vector_geojson(
        out_dir / "heldout-geom-07-correct/sources/baltic_cable.geojson",
        [line39],
        {"cable_id": ["BALTIC-FIBER-01"]},
        "LineString",
        "EPSG:4326",
    )
    write_vector_geojson(
        out_dir / "heldout-geom-07-correct/output/baltic_cable_measured.geojson",
        [line39],
        {"cable_id": ["BALTIC-FIBER-01"], "length_m": [round(true_len_39, 1)]},
        "LineString",
        "EPSG:4326",
    )
    track("heldout-geom-07-correct/sources/baltic_cable.geojson")
    track("heldout-geom-07-correct/output/baltic_cable_measured.geojson")

    # Case 40: heldout-geom-08-correct (Colorado slope: metric-scaled cell spacing dx, dy)
    t40 = from_origin(-105.5, 39.0, 0.0005, 0.0005)
    y40, x40 = np.mgrid[0:50, 0:50]
    z40 = 2800.0 + 350.0 * np.sin(x40 / 6.0) + 250.0 * np.cos(y40 / 6.0)
    # Metric cell sizes at lat 39.0 N:
    dx_m_40 = 0.0005 * 111320.0 * math.cos(math.radians(39.0))  # ~43.25 m
    dy_m_40 = 0.0005 * 111320.0                                 # ~55.66 m
    dz_dx_40 = np.gradient(z40, dx_m_40, axis=1)
    dz_dy_40 = np.gradient(z40, dy_m_40, axis=0)
    slope_correct_rad_40 = np.arctan(np.sqrt(dz_dx_40**2 + dz_dy_40**2))
    slope_correct_deg_40 = np.degrees(slope_correct_rad_40)
    write_raster(out_dir / "heldout-geom-08-correct/sources/colorado_dem_deg.tif", z40.astype(np.float32), "EPSG:4326", t40)
    write_raster(out_dir / "heldout-geom-08-correct/output/colorado_slope_degrees.tif", slope_correct_deg_40.astype(np.float32), "EPSG:4326", t40)
    track("heldout-geom-08-correct/sources/colorado_dem_deg.tif")
    track("heldout-geom-08-correct/output/colorado_slope_degrees.tif")

    # Write manifest.json
    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic generator for Terraproof held-out cases.")
    parser.add_argument("outdir", type=str, help="Output directory where cases will be generated.")
    args = parser.parse_args()

    out_dir = Path(args.outdir)
    print(f"Generating held-out cases into: {out_dir}")
    manifest = generate_all(out_dir)
    print(f"Successfully generated {len(manifest)} files across 40 verification cases.")
    print(f"Manifest written to: {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
