"""Remote-sensing value checks: rs.reflectance_range and rs.index_range.

These are sampled plausibility screens, not calibration checks. Both use the sampled
statistics from the inspector, which have scale and offset applied. A value outside the
expected range can have several causes; a missing or double-applied scale/offset is one
possible cause. A band with a non-finite scale, offset, or decoded value is a data error
and is never passed.
"""

from __future__ import annotations

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result

REFLECTANCE_MIN_P1 = -0.5
REFLECTANCE_MAX_P99 = 1.5
INDEX_MIN = -1.0001
INDEX_MAX = 1.0001


def _band_summary(band: dict) -> dict:
    stats = band["stats"]
    return {
        "index": band["index"],
        "scale": band["scale"],
        "offset": band["offset"],
        "min": stats["min"],
        "max": stats["max"],
        "p1": stats["p1"],
        "p99": stats["p99"],
        "nonfinite_count": stats["nonfinite_count"],
        "non_finite_problems": band["non_finite_problems"],
    }


def _data_error_details(bands: list[dict]) -> str | None:
    """Describe the bands with non-finite scale, offset, or decoded statistics; None when all are finite."""
    flagged = [band for band in bands if band["non_finite_problems"]]
    if not flagged:
        return None
    return "; ".join(f"band {band['index']}: " + ", ".join(band["non_finite_problems"]) for band in flagged)


def _format(value: float) -> str:
    return f"{value:.4g}"


def check_reflectance(rasters: list[dict]) -> list:
    if not rasters:
        return [result("rs.reflectance_range", NOT_RUN, "No raster input to check for reflectance range.")]
    results = []
    for dataset in rasters:
        path = dataset["path"]
        bands = dataset["bands"]
        evidence = {
            "input": path,
            "thresholds": {"p1_min": REFLECTANCE_MIN_P1, "p99_max": REFLECTANCE_MAX_P99},
            "bands": [_band_summary(band) for band in bands],
        }
        sampled = [band for band in bands if band["stats"]["valid_sample_count"]]
        bad = [
            band for band in sampled
            if band["stats"]["p99"] > REFLECTANCE_MAX_P99 or band["stats"]["p1"] < REFLECTANCE_MIN_P1
        ]
        data_error = _data_error_details(bands)
        if data_error:
            results.append(
                result(
                    "rs.reflectance_range",
                    FAIL,
                    f"Non-finite scale, offset, or decoded values in {path} ({data_error}). This is a data error; "
                    "a band with non-finite values cannot pass the reflectance screen.",
                    **evidence,
                )
            )
        elif bad:
            details = "; ".join(
                f"band {band['index']} p1={_format(band['stats']['p1'])} p99={_format(band['stats']['p99'])}"
                for band in bad
            )
            results.append(
                result(
                    "rs.reflectance_range",
                    FAIL,
                    f"Reflectance values in {path} fall outside [-0.5, 1.5] ({details}). This is a sampled "
                    "plausibility screen; one possible cause is a missing or double-applied scale/offset.",
                    **evidence,
                )
            )
        elif len(sampled) < len(bands):
            results.append(
                result(
                    "rs.reflectance_range",
                    NOT_RUN,
                    f"No valid pixels were sampled for some bands of {path}; reflectance range is not evaluated.",
                    **evidence,
                )
            )
        else:
            results.append(
                result("rs.reflectance_range", PASS,
                       f"Sampled reflectance values in {path} are within [-0.5, 1.5] (sampled plausibility screen).",
                       **evidence)
            )
    return results


def check_index(rasters: list[dict]) -> list:
    if not rasters:
        return [result("rs.index_range", NOT_RUN, "No raster input to check for index range.")]
    results = []
    for dataset in rasters:
        path = dataset["path"]
        bands = dataset["bands"]
        evidence = {
            "input": path,
            "thresholds": {"min": -1.0, "max": 1.0},
            "bands": [_band_summary(band) for band in bands],
        }
        sampled = [band for band in bands if band["stats"]["valid_sample_count"]]
        bad = [
            band for band in sampled
            if band["stats"]["min"] < INDEX_MIN or band["stats"]["max"] > INDEX_MAX
        ]
        data_error = _data_error_details(bands)
        if data_error:
            results.append(
                result(
                    "rs.index_range",
                    FAIL,
                    f"Non-finite scale, offset, or decoded values in {path} ({data_error}). This is a data error; "
                    "a band with non-finite values cannot pass the index screen.",
                    **evidence,
                )
            )
        elif bad:
            details = "; ".join(
                f"band {band['index']} min={_format(band['stats']['min'])} max={_format(band['stats']['max'])}"
                for band in bad
            )
            results.append(
                result(
                    "rs.index_range",
                    FAIL,
                    f"Index values in {path} fall outside [-1, 1] ({details}). This is a sampled plausibility screen.",
                    **evidence,
                )
            )
        elif len(sampled) < len(bands):
            results.append(
                result(
                    "rs.index_range",
                    NOT_RUN,
                    f"No valid pixels were sampled for some bands of {path}; index range is not evaluated.",
                    **evidence,
                )
            )
        else:
            results.append(result("rs.index_range", PASS,
                                  f"Sampled index values in {path} are within [-1, 1] (sampled plausibility screen).",
                                  **evidence))
    return results
