"""Opt-in exhaustive calibration/QA relations, bounded in memory across all bands.

These verify declared relations, not the scientific suitability of a workflow.
The legacy sampled checks remain available without processing_full_scan.
"""
from __future__ import annotations

import math
import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.rs_processing import ENCODINGS, RTOL, ATOL, SCL_CLOUD_CLASSES, LANDSAT_QA_MASK, _grid_problems
from terraproof.inspect.raster import inspect_raster

WINDOW_SIZE = 256


def windows(dataset):
    for row in range(0, dataset.height, WINDOW_SIZE):
        for col in range(0, dataset.width, WINDOW_SIZE):
            yield Window(col, row, min(WINDOW_SIZE, dataset.width-col), min(WINDOW_SIZE, dataset.height-row))


def calibration(output, reference, encoding=None, scale=None, offset=None, add=0.0, unit_conversion=None):
    evidence = {"output": output.get("path"), "reference_input": reference.get("path") if reference else None,
                "encoding": encoding, "unit_conversion": unit_conversion, "processing_full_scan": True, "stride": 1,
                "scan_scope": "all corresponding bands and pixels", "window_size": WINDOW_SIZE,
                "tolerance": {"rtol": RTOL, "atol": ATOL}, "min_match_fraction": 1.0}
    def answer(status, message):
        return [result("rs.scale_applied_once", status, message, **evidence)]
    if not reference or reference.get("kind") != "raster" or output.get("kind") != "raster":
        return answer(NOT_RUN, "Exhaustive calibration needs output and source rasters.")
    if encoding is not None and encoding not in ENCODINGS:
        return answer(NOT_RUN, "The declared calibration encoding is unknown.")
    if _grid_problems(reference, output) or not reference.get("crs"):
        return answer(NOT_RUN, "Exhaustive calibration requires identical declared grids and CRS.")
    try:
        with rasterio.open(reference["path"]) as src, rasterio.open(output["path"]) as dst:
            if src.count != dst.count:
                return answer(NOT_RUN, "Supply matching band counts; band selection cannot be inferred.")
            if any(np.dtype(dtype).kind not in "iuf" for dtype in (*src.dtypes, *dst.dtypes)):
                return answer(NOT_RUN, "Calibration requires real-valued raster bands.")
            if any(s != 1 or o != 0 for s, o in zip(dst.scales, dst.offsets)):
                return answer(FAIL, "Decoded output still carries a nonidentity scale/offset encoding.")
            factors = []
            for band in src.indexes:
                s = ENCODINGS[encoding]["scale"] if encoding else (src.scales[band-1] if scale is None else scale)
                o = ENCODINGS[encoding]["offset"] if encoding else (src.offsets[band-1] if offset is None else offset)
                if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (s, o)):
                    return answer(NOT_RUN, "Source calibration is missing or nonfinite.")
                factors.append({"band": band, "scale": s, "offset": o})
            evidence["band_calibration"] = factors
            matched = raw_matched = twice_matched = compared = unsupported = extra_masked = nonfinite = 0
            observed_min = expected_min = math.inf
            observed_max = expected_max = -math.inf
            for item in factors:
                band, s, o = item["band"], item["scale"], item["offset"]
                for window in windows(src):
                    raw = src.read(band, window=window)
                    source_valid = (src.read_masks(band, window=window) > 0) & np.isfinite(raw)
                    if raw.dtype.kind in "iu" and np.any(source_valid & (raw > 2**53)):
                        return answer(NOT_RUN, "Source integers exceed exact float64 arithmetic range.")
                    if raw.dtype.kind == "i" and np.any(source_valid & (raw < -2**53)):
                        return answer(NOT_RUN, "Source integers exceed exact float64 arithmetic range.")
                    stored = raw.astype("float64")
                    delivered = dst.read(band, window=window)
                    unmasked = dst.read_masks(band, window=window) > 0
                    if delivered.dtype.kind in "iu" and np.any(unmasked & (delivered > 2**53)):
                        return answer(NOT_RUN, "Output integers exceed exact float64 arithmetic range.")
                    if delivered.dtype.kind == "i" and np.any(unmasked & (delivered < -2**53)):
                        return answer(NOT_RUN, "Output integers exceed exact float64 arithmetic range.")
                    observed = delivered.astype("float64")
                    finite = np.isfinite(observed)
                    unsupported += int(np.count_nonzero(~source_valid & unmasked))
                    nonfinite += int(np.count_nonzero(unmasked & ~finite))
                    extra_masked += int(np.count_nonzero(source_valid & ~unmasked))
                    with np.errstate(over="ignore", invalid="ignore"):
                        decoded = stored*s+o
                        expected = decoded+add
                        twice = decoded*s+o+add
                    if np.any(source_valid & ~np.isfinite(expected)):
                        return answer(NOT_RUN, "Calibration overflow prevents reliable arithmetic.")
                    keep = source_valid & unmasked & finite
                    count = int(np.count_nonzero(keep))
                    compared += count
                    if count:
                        a, b = observed[keep], expected[keep]
                        matched += int(np.count_nonzero(np.isclose(a, b, rtol=RTOL, atol=ATOL)))
                        raw_matched += int(np.count_nonzero(np.isclose(a, stored[keep], rtol=RTOL, atol=ATOL)))
                        twice_matched += int(np.count_nonzero(np.isclose(a, twice[keep], rtol=RTOL, atol=ATOL)))
                        observed_min, observed_max = min(observed_min, float(a.min())), max(observed_max, float(a.max()))
                        expected_min, expected_max = min(expected_min, float(b.min())), max(expected_max, float(b.max()))
            evidence.update(compared_pixels=compared, sampled_pixels=compared, mismatched_pixels=compared-matched,
                unmasked_source_nodata_pixels=unsupported, nonfinite_output_pixels=nonfinite,
                extra_masked_source_pixels=extra_masked, bands=src.count,
                matched_once_fraction=matched/compared if compared else None,
                matched_raw_dn_fraction=raw_matched/compared if compared else None,
                matched_twice_fraction=twice_matched/compared if compared else None)
            if compared:
                evidence.update(observed_min=observed_min, observed_max=observed_max,
                                expected_min=expected_min, expected_max=expected_max)
    except (OSError, ValueError, OverflowError, rasterio.errors.RasterioError) as error:
        return answer(NOT_RUN, f"Cannot compare calibration ({type(error).__name__}).")
    if unsupported or nonfinite or matched != compared:
        return answer(FAIL, "At least one delivered band pixel violates calibration, source validity or finite output values.")
    if not compared:
        return answer(NOT_RUN, "No finite, jointly valid delivered pixel could be compared.")
    return answer(PASS, "Every jointly valid delivered band pixel matches one calibration; source invalidity is preserved. "
                  "Additional output masks are counted but their scientific policy is not verified.")


