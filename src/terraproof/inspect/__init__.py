"""Dataset inspectors. They read local files only and never use the network."""

from __future__ import annotations

import json
import os

from terraproof._common import InputError
from terraproof.inspect.raster import inspect_raster
from terraproof.inspect.stac import inspect_stac_item
from terraproof.inspect.vector import inspect_vector

__all__ = ["inspect_dataset", "inspect_raster", "inspect_stac_item", "inspect_vector"]

VECTOR_SUFFIXES = frozenset({".gpkg", ".geojson", ".json", ".shp", ".fgb", ".parquet"})
RASTER_SUFFIXES = frozenset({".tif", ".tiff", ".vrt", ".jp2"})
JSON_SUFFIXES = frozenset({".json", ".geojson"})


def _is_stac_item(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("type") == "Feature" and "stac_version" in data


def inspect_dataset(path: str | os.PathLike) -> dict:
    """Inspect a file, choosing the inspector from its extension and, for JSON, its content."""
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise InputError(f"file not found: {path}")
    suffix = os.path.splitext(path)[1].lower()
    if suffix in JSON_SUFFIXES and _is_stac_item(path):
        return inspect_stac_item(path)
    if suffix in RASTER_SUFFIXES:
        return inspect_raster(path)
    if suffix in VECTOR_SUFFIXES:
        return inspect_vector(path)
    raise InputError(f"unsupported file type '{suffix or '(none)'}': {path}")
