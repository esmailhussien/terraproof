"""Processing-level optical checks: rs.scale_applied_once, rs.cloud_mask_applied, rs.temporal_scope.

These compare an input with an output, so they need the raw pixels rather than the sampled
statistics the inspector keeps. Pixels are read at a fixed stride (no random sampling), the
first band only, and with raster scale/offset metadata *not* applied, because the point of
rs.scale_applied_once is to compare stored DN against the declared calibration.

Nothing here proves the processing chain is complete: each check measures one stated
relation between two files and says what it measured.
"""

from __future__ import annotations

import math

import numpy as np
import rasterio

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.raster import GRID_TOLERANCE
from terraproof.inspect.raster import inspect_raster

# One sample every STRIDE x STRIDE pixels (windowed, so large rasters stay cheap and the
# sample set is identical on every run).
STRIDE = 8

# A sampled pixel agrees with a hypothesis when |observed - expected| <= RTOL * |expected|
# + ATOL. These are generous enough for float32 storage of reflectance and tight enough that
# raw DN and twice-decoded values never fall inside the band around the correct one.
RTOL = 1e-4
ATOL = 1e-6

# The check passes when at least this share of samples agrees with the declared formula.
MIN_MATCH_FRACTION = 0.99

# Sentinel-2 L2A: (DN - 1000) / 10000, i.e. DN * 0.0001 with offset -0.1.
# Landsat 8/9 Collection 2 Level-2 surface reflectance: DN * 0.0000275 - 0.2.
ENCODINGS = {
    "s2-l2a": {"scale": 0.0001, "offset": -0.1},
    "landsat-c2-l2": {"scale": 0.0000275, "offset": -0.2},
}

# Sentinel-2 Scene Classification Layer classes that must not survive a cloud/shadow mask:
# 3 cloud shadow, 8 cloud medium probability, 9 cloud high probability, 10 thin cirrus.
SCL_CLOUD_CLASSES = (3, 8, 9, 10)

# Landsat 8/9 QA_PIXEL bits 1-4: dilated cloud, cirrus, cloud, cloud shadow.
LANDSAT_QA_MASK = 0b11110


def _grid_problems(reference: dict, other: dict) -> list[str]:
    """Reuse the raster.grid_alignment rule: same CRS, same pixel size, same pixel-grid origin."""
    problems = []
    reference_crs = reference["crs"]
    other_crs = other["crs"]
    if reference_crs is None or other_crs is None:
        if reference_crs is not other_crs:
            problems.append("one raster has no CRS")
    elif reference_crs["epsg"] != other_crs["epsg"] or reference_crs["wkt"] != other_crs["wkt"]:
        problems.append(f"CRS of {other['path']} differs from {reference['path']}")
    ref_transform = reference["transform"]
    other_transform = other["transform"]
    pixel_x, pixel_y = ref_transform[0], ref_transform[4]
    if pixel_x == 0 or pixel_y == 0:
        problems.append("a raster has no pixel size")
        return problems
    if (
        abs(other_transform[0] - pixel_x) > GRID_TOLERANCE * abs(pixel_x)
        or abs(other_transform[4] - pixel_y) > GRID_TOLERANCE * abs(pixel_y)
    ):
        problems.append(f"pixel size of {other['path']} differs from {reference['path']}")
    offset_x = (other_transform[2] - ref_transform[2]) / pixel_x
    offset_y = (other_transform[5] - ref_transform[5]) / pixel_y
    if abs(offset_x - round(offset_x)) > GRID_TOLERANCE or abs(offset_y - round(offset_y)) > GRID_TOLERANCE:
        problems.append(f"pixel-grid origin of {other['path']} is offset from {reference['path']}")
    return problems


