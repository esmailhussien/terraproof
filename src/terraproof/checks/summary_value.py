"""Opt-in summary check: report.summary_value.

A JSON report delivers numbers under declared keys (dots for nesting, integers for list positions, as in
``bands.0.mean``). Each declared summary names its key, its statistic, and the source it summarises; the
check recomputes the statistic and compares, one result per summary:

- raster source: ``mean``, ``count``, ``sum``, ``min`` or ``max`` of band 1's valid cells (not
  nodata, finite), decoded with the file's own scale and offset; an optional validity mask
  (`summary_mask`, 1 = include) on the same grid restricts the cells. ``fraction`` is the share of the
  source's valid cells the mask marks 1, or without a mask the share of all cells that are valid, in
  `summary_unit` ``fraction`` or ``percent``
- vector source: ``count`` of features, or their summed geodesic ``area`` or ``length`` in
  `summary_unit`; `summary_feature` (``FIELD=VALUE``) selects features

A number is accepted when it matches within the statistic's tolerance, or within rounding to the decimals
it is written with. Numbers in the report that no summary declares are listed (`undeclared_numbers`), never
judged. Nothing is read from free text, and nothing is inferred: an undeclared key, statistic, source or
unit is not-run, naming it.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.metric_values import UNITS, _geod, _read, _to_geographic
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "report.summary_value"
RASTER_STATISTICS = ("mean", "count", "sum", "min", "max", "fraction")
VECTOR_STATISTICS = ("count", "area", "length")
FRACTION_UNITS = {"fraction": 1.0, "percent": 100.0}
UNIT_STATISTICS = ("area", "length", "fraction")
RTOL, ATOL = 1e-4, 1e-6   # raster statistics: float32 storage
GEODESIC_RTOL = 0.01      # vector area and length, as geometry.metric_values
WINDOW_SIZE = 512
MAX_LISTED = 50


def _load(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle, parse_float=Decimal)


def _lookup(document, key: str):
    """The finite number under a dotted key, and half a unit in its last written decimal; None if absent."""
    value = document
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return float(value), 0.5 * 10.0 ** value.as_tuple().exponent
    return float(value), 0.5


def numeric_keys(document, prefix: str = "") -> list[str]:
    """Every number's dotted key in a JSON document."""
    if isinstance(document, dict):
        items = document.items()
    elif isinstance(document, list):
        items = ((str(i), v) for i, v in enumerate(document))
    else:
        return [prefix] if isinstance(document, (int, Decimal)) and not isinstance(document, bool) and prefix else []
    return [key for name, value in items for key in numeric_keys(value, f"{prefix}.{name}" if prefix else name)]


def _raster(source: dict, statistic: str, mask: dict | None):
    count, cells, total, low, high = 0, 0, 0.0, math.inf, -math.inf
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
                    # fraction: the share of all cells that are valid, or of valid cells the mask keeps
                    cells += int(valid.sum()) if keep_src is not None else valid.size
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
    if statistic == "fraction":
        return (count / cells if cells else None), cells
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
    if statistic in UNIT_STATISTICS and unit is None:
        missing.append("summary_unit")
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to check the delivered summary.",
                       missing_bindings=missing, **evidence)]
    if output.get("kind") != "report":
        return [result(CHECK_ID, NOT_RUN, "Summary values are checked on a JSON report output.", **evidence)]
    kind = source.get("kind")
    allowed = RASTER_STATISTICS if kind == "raster" else VECTOR_STATISTICS if kind == "vector" else ()
    units = FRACTION_UNITS if statistic == "fraction" else UNITS.get(statistic, {})
    if statistic not in allowed or (statistic in UNIT_STATISTICS and unit not in units):
        return [result(CHECK_ID, NOT_RUN, f"For a {kind} source, summary_statistic must be one of "
                       f"{', '.join(allowed) or 'none'}" + (f", and summary_unit one of {', '.join(units)}"
                                                           if statistic in UNIT_STATISTICS else "") + ".",
                       **evidence)]
    if mask is not None and (kind != "raster" or mask.get("kind") != "raster" or _grid_problems(source, mask)):
        return [result(CHECK_ID, NOT_RUN, "summary_mask must be a raster on the source's grid.", **evidence)]
    try:
        delivered = _lookup(_load(output["path"]), key)
        if delivered is None:
            return [result(CHECK_ID, NOT_RUN, f"The report holds no finite number under '{key}'.", **evidence)]
        delivered, rounding = delivered
        expected, used = (_raster(source, statistic, mask) if kind == "raster"
                          else _vector(source, statistic, feature, unit))
    except (OSError, ValueError, KeyError, rasterio.errors.RasterioError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot recompute the summary ({error}).", **evidence)]
    if expected is not None and statistic == "fraction":
        expected *= FRACTION_UNITS[unit]
    evidence.update(delivered=delivered, expected=expected, cells_or_features=used)
    if expected is None:
        return [result(CHECK_ID, NOT_RUN, "The source has no valid value to summarise.", **evidence)]
    if statistic == "count":
        agrees = delivered == expected
    else:
        tolerance = GEODESIC_RTOL * abs(expected) if kind == "vector" else RTOL * abs(expected) + ATOL
        evidence.update(tolerance=tolerance, written_rounding=rounding)
        agrees = abs(delivered - expected) <= max(tolerance, rounding * (1 + 1e-9))
    if not agrees:
        return [result(CHECK_ID, FAIL, f"The report's {key} is {delivered:g}, but the {statistic} of the declared "
                       f"source is {expected:g}.", **evidence)]
    return [result(CHECK_ID, PASS, f"The report's {key} matches the {statistic} of the declared source.", **evidence)]


def check_summaries(output: dict, entries: list[dict]) -> list:
    """One result per declared summary (key, statistic, source, unit, feature, mask), each listing the
    report's numbers that no summary declares."""
    results = [r for entry in entries for r in check_summary_value(
        output, entry.get("key"), entry.get("statistic"), entry.get("source"), entry.get("unit"),
        entry.get("feature"), entry.get("mask"))]
    if output.get("kind") == "report":
        try:
            declared = {entry.get("key") for entry in entries}
            undeclared = [key for key in numeric_keys(_load(output["path"])) if key not in declared]
        except (OSError, ValueError):
            undeclared = None
        if undeclared is not None:
            for r in results:
                r.evidence.update(undeclared_numbers=undeclared[:MAX_LISTED],
                                  undeclared_number_count=len(undeclared))
    return results
