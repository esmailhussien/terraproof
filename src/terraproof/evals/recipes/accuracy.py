"""Fixtures and oracles for the `accuracy-assessment` task specs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyproj
import shapely

from terraproof.evals.fixtures import EQUAL_AREA, UTM, write_raster, write_vector
from terraproof.evals.harness import Step
from terraproof.evals.oracles import Oracle, olofsson_estimates
from terraproof.evals.recipes._util import (
    check_step,
    correct,
    recipe,
    results_for,
    sample_csv,
    weighted_sample_csv,
    wrong,
)

# Olofsson et al. (2014), Table 8: four change classes, mapped pixel counts and the
# stratified random sample's map-by-reference counts. The constants below are the
# published values, kept here as the independent ground truth for the oracle.
CHANGE_CLASSES = ["deforestation", "forest_gain", "stable_forest", "stable_nonforest"]
PUBLISHED_MATRIX = {
    "deforestation": {"deforestation": 66, "forest_gain": 0, "stable_forest": 5, "stable_nonforest": 4},
    "forest_gain": {"deforestation": 0, "forest_gain": 55, "stable_forest": 8, "stable_nonforest": 12},
    "stable_forest": {"deforestation": 1, "forest_gain": 0, "stable_forest": 153, "stable_nonforest": 11},
    "stable_nonforest": {"deforestation": 2, "forest_gain": 1, "stable_forest": 9, "stable_nonforest": 313},
}
MAPPED_PIXELS = {
    "deforestation": 200_000,
    "forest_gain": 150_000,
    "stable_forest": 3_200_000,
    "stable_nonforest": 6_450_000,
}
PIXEL_AREA_M2 = 30 * 30
CLASS_AREAS_HA = {name: pixels * PIXEL_AREA_M2 / 10_000 for name, pixels in MAPPED_PIXELS.items()}
PUBLISHED = {
    "overall_accuracy": 0.947,
    "deforestation_user": 0.88,
    "deforestation_producer": 0.75,
    "deforestation_area_ha": 21_158.0,
    "deforestation_area_margin_ha": 6_158.0,
    "deforestation_mapped_ha": 18_000.0,
}


def _change_map(path: Path, classes: np.ndarray) -> str:
    return write_raster(
        path,
        classes,
        crs=EQUAL_AREA,
        origin=(0.0, 0.0),
        resolution=30.0,
        nodata=0,
        dtype="uint8",
        tiled=True,
        overviews=(2, 4),
    )


def _published_estimates(matrix: dict[str, dict[str, int]], areas: dict[str, float]) -> dict:
    return olofsson_estimates(matrix, areas)


def _accuracy_oracle(matrix: dict[str, dict[str, int]], areas: dict[str, float], steps: list[Step]) -> Oracle:
    oracle = Oracle("Olofsson et al. (2014) Table 8 stratified area-adjusted estimator")
    estimates = _published_estimates(matrix, areas)
    deforestation = "deforestation"
    oracle.close(
        "overall accuracy reproduces the published 0.947",
        estimates["overall_accuracy"],
        PUBLISHED["overall_accuracy"],
        0.005,
        note="independent stratified estimate from the published matrix and mapped counts",
    )
    oracle.close(
        "deforestation user's accuracy (66/75)",
        estimates["user_accuracy"][deforestation],
        PUBLISHED["deforestation_user"],
        0.005,
    )
    oracle.close(
        "deforestation area-adjusted producer's accuracy",
        estimates["producer_accuracy"][deforestation],
        PUBLISHED["deforestation_producer"],
        0.005,
    )
    oracle.close(
        "deforestation corrected area (ha)",
        estimates["area"][deforestation],
        PUBLISHED["deforestation_area_ha"],
        5.0,
    )
    oracle.close(
        "deforestation 95% CI half-width (ha, normal approximation)",
        estimates["area_margin_95"][deforestation],
        PUBLISHED["deforestation_area_margin_ha"],
        1.0,
        note="published table rounds this to 6,158 ha",
    )
    oracle.close(
        "mapped deforestation area (ha) is reported separately",
        CLASS_AREAS_HA[deforestation],
        PUBLISHED["deforestation_mapped_ha"],
        0.5,
    )
    oracle.differs_by(
        "corrected area differs from the mapped pixel-count area",
        estimates["area"][deforestation],
        CLASS_AREAS_HA[deforestation],
        1000.0,
    )

    estimate_results = results_for(steps, "accuracy.estimates")
    if not estimate_results:
        oracle.require("the accuracy.estimates check ran", False, None, "one result")
        return oracle
    evidence = estimate_results[0].evidence
    oracle.require(
        "the check reports an area-adjusted estimate per reference class",
        bool(evidence.get("area_estimated")),
        sorted(evidence.get("area_estimated", {})),
        "reference classes",
    )
    check_area = evidence.get("area_estimated", {}).get(deforestation)
    oracle.close(
        "check-reported corrected area matches the independent oracle (ha)",
        check_area if check_area is not None else float("nan"),
        estimates["area"][deforestation],
        1e-6,
    )
    oracle.require(
        "the check states the mapped area next to the corrected area",
        evidence.get("class_area_estimate", {}).get(deforestation, {}).get("mapped_area_in_strata")
        == CLASS_AREAS_HA[deforestation],
        evidence.get("class_area_estimate", {}).get(deforestation, {}).get("mapped_area_in_strata"),
        CLASS_AREAS_HA[deforestation],
    )
    return oracle


def accuracy_stratified_area(root: Path):
    """Task 1: the published Olofsson example must reproduce the independent estimates."""
    sample = sample_csv(root / "samples.csv", PUBLISHED_MATRIX, CHANGE_CLASSES)
    classes = np.zeros((40, 40), dtype="uint8")
    classes[:, :] = 4
    classes[:4, :4] = 1
    classes[:3, 4:8] = 2
    classes[8:20, :20] = 3
    change_map = _change_map(root / "change_map.tif", classes)

    steps = [
        check_step("check change_map.tif --operation area", [change_map], operation="area"),
        check_step(
            "run_checks(accuracy_samples='samples.csv', class_areas=ha)",
            [],
            accuracy_samples=_read_samples(sample),
            class_areas=CLASS_AREAS_HA,
            estimates_requested=True,
        ),
    ]
    correct_control = correct(
        "published-stratified-estimator",
        "Sample CSV and mapped class areas from Olofsson et al. (2014) Table 8, with the change map "
        "in a projected metre CRS.",
        steps,
        _accuracy_oracle(PUBLISHED_MATRIX, CLASS_AREAS_HA, steps),
    )

    wrong_steps = [
        check_step("check change_map.tif --operation area", [change_map], operation="area"),
        check_step(
            "run_checks(accuracy_samples='samples.csv') with no mapped class areas",
            [],
            accuracy_samples=_read_samples(sample),
            estimates_requested=True,
        ),
    ]
    wrong_control = wrong(
        "mapped-pixel-area-shortcut",
        "Accuracies come from the raw stratified counts and the mapped pixel counts are reported as the "
        "deforestation area; no class areas or area estimator are supplied.",
        wrong_steps,
        _raw_count_oracle(wrong_steps),
        notes="The area-adjusted estimate is unavailable, so the reported 18,000 ha cannot be the corrected area.",
    )
    return recipe(
        "accuracy-stratified-area-olofsson-example",
        correct_control,
        [wrong_control],
        automated_scope=[
            "accuracy.sample_design and accuracy.estimates statuses on the generated sample and mapped areas",
            "independent stratified recomputation of overall/user's/producer's accuracy, corrected area and 95% CI",
            "crs.metric_operation and raster.nodata_declared on the generated change map",
        ],
        remaining=[
            "The written report must show the error matrix in proportion of area and state the normal-approximation CI and kappa caveat; the harness reads numbers, not the answer text.",
            "Scientific review that the stratified sample design is the documented one for the study area.",
        ],
    )


def _read_samples(path: str) -> dict:
    from terraproof.checks.accuracy import read_samples

    return read_samples(path)


def _raw_count_oracle(steps: list[Step]) -> Oracle:
    """Oracle for the raw-count shortcut: the corrected area must still be reported as 21,158 ha."""
    oracle = Oracle("area-adjusted acceptance still requires the corrected deforestation area")
    estimate_results = results_for(steps, "accuracy.estimates")
    available = bool(estimate_results and estimate_results[0].evidence.get("area_estimated"))
    oracle.require(
        "a stratified area-adjusted estimate is available",
        available,
        available,
        True,
        note="raw counts and mapped pixel counts alone do not produce the corrected area",
    )
    reported = (
        estimate_results[0].evidence.get("area_estimated", {}).get("deforestation")
        if available
        else None
    )
    oracle.close(
        "deforestation corrected area (ha)",
        reported if reported is not None else float("nan"),
        PUBLISHED["deforestation_area_ha"],
        5.0,
    )
    oracle.require(
        "the mapped 18,000 ha is not presented as the corrected area",
        reported is not None and abs(reported - PUBLISHED["deforestation_mapped_ha"]) > 1000.0,
        reported,
        "differs from 18,000 ha",
    )
    return oracle


def accuracy_training_points(root: Path):
    """Task 2: convenience training points are not an accuracy sample."""
    map_classes = ["bare", "forest", "urban", "water", "wetland"]
    counts = {"bare": 35, "forest": 40, "urban": 30, "water": 25}
    matrix = {
        "bare": {"bare": 28, "urban": 5, "water": 2},
        "forest": {"forest": 30, "bare": 6, "urban": 4},
        "urban": {"urban": 24, "bare": 6},
        "water": {"water": 20, "bare": 3, "urban": 2},
    }
    sample = sample_csv(root / "training_points.csv", matrix, ["bare", "forest", "urban", "water"])
    xs = np.linspace(500010.0, 500600.0, 130)
    ys = np.linspace(5000010.0, 5005000.0, 130)
    points = [shapely.Point(float(x), float(y)) for x, y in zip(xs, ys)]
    training = write_vector(
        root / "training_points.gpkg",
        points,
        crs=UTM,
        geometry_type="Point",
        fields=["pid"],
        field_data=[np.arange(130)],
    )

    steps = [
        check_step("check training_points.gpkg", [training]),
        check_step(
            "run_checks(accuracy_samples='training_points.csv', min_per_class=50)",
            [],
            accuracy_samples=_read_samples(sample),
            min_per_class=50,
        ),
    ]
    oracle = Oracle("the supplied training points cannot support an accuracy statement")
    oracle.equal("map classes in the map", len(map_classes), 5)
    oracle.equal("map classes present in the training sample", sorted(matrix), sorted(counts))
    oracle.equal(
        "wetland reference units in the sample",
        sum(1 for row in matrix.values() for ref in row if ref == "wetland"),
        0,
    )
    oracle.require(
        "at least one map class has fewer than 50 reference samples",
        any(value < 50 for value in counts.values()),
        counts,
        "per-class counts >= 50 for a design-based statement",
    )
    oracle.require(
        "no stratum weights or inclusion probabilities are recorded",
        not _has_weight_column(root / "training_points.csv"),
        "no stratum_weight column",
        "design information present",
    )
    results = results_for(steps, "accuracy.sample_design")
    oracle.require(
        "accuracy.sample_design reports the failure",
        bool(results) and results[0].status == "fail",
        results[0].status if results else None,
        "fail",
    )
    correct_control = correct(
        "convenience-training-points",
        "A five-class map with an under-sampled rare wetland class and four classes of training points.",
        steps,
        oracle,
    )

    wrong_steps = [
        check_step("check training_points.gpkg", [training]),
        check_step(
            "run_checks(accuracy_samples='training_points.csv', min_per_class=10)",
            [],
            accuracy_samples=_read_samples(sample),
            min_per_class=10,
        ),
    ]
    wrong_oracle = Oracle("lowering the sample minimum does not make training points a probability sample")
    wrong_oracle.equal(
        "wetland reference units in the sample",
        sum(1 for row in matrix.values() for ref in row if ref == "wetland"),
        0,
    )
    wrong_oracle.require(
        "the rare map class is represented",
        False,
        "wetland absent",
        "every map class present",
    )
    wrong_oracle.require(
        "stratum weights from the map are recorded",
        False,
        "no weights",
        "weights present",
    )
    wrong_control = wrong(
        "relaxed-minimum-acceptance",
        "The same convenience points are accepted as an accuracy sample by lowering min_per_class to 10.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "accuracy-training-points-missing-stratum",
        correct_control,
        [wrong_control],
        automated_scope=[
            "accuracy.sample_design detects the under-sampled classes in the supplied training points",
            "geometry.valid and geometry.non_empty on the generated point layer",
            "independent confirmation that the rare wetland class has no reference units",
        ],
        remaining=[
            "The answer must explain unknown inclusion probabilities and propose a stratified random design with allocation, seed and response design; the harness does not grade prose.",
            "Expert review of the proposed design for the study area.",
        ],
    )


def _has_weight_column(path: Path) -> bool:
    header = path.read_text(encoding="utf-8").splitlines()[0]
    return "stratum_weight" in header.split(",")


def accuracy_response_design(root: Path):
    """Task 3: a delivered validation sample with documented strata and area weights."""
    strata = ["loss", "gain", "stable"]
    matrix = {
        "loss": {"loss": 54, "gain": 2, "stable": 4},
        "gain": {"loss": 1, "gain": 50, "stable": 4},
        "stable": {"loss": 6, "gain": 4, "stable": 110},
    }
    areas = {"loss": 4_000.0, "gain": 2_500.0, "stable": 120_000.0}
    total = sum(areas.values())
    weights = {name: areas[name] / total for name in strata}
    sample = weighted_sample_csv(root / "validation_sample.csv", matrix, strata, weights)

    coordinates = [
        (500000.0 + 37.0 * index, 5000000.0 + 23.0 * index) for index in range(235)
    ]
    labels = (
        ["loss"] * 60 + ["gain"] * 55 + ["stable"] * 120
    )
    points = [shapely.Point(x, y) for x, y in coordinates]
    delivered = write_vector(
        root / "validation_sample.gpkg",
        points,
        crs=EQUAL_AREA,
        geometry_type="Point",
        fields=["unit_id", "stratum"],
        field_data=[np.arange(235), np.asarray(labels, dtype=object)],
    )
    planned = write_vector(
        root / "planned_sample.gpkg",
        points,
        crs=EQUAL_AREA,
        geometry_type="Point",
        fields=["unit_id", "stratum"],
        field_data=[np.arange(235), np.asarray(labels, dtype=object)],
    )

    steps = [
        check_step(
            "check validation_sample.gpkg --compare-to planned_sample.gpkg",
            [delivered],
            compare_to=planned,
        ),
        check_step(
            "run_checks(accuracy_samples='validation_sample.csv', class_areas=ha, estimates_requested=True)",
            [],
            accuracy_samples=_read_samples(sample),
            class_areas=areas,
            estimates_requested=True,
        ),
    ]
    oracle = Oracle("delivered stratified sample: strata coverage, allocation and mapped-area weights")
    oracle.equal("point records delivered", 235, 235)
    oracle.equal("unique sample unit ids", 235, 235)
    oracle.equal("map classes with reference units", sorted(matrix), sorted(strata))
    oracle.require(
        "every stratum meets the 50-unit minimum",
        all(sum(row.values()) >= 50 for row in matrix.values()),
        {name: sum(row.values()) for name, row in matrix.items()},
        ">= 50 units per stratum",
    )
    oracle.equal("the sample carries stratum weights", _csv_header(root / "validation_sample.csv"), [
        "map_class",
        "ref_class",
        "stratum_weight",
    ])
    weight_rows = (root / "validation_sample.csv").read_text(encoding="utf-8").splitlines()[1:]
    recorded = {}
    for line in weight_rows:
        map_class, _ref, weight = line.split(",")
        recorded[map_class] = float(weight)
    for name in strata:
        oracle.close(
            f"{name} stratum weight equals its mapped-area share",
            recorded.get(name, float("nan")),
            weights[name],
            1e-5,
        )
    crs = pyproj.CRS.from_epsg(6933)
    oracle.require(
        "the delivered layer is in a projected metre CRS",
        crs.is_projected and crs.axis_info[0].unit_name in ("metre", "meter"),
        crs.axis_info[0].unit_name,
        "metre",
    )
    correct_control = correct(
        "documented-stratified-sample",
        "235 points, one per sample unit, drawn by change-map stratum with mapped-area weights and a "
        "planned-sample record count.",
        steps,
        oracle,
    )

    tiny_matrix = {
        "loss": {"loss": 12},
        "gain": {"gain": 54, "stable": 4},
        "stable": {"stable": 117, "loss": 3},
    }
    tiny_sample = weighted_sample_csv(root / "validation_sample_tiny_loss.csv", tiny_matrix, strata, weights)
    tiny_points = points[:190]
    tiny = write_vector(
        root / "validation_sample_tiny_loss.gpkg",
        tiny_points,
        crs=EQUAL_AREA,
        geometry_type="Point",
        fields=["unit_id", "stratum"],
        field_data=[np.arange(190), np.asarray(["loss"] * 12 + ["gain"] * 58 + ["stable"] * 120, dtype=object)],
    )
    wrong_steps = [
        check_step("check validation_sample_tiny_loss.gpkg --compare-to planned_sample.gpkg", [tiny], compare_to=planned),
        check_step(
            "run_checks(accuracy_samples='validation_sample_tiny_loss.csv', class_areas=ha)",
            [],
            accuracy_samples=_read_samples(tiny_sample),
            class_areas=areas,
            estimates_requested=True,
        ),
    ]
    wrong_oracle = Oracle("the delivered sample must give the rare loss stratum enough units")
    wrong_oracle.require(
        "the loss stratum meets the 50-unit minimum",
        sum(tiny_matrix["loss"].values()) >= 50,
        sum(tiny_matrix["loss"].values()),
        ">= 50 units",
    )
    wrong_oracle.require(
        "the delivered layer keeps the planned sample size",
        190 == 235,
        190,
        235,
    )
    wrong_control = wrong(
        "rare-stratum-underallocated",
        "Only 12 loss units are drawn and the delivered layer holds 190 of the 235 planned units.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "accuracy-response-design-change-sample",
        correct_control,
        [wrong_control],
        automated_scope=[
            "geometry, CRS and scope.record_count on the delivered point layer",
            "accuracy.sample_design on the stratified sample and its mapped-area weights",
            "independent check that every change stratum meets the minimum allocation and carries its mapped-area weight",
        ],
        remaining=[
            "The response design (spatial unit, reference dates, mixed-pixel and agreement protocol, interpreter confidence) is a written deliverable; the harness cannot grade it.",
            "Review of the sample on reference imagery that covers both change dates.",
        ],
    )


def _csv_header(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()[0].split(",")


RECIPES = {
    "accuracy-stratified-area-olofsson-example": accuracy_stratified_area,
    "accuracy-training-points-missing-stratum": accuracy_training_points,
    "accuracy-response-design-change-sample": accuracy_response_design,
}
