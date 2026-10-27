"""Opt-in spectral-index verification against explicitly supplied source bands.

Read every cell in bounded windows. Calibration comes only from each source band's own
scale/offset metadata; roles are declared by the caller, never guessed from filenames.
Additional output masking warns: its QA policy cannot be verified from these inputs.

Formulas (physical reflectance in, the named index out):

- ``ndvi``  (NIR - red) / (NIR + red)
- ``nbr``   (NIR - SWIR2) / (NIR + SWIR2)
- ``dnbr``  NBR(pre) - NBR(post), pre-fire minus post-fire
- ``ndwi``  McFeeters NDWI, (green - NIR) / (green + NIR)
- ``mndwi`` (green - SWIR1) / (green + SWIR1)
- ``ndmi``  Gao's moisture index, (NIR - SWIR1) / (NIR + SWIR1)
- ``savi``  1.5 (NIR - red) / (NIR + red + 0.5)
- ``evi``   2.5 (NIR - red) / (NIR + 6 red - 7.5 blue + 1)

A cell is supported when every operand is valid and finite and the denominator is not
zero; an unsupported cell must be nodata in the output.
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
EPS = 1e-12


def _ratio(numerator, denominator):
    valid = np.isfinite(numerator) & np.isfinite(denominator) & (np.abs(denominator) > EPS)
    value = np.zeros(np.shape(denominator), dtype="float64")
    np.divide(numerator, denominator, out=value, where=valid)
    return value, valid


def _normalized(a, b):
    return _ratio(a - b, a + b)


def _dnbr(v):
    pre, pre_ok = _normalized(v["pre_nir"], v["pre_swir2"])
    post, post_ok = _normalized(v["post_nir"], v["post_swir2"])
    return pre - post, pre_ok & post_ok


# name -> (operand roles, label, function of {role: physical values} -> (index, supported))
FORMULAS = {
    "ndvi": (("nir", "red"), "(NIR-red)/(NIR+red)", lambda v: _normalized(v["nir"], v["red"])),
    "nbr": (("nir", "swir2"), "(NIR-SWIR2)/(NIR+SWIR2)", lambda v: _normalized(v["nir"], v["swir2"])),
    "dnbr": (("pre_nir", "pre_swir2", "post_nir", "post_swir2"), "NBR(pre)-NBR(post)", _dnbr),
    "ndwi": (("green", "nir"), "McFeeters (green-NIR)/(green+NIR)", lambda v: _normalized(v["green"], v["nir"])),
    "mndwi": (("green", "swir1"), "(green-SWIR1)/(green+SWIR1)", lambda v: _normalized(v["green"], v["swir1"])),
    "ndmi": (("nir", "swir1"), "Gao (NIR-SWIR1)/(NIR+SWIR1)", lambda v: _normalized(v["nir"], v["swir1"])),
    "savi": (("nir", "red"), "1.5(NIR-red)/(NIR+red+0.5)",
             lambda v: _ratio(1.5 * (v["nir"] - v["red"]), v["nir"] + v["red"] + 0.5)),
    "evi": (("blue", "red", "nir"), "2.5(NIR-red)/(NIR+6red-7.5blue+1)",
            lambda v: _ratio(2.5 * (v["nir"] - v["red"]), v["nir"] + 6 * v["red"] - 7.5 * v["blue"] + 1)),
}


def _operands(formula: str, nir: dict | None, red: dict | None, bands: dict | None) -> dict:
    """Role -> inspected dataset, with an optional 1-based ``band`` key for multi-band sources."""
    operands = dict(bands or {})
    if nir is not None:
        operands.setdefault("nir", nir)
    if red is not None:
        operands.setdefault("red", red)
    return operands


def check_index_formula(output: dict, formula: str | None, nir: dict | None, red: dict | None,
                        bands: dict | None = None) -> list:
    operands = _operands(formula or "", nir, red, bands)
    roles = FORMULAS[formula][0] if formula in FORMULAS else ()
    evidence = {"output": output.get("path"), "formula": formula,
                **{role: operands[role].get("path") if operands.get(role) else None for role in roles or ("nir", "red")}}
    if formula not in FORMULAS or any(operands.get(role) is None for role in roles):
        need = ", ".join(roles) if roles else "nir and red"
        return [result(CHECK_ID, NOT_RUN, f"Declare index_formula ({', '.join(sorted(FORMULAS))}) and supply its "
                       f"source rasters ({need}).", **evidence)]
    _, label, compute = FORMULAS[formula]
    name = formula.upper()
    sources = {role: operands[role] for role in roles}
    if any(ds.get("kind") != "raster" for ds in (output, *sources.values())):
        return [result(CHECK_ID, NOT_RUN, f"{name} verification requires raster datasets.", **evidence)]
    problems = [problem for ds in {id(ds): ds for ds in sources.values()}.values()
                for problem in _grid_problems(ds, output)]
    if problems:
        return [result(CHECK_ID, NOT_RUN, f"{name} and source bands must have identical supported grids.",
                       problems=problems, **evidence)]
    try:
        with ExitStack() as stack:
            dst = stack.enter_context(rasterio.open(output["path"]))
            opened = {}
            for role, ds in sources.items():
                if ds["path"] not in opened:
                    opened[ds["path"]] = stack.enter_context(rasterio.open(ds["path"]))
            band = {role: int(ds.get("band") or 1) for role, ds in sources.items()}
            srcs = {role: opened[ds["path"]] for role, ds in sources.items()}
            if dst.count != 1 or any(src.crs is None for src in (dst, *srcs.values())):
                return [result(CHECK_ID, NOT_RUN, "Supply a single-band output and rasters with declared CRSs.",
                               **evidence)]
            if any(not 1 <= band[role] <= src.count or (src.count > 1 and not sources[role].get("band"))
                   for role, src in srcs.items()):
                return [result(CHECK_ID, NOT_RUN, "Name the band of every multi-band source; each band number "
                               "must exist.", **evidence)]
            if any(src.dtypes[band[role] - 1].startswith("complex") for role, src in srcs.items()) or \
                    dst.dtypes[0].startswith("complex"):
                return [result(CHECK_ID, NOT_RUN, f"Complex-valued bands are unsupported for {name}.", **evidence)]
            calibration = {role: {"scale": src.scales[band[role] - 1], "offset": src.offsets[band[role] - 1]}
                           for role, src in srcs.items()}
            calibration["output"] = {"scale": dst.scales[0], "offset": dst.offsets[0]}
            if not all(math.isfinite(value) for params in calibration.values() for value in params.values()):
                return [result(CHECK_ID, NOT_RUN, "Raster scale/offset must be finite.", **evidence)]
            evidence.update(calibration=calibration, tolerance={"rtol": RTOL, "atol": ATOL},
                            bands={role: band[role] for role in roles if srcs[role].count > 1})
            compared = mismatched = unsupported = extra_masked = 0
            for row in range(0, dst.height, WINDOW_SIZE):
                for col in range(0, dst.width, WINDOW_SIZE):
                    window = Window(col, row, min(WINDOW_SIZE, dst.width - col), min(WINDOW_SIZE, dst.height - row))
                    out = dst.read(1, window=window, masked=True).astype("float64")
                    values, source_valid = {}, np.ones(out.shape, dtype=bool)
                    for role, src in srcs.items():
                        data = src.read(band[role], window=window, masked=True).astype("float64")
                        values[role] = np.ma.getdata(data) * calibration[role]["scale"] + calibration[role]["offset"]
                        source_valid &= ~np.ma.getmaskarray(data) & np.isfinite(values[role])
                    expected, supported = compute(values)
                    source_valid &= supported & np.isfinite(expected)
                    observed = np.ma.getdata(out) * calibration["output"]["scale"] + calibration["output"]["offset"]
                    output_unmasked = ~np.ma.getmaskarray(out)
                    output_valid = output_unmasked & np.isfinite(observed)
                    unsupported += int(np.count_nonzero(output_unmasked & (~source_valid | ~np.isfinite(observed))))
                    extra_masked += int(np.count_nonzero(source_valid & ~output_unmasked))
                    keep = source_valid & output_valid
                    compared += int(np.count_nonzero(keep))
                    mismatched += int(np.count_nonzero(keep & ~np.isclose(observed, expected, rtol=RTOL, atol=ATOL)))
            evidence.update(compared_cells=compared, mismatched_cells=mismatched,
                            unsupported_output_cells=unsupported, extra_masked_cells=extra_masked)
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError, TypeError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot compare raster values ({type(error).__name__}).", **evidence)]
    if mismatched or unsupported:
        return [result(CHECK_ID, FAIL, f"Delivered {name} disagrees with calibrated {label}, "
                       "or contains unmasked values without finite source support.", **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, "No valid delivered cell could be compared with calibrated source bands.", **evidence)]
    if extra_masked:
        return [result(CHECK_ID, WARN, f"Compared {name} values agree; extra output masking needs a separate QA policy review.", **evidence)]
    return [result(CHECK_ID, PASS, f"Every delivered {name} cell and its source support match calibrated {label}.", **evidence)]
