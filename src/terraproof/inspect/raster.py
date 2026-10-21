"""Read-only raster inspection with rasterio."""

from __future__ import annotations

import math
import os

import numpy as np
import rasterio
from rasterio.enums import Resampling

from terraproof._common import crs_summary

# Sampling reads at most this many pixels per side so large rasters stay fast.
MAX_SAMPLE_SIDE = 1024


def _band_stats(src, band: int, scale: float, offset: float) -> dict:
    """Sampled statistics over valid pixels, with scale and offset applied.

    A decimated nearest-neighbour read keeps the result deterministic and cheap.
    """
    height, width = src.height, src.width
    factor = max(1, math.ceil(max(height, width) / MAX_SAMPLE_SIDE))
    out_shape = (math.ceil(height / factor), math.ceil(width / factor))
    data = src.read(band, out_shape=out_shape, masked=True, resampling=Resampling.nearest)
    values = np.ma.compressed(data).astype(np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {"valid_sample_count": 0, "min": None, "max": None, "p1": None, "p99": None}
    if scale != 1.0 or offset != 0.0:
        values = values * scale + offset
    p1, p99 = np.percentile(values, [1, 99])
    return {
        "valid_sample_count": int(values.size),
        "min": float(values.min()),
        "max": float(values.max()),
        "p1": float(p1),
        "p99": float(p99),
    }


def inspect_raster(path: str | os.PathLike) -> dict:
    """Describe a raster: grid, CRS, per-band dtype, nodata, scale/offset, layout, and sampled statistics."""
    path = os.fspath(path)
    with rasterio.open(path) as src:
        transform = list(src.transform)[:6]
        bands = []
        for position, band in enumerate(src.indexes):
            rows, cols = src.block_shapes[position]
            scale, offset = src.scales[position], src.offsets[position]
            bands.append(
                {
                    "index": int(band),
                    "dtype": src.dtypes[position],
                    "nodata": src.nodatavals[position],
                    "scale": scale,
                    "offset": offset,
                    "block_size": {"width": int(cols), "height": int(rows)},
                    "overview_count": len(src.overviews(band)),
                    "stats": _band_stats(src, band, scale, offset),
                }
            )
        return {
            "kind": "raster",
            "path": path,
            "driver": src.driver,
            "crs": crs_summary(src.crs) if src.crs else None,
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "transform": transform,
            "resolution": [abs(transform[0]), abs(transform[4])],
            "bounds": list(src.bounds),
            "tiled": bool(src.profile.get("tiled", False)),
            "compression": getattr(src.compression, "value", None),
            "bands": bands,
        }
