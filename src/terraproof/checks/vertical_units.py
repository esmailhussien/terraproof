"""Opt-in vertical-unit check: raster.vertical_units.

The caller declares the vertical unit of each source and of the output, and how the output was
made from the sources:

- ``convert``      one source, the output is that surface in the output's unit
- ``difference``   two sources, the output is the first minus the second (for example a change or
                   a height above a surface), in the output's unit
- ``minus-level``  one source and a declared level in the output's unit; the output is the source
                   minus the level (for example orthometric height from an ellipsoidal height and a
                   constant geoid separation; use ``difference`` with a geoid grid instead)
- ``depth-to-elevation``  one source of depths (positive down); the output is the same surface as
                   elevations (positive up) in the output's unit
- ``depth-below-level``  one source surface and a declared level in the output's unit; the output is
                   the level minus the surface where the surface is below it, and 0 elsewhere (for
                   example flood depth for a water-surface level)

Every delivered cell where all sources and the output are valid is compared with the declared
operation done in metres and converted to the output unit. A band unit label on the output that
names a different unit also fails. Sources and output must share one grid. Nothing is inferred:
an undeclared unit or operation is not-run, naming what to declare. Vertical datum differences
(orthometric against ellipsoidal heights) are not unit errors and are not checked here.
"""
from __future__ import annotations

from contextlib import ExitStack

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "raster.vertical_units"
OPERATIONS = {"convert": 1, "difference": 2, "depth-below-level": 1, "minus-level": 1, "depth-to-elevation": 1}
METRES = {"metre": 1.0, "foot": 0.3048, "us-survey-foot": 1200.0 / 3937.0, "fathom": 1.8288}
ALIASES = {"m": "metre", "meter": "metre", "meters": "metre", "metres": "metre", "metre": "metre",
           "ft": "foot", "feet": "foot", "foot": "foot", "international-foot": "foot",
           "us-ft": "us-survey-foot", "us-survey-foot": "us-survey-foot", "us-survey-feet": "us-survey-foot",
           "ftus": "us-survey-foot", "fathom": "fathom", "fathoms": "fathom", "fm": "fathom"}
RTOL = 1e-4
ATOL = 1e-3
WINDOW_SIZE = 256


def unit_name(value) -> str | None:
    """The canonical unit for a declared or labelled unit, or None when it is not a known length unit."""
    if not isinstance(value, str):
        return None
    return ALIASES.get(value.strip().lower().replace(" ", "-").replace("_", "-"))


def check_vertical_units(output: dict, sources: list | None, source_units: list | None,
                         operation: str | None, unit: str | None, level: float | None = None) -> list:
    evidence = {"output": output.get("path"), "operation": operation, "output_unit": unit, "level": level,
                "sources": [source.get("path") for source in sources or []], "source_units": source_units}
    missing = [name for name, value in (("vertical_operation", operation), ("vertical_unit", unit),
                                        ("vertical_sources", sources), ("vertical_source_units", source_units))
               if not value]
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to check vertical units; units are "
                       "never inferred.", missing_bindings=missing, **evidence)]
    if operation not in OPERATIONS or len(sources) != OPERATIONS[operation] or len(source_units) != len(sources):
        return [result(CHECK_ID, NOT_RUN, "difference takes two sources and every other operation one, each "
                       "with one declared unit.", **evidence)]
    if operation in ("depth-below-level", "minus-level") and not (isinstance(level, (int, float)) and not isinstance(level, bool)
                                                 and np.isfinite(level)):
        return [result(CHECK_ID, NOT_RUN, f"Declare vertical_level, the level in the output unit, for "
                       f"{operation}.", missing_bindings=["vertical_level"], **evidence)]
    units = [unit_name(value) for value in (*source_units, unit)]
    if None in units:
        return [result(CHECK_ID, NOT_RUN, f"Declared units must be one of {', '.join(METRES)}.", **evidence)]
    *source_canonical, output_canonical = units
    if any(layer.get("kind") != "raster" for layer in (output, *sources)):
        return [result(CHECK_ID, NOT_RUN, "Vertical units are checked on raster datasets.", **evidence)]
    problems = [problem for source in sources for problem in _grid_problems(source, output)]
    if problems:
        return [result(CHECK_ID, NOT_RUN, "The output and its sources must share one grid.", problems=problems,
                       **evidence)]
    factors = [METRES[name] for name in source_canonical]
    try:
        with ExitStack() as files:
            dst = files.enter_context(rasterio.open(output["path"]))
            srcs = [files.enter_context(rasterio.open(source["path"])) for source in sources]
            label = (dst.units or ("",))[0]
            if label and unit_name(label) not in (None, output_canonical):
                evidence["output_unit_label"] = label
                return [result(CHECK_ID, FAIL, f"The output band is labelled {label!r}, but its declared unit is "
                               f"{output_canonical}.", **evidence)]
            compared = mismatched = 0
            ratios = []
            for row in range(0, dst.height, WINDOW_SIZE):
                for col in range(0, dst.width, WINDOW_SIZE):
                    window = Window(col, row, min(WINDOW_SIZE, dst.width - col), min(WINDOW_SIZE, dst.height - row))
                    reads = [src.read(1, window=window, masked=True) for src in (*srcs, dst)]
                    values = [np.ma.getdata(r).astype("float64") * src.scales[0] + src.offsets[0]
                              for r, src in zip(reads, (*srcs, dst))]
                    valid = np.logical_and.reduce([~np.ma.getmaskarray(r) & np.isfinite(v)
                                                   for r, v in zip(reads, values)])
                    metres = values[0] * factors[0] - (values[1] * factors[1] if operation == "difference" else 0.0)
                    expected = metres / METRES[output_canonical]
                    if operation == "depth-below-level":
                        expected = np.maximum(level - expected, 0.0)
                    elif operation == "minus-level":
                        expected = expected - level
                    elif operation == "depth-to-elevation":
                        expected = -expected
                    observed = values[-1]
                    wrong = valid & ~np.isclose(observed, expected, rtol=RTOL, atol=ATOL)
                    compared += int(np.count_nonzero(valid))
                    mismatched += int(np.count_nonzero(wrong))
                    usable = wrong & (np.abs(expected) > ATOL)
                    if len(ratios) < 5000:  # a bounded sample is enough to show a factor such as 3.2808
                        ratios.extend((observed[usable] / expected[usable])[:1000].tolist())
            evidence.update(compared_cells=compared, mismatched_cells=mismatched,
                            tolerance={"rtol": RTOL, "atol": ATOL})
            if ratios:
                evidence["median_observed_to_expected"] = round(float(np.median(ratios)), 4)
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot compare raster values ({type(error).__name__}).", **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, "No cell is valid in the output and every source.", **evidence)]
    if mismatched:
        return [result(CHECK_ID, FAIL, f"{mismatched} of {compared} cells disagree with the declared {operation} "
                       f"in {output_canonical}; units may be mixed or mislabelled.", **evidence)]
    return [result(CHECK_ID, PASS, f"Every compared cell matches the declared {operation} in {output_canonical}.",
                   **evidence)]
