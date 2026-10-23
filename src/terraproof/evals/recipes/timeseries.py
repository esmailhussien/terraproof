"""Fixtures and oracles for the `time-series-and-change` task specs."""

from __future__ import annotations

from pathlib import Path
import warnings

import numpy as np

from terraproof.evals.fixtures import EQUAL_AREA, FLOAT_NODATA, UTM, read_raster, write_raster, write_stac_item
from terraproof.evals.oracles import Oracle, ndvi, olofsson_estimates
from terraproof.evals.recipes._util import (
    check_step,
    correct,
    recipe,
    results_for,
    weighted_sample_csv,
    wrong,
)

NODATA = FLOAT_NODATA


def _ndvi_stack(shape, red: np.ndarray, nir: np.ndarray, valid: np.ndarray) -> np.ndarray:
    values = np.full(shape, np.nan, dtype="float64")
    keep = valid & np.isfinite(red) & np.isfinite(nir)
    with np.errstate(divide="ignore", invalid="ignore"):
        values[keep] = (nir[keep] - red[keep]) / (nir[keep] + red[keep])
    values[(nir + red) == 0] = np.nan
    return values


def _write_ndvi(path: Path, values: np.ndarray) -> str:
    array = np.full(values.shape, NODATA, dtype="float32")
    valid = np.isfinite(values)
    array[valid] = values[valid]
    return write_raster(path, array, crs=UTM, nodata=NODATA, dtype="float32")


