"""Opt-in SAR speckle-filter check: sar.filter_domain.

A declared boxcar (moving mean) filter of a backscatter image is recomputed from its unfiltered
source, on the same grid, in linear power: dB values are converted with 10^(x/10), averaged over
the size x size window, and converted back. Averaging the dB values instead (a geometric mean of
power) biases the result low over heterogeneous areas. The declared `sar_expect` domain
(sigma0-db or sigma0-linear) applies to both source and output. Only cells whose whole window is
valid in the source are compared; edge and gap cells are not checked here.
"""
from __future__ import annotations

from contextlib import ExitStack

import numpy as np
import rasterio
from numpy.lib.stride_tricks import sliding_window_view
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "sar.filter_domain"
FILTERS = ("boxcar",)
DOMAINS = ("sigma0-db", "sigma0-linear")
WINDOW_SIZE = 256
RTOL = {"sigma0-db": 0.0, "sigma0-linear": 1e-4}
ATOL = {"sigma0-db": 1e-3, "sigma0-linear": 1e-7}


def _means(block, size, domain):
    """(power mean, dB mean) of every complete size x size window, in the declared domain."""
    windows = sliding_window_view(block, (size, size))
    complete = ~np.isnan(windows).any(axis=(-1, -2))
    with np.errstate(divide="ignore", invalid="ignore"):
        if domain == "sigma0-db":
            power = 10 * np.log10(np.mean(10 ** (windows / 10), axis=(-1, -2)))
            in_db = np.mean(windows, axis=(-1, -2))
        else:
            power = np.mean(windows, axis=(-1, -2))
            in_db = 10 ** (np.mean(10 * np.log10(windows), axis=(-1, -2)) / 10)
    return power, in_db, complete


def check_filter_domain(output: dict, source: dict | None, name: str | None, size: int | None,
                        domain: str | None) -> list:
    evidence = {"output": output.get("path"), "source": (source or {}).get("path"), "filter": name,
                "size": size, "domain": domain}
    missing = [key for key, value in (("sar_filter", name), ("sar_filter_size", size),
                                      ("sar_filter_source", source), ("sar_expect", domain)) if value is None]
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to recompute the filter.",
                       missing_bindings=missing, **evidence)]
    if name not in FILTERS or domain not in DOMAINS or type(size) is not int or size < 3 or size % 2 == 0:
        return [result(CHECK_ID, NOT_RUN, f"sar_filter must be one of {', '.join(FILTERS)}, sar_filter_size an odd "
                       f"integer of at least 3, and sar_expect one of {', '.join(DOMAINS)}.", **evidence)]
    if output.get("kind") != "raster" or source.get("kind") != "raster":
        return [result(CHECK_ID, NOT_RUN, "The filter is checked on raster datasets.", **evidence)]
    problems = _grid_problems(source, output)
    if problems:
        return [result(CHECK_ID, NOT_RUN, "The output and its source must share one grid.", problems=problems,
                       **evidence)]
    half = size // 2
    compared = mismatched = matches_db_mean = 0
    worst = 0.0
    try:
        with ExitStack() as files:
            src = files.enter_context(rasterio.open(source["path"]))
            dst = files.enter_context(rasterio.open(output["path"]))
            if src.count != 1 or dst.count != 1:
                return [result(CHECK_ID, NOT_RUN, "Supply single-band rasters.", **evidence)]
            for row in range(0, dst.height, WINDOW_SIZE):
                for col in range(0, dst.width, WINDOW_SIZE):
                    height, width = min(WINDOW_SIZE, dst.height - row), min(WINDOW_SIZE, dst.width - col)
                    # The source window carries a halo of half the filter on every side, padded with gaps.
                    halo = Window(col - half, row - half, width + 2 * half, height + 2 * half)
                    block = np.ma.filled(src.read(1, window=halo, boundless=True, masked=True).astype("float64"),
                                         np.nan)
                    block[~np.isfinite(block)] = np.nan
                    power, in_db, complete = _means(block, size, domain)
                    delivered = dst.read(1, window=Window(col, row, width, height), masked=True).astype("float64")
                    valid = complete & ~np.ma.getmaskarray(delivered) & np.isfinite(power)
                    got = np.ma.getdata(delivered)[valid]
                    expected, wrong = power[valid], in_db[valid]
                    tolerance = RTOL[domain] * np.abs(expected) + ATOL[domain]
                    off = np.abs(got - expected) > tolerance
                    compared += int(valid.sum())
                    mismatched += int(off.sum())
                    with np.errstate(invalid="ignore"):
                        matches_db_mean += int((off & (np.abs(got - wrong) <= tolerance)).sum())
                    if off.any():
                        worst = max(worst, float(np.max(np.abs(got - expected)[off])))
    except rasterio.errors.RasterioIOError as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot read pixel values: {error}", **evidence)]
    evidence.update(compared_cells=compared, mismatched_cells=mismatched, cells_matching_db_average=matches_db_mean,
                    max_abs_difference=worst)
    if compared == 0:
        return [result(CHECK_ID, NOT_RUN, "No cell has a complete valid filter window to compare.", **evidence)]
    if mismatched:
        cause = (f"; {matches_db_mean} of them match the mean of the dB values, so the filter was applied in dB "
                 "instead of linear power" if matches_db_mean else "")
        return [result(CHECK_ID, FAIL, f"{mismatched} of {compared} cells differ from a {size}x{size} boxcar in "
                       f"linear power{cause}.", **evidence)]
    return [result(CHECK_ID, PASS, f"All {compared} cells with a complete window match a {size}x{size} boxcar "
                   "in linear power.", **evidence)]
