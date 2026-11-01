#!/usr/bin/env python
"""Fetch the real public-source windows and metadata used by the
verification-heldout-real cases.

Usage:
    python fetch.py <cache-dir>

Fetched files are written under <cache-dir> together with manifest.json
(SHA-256 of every fetched file). The URLs are fixed so that a rerun fetches
byte-identical content. No account, API key or requester-pays bucket is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.windows import Window
import requests

# Sentinel-2 L2A scene chosen for the cases (Earth Search STAC, collection
# sentinel-2-l2a; tile 32TMS, 2025-08-31). Derived stage-1 products served by
# Earth Search / element84 as public COGs.
S2_ITEM_URL = (
    "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/"
    "S2B_32TMS_20250831_0_L2A"
)
S2_COGBASE = (
    "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/"
    "32/T/MS/2025/8/S2B_32TMS_20250831_0_L2A/"
)
S2_TILEINFO_URL = S2_COGBASE + "tileinfo_metadata.json"
S2_GRANULE_URL = S2_COGBASE + "granule_metadata.xml"

# Window (col_off, row_off, width, height) in the coordinate reference of each
# raster window source. Window A sits over the Bernese Oberland (Canton Bern,
# Switzerland): mixed vegetation, snow, water, shadow and clouds.
S2_WA_SCL = (4200, 0, 512, 512)      # 20 m, SCL
S2_WA_B11 = (4200, 0, 512, 512)      # 20 m, SWIR16 (B11)
# 10 m band windows aligned to S2_WA_SCL.
S2_WA_10M = (8400, 0, 1024, 1024)
# Window B sits on the swath edge of the same scene: the tileinfo data
# boundary leaves a no-data wedge; this window is entirely fill (SCL class 0).
S2_WB_SCL = (4830, 4426, 512, 512)   # 20 m, SCL (all class 0)
S2_WB_B11 = (4830, 4426, 512, 512)   # 20 m, SWIR16 (all fill value 0)
S2_WB_10M = (9660, 8852, 1024, 1024)  # 10 m, aligned to S2_WB_SCL

# Copernicus DEM GLO-30 windows (EPSG:4326, elevation in metres).
# Nepal tile, window x=1000 y=1000 400x400.
COPDEM_NEPAL_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N28_00_E084_00_DEM/"
    "Copernicus_DSM_COG_10_N28_00_E084_00_DEM.tif"
)
COPDEM_NEPAL_WIN = (1000, 1000, 400, 400)
# Svalbard tile N78 E016: high latitude; X spacing in degrees is 3x the Y
# spacing (as stored in the raster geotransform).
COPDEM_SVALBARD_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N78_00_E016_00_DEM/"
    "Copernicus_DSM_COG_10_N78_00_E016_00_DEM.tif"
)
COPDEM_SVALBARD_WIN = (300, 1400, 400, 400)

# USGS 3DEP 1/3 arc-second tiles and their FGDC metadata sidecars (public).
DEP3_N31W091_TIF = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "n31w091/USGS_13_n31w091.tif"
)
DEP3_N31W091_XML = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "n31w091/USGS_13_n31w091.xml"
)
DEP3_N31W091_WIN = (6000, 7000, 604, 604)
DEP3_N22W159_TIF = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "n22w159/USGS_13_n22w159.tif"
)
DEP3_N22W159_XML = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "n22w159/USGS_13_n22w159.xml"
)
DEP3_N22W159_WIN = (9060, 6860, 512, 512)

# Natural Earth 110m admin-0 countries, pinned to the v5.1.2 tag
# (public domain; CRS84).
NE_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/"
    "geojson/ne_110m_admin_0_countries.geojson"
)

COG_OPTS = {"driver": "GTiff", "tiled": True, "compression": "deflate",
            "predictor": 2, "blockxsize": 512, "blockysize": 512}


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_plain(url: str, dest: Path) -> None:
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)


def _fetch_window(url: str, window: tuple, dest: Path) -> None:
    """Fetch a small COG window and save it as a small tiled raster."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(url, mode="r") as src:
        col_off, row_off, width, height = window
        read_window = Window(col_off, row_off, width, height)
        arr = src.read(1, window=read_window)
        if arr.size == 0:
            raise RuntimeError(f"window {window} of {url} read nothing")
        profile = dict(
            driver="GTiff",
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="deflate",
            nodata=src.nodata,
            crs=src.crs,
            transform=src.window_transform(read_window),
            width=arr.shape[1],
            height=arr.shape[0],
            count=1,
            dtype=src.dtypes[0],
        )
    with rasterio.open(dest, mode="w", **profile) as dst:
        dst.write(arr, 1)
    # overviews: halfx build nested to 2 levels then saved to the file
    with rasterio.open(dest, mode="r+") as dst:
        dst.build_overviews([2, 4])


