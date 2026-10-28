"""Phase 7 regression set: seeded mistakes from Phase 6 tasks that declared arguments now catch.

Each case regenerates a Phase 6 headroom task (checkout-only fixtures), declares what a careful user
knows about its sources, and requires that the reference output keeps its expected grade while the
seeded mistake fails the named check. These cases, and the Phase 6 live failures behind them, were
used to build the checks, so they guard against regressions; they do not measure the checks (the
sealed V0 cases do that once, in V4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from terraproof.checks import run_checks
from terraproof.evidence.grade import ADVISORY, CHECKS_PASSED, REVIEW, grade_for
from terraproof.inspect import inspect_dataset

lift = pytest.importorskip("terraproof.evals.lift")

ELEVATION = dict(vertical_operation="difference", vertical_sources=["dem_2023.tif", "dem_2015.tif"],
                 vertical_source_units=["metre", "foot"], vertical_unit="metre")
FLOOD = dict(vertical_operation="depth-below-level", vertical_sources=["dem.tif"], vertical_source_units=["foot"],
             vertical_unit="metre", vertical_level=12.0)
MODIS_QUALITY = dict(qa_path="QC_Day.tif", qa_kind="keep-codes", qa_keep_codes=[0], processing_full_scan=True)
REANALYSIS = dict(reference_input="t2m.tif", unit_conversion="kelvin-to-celsius")
HLS = dict(reference_input="B8A.tif", decode_scale=0.0001, decode_offset=0.0)
SCL = dict(qa_path="SCL.tif", qa_kind="s2-scl", processing_full_scan=True)
QA_PIXEL = dict(qa_path="qa_pixel.tif", qa_kind="landsat-qa-pixel", processing_full_scan=True)
LANDCOVER_CHANGE = dict(support_sources=["landcover_2019.tif", "landcover_2023.tif"], support_source_nodata=[0, 0],
                        support_rule="all")
THIRDS = [1 / 3, 1 / 3, 1 / 3]

# case -> (task, seeded file, check that must fail, declared arguments, grade the reference keeps)
CASES = {
    "elevation-feet-ignored": ("hr-elevation-change-mixed-units", "units-ignored.tif", "raster.vertical_units",
                               ELEVATION, CHECKS_PASSED),
    "elevation-change-in-feet": ("hr-elevation-change-mixed-units", "change-in-feet.tif", "raster.vertical_units",
                                 ELEVATION, CHECKS_PASSED),
    "flood-feet-as-metres": ("hr-flood-depth-feet", "feet-as-metres.tif", "raster.vertical_units", FLOOD,
                             CHECKS_PASSED),
    "flood-depth-in-feet": ("hr-flood-depth-feet", "depth-in-feet.tif", "raster.vertical_units", FLOOD,
                            CHECKS_PASSED),
    "landsat-fill-decoded": ("hr-landsat-undeclared-fill", "fill-decoded.tif", "raster.nodata_support", dict(
        support_sources=["red.tif"], support_source_nodata=[0], support_rule="all"), CHECKS_PASSED),
    "landcover-fill-as-class": ("hr-landcover-change-fill", "fill-as-class.tif", "raster.nodata_support",
                                LANDCOVER_CHANGE, CHECKS_PASSED),
    "modis-fill-as-value": ("hr-modis-ndvi-scaled", "fill-as-value.tif", "raster.nodata_support", dict(
        support_sources=["ndvi.tif"], support_rule="all"), CHECKS_PASSED),
    "modis-unscaled": ("hr-modis-ndvi-scaled", "unscaled.tif", "rs.scale_applied_once", dict(
        reference_input="ndvi.tif"), CHECKS_PASSED),
    "hls-unscaled": ("hr-hls-nir-reflectance", "unscaled.tif", "rs.scale_applied_once", HLS, CHECKS_PASSED),
    "hls-s2-offset": ("hr-hls-nir-reflectance", "s2-offset-applied.tif", "rs.scale_applied_once", HLS, CHECKS_PASSED),
    "reanalysis-kelvin": ("hr-reanalysis-air-temperature", "kelvin.tif", "rs.scale_applied_once", REANALYSIS,
                          CHECKS_PASSED),
    "reanalysis-packed": ("hr-reanalysis-air-temperature", "packed-values.tif", "rs.scale_applied_once", REANALYSIS,
                          CHECKS_PASSED),
    "lst-kelvin": ("hr-modis-lst-quality", "kelvin.tif", "rs.scale_applied_once", dict(
        reference_input="LST_Day_1km.tif", unit_conversion="kelvin-to-celsius"), CHECKS_PASSED),
    "lst-mandatory-only": ("hr-modis-lst-quality", "mandatory-only.tif", "rs.cloud_mask_applied", MODIS_QUALITY,
                           CHECKS_PASSED),
    "lst-error-only": ("hr-modis-lst-quality", "lst-error-only.tif", "rs.cloud_mask_applied", MODIS_QUALITY,
                       CHECKS_PASSED),
    "scl-clouds-only": ("hr-s2-scl-red", "clouds-only.tif", "rs.cloud_mask_applied", SCL, CHECKS_PASSED),
    "qa-pixel-clear-bit-only": ("hr-landsat-clear-red", "clear-bit-only.tif", "rs.cloud_mask_applied", QA_PIXEL,
                                CHECKS_PASSED),
    "radsat-off-by-one-bit": ("hr-landsat-red-saturation", "off-by-one-bit.tif", "rs.cloud_mask_applied", dict(
        qa_path="qa_radsat.tif", qa_kind="keep-codes", qa_keep_codes=[0, 4, 16], processing_full_scan=True),
        CHECKS_PASSED),
    "slope-degrees-as-metres": ("hr-slope-geographic", "degrees-as-metres.tif", "terrain.slope_consistent", dict(
        dem="dem.tif"), REVIEW),  # the reference uses another stencil, which warns
    "slope-no-latitude-scaling": ("hr-slope-geographic", "no-latitude-scaling.tif", "terrain.slope_consistent", dict(
        dem="dem.tif"), REVIEW),
    "rain-dry-as-missing": ("hr-rainfall-dry-days", "dry-as-missing.tif", "rs.stack_reduction", dict(
        stack=["rain_day1.tif", "rain_day2.tif", "rain_day3.tif"], stack_reduction="weighted-sum",
        stack_weights=THIRDS), CHECKS_PASSED),
    "brightness-uint8-sum": ("hr-three-date-mean-8bit", "uint8-sum.tif", "rs.stack_reduction", dict(
        stack=["brightness_1.tif", "brightness_2.tif", "brightness_3.tif"], stack_reduction="weighted-sum",
        stack_weights=THIRDS), CHECKS_PASSED),
    "sar-linear-delivered": ("hr-sar-boxcar-db", "linear-power-delivered.tif", "sar.value_domain", dict(
        sar_expect="sigma0-db"), CHECKS_PASSED),
}


def _declare(root: Path, arguments: dict) -> dict:
    declared = {}
    for key, value in arguments.items():
        if key in ("vertical_sources", "support_sources", "stack"):
            value = [inspect_dataset(str(root / name)) for name in value]
        elif key in ("reference_input", "dem"):
            value = inspect_dataset(str(root / value))
        elif key == "qa_path":
            value = str(root / value)
        declared[key] = value
    return declared


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase7-regression")
    tasks = {}
    for task_id, *_ in CASES.values():
        if task_id not in tasks:
            tasks[task_id] = root / task_id
            lift._generate(lift.lift_task(task_id), tasks[task_id])
    return tasks


@pytest.mark.parametrize("case", sorted(CASES))
def test_declared_arguments_catch_the_seeded_mistake_and_keep_the_reference(generated, case):
    task_id, wrong, check_id, arguments, reference_grade = CASES[case]
    root = generated[task_id]
    declared = _declare(root, arguments)
    reference = run_checks([inspect_dataset(str(root / "result.tif"))], **declared)
    assert grade_for(reference) == reference_grade, [(r.id, r.status) for r in reference if r.status != "pass"]
    mistake = run_checks([inspect_dataset(str(root / wrong))], **declared)
    assert grade_for(mistake) == ADVISORY
    assert any(r.id == check_id and r.status == "fail" for r in mistake)
