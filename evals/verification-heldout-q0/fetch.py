#!/usr/bin/env python
"""Fetch the real public-source windows and metadata used by the
verification-heldout-q0 cases.

Usage:
    python fetch.py <cache-dir>

Fetched files are written under <cache-dir> together with manifest.json
(SHA-256 of every fetched file). The URLs are fixed so that a rerun fetches
byte-identical content. No account, API key or requester-pays bucket is used.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import rasterio
from rasterio.windows import Window
import requests

# ---- Sentinel-2 L2A, Earth Search distribution `sentinel-2-l2a` (v0): the
# stored COG values already include the -0.1 BOA offset (established by the
# item's own `earthsearch:boa_offset_applied = true` property and by decoded
# water reflectances; see README).
V0_ITEM_URL = (
    "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/"
    "S2B_32TMS_20250831_0_L2A"
)
V0_BASE = (
    "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/"
    "32/T/MS/2025/8/S2B_32TMS_20250831_0_L2A/"
)

# ---- Sentinel-2 L2A, Earth Search distribution `sentinel-2-c1-l2a` (c1):
# stored COG values are raw SAFE DNs; the -0.1 BOA offset must still be
# applied (established by pixel evidence and the absence of the
# earthsearch:boa_offset_applied property; see README).
C1_ITEM_URL = (
    "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/"
    "S2B_T32TMS_20230928T102123_L2A"
)
C1_BASE = (
    "https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/"
    "sentinel-2-c1-l2a/32/T/MS/2023/9/S2B_T32TMS_20230928T102123_L2A/"
)

# Window A (over the Bernese Oberland: vegetation, snow, water, shadow and
# clouds in the v0 scene; vegetation, snow and water in the c1 scene).
WA_SCL = (4200, 0, 512, 512)          # 20 m, SCL
WA_B11 = (4200, 0, 512, 512)          # 20 m, SWIR16
WA_10M = (8400, 0, 1024, 1024)        # 10 m bands, aligned to WA_SCL
# Window B sits in the swath-edge no-data wedge of the v0 scene (SCL and
# bands entirely at the declared fill value 0).
WB_SCL = (4830, 4426, 512, 512)       # 20 m, SCL (all class 0)
WB_10M = (9660, 8852, 1024, 1024)     # 10 m band aligned to WB_SCL

COPDEM_NEPAL_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N28_00_E084_00_DEM/"
    "Copernicus_DSM_COG_10_N28_00_E084_00_DEM.tif"
)
COPDEM_NEPAL_WIN = (1000, 1000, 400, 400)
COPDEM_SVALBARD_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N78_00_E016_00_DEM/"
    "Copernicus_DSM_COG_10_N78_00_E016_00_DEM.tif"
)
COPDEM_SVALBARD_WIN = (300, 1400, 400, 400)

DEP3_TILES = {
    "n31w091": {
        "tif": "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/"
               "current/n31w091/USGS_13_n31w091.tif",
        "xml": "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/"
               "current/n31w091/USGS_13_n31w091.xml",
        "win": (6000, 7000, 604, 604),
    },
    "n22w159": {
        "tif": "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/"
               "current/n22w159/USGS_13_n22w159.tif",
        "xml": "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/"
               "current/n22w159/USGS_13_n22w159.xml",
        "win": (9060, 6860, 512, 512),
    },
}

NE_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/"
    "geojson/ne_110m_admin_0_countries.geojson"
)


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
            predictor=2,
            dtype=src.dtypes[0],
            nodata=src.nodata,
            crs=src.crs,
            transform=src.window_transform(read_window),
            width=arr.shape[1],
            height=arr.shape[0],
            count=1,
        )
    with rasterio.open(dest, mode="w", **profile) as dst:
        dst.write(arr, 1)
    with rasterio.open(dest, mode="r+") as dst:
        dst.build_overviews([2, 4])


def fetch_all(cache_dir: str) -> dict:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    s2v0 = root / "s2-v0"
    s2c1 = root / "s2-c1"
    cop = root / "copdem"
    dep = root / "usgs3dep"
    ne = root / "naturalearth"

    _fetch_plain(V0_ITEM_URL, s2v0 / "item.json")
    names.append("s2-v0/item.json")
    _fetch_plain(V0_BASE + "tileinfo_metadata.json", s2v0 / "tileinfo_metadata.json")
    names.append("s2-v0/tileinfo_metadata.json")
    _fetch_plain(V0_BASE + "granule_metadata.xml", s2v0 / "granule_metadata.xml")
    names.append("s2-v0/granule_metadata.xml")

    _fetch_plain(C1_ITEM_URL, s2c1 / "item.json")
    names.append("s2-c1/item.json")
    _fetch_plain(C1_BASE + "tileInfo.json", s2c1 / "tileInfo.json")
    names.append("s2-c1/tileInfo.json")
    _fetch_plain(C1_BASE + "product_metadata.xml", s2c1 / "product_metadata.xml")
    names.append("s2-c1/product_metadata.xml")

    _fetch_window(V0_BASE + "SCL.tif", WA_SCL, s2v0 / "wa_SCL.tif")
    names.append("s2-v0/wa_SCL.tif")
    for band in ("B02", "B03", "B08"):
        _fetch_window(V0_BASE + f"{band}.tif", WA_10M, s2v0 / f"wa_{band}.tif")
        names.append(f"s2-v0/wa_{band}.tif")
    _fetch_window(V0_BASE + "B11.tif", WA_B11, s2v0 / "wa_B11.tif")
    names.append("s2-v0/wa_B11.tif")
    _fetch_window(V0_BASE + "SCL.tif", WB_SCL, s2v0 / "wb_SCL.tif")
    names.append("s2-v0/wb_SCL.tif")
    _fetch_window(V0_BASE + "B03.tif", WB_10M, s2v0 / "wb_B03.tif")
    names.append("s2-v0/wb_B03.tif")

    for band in ("SCL", "B11"):
        _fetch_window(C1_BASE + f"{band}.tif", WA_SCL, s2c1 / f"wa_{band}.tif")
        names.append(f"s2-c1/wa_{band}.tif")
    for band in ("B02", "B03", "B08"):
        _fetch_window(C1_BASE + f"{band}.tif", WA_10M, s2c1 / f"wa_{band}.tif")
        names.append(f"s2-c1/wa_{band}.tif")

    _fetch_window(COPDEM_NEPAL_URL, COPDEM_NEPAL_WIN, cop / "n28e084_win.tif")
    names.append("copdem/n28e084_win.tif")
    _fetch_window(COPDEM_SVALBARD_URL, COPDEM_SVALBARD_WIN, cop / "n78e016_win.tif")
    names.append("copdem/n78e016_win.tif")

    for tile, spec in DEP3_TILES.items():
        _fetch_window(spec["tif"], spec["win"], dep / f"USGS_13_{tile}_win.tif")
        names.append(f"usgs3dep/USGS_13_{tile}_win.tif")
        _fetch_plain(spec["xml"], dep / f"USGS_13_{tile}.xml")
        names.append(f"usgs3dep/USGS_13_{tile}.xml")

    _fetch_plain(NE_COUNTRIES_URL, ne / "ne_110m_admin_0_countries.geojson")
    names.append("naturalearth/ne_110m_admin_0_countries.geojson")

    manifest = {"files": sorted(names), "sha256": {}}
    for name in sorted(names):
        p = root / name
        if not p.is_file():
            raise RuntimeError(f"missing fetched file: {name}")
        manifest["sha256"][name] = _sha256_of(p)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
