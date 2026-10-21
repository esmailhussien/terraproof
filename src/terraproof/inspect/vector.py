"""Read-only vector inspection with pyogrio and shapely (no pandas)."""

from __future__ import annotations

import math
import os

import numpy as np
import pyogrio
import pyogrio.raw
import shapely

from terraproof._common import GEOMETRY_TYPE_NAMES, InputError, crs_summary

INDEX_SAMPLE_SIZE = 10


def _first_indices(mask: np.ndarray) -> list[int]:
    return np.flatnonzero(mask)[:INDEX_SAMPLE_SIZE].tolist()


def _null_count(values: np.ndarray) -> int:
    kind = values.dtype.kind
    if kind == "f":
        return int(np.isnan(values).sum())
    if kind in "mM":
        return int(np.isnat(values).sum())
    if kind == "O":
        return sum(1 for item in values if item is None or (isinstance(item, float) and math.isnan(item)))
    return 0


def _bounds(total_bounds) -> list[float] | None:
    if total_bounds is None:
        return None
    values = [float(v) for v in total_bounds]
    if any(math.isnan(v) for v in values):
        return None
    return values


def inspect_vector(path: str | os.PathLike, layer: str | None = None) -> dict:
    """Describe a vector layer: CRS, bounds, fields, geometry types, and geometry problems."""
    path = os.fspath(path)
    info = pyogrio.read_info(path, layer=layer)
    meta, _fids, geoms, field_data = pyogrio.raw.read(path, layer=layer)
    if geoms is None:
        raise InputError(f"layer has no geometry column: {path}")

    geom_objects = shapely.from_wkb(geoms)
    missing = np.asarray(shapely.is_missing(geom_objects), dtype=bool)
    empty = np.asarray(shapely.is_empty(geom_objects), dtype=bool) & ~missing
    invalid = ~np.asarray(shapely.is_valid(geom_objects), dtype=bool) & ~missing

    type_ids = np.asarray(shapely.get_type_id(geom_objects))[~missing]
    type_counts: dict[str, int] = {}
    for type_id, count in zip(*np.unique(type_ids, return_counts=True)):
        type_counts[GEOMETRY_TYPE_NAMES[int(type_id)]] = int(count)
    type_counts = dict(sorted(type_counts.items()))

    ogr_types = list(meta.get("ogr_types", []))
    fields = []
    for index, name in enumerate(meta["fields"]):
        fields.append(
            {
                "name": str(name),
                "type": ogr_types[index] if index < len(ogr_types) else str(meta["dtypes"][index]),
                "null_count": _null_count(field_data[index]),
            }
        )

    return {
        "kind": "vector",
        "path": path,
        "driver": info["driver"],
        "layer": info["layer_name"],
        "feature_count": int(len(geoms)),
        "crs": crs_summary(info["crs"]),
        "bounds": _bounds(info["total_bounds"]),
        "geometry_types": list(type_counts),
        "geometry_type_counts": type_counts,
        "fields": fields,
        "geometry": {
            "null_count": int(missing.sum()),
            "empty_count": int(empty.sum()),
            "invalid_count": int(invalid.sum()),
            "null_indices": _first_indices(missing),
            "empty_indices": _first_indices(empty),
            "invalid_indices": _first_indices(invalid),
        },
    }