def _raw_window(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (values, valid) for a fixed-stride sample of band 1, with no scale/offset applied."""
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"no CRS: {path}")
        data = src.read(1, masked=True, out_shape=src.shape, resampling=rasterio.enums.Resampling.nearest)
    rows = np.arange(0, data.shape[0], STRIDE)
    cols = np.arange(0, data.shape[1], STRIDE)
    sample = data[np.ix_(rows, cols)]
    return np.ma.getdata(sample).astype(np.float64), ~np.ma.getmaskarray(sample)


def _match_fraction(observed: np.ndarray, expected: np.ndarray) -> float:
    if observed.size == 0:
        return 0.0
    within = np.abs(observed - expected) <= RTOL * np.abs(expected) + ATOL
    return float(np.count_nonzero(within) / observed.size)


def check_scale_applied_once(
    output: dict,
    reference_input: dict,
    encoding: str | None = None,
    scale: float | None = None,
    offset: float | None = None,
) -> list:
    """Compare output pixels with `reference_input` DN through one declared calibration.

    The expected value is DN * scale + offset. `scale`/`offset` come from the input's own
    raster metadata unless `encoding` names a product whose calibration is documented
    (s2-l2a, landsat-c2-l2). The output is compared against that formula once, against the
    raw DN (decoding not applied), and against the formula applied twice.
    """
    if reference_input is None:
        return [
            result(
                "rs.scale_applied_once",
                NOT_RUN,
                f"No input DN dataset was given, so the scale and offset applied when writing "
                f"{output['path']} could not be compared with the input.",
                output=output["path"],
                reference_input=None,
            )
        ]

    if reference_input.get("kind") != "raster":
        return [
            result(
                "rs.scale_applied_once",
                NOT_RUN,
                f"Scale-applied-once needs a raster input DN dataset, but {reference_input.get('path')} "
                f"is a {reference_input.get('kind')} dataset.",
                output=output["path"],
                reference_input=reference_input.get("path"),
            )
        ]

    if encoding is not None and encoding not in ENCODINGS:
        return [
            result(
                "rs.scale_applied_once",
                NOT_RUN,
                f"Unknown encoding '{encoding}'. Known encodings: {', '.join(sorted(ENCODINGS))}.",
                output=output["path"],
                reference_input=reference_input["path"],
                encoding=encoding,
            )
        ]

    grid_problems = _grid_problems(reference_input, output)
    if grid_problems:
        return [
            result(
                "rs.scale_applied_once",
                NOT_RUN,
                f"Output {output['path']} and input {reference_input['path']} are not on the same grid "
                f"({'; '.join(grid_problems)}), so no pixel-wise comparison is possible.",
                output=output["path"],
                reference_input=reference_input["path"],
                problems=grid_problems,
            )
        ]

    if encoding is not None:
        scale, offset = ENCODINGS[encoding]["scale"], ENCODINGS[encoding]["offset"]
        scale_source = f"encoding '{encoding}'"
    else:
        band = reference_input["bands"][0]
        scale = band["scale"] if scale is None else scale
        offset = band["offset"] if offset is None else offset
        scale_source = "input raster metadata"

    if not math.isfinite(scale) or not math.isfinite(offset):
        return [
            result(
                "rs.scale_applied_once",
                FAIL,
                f"Calibration from {scale_source} is not finite (scale={scale}, offset={offset}); "
                "the decoded expectation cannot be computed.",
                output=output["path"],
                reference_input=reference_input["path"],
                scale=scale,
                offset=offset,
                scale_source=scale_source,
            )
        ]

    try:
        dn, dn_valid = _raw_window(reference_input["path"])
        out, out_valid = _raw_window(output["path"])
    except (ValueError, rasterio.errors.RasterioIOError) as error:
        return [
            result(
                "rs.scale_applied_once",
                NOT_RUN,
                f"Cannot read stored pixel values: {error}",
                output=output["path"],
                reference_input=reference_input["path"],
            )
        ]

    keep = dn_valid & out_valid & np.isfinite(dn) & np.isfinite(out)
    sampled = int(np.count_nonzero(keep))
    evidence = {
        "output": output["path"],
        "reference_input": reference_input["path"],
        "scale": scale,
        "offset": offset,
        "scale_source": scale_source,
        "encoding": encoding,
        "stride": STRIDE,
        "tolerance": {"rtol": RTOL, "atol": ATOL},
        "min_match_fraction": MIN_MATCH_FRACTION,
        "sampled_pixels": sampled,
    }
    if sampled == 0:
        return [
            result(
                "rs.scale_applied_once",
                NOT_RUN,
                f"No pixel of {output['path']} is valid in both it and {reference_input['path']}; "
                "no pixel-wise comparison is possible.",
                **evidence,
            )
        ]

    dn_k, out_k = dn[keep], out[keep]
    once = dn_k * scale + offset
    twice = once * scale + offset
    matched_once = _match_fraction(out_k, once)
    matched_twice = _match_fraction(out_k, twice)
    matched_raw = _match_fraction(out_k, dn_k)
    evidence.update(
        {
            "matched_once_fraction": matched_once,
            "matched_twice_fraction": matched_twice,
            "matched_raw_dn_fraction": matched_raw,
            "observed_min": float(out_k.min()),
            "observed_max": float(out_k.max()),
            "expected_min": float(once.min()),
            "expected_max": float(once.max()),
        }
    )

    if matched_once >= MIN_MATCH_FRACTION:
        return [
            result(
                "rs.scale_applied_once",
                PASS,
                f"{matched_once:.4%} of {sampled} sampled pixels of {output['path']} equal "
                f"DN x {scale:g} + {offset:g} from {scale_source} within rel {RTOL:g} / abs {ATOL:g}. "
                "This compares stored pixels on a fixed stride; it does not verify any other processing step.",
                **evidence,
            )
        ]
    if matched_raw >= MIN_MATCH_FRACTION:
        relation = "equals the raw input DN (calibration not applied)"
    elif matched_twice >= MIN_MATCH_FRACTION:
        relation = "equals the calibration applied twice"
    else:
        relation = (
            f"matches neither the decoded values (DN x {scale:g} + {offset:g}) nor the raw DN nor the "
            "doubly decoded values; the observed relation to the input is unclassified"
        )
    return [
        result(
            "rs.scale_applied_once",
            FAIL,
            f"Only {matched_once:.4%} of {sampled} sampled pixels of {output['path']} equal "
            f"DN x {scale:g} + {offset:g} from {scale_source} (threshold {MIN_MATCH_FRACTION:.0%}); the output {relation}.",
            **evidence,
        )
    ]


def _flagged(qa_path: str, qa_kind: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (values, flagged) on a fixed stride for an SCL or Landsat QA_PIXEL raster."""
    with rasterio.open(qa_path) as src:
        data = src.read(1, masked=True, out_shape=src.shape, resampling=rasterio.enums.Resampling.nearest)
    rows = np.arange(0, data.shape[0], STRIDE)
    cols = np.arange(0, data.shape[1], STRIDE)
    sample = np.ma.getdata(data)[np.ix_(rows, cols)].astype(np.float64)
    if qa_kind == "s2-scl":
        flagged = np.isin(np.rint(sample), SCL_CLOUD_CLASSES)
    elif qa_kind == "landsat-qa-pixel":
        flagged = (np.rint(sample).astype(np.int64) & LANDSAT_QA_MASK) != 0
    else:
        raise ValueError(f"unknown qa_kind: {qa_kind}")
    return sample, flagged


def check_cloud_mask_applied(output: dict, qa_path: str | None, qa_kind: str | None) -> list:
    """Every cloud/shadow-flagged pixel of the QA raster must be nodata in the output.

    Masked pixels are those that are nodata in the output, or NaN, or outside the declared
    scale/offset reading: the check cannot claim a pixel was masked when it holds a value.
    """
    if qa_path is None or qa_kind is None:
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                "No QA raster given (qa_path and qa_kind are both required to check that cloud and shadow "
                "pixels were masked).",
                output=output["path"],
                qa_path=qa_path,
                qa_kind=qa_kind,
            )
        ]
    if qa_kind not in ("s2-scl", "landsat-qa-pixel"):
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                f"Unknown QA kind '{qa_kind}'. Known kinds: s2-scl, landsat-qa-pixel.",
                output=output["path"],
                qa_path=qa_path,
                qa_kind=qa_kind,
            )
        ]

    try:
        qa_dataset = inspect_raster(qa_path)
    except Exception as error:  # a missing or unreadable QA raster is not a masking verdict
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                f"Cannot inspect the QA raster {qa_path}: {error}",
                output=output["path"],
                qa_path=qa_path,
                qa_kind=qa_kind,
            )
        ]

    grid_problems = _grid_problems(qa_dataset, output)
    if grid_problems:
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                f"QA raster {qa_path} and output {output['path']} are not aligned ({'; '.join(grid_problems)}), "
                "so QA pixels cannot be compared with output pixels.",
                output=output["path"],
                qa_path=qa_path,
                qa_kind=qa_kind,
                problems=grid_problems,
            )
        ]

    if qa_kind == "s2-scl":
        criteria = f"Sentinel-2 SCL classes {', '.join(str(c) for c in SCL_CLOUD_CLASSES)}"
    else:
        criteria = "Landsat QA_PIXEL bits 1-4 (dilated cloud, cirrus, cloud, cloud shadow)"
    evidence = {
        "output": output["path"],
        "qa_path": qa_path,
        "qa_kind": qa_kind,
        "flagged_criteria": criteria,
        "stride": STRIDE,
    }

    try:
        _, flagged = _flagged(qa_path, qa_kind)
        out, out_valid = _raw_window(output["path"])
    except Exception as error:
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                f"Cannot read stored pixel values: {error}",
                **evidence,
            )
        ]
    if flagged.shape != out.shape:
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                f"Sampled QA and output shapes differ ({flagged.shape} vs {out.shape}); the grids are not comparable.",
                **evidence,
            )
        ]

    flagged_pixels = int(np.count_nonzero(flagged))
    evidence["flagged_pixels"] = flagged_pixels
    if flagged_pixels == 0:
        return [
            result(
                "rs.cloud_mask_applied",
                NOT_RUN,
                f"The QA raster {qa_path} flags no pixels matching {criteria} on the sampled stride, so "
                "nothing can be confirmed about masking.",
                **evidence,
            )
        ]

    unmasked = flagged & out_valid & np.isfinite(out)
    unmasked_count = int(np.count_nonzero(unmasked))
    evidence["unmasked_flagged_pixels"] = unmasked_count
    evidence["unmasked_fraction"] = unmasked_count / flagged_pixels
    if unmasked_count == 0:
        return [
            result(
                "rs.cloud_mask_applied",
                PASS,
                f"All {flagged_pixels} sampled pixels flagged as {criteria} are nodata or NaN in "
                f"{output['path']}. This samples one pixel every {STRIDE}x{STRIDE}; it does not verify the "
                "cloud-detection method or the mask's spatial dilation.",
                **evidence,
            )
        ]
    return [
        result(
            "rs.cloud_mask_applied",
            FAIL,
            f"{unmasked_count} of {flagged_pixels} sampled pixels flagged as {criteria} "
            f"({unmasked_count / flagged_pixels:.2%}) still hold values in {output['path']}; the cloud/shadow "
            "mask was not applied to them.",
            **evidence,
        )
    ]


