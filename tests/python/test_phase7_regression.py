"""Phase 7 regression set: development seeded mistakes that declared arguments now catch.

Each case regenerates a Phase 6 development task (checkout-only fixtures), declares what a careful
user knows about its sources, and requires that the reference output keeps a clean grade while the
seeded mistake fails. These cases were used to build the checks, so they guard against regressions;
they do not measure the checks (the sealed V0 cases do that once, in V4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from terraproof.checks import run_checks
from terraproof.evidence.grade import ADVISORY, CHECKS_PASSED, grade_for
from terraproof.inspect import inspect_dataset

lift = pytest.importorskip("terraproof.evals.lift")

CASES = {
    "elevation-feet-ignored": ("hr-elevation-change-mixed-units", "units-ignored.tif", "raster.vertical_units", dict(
        vertical_operation="difference", vertical_sources=["dem_2023.tif", "dem_2015.tif"],
        vertical_source_units=["metre", "foot"], vertical_unit="metre")),
    "elevation-change-in-feet": ("hr-elevation-change-mixed-units", "change-in-feet.tif", "raster.vertical_units", dict(
        vertical_operation="difference", vertical_sources=["dem_2023.tif", "dem_2015.tif"],
        vertical_source_units=["metre", "foot"], vertical_unit="metre")),
    "landsat-fill-decoded": ("hr-landsat-undeclared-fill", "fill-decoded.tif", "raster.nodata_support", dict(
        support_sources=["red.tif"], support_source_nodata=[0], support_rule="all")),
    "modis-fill-as-value": ("hr-modis-ndvi-scaled", "fill-as-value.tif", "raster.nodata_support", dict(
        support_sources=["ndvi.tif"], support_rule="all")),
    "modis-unscaled": ("hr-modis-ndvi-scaled", "unscaled.tif", "rs.scale_applied_once", dict(
        reference_input="ndvi.tif")),
    "rain-dry-as-missing": ("hr-rainfall-dry-days", "dry-as-missing.tif", "rs.stack_reduction", dict(
        stack=["rain_day1.tif", "rain_day2.tif", "rain_day3.tif"], stack_reduction="weighted-sum",
        stack_weights=[1 / 3, 1 / 3, 1 / 3])),
}


def _declare(root: Path, arguments: dict) -> dict:
    declared = {}
    for key, value in arguments.items():
        if key in ("vertical_sources", "support_sources", "stack"):
            value = [inspect_dataset(str(root / name)) for name in value]
        elif key == "reference_input":
            value = inspect_dataset(str(root / value))
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
    task_id, wrong, check_id, arguments = CASES[case]
    root = generated[task_id]
    declared = _declare(root, arguments)
    reference = run_checks([inspect_dataset(str(root / "result.tif"))], **declared)
    assert grade_for(reference) == CHECKS_PASSED, [(r.id, r.status) for r in reference if r.status != "pass"]
    mistake = run_checks([inspect_dataset(str(root / wrong))], **declared)
    assert grade_for(mistake) == ADVISORY
    assert any(r.id == check_id and r.status == "fail" for r in mistake)
