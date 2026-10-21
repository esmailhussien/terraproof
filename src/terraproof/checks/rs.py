"""Remote-sensing value checks: rs.reflectance_range and rs.index_range.

Both use the sampled statistics from the inspector, which already have scale and
offset applied. A value outside the expected physical range therefore means the
scale or offset was not applied, or was applied twice.
"""

from __future__ import annotations

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result

REFLECTANCE_MIN_P1 = -0.5
REFLECTANCE_MAX_P99 = 1.5
INDEX_MIN = -1.0001
INDEX_MAX = 1.0001


def _band_summary(band: dict) -> dict:
    stats = band["stats"]
    return {"index": band["index"], "min": stats["min"], "max": stats["max"], "p1": stats["p1"], "p99": stats["p99"]}


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
        if bad:
            details = "; ".join(
                f"band {band['index']} p1={_format(band['stats']['p1'])} p99={_format(band['stats']['p99'])}"
                for band in bad
            )
            results.append(
                result(
                    "rs.reflectance_range",
                    FAIL,
                    f"Reflectance values in {path} fall outside [-0.5, 1.5] ({details}). Scale/offset is "
                    "likely not applied, or applied twice.",
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
                result("rs.reflectance_range", PASS, f"Sampled reflectance values in {path} are within [-0.5, 1.5].",
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
        if bad:
            details = "; ".join(
                f"band {band['index']} min={_format(band['stats']['min'])} max={_format(band['stats']['max'])}"
                for band in bad
            )
            results.append(
                result(
                    "rs.index_range",
                    FAIL,
                    f"Index values in {path} fall outside [-1, 1] ({details}).",
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
            results.append(result("rs.index_range", PASS, f"Sampled index values in {path} are within [-1, 1].",
                                  **evidence))
    return results
