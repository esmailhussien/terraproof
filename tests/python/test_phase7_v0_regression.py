"""Phase 7: the V4 misses and false alarms on the spent V0 cases, kept as regression tests.

The V0 held-out cases were measured once (V4) and are now spent. These tests pin the fixes that
followed: delivered metric values instead of the output CRS, over-masking under a declared QA rule,
a declared DEM vertical unit, vertical datum shifts and fathoms. They guard against regressions and
do not measure the checks; the next measurement needs fresh sealed cases.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from terraproof.checks import run_checks
from terraproof.evidence.grade import ADVISORY, grade_for
from terraproof.inspect import inspect_dataset

ROOT = Path(__file__).resolve().parents[2]
HELDOUT = ROOT / "evals" / "verification-heldout"


@pytest.fixture(scope="module")
def v0(tmp_path_factory):
    out = tmp_path_factory.mktemp("v0")
    subprocess.run([sys.executable, "-I", str(HELDOUT / "generate.py"), str(out)], check=True, capture_output=True)
    document = json.loads((HELDOUT / "cases.json").read_text(encoding="utf-8"))
    cases = document["cases"] if isinstance(document, dict) else document
    return out, {case["id"]: case for case in cases}


def _run(v0, case_id, **arguments):
    base, cases = v0
    case = cases[case_id]
    resolved = {}
    for key, value in arguments.items():
        if key in ("vertical_sources",):
            value = [inspect_dataset(str(base / case["declared"][name])) for name in value]
        elif key in ("dem", "buffer_source"):
            value = inspect_dataset(str(base / case["declared"][value]))
        elif key in ("qa_path", "qa_source"):
            value = str(base / case["declared"][value])
        resolved[key] = value
    return run_checks([inspect_dataset(str(base / case["output"]))], **resolved)


def _status(results, check_id):
    return {r.status for r in results if r.id == check_id}


@pytest.mark.parametrize("case_id,quantity,expected", [
    ("heldout-geom-01-wrong", "area", "fail"), ("heldout-geom-05-correct", "area", "pass"),
    ("heldout-geom-03-wrong", "length", "fail"), ("heldout-geom-07-correct", "length", "pass"),
])
def test_delivered_area_and_length_are_checked_geodesically_in_any_crs(v0, case_id, quantity, expected):
    declared = v0[1][case_id]["declared"]
    results = _run(v0, case_id, metric_quantity=quantity, metric_property=declared["metric_property_name"],
                   metric_unit=declared["metric_unit"])
    assert _status(results, "geometry.metric_values") == {expected}


@pytest.mark.parametrize("case_id,expected", [("heldout-geom-02-wrong", "fail"), ("heldout-geom-06-correct", "pass")])
def test_buffers_are_checked_by_ground_distance(v0, case_id, expected):
    distance = v0[1][case_id]["declared"]["buffer_distance_m"]
    results = _run(v0, case_id, metric_quantity="buffer", buffer_distance_m=distance, buffer_source="primary_source")
    assert _status(results, "geometry.metric_values") == {expected}


@pytest.mark.parametrize("case_id,expected", [("heldout-qa-04-wrong", "fail"), ("heldout-qa-05-correct", "pass")])
def test_declared_qa_rule_catches_over_masking_with_the_source_band(v0, case_id, expected):
    keep = v0[1][case_id]["declared"]["valid_qa_classes"]
    results = _run(v0, case_id, qa_path="qa_layer", qa_kind="keep-codes", qa_keep_codes=keep,
                   processing_full_scan=True, qa_source="primary_source")
    assert _status(results, "rs.cloud_mask_applied") == {expected}


@pytest.mark.parametrize("case_id,expected", [("heldout-geom-04-wrong", "fail"), ("heldout-geom-08-correct", "warn")])
def test_declared_dem_unit_enables_slope_on_unlabelled_dems(v0, case_id, expected):
    results = _run(v0, case_id, dem="primary_source", dem_vertical_unit="metre")
    assert _status(results, "terrain.slope_consistent") == {expected}  # the correct case uses another stencil


def test_constant_geoid_separation_is_minus_level(v0):
    declared = v0[1]["heldout-vert-03-wrong"]["declared"]
    results = _run(v0, "heldout-vert-03-wrong", vertical_operation="minus-level", vertical_sources=["primary_source"],
                   vertical_source_units=["metre"], vertical_unit="metre", vertical_level=declared["geoid_undulation_m"])
    assert grade_for(results) == ADVISORY and _status(results, "raster.vertical_units") == {"fail"}


def test_geoid_grid_is_a_difference_and_fathoms_convert(v0):
    grid = _run(v0, "heldout-vert-07-correct", vertical_operation="difference",
                vertical_sources=["primary_source", "secondary_source"], vertical_source_units=["metre", "metre"],
                vertical_unit="metre")
    assert _status(grid, "raster.vertical_units") == {"pass"}
    fathoms = _run(v0, "heldout-vert-08-correct", vertical_operation="convert", vertical_sources=["primary_source"],
                   vertical_source_units=["fathom"], vertical_unit="metre")
    assert _status(fathoms, "raster.vertical_units") == {"pass"}


def test_over_masking_without_the_source_band_only_warns(make_raster):
    from terraproof.checks.processing_full import cloud_mask
    codes = np.zeros((16, 16), dtype="uint8")
    codes[:4] = 9  # cloud
    qa = make_raster("qa.tif", codes, nodata=None)
    values = np.full((16, 16), 0.3, dtype="float32")
    values[:8] = -9999.0  # clouds masked, and half of the clear rows too
    out = inspect_dataset(make_raster("out.tif", values, nodata=-9999.0))
    assert cloud_mask(out, qa, "keep-codes", [0])[0].status == "warn"


def test_a_dem_label_that_contradicts_the_declared_unit_is_a_conflict(make_raster):
    from terraproof.checks.terrain import check_slope_consistent
    import rasterio
    dem = make_raster("dem.tif", np.random.default_rng(1).uniform(100, 200, (16, 16)).astype("float32"))
    with rasterio.open(dem, "r+") as dst:
        dst.units = ("ft",)
    slope = make_raster("slope.tif", np.ones((16, 16), dtype="float32"))
    check = check_slope_consistent(inspect_dataset(slope), inspect_dataset(dem), "metre")[0]
    assert check.status == "not-run" and "conflict" in check.message


def test_undeclared_metric_bindings_are_not_run(make_vector):
    from shapely.geometry import Polygon
    path = make_vector("parcel.gpkg", [Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])])
    check = [r for r in run_checks([inspect_dataset(path)], metric_quantity="area") if r.id == "geometry.metric_values"]
    assert check[0].status == "not-run" and check[0].evidence["missing_bindings"] == ["metric_property", "metric_unit"]
