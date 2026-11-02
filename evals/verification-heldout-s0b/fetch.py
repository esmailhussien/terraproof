#!/usr/bin/env python
"""Fetch the real public-source windows and metadata used by the
verification-heldout-s0b cases (all new places; at least one above 65 deg).

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

# Sentinel-2 L2A scene: Tromso area (MGRS tile 33WXT, 2025-09-15; lat ~69-70 N),
# Earth Search `sentinel-2-l2a`, COGs on the public sentinel-cogs bucket.
S2_ITEM_URL = (
    "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/"
    "S2C_33WXT_20250915_0_L2A"
)
S2_BASE = (
    "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/"
    "33/W/XT/2025/9/S2C_33WXT_20250915_0_L2A/"
)

# 20 m classification windows: A = rich (shadow, veg, water, clouds 8/9, snow),
# B = swath-edge wedge (class 0 everywhere), C = swath edge (fill, land,
# water mixed).
S2_WA = (5184, 1872, 256, 256)
S2_WB = (0, 0, 512, 512)
S2_WC = (4224, 192, 512, 512)
S2_WA_10M = (10368, 3744, 512, 512)   # 10 m bands aligned to window A
S2_WB_10M = (0, 0, 1024, 1024)        # 10 m band aligned to window B

# Copernicus DEM GLO-30 windows (both new tiles).
COPDEM_NORWAY = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N69_00_E019_00_DEM/"
    "Copernicus_DSM_COG_10_N69_00_E019_00_DEM.tif",
    (1200, 2400, 400, 400),     # Lyngen, Norway; lat ~69.3 N; X spacing 2x Y
)
COPDEM_MATTERHORN = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N46_00_E007_00_DEM/"
    "Copernicus_DSM_COG_10_N46_00_E007_00_DEM.tif",
    (2400, 3100, 400, 400),     # Matterhorn/Zermatt region; lat ~46.1 N
)

# USGS 3DEP 1/3 arc-second tile n33w118 (Los Angeles coast) + sidecar.
DEP3_N33W118_TIF = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "n33w118/USGS_13_n33w118.tif"
)
DEP3_N33W118_XML = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "n33w118/USGS_13_n33w118.xml"
)
DEP3_WIN = (8650, 4830, 604, 604)   # coastal: declared fill, land, many real zeros

# Natural Earth 110m admin-0 countries, pinned at tag v5.1.2 (public domain).
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
    s2 = root / "s2"
    cop = root / "copdem"
    dep = root / "usgs3dep"
    ne = root / "naturalearth"

    _fetch_plain(S2_ITEM_URL, s2 / "item.json")
    names.append("s2/item.json")
    _fetch_plain(S2_BASE + "tileinfo_metadata.json", s2 / "tileinfo_metadata.json")
    names.append("s2/tileinfo_metadata.json")
    _fetch_plain(S2_BASE + "granule_metadata.xml", s2 / "granule_metadata.xml")
    names.append("s2/granule_metadata.xml")

    _fetch_window(S2_BASE + "SCL.tif", S2_WA, s2 / "wa_SCL.tif")
    names.append("s2/wa_SCL.tif")
    _fetch_window(S2_BASE + "SCL.tif", S2_WB, s2 / "wb_SCL.tif")
    names.append("s2/wb_SCL.tif")
    _fetch_window(S2_BASE + "SCL.tif", S2_WC, s2 / "wc_SCL.tif")
    names.append("s2/wc_SCL.tif")
    for band in ("B02", "B03", "B08"):
        _fetch_window(S2_BASE + f"{band}.tif", S2_WA_10M, s2 / f"wa_{band}.tif")
        names.append(f"s2/wa_{band}.tif")
    _fetch_window(S2_BASE + "B03.tif", S2_WB_10M, s2 / "wb_B03.tif")
    names.append("s2/wb_B03.tif")

    for rel, (u, win) in (("norway", COPDEM_NORWAY),
                          ("matterhorn", COPDEM_MATTERHORN)):
        _fetch_window(u, win, cop / f"{rel}_win.tif")
        names.append(f"copdem/{rel}_win.tif")

    _fetch_window(DEP3_N33W118_TIF, DEP3_WIN, dep / "USGS_13_n33w118_win.tif")
    names.append("usgs3dep/USGS_13_n33w118_win.tif")
    _fetch_plain(DEP3_N33W118_XML, dep / "USGS_13_n33w118.xml")
    names.append("usgs3dep/USGS_13_n33w118.xml")

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