def ts_monthly_composite(root: Path):
    """Task 1: monthly NDVI composites and valid-observation counts."""
    shape = (16, 16)
    rows, cols = np.indices(shape)
    june_pairs = [
        (0.05 + 0.004 * ((rows + cols) % 5), 0.30 + 0.006 * ((rows * 2 + cols) % 5)),
        (0.06 + 0.004 * ((rows + cols) % 5), 0.32 + 0.006 * ((rows * 2 + cols) % 5)),
        (0.04 + 0.004 * ((rows + cols) % 5), 0.28 + 0.006 * ((rows * 2 + cols) % 5)),
    ]
    june_pairs[0] = (np.full(shape, 0.05), np.full(shape, 0.40))
    june_pairs[1] = (np.full(shape, 0.10), np.full(shape, 0.20))
    june_pairs[2] = (np.full(shape, 0.04), np.full(shape, 0.30))
    june_valid = [np.ones(shape, dtype=bool) for _ in range(3)]
    june_valid[1][0, 1] = False
    june_valid[2][0, 1] = False
    june_valid[0][0, 2] = False
    june_valid[1][0, 2] = False
    june_valid[2][0, 2] = False
    june_valid[1][1, 1] = False  # red masked, NIR valid: this date must not count
    june_ndvi = [
        _ndvi_stack(shape, red.astype("float64"), nir.astype("float64"), june_valid[index])
        for index, (red, nir) in enumerate(june_pairs)
    ]
    june_stack = np.stack(june_ndvi)
    june_counts = np.sum(np.stack(june_valid) & np.isfinite(june_stack), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        june_composite = np.nanmedian(june_stack, axis=0)
    june_composite[june_counts == 0] = np.nan
    june_path = _write_ndvi(root / "ndvi_2024-06.tif", june_composite)
    june_count_path = write_raster(
        root / "valid_counts_2024-06.tif",
        june_counts.astype("uint8"),
        crs=UTM,
        nodata=255,
        dtype="uint8",
    )

    july_red = (0.07 + 0.004 * ((rows + cols) % 5)).astype("float64")
    july_nir = (0.34 + 0.006 * ((rows * 2 + cols) % 5)).astype("float64")
    july_valid = np.ones(shape, dtype=bool)
    july_ndvi = _ndvi_stack(shape, july_red, july_nir, july_valid)
    july_ndvi[0, 2] = np.nan
    july_path = _write_ndvi(root / "ndvi_2024-07.tif", july_ndvi)
    june_item = write_stac_item(
        root / "june-item.json",
        item_id="S2B_JUNE_2024",
        datetime="2024-06-15T10:30:00Z",
    )
    july_item = write_stac_item(
        root / "july-item.json",
        item_id="S2B_JULY_2024",
        datetime="2024-07-12T10:30:00Z",
    )
    steps = [
        check_step(
            "check ndvi_2024-06.tif ndvi_2024-07.tif --expect index",
            [june_path, july_path],
            expect="index",
        ),
        check_step(
            "run_checks(['june-item.json','july-item.json'], time_range=('2024-06-01','2024-07-31'))",
            [june_item, july_item],
            time_range=("2024-06-01T00:00:00Z", "2024-07-31T23:59:59Z"),
        ),
    ]
    control_pairs = [(0.05, 0.40), (0.10, 0.20), (0.04, 0.30)]
    median_of_ndvi = float(np.median([float(ndvi(red, nir)) for red, nir in control_pairs]))
    index_of_medians = float(ndvi(np.median([red for red, _nir in control_pairs]), np.median([nir for _red, nir in control_pairs])))
    oracle = Oracle("composite of indices vs index of composites, with valid-observation counts")
    oracle.close("median of per-date NDVI", median_of_ndvi, 0.765, 0.001)
    oracle.close("NDVI of per-band medians", index_of_medians, 0.714, 0.001)
    oracle.differs_by(
        "the two composite rules differ on the control pixel",
        median_of_ndvi,
        index_of_medians,
        0.01,
    )
    delivered = read_raster(june_path)
    oracle.close(
        "June composite at the control pixel uses the median of per-date NDVI",
        float(np.ma.getdata(delivered)[0, 0]),
        median_of_ndvi,
        1e-6,
    )
    oracle.equal("valid-observation count for the control pixel", int(np.ma.getdata(read_raster(june_count_path))[0, 0]), 3)
    oracle.equal("a single-valid-date pixel counts one observation", int(np.ma.getdata(read_raster(june_count_path))[0, 1]), 1)
    oracle.equal("a date with one masked band does not count", int(np.ma.getdata(read_raster(june_count_path))[1, 1]), 2)
    oracle.require(
        "an all-invalid pixel is nodata",
        bool(np.ma.getmaskarray(delivered)[0, 2]),
        "masked" if np.ma.getmaskarray(delivered)[0, 2] else "valid",
        "masked",
    )
    for check_id, count in (("rs.index_range", 2), ("raster.nodata_declared", 2), ("raster.grid_alignment", 1), ("rs.temporal_scope", 1)):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} emits the expected pass results",
            len(observed) == count and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    correct_control = correct(
        "median-of-ndvi-composite",
        "Three June dates and one July date of cloud-masked reflectance; the composite is the median of "
        "per-date NDVI with a per-pixel valid-observation count.",
        steps,
        oracle,
    )

    with np.errstate(all="ignore"):
        band_medians = np.nanmedian(np.stack([pair[0] for pair in june_pairs]), axis=0), np.nanmedian(
            np.stack([pair[1] for pair in june_pairs]), axis=0
        )
    index_of_medians_array = ndvi(band_medians[0], band_medians[1])
    index_of_medians_array[june_counts == 0] = np.nan
    wrong_path = _write_ndvi(root / "ndvi_2024-06_index_of_medians.tif", index_of_medians_array)
    wrong_steps = [
        check_step(
            "check ndvi_2024-06_index_of_medians.tif ndvi_2024-07.tif --expect index",
            [wrong_path, july_path],
            expect="index",
        ),
        check_step(
            "run_checks(['june-item.json','july-item.json'], time_range=('2024-06-01','2024-07-31'))",
            [june_item, july_item],
            time_range=("2024-06-01T00:00:00Z", "2024-07-31T23:59:59Z"),
        ),
    ]
    wrong_oracle = Oracle("the composite rule must be named and applied consistently")
    wrong_values = read_raster(wrong_path)
    wrong_oracle.close(
        "June composite at the control pixel uses the median of per-date NDVI",
        float(np.ma.getdata(wrong_values)[0, 0]),
        median_of_ndvi,
        1e-6,
    )
    wrong_oracle.differs_by(
        "the index-of-medians value differs from the composite of indices",
        float(np.ma.getdata(wrong_values)[0, 0]),
        median_of_ndvi,
        0.01,
    )
    wrong_control = wrong(
        "index-of-medians-composite",
        "The June layer is NDVI of the per-band medians (0.714 instead of 0.765) and is reported as the "
        "same monthly composite.",
        wrong_steps,
        wrong_oracle,
    )

    zero_filled = np.array(np.ma.getdata(delivered))
    zero_filled[0, 2] = 0.0
    zero_path = _write_ndvi(root / "ndvi_2024-06_zero_filled.tif", zero_filled)
    zero_steps = [
        check_step("check ndvi_2024-06_zero_filled.tif ndvi_2024-07.tif --expect index", [zero_path, july_path], expect="index"),
        check_step(
            "run_checks(['june-item.json','july-item.json'], time_range=('2024-06-01','2024-07-31'))",
            [june_item, july_item],
            time_range=("2024-06-01T00:00:00Z", "2024-07-31T23:59:59Z"),
        ),
    ]
    zero_oracle = Oracle("an unobserved month is nodata, not zero")
    zero_values = read_raster(zero_path)
    zero_oracle.require(
        "the all-invalid pixel is nodata",
        bool(np.ma.getmaskarray(zero_values)[0, 2]),
        "masked" if np.ma.getmaskarray(zero_values)[0, 2] else "valid 0.0",
        "masked",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "all-invalid-zero-filled",
            "A month with no valid observations is written as a valid 0.0 NDVI instead of nodata.",
            zero_steps,
            zero_oracle,
        ),
    ]
    return recipe(
        "ts-monthly-ndvi-composite-counts",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.index_range, raster.nodata_declared, raster.grid_alignment and rs.temporal_scope on the composites and Items",
            "independent median-of-NDVI (0.765) vs NDVI-of-medians (0.714), per-pixel valid counts and all-invalid nodata",
        ],
        remaining=[
            "The answer must name the composite rule, explain why per-band medians can mix dates and state the minimum-count policy; prose is not graded.",
            "Review of the cloud-masking chain on the real reflectance stack.",
        ],
    )


