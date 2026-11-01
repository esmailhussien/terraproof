"""Opt-in categorical check: raster.categorical_codes.

Every valid output cell must hold a class code that occurs among the valid cells of the declared
class source. Bilinear, cubic or average resampling of a class raster invents codes between
neighbouring classes; nearest and mode cannot. The grids may differ, since the output is usually
a resampled or reprojected copy. A subset is necessary, not sufficient: a nearest-neighbour shift
or a dropped class keeps every code valid and is not detected here.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result

CHECK_ID = "raster.categorical_codes"
WINDOW_SIZE = 512
# More distinct codes than this is not a class raster.
MAX_CODES = 65536
SAMPLE = 10


def _windows(dataset):
    for row in range(0, dataset.height, WINDOW_SIZE):
        for col in range(0, dataset.width, WINDOW_SIZE):
            yield Window(col, row, min(WINDOW_SIZE, dataset.width - col), min(WINDOW_SIZE, dataset.height - row))


def _valid(dataset, window):
    values = dataset.read(1, window=window, masked=True)
    data = np.ma.getdata(values)[~np.ma.getmaskarray(values)]
    return data[np.isfinite(data)] if data.dtype.kind == "f" else data


def check_categorical_codes(output: dict, source: dict | None) -> list:
    evidence = {"output": output.get("path"), "source": (source or {}).get("path")}
    if source is None:
        return [result(CHECK_ID, NOT_RUN, "Declare categorical_source, the class raster the output was made from, "
                       "to check its class codes.", missing_bindings=["categorical_source"], **evidence)]
    if output.get("kind") != "raster" or source.get("kind") != "raster":
        return [result(CHECK_ID, NOT_RUN, "Class codes are checked on raster datasets.", **evidence)]
    try:
        with rasterio.open(source["path"]) as src, rasterio.open(output["path"]) as dst:
            if src.count != 1 or dst.count != 1:
                return [result(CHECK_ID, NOT_RUN, "Supply single-band class rasters.", **evidence)]
            codes = np.array([], dtype="float64")
            for window in _windows(src):
                codes = np.union1d(codes, np.unique(_valid(src, window)).astype("float64"))
                if codes.size > MAX_CODES:
                    return [result(CHECK_ID, NOT_RUN, f"The source has more than {MAX_CODES} distinct values, so it "
                                   "is not a class raster.", **evidence)]
            if codes.size == 0:
                return [result(CHECK_ID, NOT_RUN, "The source has no valid cells.", **evidence)]
            compared = invented = 0
            examples = np.array([], dtype="float64")
            for window in _windows(dst):
                values = _valid(dst, window).astype("float64")
                outside = values[~np.isin(values, codes)]
                compared += values.size
                invented += outside.size
                if examples.size < SAMPLE and outside.size:
                    examples = np.union1d(examples, np.unique(outside))[:SAMPLE]
    except rasterio.errors.RasterioIOError as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot read pixel values: {error}", **evidence)]
    evidence.update(source_code_count=int(codes.size), compared_cells=compared)
    if compared == 0:
        return [result(CHECK_ID, NOT_RUN, "The output has no valid cells to compare.", **evidence)]
    if invented:
        return [result(CHECK_ID, FAIL, f"{invented} of {compared} valid cells hold codes the source never has, such "
                       f"as {[float(v) for v in examples]}; class codes were blended (bilinear, cubic or average "
                       "resampling). Resample class rasters with nearest or mode.",
                       invented_cells=invented, invented_examples=[float(v) for v in examples], **evidence)]
    return [result(CHECK_ID, PASS, f"All {compared} valid cells hold one of the source's {codes.size} class codes.",
                   **evidence)]
