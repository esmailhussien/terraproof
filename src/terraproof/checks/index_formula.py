"""Opt-in NDVI verification against explicitly supplied red/NIR single-band rasters.

Read every cell in bounded windows. Calibration comes only from each source's own
scale/offset metadata; roles are declared by the caller, never guessed from filenames.
Additional output masking warns: its QA policy cannot be verified from these inputs.
"""
from __future__ import annotations

from contextlib import ExitStack
import math

import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "rs.index_formula"
RTOL = 1e-5
ATOL = 1e-6
WINDOW_SIZE = 512


def check_index_formula(output: dict, formula: str | None, nir: dict | None, red: dict | None) -> list:
    evidence = {"output": output.get("path"), "formula": formula,
                "nir": nir.get("path") if nir else None, "red": red.get("path") if red else None}
    if formula != "ndvi" or nir is None or red is None:
        return [result(CHECK_ID, NOT_RUN, "Declare index_formula=ndvi and supply both nir and red source rasters.", **evidence)]
    if any(ds.get("kind") != "raster" for ds in (output, nir, red)):
        return [result(CHECK_ID, NOT_RUN, "NDVI verification requires three raster datasets.", **evidence)]
    problems = _grid_problems(nir, output) + _grid_problems(red, output)
    if problems:
        return [result(CHECK_ID, NOT_RUN, "NDVI and source bands must have identical supported grids.",
                       problems=problems, **evidence)]
    try:
        with ExitStack() as stack:
            dst, nsrc, rsrc = [stack.enter_context(rasterio.open(ds["path"])) for ds in (output, nir, red)]
            if any(src.count != 1 for src in (dst, nsrc, rsrc)) or any(src.crs is None for src in (dst, nsrc, rsrc)):
                return [result(CHECK_ID, NOT_RUN, "Supply single-band rasters with declared CRSs.", **evidence)]
            if any(src.dtypes[0].startswith("complex") for src in (dst, nsrc, rsrc)):
                return [result(CHECK_ID, NOT_RUN, "Complex-valued bands are unsupported for NDVI.", **evidence)]
            calibration = {role: {"scale": src.scales[0], "offset": src.offsets[0]}
                           for role, src in (("nir", nsrc), ("red", rsrc), ("output", dst))}
            if not all(math.isfinite(value) for params in calibration.values() for value in params.values()):
                return [result(CHECK_ID, NOT_RUN, "Raster scale/offset must be finite.", **evidence)]
            evidence.update(calibration=calibration, tolerance={"rtol": RTOL, "atol": ATOL})
            compared = mismatched = unsupported = extra_masked = 0
            for row in range(0, dst.height, WINDOW_SIZE):
                for col in range(0, dst.width, WINDOW_SIZE):
                    window = Window(col, row, min(WINDOW_SIZE, dst.width - col), min(WINDOW_SIZE, dst.height - row))
                    out, n, r = [src.read(1, window=window, masked=True).astype("float64")
                                 for src in (dst, nsrc, rsrc)]
                    nv = np.ma.getdata(n) * nsrc.scales[0] + nsrc.offsets[0]
                    rv = np.ma.getdata(r) * rsrc.scales[0] + rsrc.offsets[0]
                    observed = np.ma.getdata(out) * dst.scales[0] + dst.offsets[0]
                    denom = nv + rv
                    source_valid = (~np.ma.getmaskarray(n) & ~np.ma.getmaskarray(r)
                                    & np.isfinite(nv) & np.isfinite(rv) & np.isfinite(denom)
                                    & (np.abs(denom) > 1e-12))
                    output_unmasked = ~np.ma.getmaskarray(out)
                    output_valid = output_unmasked & np.isfinite(observed)
                    unsupported += int(np.count_nonzero(output_unmasked & (~source_valid | ~np.isfinite(observed))))
                    extra_masked += int(np.count_nonzero(source_valid & ~output_unmasked))
                    keep = source_valid & output_valid
                    expected = np.zeros(nv.shape, dtype="float64")
                    np.divide(nv - rv, denom, out=expected, where=source_valid)
                    compared += int(np.count_nonzero(keep))
                    mismatched += int(np.count_nonzero(keep & ~np.isclose(observed, expected, rtol=RTOL, atol=ATOL)))
            evidence.update(compared_cells=compared, mismatched_cells=mismatched,
                            unsupported_output_cells=unsupported, extra_masked_cells=extra_masked)
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot compare raster values ({type(error).__name__}).", **evidence)]
    if mismatched or unsupported:
        return [result(CHECK_ID, FAIL, "Delivered NDVI disagrees with calibrated (NIR-red)/(NIR+red), "
                       "or contains unmasked values without finite source support.", **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, "No valid delivered cell could be compared with calibrated source bands.", **evidence)]
    if extra_masked:
        return [result(CHECK_ID, WARN, "Compared NDVI values agree; extra output masking needs a separate QA policy review.", **evidence)]
    return [result(CHECK_ID, PASS, "Every delivered NDVI cell and its source support match calibrated (NIR-red)/(NIR+red).", **evidence)]
