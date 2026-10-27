"""Opt-in temporal/stack reduction check: rs.stack_reduction.

Every delivered cell is compared with a declared per-pixel reduction of an ordered stack of
single-band rasters on the output's grid. The caller declares the reduction and, where it
needs them, one weight per layer (durations in hours for an accumulation, decimal times for
a trend). Layers are read in bounded windows; a layer cell is valid when it is unmasked and
finite.

- ``median``         median of the valid layers
- ``weighted-sum``   sum of weight x value; every layer must be valid (incomplete coverage is
                     unsupported), e.g. rainfall rates x interval hours
- ``mean-power-db``  layers in dB are averaged in linear power, 10 log10(mean(10^(x/10)))
- ``ols-slope``      ordinary least-squares slope of the valid values against the weights
- ``count``          number of valid layers

A cell is supported when at least ``min_count`` layers are valid (default 1; ``weighted-sum``
needs all of them). An unsupported cell must be nodata in the output, and a supported cell
must hold the reduced value. Extra output masking warns. Nothing here checks how the input
layers themselves were made (cloud screening, calibration): pair it with those checks.
"""
from __future__ import annotations

from contextlib import ExitStack
import math
import warnings

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "rs.stack_reduction"
REDUCTIONS = ("count", "mean-power-db", "median", "ols-slope", "weighted-sum")
WEIGHTED = ("ols-slope", "weighted-sum")
RTOL = 1e-5
ATOL = 1e-6
WINDOW_SIZE = 256


def _reduce(reduction: str, values: np.ndarray, valid: np.ndarray, weights, min_count: int):
    count = valid.sum(axis=0)
    support = count >= (len(values) if reduction == "weighted-sum" else max(1, min_count))
    data = np.where(valid, values, np.nan)
    expected = np.zeros(count.shape, dtype="float64")
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-invalid cells are unsupported, not errors
        if reduction == "median":
            expected = np.nanmedian(np.where(support[None], data, 0.0), axis=0)
        elif reduction == "count":
            expected = count.astype("float64")
            support = np.ones(count.shape, dtype=bool)
        elif reduction == "weighted-sum":
            expected = np.nansum(data * np.asarray(weights)[:, None, None], axis=0)
        elif reduction == "mean-power-db":
            expected = 10.0 * np.log10(np.nanmean(np.power(10.0, data / 10.0), axis=0))
        elif reduction == "ols-slope":
            x = np.where(valid, np.asarray(weights, dtype="float64")[:, None, None], np.nan)
            mx, my = np.nanmean(x, axis=0), np.nanmean(data, axis=0)
            numerator = np.nansum((x - mx) * (data - my), axis=0)
            denominator = np.nansum((x - mx) ** 2, axis=0)
            support &= denominator > 1e-12
            expected = np.divide(numerator, denominator, out=np.zeros(count.shape), where=support)
    support &= np.isfinite(expected)
    return expected, support


def check_stack_reduction(output: dict, stack: list | None, reduction: str | None,
                          weights: list | None = None, min_count: int | None = None) -> list:
    evidence = {"output": output.get("path"), "reduction": reduction,
                "stack": [layer.get("path") for layer in stack or []], "weights": weights, "min_count": min_count}
    if reduction not in REDUCTIONS or not stack:
        return [result(CHECK_ID, NOT_RUN, f"Declare stack_reduction ({', '.join(REDUCTIONS)}) and supply the "
                       "ordered input layers.", **evidence)]
    if reduction in WEIGHTED and (weights is None or len(weights) != len(stack)
                                  or not all(isinstance(w, (int, float)) and math.isfinite(w) for w in weights)):
        return [result(CHECK_ID, NOT_RUN, f"{reduction} needs one finite weight per input layer "
                       "(hours for an accumulation, times for a trend).", **evidence)]
    if any(layer.get("kind") != "raster" for layer in (output, *stack)):
        return [result(CHECK_ID, NOT_RUN, "Stack reduction requires raster datasets.", **evidence)]
    problems = [problem for layer in stack for problem in _grid_problems(layer, output)]
    if problems:
        return [result(CHECK_ID, NOT_RUN, "The output and every stack layer must share one supported grid.",
                       problems=problems, **evidence)]
    try:
        with ExitStack() as files:
            dst = files.enter_context(rasterio.open(output["path"]))
            layers = [files.enter_context(rasterio.open(layer["path"])) for layer in stack]
            if any(src.count != 1 or src.crs is None for src in (dst, *layers)):
                return [result(CHECK_ID, NOT_RUN, "Supply single-band rasters with declared CRSs.", **evidence)]
            compared = mismatched = unsupported = extra_masked = 0
            for row in range(0, dst.height, WINDOW_SIZE):
                for col in range(0, dst.width, WINDOW_SIZE):
                    window = Window(col, row, min(WINDOW_SIZE, dst.width - col), min(WINDOW_SIZE, dst.height - row))
                    reads = [src.read(1, window=window, masked=True) for src in layers]
                    values = np.stack([np.ma.getdata(r).astype("float64") * src.scales[0] + src.offsets[0]
                                       for r, src in zip(reads, layers)])
                    valid = np.stack([~np.ma.getmaskarray(r) for r in reads]) & np.isfinite(values)
                    expected, support = _reduce(reduction, values, valid, weights, min_count or 1)
                    out = dst.read(1, window=window, masked=True)
                    observed = np.ma.getdata(out).astype("float64") * dst.scales[0] + dst.offsets[0]
                    delivered = ~np.ma.getmaskarray(out)
                    unsupported += int(np.count_nonzero(delivered & (~support | ~np.isfinite(observed))))
                    extra_masked += int(np.count_nonzero(support & ~delivered))
                    keep = support & delivered & np.isfinite(observed)
                    compared += int(np.count_nonzero(keep))
                    mismatched += int(np.count_nonzero(keep & ~np.isclose(observed, expected, rtol=RTOL, atol=ATOL)))
            evidence.update(compared_cells=compared, mismatched_cells=mismatched, unsupported_output_cells=unsupported,
                            extra_masked_cells=extra_masked, tolerance={"rtol": RTOL, "atol": ATOL})
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot compare raster values ({type(error).__name__}).", **evidence)]
    if mismatched or unsupported:
        return [result(CHECK_ID, FAIL, f"Delivered values disagree with the declared {reduction} of the input stack, "
                       "or cells without enough valid inputs hold values.", **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, "No supported delivered cell could be compared.", **evidence)]
    if extra_masked:
        return [result(CHECK_ID, WARN, f"Compared cells match the declared {reduction}; extra output masking needs "
                       "review.", **evidence)]
    return [result(CHECK_ID, PASS, f"Every delivered cell matches the declared {reduction} of the input stack, and "
                   "cells without enough valid inputs are nodata.", **evidence)]
