"""Helpers shared by the inspectors, checks, and evidence report."""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

import numpy as np
import pyproj

GEOMETRY_TYPE_NAMES = {
    0: "Point",
    1: "LineString",
    2: "LinearRing",
    3: "Polygon",
    4: "MultiPoint",
    5: "MultiLineString",
    6: "MultiPolygon",
    7: "GeometryCollection",
}


class InputError(ValueError):
    """An input file is missing, unreadable, or not a supported dataset."""


def sha256_and_size(path: str | os.PathLike) -> tuple[str, int]:
    """Return the SHA-256 hex digest and byte size of a file."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def crs_summary(crs_value: Any) -> dict | None:
    """Describe a CRS given as WKT, an authority string, or a rasterio/pyproj CRS.

    Returns None when there is no CRS.
    """
    if crs_value is None:
        return None
    crs = pyproj.CRS.from_user_input(crs_value)
    axis_units = crs.axis_info[0].unit_name if crs.axis_info else None
    return {
        "wkt": crs.to_wkt(),
        "epsg": crs.to_epsg(),
        "name": crs.name,
        "is_geographic": bool(crs.is_geographic),
        "is_projected": bool(crs.is_projected),
        "axis_units": axis_units,
    }


def jsonable(value: Any) -> Any:
    """Convert numpy and path values to JSON-safe Python values.

    Non-finite floats become the strings "NaN", "Infinity", and "-Infinity" so
    that a NaN nodata value is not mistaken for "no nodata declared".
    """
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return value