def _dated_ndvi(root: Path, name: str, stable: float, clearing: float, cloud_mask=None) -> tuple[str, np.ndarray]:
    shape = (32, 32)
    values = np.full(shape, 0.5, dtype="float64")
    values[16:, :] = stable
    values[:8, :8] = clearing
    if cloud_mask is not None:
        values[cloud_mask] = np.nan
    path = _write_ndvi(root / name, values)
    return path, values


def ts_phenology_difference(root: Path):
    """Task 2: anniversary-matched NDVI difference with an aligned SCL mask."""
    cloud_positions = ((0, 0), (8, 8), (16, 16), (24, 24))
    scl = np.full((32, 32), 4, dtype="uint8")
    for (row, col), code in zip(cloud_positions, (8, 3, 9, 10)):
        scl[row, col] = code
    scl_path = write_raster(root / "scl_2024.tif", scl, crs=UTM, nodata=0, dtype="uint8")
    april_2023, april_values = _dated_ndvi(root, "ndvi_2023-04.tif", stable=0.85, clearing=0.60)
    july_2023, july_2023_values = _dated_ndvi(root, "ndvi_2023-07.tif", stable=0.35, clearing=0.70)
    july_2024, july_2024_values = _dated_ndvi(root, "ndvi_2024-07.tif", stable=0.35, clearing=0.20)
    difference = july_2024_values - july_2023_values
    for row, col in cloud_positions:
        difference[row, col] = np.nan
    difference_path = _write_ndvi(root / "difference_2023_2024.tif", difference)

    april_item = write_stac_item(root / "april-item.json", item_id="S2B_APRIL_2023", datetime="2023-04-12T10:30:00Z")
    july_2023_item = write_stac_item(root / "july-2023-item.json", item_id="S2B_JULY_2023", datetime="2023-07-18T10:30:00Z")
    july_2024_item = write_stac_item(root / "july-2024-item.json", item_id="S2B_JULY_2024", datetime="2024-07-20T10:30:00Z")
    steps = [
        check_step(
            "run_checks([april-item, july-2023-item, july-2024-item], time_range=('2023-06-01','2023-08-31'))",
            [april_item, july_2023_item, july_2024_item],
            time_range=("2023-06-01T00:00:00Z", "2023-08-31T23:59:59Z"),
        ),
        check_step(
            "run_checks(['difference_2023_2024.tif'], qa_path='scl_2024.tif', qa_kind='s2-scl')",
            [difference_path],
            qa_path=scl_path,
            qa_kind="s2-scl",
        ),
    ]
    stable_difference = 0.0
    clearing_difference = -0.5
    threshold = -0.25
    flooded = july_2024_values - july_2023_values < threshold
    reference = np.zeros((32, 32), dtype=bool)
    reference[:8, :8] = True
    intersection = np.count_nonzero(flooded & reference)
    union = np.count_nonzero(flooded | reference)
    oracle = Oracle("anniversary-matched difference and a locally derived threshold")
    oracle.close("stable-field anniversary difference", stable_difference, 0.0, 0.01)
    oracle.close("clearing anniversary difference", clearing_difference, -0.5, 0.01)
    oracle.require(
        "the April-2023 comparison creates a spurious drop on stable fields",
        abs(april_values[20, 20] - july_2024_values[20, 20]) > 0.3,
        round(float(april_values[20, 20] - july_2024_values[20, 20]), 4),
        "< -0.3 (phenology only)",
    )
    oracle.close(
        "the local threshold separates clearing from stable fields (IoU with the reference sample)",
        intersection / union if union else 0.0,
        1.0,
        1e-9,
    )
    delivered = read_raster(difference_path)
    oracle.close("delivered difference at a stable-field pixel", float(np.ma.getdata(delivered)[20, 20]), 0.0, 1e-6)
    oracle.close("delivered difference at a clearing pixel", float(np.ma.getdata(delivered)[4, 4]), -0.5, 1e-6)
    for row, col in cloud_positions:
        oracle.require(
            f"SCL-flagged pixel ({row},{col}) is nodata in the difference",
            bool(np.ma.getmaskarray(delivered)[row, col]),
            "masked" if np.ma.getmaskarray(delivered)[row, col] else "valid",
            "masked",
        )
    temporal_status = results_for(steps, "rs.temporal_scope")
    cloud_status = results_for(steps, "rs.cloud_mask_applied")
    nodata_status = results_for(steps, "raster.nodata_declared")
    oracle.require(
        "rs.temporal_scope fails on the April Item outside the June-August window",
        bool(temporal_status) and temporal_status[0].status == "fail",
        temporal_status[0].status if temporal_status else None,
        "fail",
    )
    oracle.require(
        "rs.cloud_mask_applied passes on the masked difference",
        bool(cloud_status) and cloud_status[0].status == "pass",
        cloud_status[0].status if cloud_status else None,
        "pass",
    )
    oracle.require(
        "raster.nodata_declared passes on the difference",
        bool(nodata_status) and nodata_status[0].status == "pass",
        nodata_status[0].status if nodata_status else None,
        "pass",
    )
    correct_control = correct(
        "anniversary-difference",
        "July 2023 and July 2024 NDVI differenced on the intersection of both valid masks with the 2024 "
        "SCL cloud/shadow classes as nodata; the April 2023 Item is flagged as out of window.",
        steps,
        oracle,
    )

    spurious = july_2024_values - april_values
    for row, col in cloud_positions:
        spurious[row, col] = np.nan
    spurious_path = _write_ndvi(root / "difference_april_2024.tif", spurious)
    wrong_steps = [
        check_step(
            "run_checks([april-item, july-2023-item, july-2024-item], time_range=('2023-06-01','2023-08-31'))",
            [april_item, july_2023_item, july_2024_item],
            time_range=("2023-06-01T00:00:00Z", "2023-08-31T23:59:59Z"),
        ),
        check_step(
            "run_checks(['difference_april_2024.tif'], qa_path='scl_2024.tif', qa_kind='s2-scl')",
            [spurious_path],
            qa_path=scl_path,
            qa_kind="s2-scl",
        ),
    ]
    wrong_oracle = Oracle("a spring-to-summer difference is phenology, not vegetation loss")
    wrong_values = read_raster(spurious_path)
    wrong_oracle.close(
        "stable-field difference is near zero under anniversary matching",
        float(np.ma.getdata(wrong_values)[20, 20]),
        0.0,
        0.05,
    )
    wrong_oracle.require(
        "stable fields are not flagged as loss by the local threshold",
        float(np.ma.getdata(wrong_values)[20, 20]) > threshold,
        float(np.ma.getdata(wrong_values)[20, 20]),
        f"> {threshold}",
    )
    wrong_control = wrong(
        "spring-to-summer-difference",
        "The April 2023 scene is differenced against July 2024, so crop phenology appears as vegetation loss.",
        wrong_steps,
        wrong_oracle,
    )

    unmasked = np.array(np.ma.getdata(read_raster(difference_path)))
    for row, col in cloud_positions:
        unmasked[row, col] = 0.0
    unmasked_path = _write_ndvi(root / "difference_unmasked.tif", unmasked)
    unmasked_steps = [
        check_step(
            "run_checks(['difference_unmasked.tif'], qa_path='scl_2024.tif', qa_kind='s2-scl')",
            [unmasked_path],
            qa_path=scl_path,
            qa_kind="s2-scl",
        ),
    ]
    unmasked_oracle = Oracle("cloud and shadow pixels must not survive in the difference")
    unmasked_values = read_raster(unmasked_path)
    unmasked_oracle.require(
        "SCL-flagged pixels are nodata in the difference",
        all(bool(np.ma.getmaskarray(unmasked_values)[row, col]) for row, col in cloud_positions),
        "some flagged pixels keep values",
        "all flagged pixels masked",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "clouds-not-masked",
            "The difference keeps values at SCL cloud and shadow pixels; rs.cloud_mask_applied fails.",
            unmasked_steps,
            unmasked_oracle,
        ),
    ]
    return recipe(
        "ts-phenology-matched-difference",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.temporal_scope on the supplied Items, rs.cloud_mask_applied and raster.nodata_declared on the difference",
            "independent anniversary vs spring-to-summer differences, cloud masking and a threshold derived from the reference sample",
        ],
        remaining=[
            "The answer must explain that signal change is not cause and that the change map still needs a stratified accuracy assessment; prose is not graded.",
            "Review of the locally derived threshold and sensitivity on the real scene pair.",
        ],
    )


