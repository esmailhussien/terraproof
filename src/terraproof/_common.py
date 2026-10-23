"""Helpers shared by the inspectors, checks, and evidence report."""

from __future__ import annotations

import hashlib
import math
import os
import sys
from pathlib import Path
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


def assets_root() -> Path:
    """The directory that holds `skills/` and `routing/`, in a checkout or an install.

    The current working directory is never used: the assets belong to the installed
    package, not to whichever project happens to be open.
    """
    package = Path(__file__).resolve().parent
    candidates = [package, package / "data", package / "_data", package / "resources",
                  Path(sys.prefix) / "share" / "terraproof", *package.parents]
    for candidate in candidates:
        if (candidate / "routing" / "registry.json").is_file() and (candidate / "skills").is_dir():
            return candidate
    raise InputError("Terraproof skills/routing assets not found beside the package or in share/terraproof")


def sha256_and_size(path: str | os.PathLike) -> tuple[str, int]:
    """Return the SHA-256 hex digest and byte size of a file."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _horizontal_component(crs: pyproj.CRS) -> pyproj.CRS | None:
    """The horizontal part of a compound CRS (its first non-vertical component), or the CRS itself."""
    if not crs.is_compound:
        return crs
    for component in crs.sub_crs_list:
        if not component.is_vertical:
            return component
    return None


def _kind(crs: pyproj.CRS | None) -> str:
    if crs is None:
        return "none"
    if crs.is_projected:
        return "projected"
    if crs.is_geographic:
        return "geographic"
    if crs.is_geocentric:
        return "geocentric"
    return "other"


def crs_summary(crs_value: Any) -> dict | None:
    """Describe a CRS given as WKT, an authority string, or a rasterio/pyproj CRS.

    `horizontal_kind` and `horizontal_axis_units` describe the horizontal component, which
    for a compound CRS (horizontal + vertical) is the first non-vertical sub-CRS. `horizontal_kind`
    is one of projected, geographic, geocentric, other, or none. Returns None when there is no CRS.
    """
    if crs_value is None:
        return None
    crs = pyproj.CRS.from_user_input(crs_value)
    axis_units = crs.axis_info[0].unit_name if crs.axis_info else None
    horizontal = _horizontal_component(crs)
    horizontal_units = horizontal.axis_info[0].unit_name if horizontal is not None and horizontal.axis_info else None
    return {
        "wkt": crs.to_wkt(),
        "epsg": crs.to_epsg(),
        "name": crs.name,
        "is_geographic": bool(crs.is_geographic),
        "is_projected": bool(crs.is_projected),
        "is_geocentric": bool(crs.is_geocentric),
        "axis_units": axis_units,
        "horizontal_kind": _kind(horizontal),
        "horizontal_axis_units": horizontal_units,
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
