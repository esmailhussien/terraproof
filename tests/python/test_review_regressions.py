"""Regressions for the independent v0.5.0 review (Codex hand-off, 2026-10-24), one test per finding."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

from terraproof.checks import run_checks
from terraproof.evals import lift
from terraproof.inspect import inspect_dataset


def _score(tmp_path, task_id, write_output):
    """Generate a task's reference, write a deliverable from it, and grade it like an agent's file."""
    task = lift.lift_task(task_id)
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    write_output(reference, outputs)
    digests = {name: lift._digest(reference / name) for name in task.inputs}
    return lift.score_outputs(task, lift._specs()[task.task_id], outputs, tmp_path / "scoring", digests)


def _samples(*groups):
    records = []
    for map_class, ref_class, count in groups:
        records += [dict(map_class=map_class, ref_class=ref_class, stratum_weight=None)] * count
    return dict(path="samples.csv", records=records, has_weights=False)


def _by_id(results):
    return {result.id: result for result in results}


def test_f1_subtraction_oracle_reads_the_delivered_pixels(tmp_path):
    def all_zero_with_correct_mask(reference, outputs):
        with rasterio.open(reference / "difference.tif") as src:
            original, profile = src.read(1), src.profile
        wrong = np.zeros(original.shape, dtype=original.dtype)
        wrong[original == profile["nodata"]] = profile["nodata"]
        with rasterio.open(outputs / "difference.tif", "w", **profile) as dst:
            dst.write(wrong, 1)

    record = _score(tmp_path, "raster-nodata-dtype-windowing", all_zero_with_correct_mask)
    assert record["accepted"] is False and record["oracle_ok"] is False
    assert "every valid output pixel equals first minus second" in record["failed_assertions"]


def test_f2_grader_enforces_the_input_grid_contract(tmp_path):
    def right_values_wrong_grid(reference, outputs):
        with rasterio.open(reference / "ndvi.tif") as src:
            values, profile = src.read(1), src.profile
        profile.update(crs="EPSG:3857", transform=from_origin(0, 0, 1, 1))
        with rasterio.open(outputs / "ndvi.tif", "w", **profile) as dst:
            dst.write(values, 1)

    record = _score(tmp_path, "indices-ndvi-physical-inputs", right_values_wrong_grid)
    assert record["accepted"] is False and record["contract_ok"] is False
    assert "contract" in record["caught_by"]
    assert any("CRS" in failure for failure in record["contract_failures"])
    assert any("transform" in failure for failure in record["contract_failures"])


def test_f3_unsampled_mapped_stratum_blocks_design_and_estimates():
    results = _by_id(run_checks([], accuracy_samples=_samples(("A", "A", 50), ("B", "B", 50)),
                                class_areas={"A": 100, "B": 100, "C": 800}, estimates_requested=True))
    assert results["accuracy.sample_design"].status == "fail"
    assert results["accuracy.sample_design"].evidence["unsampled_strata"] == ["C"]
    assert results["accuracy.estimates"].status == "not-run"
    assert "overall_accuracy" not in results["accuracy.estimates"].evidence


def test_f4_grid_alignment_rejects_a_sheared_grid(tmp_path):
    paths = []
    for name, shear in (("north", 0), ("shear", 3)):
        path = tmp_path / f"{name}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=16, height=16, count=1, dtype="uint8",
                           crs="EPSG:32636", nodata=255, transform=Affine(10, shear, 500000, 0, -10, 5000000)) as dst:
            dst.write(np.ones((16, 16), dtype="uint8"), 1)
        paths.append(path)
    alignment = _by_id(run_checks([inspect_dataset(p) for p in paths]))["raster.grid_alignment"]
    assert alignment.status == "fail"
    assert any("rotation or shear" in problem for problem in alignment.evidence["problems"])


def test_f4_matching_rotated_grids_still_align(tmp_path):
    paths = []
    for name, origin in (("first", (500000, 5000000)), ("second", (500000 + 10 * 2 + 3 * 1, 5000000 - 10 * 1))):
        path = tmp_path / f"{name}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=16, height=16, count=1, dtype="uint8",
                           crs="EPSG:32636", nodata=255, transform=Affine(10, 3, origin[0], 0, -10, origin[1])) as dst:
            dst.write(np.ones((16, 16), dtype="uint8"), 1)
        paths.append(path)
    assert _by_id(run_checks([inspect_dataset(p) for p in paths]))["raster.grid_alignment"].status == "pass"


def test_f5_mde_never_exceeds_the_discordance():
    assert lift.mcnemar_mde(27, 6 / 27) is None  # the main run's observed discordance
    for pairs in (9, 27, 45, 90, 270):
        for discordance in (0.05, 0.1, 0.2, 0.3, 0.5, 1.0):
            value = lift.mcnemar_mde(pairs, discordance)
            assert value is None or value <= discordance + 1e-12


def test_f6_negative_class_area_is_rejected():
    results = _by_id(run_checks([], accuracy_samples=_samples(("A", "A", 50), ("B", "B", 50)),
                                class_areas={"A": 100, "B": -50}, estimates_requested=True))
    assert results["accuracy.estimates"].status == "not-run"
    assert results["accuracy.sample_design"].status == "not-run"
    assert "non-negative" in results["accuracy.estimates"].message


def test_f7_reference_only_class_has_zero_producer_accuracy():
    results = _by_id(run_checks([], accuracy_samples=_samples(("A", "A", 50), ("A", "C", 50)),
                                class_areas={"A": 100}, estimates_requested=True))
    estimates = results["accuracy.estimates"]
    assert estimates.status == "pass"
    assert estimates.evidence["producer_accuracy"]["C"] == 0.0
    assert estimates.evidence["overall_accuracy"] == pytest.approx(0.5)


def test_f8_reversed_stac_interval_is_not_in_window(tmp_path):
    item = tmp_path / "item.json"
    item.write_text(json.dumps({
        "type": "Feature", "stac_version": "1.0.0", "id": "reversed", "geometry": None, "assets": {},
        "properties": {"datetime": None, "start_datetime": "2025-01-01T00:00:00Z",
                       "end_datetime": "2023-01-01T00:00:00Z", "proj:epsg": 32636},
    }), encoding="utf-8")
    scope = _by_id(run_checks([inspect_dataset(item)], time_range=("2024-01-01", "2024-12-31")))["rs.temporal_scope"]
    assert scope.status != "pass"
    reasons = [entry["reason"] for entry in scope.evidence["items_without_time"]]
    assert "start_datetime is after end_datetime" in reasons


def _probe(reference, outputs, name, kind):
    """Overwrite one deliverable with a corrupted copy of the reference: zero, +1 or flip the valid pixels."""
    with rasterio.open(reference / name) as src:
        values, profile = src.read(1), src.profile
    nodata = profile.get("nodata")
    valid = np.ones(values.shape, bool) if nodata is None else values != nodata
    wrong = values.copy()
    if kind == "zeros":
        wrong[valid] = 0
    elif kind == "plus_one":
        wrong[valid] = wrong[valid] + 1
    else:
        wrong = wrong[::-1].copy()
    with rasterio.open(outputs / name, "w", **profile) as dst:
        dst.write(wrong, 1)


@pytest.mark.parametrize("task_id,name", [(task.task_id, name) for task in lift.LIFT_TASKS
                                          for name in task.deliverable_names])
@pytest.mark.parametrize("kind", ["zeros", "plus_one", "flipped_rows"])
def test_every_lift_deliverable_is_graded_from_the_delivered_file(tmp_path, task_id, name, kind):
    """No deliverable may be accepted after its valid pixels are zeroed, shifted by one, or flipped.

    This probe found sr_nir.tif (satellite-s2-baseline-offset-mask) ungraded and a row-flipped
    composite_counts.tif (satellite-seasonal-harmonized-composite) accepted.
    """
    task = lift.lift_task(task_id)

    def corrupt_one(reference, outputs):
        for other in task.deliverable_names:
            shutil.copyfile(reference / other, outputs / other)
        _probe(reference, outputs, name, kind)

    assert _score(tmp_path, task_id, corrupt_one)["accepted"] is False
