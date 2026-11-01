"""Opt-in summary check: report.summary_value.

A JSON report delivers one number under a declared key (`summary_key`, dots for nesting). The check
recomputes the declared statistic (`summary_statistic`) from the declared source and compares:

- raster source: ``mean``, ``count``, ``sum``, ``min`` or ``max`` of band 1's valid cells (not
  nodata, finite), decoded with the file's own scale and offset; an optional validity mask
  (`summary_mask`, 1 = include) on the same grid restricts the cells
- vector source: ``count`` of features, or their summed geodesic ``area`` or ``length`` in
  `summary_unit`; `summary_feature` (``FIELD=VALUE``) selects features

Nothing is read from free text, and nothing is inferred: an undeclared key, statistic, source or
unit is not-run, naming it.
"""
from __future__ import annotations

import json
import math

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.metric_values import UNITS, _geod, _read, _to_geographic
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "report.summary_value"
RASTER_STATISTICS = ("mean", "count", "sum", "min", "max")
VECTOR_STATISTICS = ("count", "area", "length")
RTOL, ATOL = 1e-4, 1e-6   # raster statistics: rounding in the report, float32 storage
GEODESIC_RTOL = 0.01      # vector area and length, as geometry.metric_values
WINDOW_SIZE = 512


def _delivered(path: str, key: str):
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _raster(source: dict, statistic: str, mask: dict | None):
    count, total, low, high = 0, 0.0, math.inf, -math.inf
    with rasterio.open(source["path"]) as src:
        scale, offset = src.scales[0], src.offsets[0]
        keep_src = rasterio.open(mask["path"]) if mask else None
        try:
            for row in range(0, src.height, WINDOW_SIZE):
                for col in range(0, src.width, WINDOW_SIZE):
                    window = Window(col, row, min(WINDOW_SIZE, src.width - col), min(WINDOW_SIZE, src.height - row))
                    read = src.read(1, window=window, masked=True)
                    values = np.ma.getdata(read).astype("float64") * scale + offset
                    valid = ~np.ma.getmaskarray(read) & np.isfinite(values)
                    if keep_src is not None:
                        valid &= keep_src.read(1, window=window) == 1
                    chosen = values[valid]
                    count += chosen.size
                    if chosen.size:
                        total += float(chosen.sum())
                        low, high = min(low, float(chosen.min())), max(high, float(chosen.max()))
        finally:
            if keep_src is not None:
                keep_src.close()
    if statistic == "count":
        return count, count
    if not count:
        return None, 0
    return {"mean": total / count, "sum": total, "min": low, "max": high}[statistic], count


def _vector(source: dict, statistic: str, feature: str | None, unit: str | None):
    crs, geoms, fields = _read(source["path"])
    chosen = list(range(len(geoms)))
    if feature:
        field, _, wanted = feature.partition("=")
        if field not in fields:
            raise ValueError(f"the source has no field '{field}'")
        chosen = [i for i in chosen if str(fields[field][i]) == wanted]
    if statistic == "count":
        return len(chosen), len(chosen)
    if crs is None:
        raise ValueError("the vector source declares no CRS")
    geographic, to_geographic = _to_geographic(crs)
    geod = _geod(geographic)
    total = 0.0
    for i in chosen:
        geom = geoms[i]
        if geom is None or geom.is_empty:
            continue
        lonlat = to_geographic(geom) if to_geographic else geom
        total += (abs(geod.geometry_area_perimeter(lonlat)[0]) if statistic == "area" else geod.geometry_length(lonlat))
    return total / UNITS[statistic][unit], len(chosen)


def check_summary_value(output: dict, key: str | None, statistic: str | None, source: dict | None,
                        unit: str | None = None, feature: str | None = None, mask: dict | None = None) -> list:
    evidence = {"output": output.get("path"), "summary_key": key, "summary_statistic": statistic,
                "summary_source": (source or {}).get("path"), "summary_unit": unit, "summary_feature": feature,
                "summary_mask": (mask or {}).get("path")}
    missing = [name for name, value in (("summary_key", key), ("summary_statistic", statistic),
                                        ("summary_source", source)) if value is None]
    if statistic in ("area", "length") and unit is None:
        missing.append("summary_unit")
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to check the delivered summary.",
                       missing_bindings=missing, **evidence)]
    if output.get("kind") != "report":
        return [result(CHECK_ID, NOT_RUN, "Summary values are checked on a JSON report output.", **evidence)]
    kind = source.get("kind")
    allowed = RASTER_STATISTICS if kind == "raster" else VECTOR_STATISTICS if kind == "vector" else ()
    if statistic not in allowed or (statistic in ("area", "length") and unit not in UNITS[statistic]):
        return [result(CHECK_ID, NOT_RUN, f"For a {kind} source, summary_statistic must be one of "
                       f"{', '.join(allowed) or 'none'}" + (f", and summary_unit one of {', '.join(UNITS[statistic])}"
                                                           if statistic in ("area", "length") else "") + ".",
                       **evidence)]
    if mask is not None and (kind != "raster" or mask.get("kind") != "raster" or _grid_problems(source, mask)):
        return [result(CHECK_ID, NOT_RUN, "summary_mask must be a raster on the source's grid.", **evidence)]
    try:
        delivered = _delivered(output["path"], key)
        if delivered is None:
            return [result(CHECK_ID, NOT_RUN, f"The report holds no finite number under '{key}'.", **evidence)]
        expected, used = (_raster(source, statistic, mask) if kind == "raster"
                          else _vector(source, statistic, feature, unit))
    except (OSError, ValueError, KeyError, rasterio.errors.RasterioError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot recompute the summary ({error}).", **evidence)]
    evidence.update(delivered=delivered, expected=expected, cells_or_features=used)
    if expected is None:
        return [result(CHECK_ID, NOT_RUN, "The source has no valid value to summarise.", **evidence)]
    if statistic == "count":
        agrees = delivered == expected
    else:
        tolerance = GEODESIC_RTOL * abs(expected) if kind == "vector" else RTOL * abs(expected) + ATOL
        agrees = abs(delivered - expected) <= tolerance
    if not agrees:
        return [result(CHECK_ID, FAIL, f"The report's {key} is {delivered:g}, but the {statistic} of the declared "
                       f"source is {expected:g}.", **evidence)]
    return [result(CHECK_ID, PASS, f"The report's {key} matches the {statistic} of the declared source.", **evidence)]
