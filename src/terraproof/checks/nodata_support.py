"""Opt-in valid-support check: raster.nodata_support.

The caller declares the source rasters an output was made from and how their valid cells combine:

- ``all``   a cell is valid only where every source is valid (differences, ratios, band maths)
- ``any``   a cell is valid where at least one source is valid (composites that skip gaps)

A source cell is valid when it is finite, unmasked and, if the caller declares that source's fill
value, not equal to it. Declaring the fill matters when a source stores fill as 0 without saying so.
The output must be valid exactly where the rule says: an output value where the sources hold only
fill means fill was treated as data, and output nodata where the sources are valid means valid
values (for example real zeros) were treated as fill. Both fail. Sources and output must share one
grid. Cloud or QA masking that legitimately removes valid cells is not described by this rule: use
rs.cloud_mask_applied for it.
"""
from __future__ import annotations

from contextlib import ExitStack
import math

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "raster.nodata_support"
RULES = ("all", "any")
WINDOW_SIZE = 256


def _fill_values(source_nodata, count):
    """One declared fill value (or None to use the file's own mask) per source."""
    if source_nodata is None:
        return [None] * count
    if len(source_nodata) != count:
        return None
    values = []
    for value in source_nodata:
        if value is None:
            values.append(None)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            values.append(float(value))
        else:
            return None
    return values


def check_nodata_support(output: dict, sources: list | None, source_nodata: list | None, rule: str | None) -> list:
    evidence = {"output": output.get("path"), "rule": rule, "sources": [s.get("path") for s in sources or []],
                "source_nodata": source_nodata}
    missing = [name for name, value in (("support_rule", rule), ("support_sources", sources)) if not value]
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to check the output's valid support.",
                       missing_bindings=missing, **evidence)]
    fills = _fill_values(source_nodata, len(sources))
    if rule not in RULES or fills is None:
        return [result(CHECK_ID, NOT_RUN, f"support_rule must be one of {', '.join(RULES)}, with at most one finite "
                       "fill value per source.", **evidence)]
    if any(layer.get("kind") != "raster" for layer in (output, *sources)):
        return [result(CHECK_ID, NOT_RUN, "Valid support is checked on raster datasets.", **evidence)]
    problems = [problem for source in sources for problem in _grid_problems(source, output)]
    if problems:
        return [result(CHECK_ID, NOT_RUN, "The output and its sources must share one grid.", problems=problems,
                       **evidence)]
    try:
        with ExitStack() as files:
            dst = files.enter_context(rasterio.open(output["path"]))
            srcs = [files.enter_context(rasterio.open(source["path"])) for source in sources]
            if any(src.count != 1 for src in (dst, *srcs)):
                return [result(CHECK_ID, NOT_RUN, "Supply single-band rasters.", **evidence)]
            supported = fill_as_data = valid_as_fill = 0
            for row in range(0, dst.height, WINDOW_SIZE):
                for col in range(0, dst.width, WINDOW_SIZE):
                    window = Window(col, row, min(WINDOW_SIZE, dst.width - col), min(WINDOW_SIZE, dst.height - row))
                    masks = []
                    for src, fill in zip(srcs, fills):
                        read = src.read(1, window=window, masked=True)
                        data = np.ma.getdata(read).astype("float64")
                        valid = ~np.ma.getmaskarray(read) & np.isfinite(data)
                        if fill is not None:
                            valid &= data != fill
                        masks.append(valid)
                    expected = np.logical_and.reduce(masks) if rule == "all" else np.logical_or.reduce(masks)
                    out = dst.read(1, window=window, masked=True)
                    delivered = ~np.ma.getmaskarray(out) & np.isfinite(np.ma.getdata(out).astype("float64"))
                    supported += int(np.count_nonzero(expected))
                    fill_as_data += int(np.count_nonzero(delivered & ~expected))
                    valid_as_fill += int(np.count_nonzero(expected & ~delivered))
            evidence.update(supported_cells=supported, fill_treated_as_data_cells=fill_as_data,
                            valid_treated_as_fill_cells=valid_as_fill, output_nodata=dst.nodata)
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot compare raster masks ({type(error).__name__}).", **evidence)]
    if fill_as_data or valid_as_fill:
        return [result(CHECK_ID, FAIL, f"The output's valid cells differ from the sources' declared support "
                       f"({rule}): {fill_as_data} cells hold values where the sources are fill, and "
                       f"{valid_as_fill} valid cells are nodata.", **evidence)]
    if not supported:
        return [result(CHECK_ID, NOT_RUN, "The sources have no valid cell under the declared rule.", **evidence)]
    return [result(CHECK_ID, PASS, f"The output is valid exactly where the sources' declared support ({rule}) is.",
                   **evidence)]