def fetch_all(cache_dir: str) -> dict:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    files: dict = {}
    s2 = root / "s2"
    cop = root / "copdem"
    dep = root / "usgs3dep"
    ne = root / "naturalearth"

    # STAC item + tileinfo + granule metadata (metadata as found).
    _fetch_plain(S2_ITEM_URL, s2 / "S2B_32TMS_20250831_0_L2A.item.json")
    files["s2/S2B_32TMS_20250831_0_L2A.item.json"] = None
    _fetch_plain(S2_TILEINFO_URL, s2 / "tileinfo_metadata.json")
    files["s2/tileinfo_metadata.json"] = None
    _fetch_plain(S2_GRANULE_URL, s2 / "granule_metadata.xml")
    files["s2/granule_metadata.xml"] = None

    # S2 windows.
    _fetch_window(S2_COGBASE + "SCL.tif", S2_WA_SCL, s2 / "wa_SCL.tif")
    files["s2/wa_SCL.tif"] = None
    _fetch_window(S2_COGBASE + "B11.tif", S2_WA_B11, s2 / "wa_B11.tif")
    files["s2/wa_B11.tif"] = None
    for band in ("B02", "B03", "B08"):
        _fetch_window(S2_COGBASE + band + ".tif", S2_WA_10M, s2 / f"wa_{band}.tif")
        files[f"s2/wa_{band}.tif"] = None
    _fetch_window(S2_COGBASE + "SCL.tif", S2_WB_SCL, s2 / "wb_SCL.tif")
    files["s2/wb_SCL.tif"] = None
    _fetch_window(S2_COGBASE + "B11.tif", S2_WB_B11, s2 / "wb_B11.tif")
    files["s2/wb_B11.tif"] = None
    _fetch_window(S2_COGBASE + "B03.tif", S2_WB_10M, s2 / "wb_B03.tif")
    files["s2/wb_B03.tif"] = None

    # Copernicus DEM windows.
    _fetch_window(COPDEM_NEPAL_URL, COPDEM_NEPAL_WIN, cop / "n28e084_win.tif")
    files["copdem/n28e084_win.tif"] = None
    _fetch_window(COPDEM_SVALBARD_URL, COPDEM_SVALBARD_WIN, cop / "n78e016_win.tif")
    files["copdem/n78e016_win.tif"] = None

    # 3DEP windows + metadata sidecars.
    for name, tif_url, xml_url, win in (
        ("n31w091", DEP3_N31W091_TIF, DEP3_N31W091_XML, DEP3_N31W091_WIN),
        ("n22w159", DEP3_N22W159_TIF, DEP3_N22W159_XML, DEP3_N22W159_WIN),
    ):
        _fetch_window(tif_url, win, dep / f"USGS_13_{name}_win.tif")
        files[f"usgs3dep/USGS_13_{name}_win.tif"] = None
        _fetch_plain(xml_url, dep / f"USGS_13_{name}.xml")
        files[f"usgs3dep/USGS_13_{name}.xml"] = None

    # Natural Earth.
    _fetch_plain(NE_COUNTRIES_URL, ne / "ne_110m_admin_0_countries.geojson")
    files["naturalearth/ne_110m_admin_0_countries.geojson"] = None

    manifest = {"files": sorted(files), "sha256": {}}
    for name in sorted(files):
        p = root / name
        if not p.is_file():
            raise RuntimeError(f"missing fetched file: {name}")
        manifest["sha256"][name] = _sha256_of(p)
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    m = fetch_all(argv[1])
    print(json.dumps(m["sha256"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