def _parse_time(value: str | None, field: str) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    from datetime import datetime

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, f"{field} '{value}' is not an ISO 8601 date-time"
    if parsed.tzinfo is None:
        from datetime import timezone

        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp(), None


def check_temporal_scope(items: list[dict], time_range: tuple[str, str] | list | None) -> list:
    """Every STAC item time must fall inside the declared range (inclusive).

    An item with start_datetime/end_datetime is in range only when its whole interval is.
    """
    if not time_range:
        return [
            result(
                "rs.temporal_scope",
                NOT_RUN,
                "No time_range given; the acquisition times of the STAC items were not compared with a "
                "declared range.",
                inputs=[item["path"] for item in items],
            )
        ]
    if len(time_range) != 2:
        return [
            result(
                "rs.temporal_scope",
                NOT_RUN,
                f"time_range must have exactly two ISO bounds (start, end); got {len(time_range)}.",
                inputs=[item["path"] for item in items],
            )
        ]
    start, start_error = _parse_time(time_range[0], "start")
    end, end_error = _parse_time(time_range[1], "end")
    if start_error or end_error:
        return [
            result(
                "rs.temporal_scope",
                NOT_RUN,
                f"Cannot compare times: {start_error or end_error}.",
                inputs=[item["path"] for item in items],
                time_range=list(time_range),
            )
        ]
    if start > end:
        return [
            result(
                "rs.temporal_scope",
                NOT_RUN,
                f"time_range start {time_range[0]} is after end {time_range[1]}; the range is empty.",
                inputs=[item["path"] for item in items],
                time_range=list(time_range),
            )
        ]

    inputs = [item["path"] for item in items]
    evidence_common = {"time_range": list(time_range), "inputs": inputs}
    if not items:
        return [
            result(
                "rs.temporal_scope",
                NOT_RUN,
                f"No STAC item given, so no acquisition time could be compared with {time_range[0]}..{time_range[1]}.",
                **evidence_common,
            )
        ]

    undated = []
    out_of_range = []
    inside = []
    for item in items:
        if item["datetime"] is not None:
            low, label_error = _parse_time(item["datetime"], "datetime")
            if label_error:
                undated.append({"item": item["path"], "reason": label_error})
                continue
            high = low
        elif item["start_datetime"] is not None and item["end_datetime"] is not None:
            low, low_error = _parse_time(item["start_datetime"], "start_datetime")
            high, high_error = _parse_time(item["end_datetime"], "end_datetime")
            if low_error or high_error:
                undated.append({"item": item["path"], "reason": low_error or high_error})
                continue
        else:
            undated.append({"item": item["path"], "reason": "no datetime or start/end_datetime"})
            continue
        record = {
            "item": item["path"],
            "id": item["id"],
            "datetime": item["datetime"],
            "start_datetime": item["start_datetime"],
            "end_datetime": item["end_datetime"],
        }
        if low < start or high > end:
            out_of_range.append(record)
        else:
            inside.append(record)

    evidence = dict(evidence_common)
    evidence.update({"inside_range": inside, "out_of_range": out_of_range, "items_without_time": undated})
    if out_of_range:
        listed = ", ".join(
            f"{record['id'] or record['item']} ({record['datetime'] or record['start_datetime']})"
            for record in out_of_range
        )
        return [
            result(
                "rs.temporal_scope",
                FAIL,
                f"{len(out_of_range)} of {len(items)} STAC items fall outside {time_range[0]}..{time_range[1]}: {listed}.",
                **evidence,
            )
        ]
    if undated:
        listed = ", ".join(record["item"] for record in undated)
        return [
            result(
                "rs.temporal_scope",
                NOT_RUN,
                f"{len(inside)} items are inside {time_range[0]}..{time_range[1]}, but {len(undated)} items have "
                f"no usable acquisition time and could not be confirmed: {listed}.",
                **evidence,
            )
        ]
    return [
        result(
            "rs.temporal_scope",
            PASS,
            f"All {len(items)} STAC items lie inside {time_range[0]}..{time_range[1]}.",
            **evidence,
        )
    ]