def cloud_mask(output, qa_path, qa_kind, keep_codes=None):
    """Every flagged QA location must be invalid in every output band. With qa_kind "keep-codes" the
    caller declares the acceptable QA codes, and every other code is flagged."""
    evidence = {"output": output.get("path"), "qa_path": qa_path, "qa_kind": qa_kind, "qa_keep_codes": keep_codes,
                "processing_full_scan": True, "stride": 1, "scan_scope": "all output bands and QA pixels",
                "window_size": WINDOW_SIZE}
    def answer(status, message):
        return [result("rs.cloud_mask_applied", status, message, **evidence)]
    if not qa_path or qa_kind not in ("s2-scl", "landsat-qa-pixel", "keep-codes") or output.get("kind") != "raster":
        return answer(NOT_RUN, "Supply an output raster and known QA raster/kind.")
    if qa_kind == "keep-codes" and (not keep_codes or not all(type(code) is int and code >= 0 for code in keep_codes)):
        evidence["missing_bindings"] = ["qa_keep_codes"]
        return answer(NOT_RUN, "Declare qa_keep_codes, the QA codes your quality rule accepts; nothing is inferred.")
    try:
        qa = inspect_raster(qa_path)
        if _grid_problems(qa, output) or not qa.get("crs"):
            return answer(NOT_RUN, "QA and output need identical declared grids and CRS.")
        with rasterio.open(qa_path) as src, rasterio.open(output["path"]) as dst:
            if src.count != 1 or np.dtype(src.dtypes[0]).kind not in "iu" or src.scales != (1.,) or src.offsets != (0.,):
                return answer(NOT_RUN, "QA must be one integer band of unscaled categorical/bit codes.")
            if any(np.dtype(dtype).kind not in "iuf" for dtype in dst.dtypes):
                return answer(NOT_RUN, "Cloud-mask verification needs real-valued output bands.")
            flagged_count = unmasked_count = band_count = unavailable = 0
            for window in windows(src):
                codes = src.read(1, window=window)
                known = src.read_masks(1, window=window) > 0
                in_range = (codes >= 0) & (codes <= (11 if qa_kind == "s2-scl" else 65535))
                known &= in_range
                if qa_kind == "keep-codes":
                    flagged = known & ~np.isin(codes, keep_codes)
                else:
                    flagged = known & (np.isin(codes, SCL_CLOUD_CLASSES) if qa_kind == "s2-scl"
                                       else (codes.astype("uint64") & LANDSAT_QA_MASK) != 0)
                flagged_count += int(np.count_nonzero(flagged))
                any_band_unmasked = np.zeros(codes.shape, dtype=bool)
                any_band_valid = np.zeros(codes.shape, dtype=bool)
                for band in dst.indexes:
                    values = dst.read(band, window=window)
                    valid = (dst.read_masks(band, window=window) > 0) & ~np.isnan(values)
                    bad = flagged & valid
                    band_count += int(np.count_nonzero(bad))
                    any_band_unmasked |= bad
                    any_band_valid |= valid
                unmasked_count += int(np.count_nonzero(any_band_unmasked))
                # Missing QA is unverifiable only where the output still holds a value there.
                unavailable += int(np.count_nonzero(~known & any_band_valid))
            evidence.update(flagged_pixels=flagged_count, unmasked_flagged_pixels=unmasked_count,
                unmasked_flagged_band_pixels=band_count, unavailable_qa_pixels=unavailable, bands=dst.count,
                unmasked_fraction=unmasked_count/flagged_count if flagged_count else None)
    except (OSError, ValueError, OverflowError, rasterio.errors.RasterioError) as error:
        return answer(NOT_RUN, f"Cannot compare QA ({type(error).__name__}).")
    if unmasked_count:
        return answer(FAIL, "At least one QA-flagged location still has a value in an output band.")
    if unavailable:
        return answer(NOT_RUN, "Missing or unsupported QA codes leave part of the output unverifiable.")
    if not flagged_count:
        return answer(NOT_RUN, "QA flags no cloud/shadow locations; masking cannot be confirmed.")
    return answer(PASS, "Every QA-flagged location is invalid or NaN in every output band. "
                  "This does not validate cloud detection, dilation or additional output masking.")