def ts_change_accuracy(root: Path):
    """Task 3: a change map assessed with a stratified sample and area-adjusted estimates."""
    change_classes = ["loss", "gain", "stable_forest", "stable_nonforest"]
    matrix = {
        "loss": {"loss": 52, "gain": 1, "stable_forest": 4, "stable_nonforest": 3},
        "gain": {"loss": 1, "gain": 48, "stable_forest": 3, "stable_nonforest": 3},
        "stable_forest": {"loss": 5, "gain": 2, "stable_forest": 90, "stable_nonforest": 8},
        "stable_nonforest": {"loss": 6, "gain": 3, "stable_forest": 9, "stable_nonforest": 102},
    }
    areas = {"loss": 500.0, "gain": 300.0, "stable_forest": 20_000.0, "stable_nonforest": 40_000.0}
    total = sum(areas.values())
    weights = {name: areas[name] / total for name in change_classes}
    sample = weighted_sample_csv(root / "change_sample.csv", matrix, change_classes, weights)

    shape = (16, 16)
    change_map = np.full(shape, 4, dtype="uint8")
    change_map[:3, :3] = 1
    change_map[:3, 4:7] = 2
    change_map[8:14, :] = 3
    change_map[0, 0] = 0
    map_path = write_raster(root / "change_map.tif", change_map, crs=EQUAL_AREA, nodata=0, dtype="uint8")

    from terraproof.checks.accuracy import read_samples

    steps = [
        check_step("check change_map.tif", [map_path]),
        check_step(
            "run_checks(accuracy_samples='change_sample.csv', class_areas=ha, estimates_requested=True)",
            [],
            accuracy_samples=read_samples(sample),
            class_areas=areas,
            estimates_requested=True,
        ),
    ]
    estimates = olofsson_estimates(matrix, areas)
    oracle = Oracle("change-map stratified sample, area-adjusted loss/gain and 95% intervals")
    for name in ("loss", "gain"):
        oracle.close(f"{name} area-adjusted area (ha)", estimates["area"][name], estimates["area"][name], 1e-9)
    oracle.differs_by(
        "area-adjusted loss differs from the mapped pixel-count area",
        estimates["area"]["loss"],
        areas["loss"],
        50.0,
    )
    oracle.require(
        "every change stratum has reference units and a mapped-area weight",
        all(sum(matrix[name].values()) >= 50 for name in change_classes)
        and all(weights[name] > 0 for name in change_classes),
        {name: sum(matrix[name].values()) for name in change_classes},
        ">= 50 units per stratum with non-zero weights",
    )
    estimate_results = results_for(steps, "accuracy.estimates")
    oracle.require(
        "accuracy.estimates reports a result with per-class areas",
        bool(estimate_results) and bool(estimate_results[0].evidence.get("area_estimated")),
        "missing" if not estimate_results else sorted(estimate_results[0].evidence.get("area_estimated", {})),
        "area estimates present",
    )
    if estimate_results and estimate_results[0].evidence.get("area_estimated"):
        reported_loss = estimate_results[0].evidence["area_estimated"]["loss"]
        oracle.close(
            "check-reported loss area matches the independent estimator (ha)",
            reported_loss,
            estimates["area"]["loss"],
            1e-6,
        )
    oracle.require(
        "accuracy.sample_design passes on the stratified sample",
        bool(results_for(steps, "accuracy.sample_design")) and results_for(steps, "accuracy.sample_design")[0].status == "pass",
        [result.status for result in results_for(steps, "accuracy.sample_design")],
        "pass",
    )
    correct_control = correct(
        "change-map-stratified-assessment",
        "A change map in an equal-area CRS with rare loss/gain classes, a stratified reference sample with "
        "mapped-area weights and the corrected area estimates.",
        steps,
        oracle,
    )

    from terraproof.checks.accuracy import read_samples as read_samples_map

    wrong_steps = [
        check_step("check change_map.tif", [map_path]),
        check_step(
            "run_checks(accuracy_samples='change_sample.csv') with no mapped class areas",
            [],
            accuracy_samples=read_samples_map(sample),
            estimates_requested=True,
        ),
    ]
    wrong_oracle = Oracle("single-date accuracies and mapped pixel counts are not change accuracy")
    wrong_estimate = results_for(wrong_steps, "accuracy.estimates")
    wrong_oracle.require(
        "a stratified area-adjusted estimate is available",
        bool(wrong_estimate and wrong_estimate[0].evidence.get("area_estimated")),
        bool(wrong_estimate and wrong_estimate[0].evidence.get("area_estimated")),
        True,
    )
    wrong_oracle.require(
        "the corrected loss area is not the mapped 500 ha",
        abs(estimates["area"]["loss"] - areas["loss"]) > 50.0,
        round(estimates["area"]["loss"], 3),
        "differs from 500 ha",
    )
    wrong_control = wrong(
        "mapped-pixel-count-area",
        "No class areas or area estimator are supplied, so the mapped pixel-count area is reported as the "
        "deforestation area and no confidence interval exists.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "ts-post-classification-change-validation",
        correct_control,
        [wrong_control],
        automated_scope=[
            "raster.nodata_declared and crs.defined on the change map, accuracy.sample_design and accuracy.estimates on the sample",
            "independent stratified estimator for loss/gain areas, 95% intervals and the mapped-vs-corrected difference",
        ],
        remaining=[
            "The answer must explain why single-date accuracies do not describe change accuracy and report the area-proportion matrix; prose is not graded.",
            "Review of the change sample drawn from the change-map strata on reference imagery.",
        ],
    )


RECIPES = {
    "ts-monthly-ndvi-composite-counts": ts_monthly_composite,
    "ts-phenology-matched-difference": ts_phenology_difference,
    "ts-post-classification-change-validation": ts_change_accuracy,
}
