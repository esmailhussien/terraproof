"""Tests for the preflight plan-assessment API."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from terraproof._common import crs_summary
from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN
from terraproof.inspect import inspect_dataset
from terraproof.preflight import run_preflight


def _ids(results):
    return [r.id for r in results]


def _status(results, check_id):
    matches = [r for r in results if r.id == check_id]
    assert len(matches) == 1
    return matches[0].status


def _message(results, check_id):
    matches = [r for r in results if r.id == check_id]
    assert len(matches) == 1
    return matches[0].message


# --- Plan validation ---


def test_rejects_unknown_operation():
    with pytest.raises(ValueError, match="operation"):
        run_preflight([], {"operation": "volume"})


def test_rejects_unknown_expect():
    with pytest.raises(ValueError, match="expect"):
        run_preflight([], {"expect": "temperature"})


def test_rejects_bad_time_range_length():
    with pytest.raises(ValueError, match="time_range"):
        run_preflight([], {"time_range": ["2024-01-01"]})


def test_rejects_non_iso_time_range():
    with pytest.raises(ValueError, match="ISO 8601"):
        run_preflight([], {"time_range": ["last summer", "2024-12-31"]})


def test_rejects_unknown_plan_field():
    with pytest.raises(ValueError, match="unknown plan field"):
        run_preflight([], {"cloud_cover": 10})


def test_rejects_non_object_plan():
    with pytest.raises(ValueError, match="JSON object"):
        run_preflight([], ["operation", "area"])


# --- Deterministic order ---


def test_emitted_ids_are_sorted(make_raster):
    path = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)
    ds = inspect_dataset(path)
    results = run_preflight([ds], {"operation": "area"})

    assert _ids(results) == sorted(_ids(results))


def test_all_seven_rules_can_be_triggered(make_raster, make_stac_item, tmp_path):
    # Reflectance plan triggers six of the seven rules; index is tested separately.
    raster_a = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0))
    raster_b = inspect_dataset(make_raster("b.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0))
    item = inspect_dataset(make_stac_item("item.json", {"datetime": "2024-06-15T00:00:00Z"}))
    plan = {
        "operation": "area",
        "target_crs": "EPSG:32636",
        "reproject": True,
        "combine": True,
        "alignment": True,
        "categorical": True,
        "resampling": "nearest",
        "expect": "reflectance",
        "decode": True,
        "time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"],
        "measurement_units": "sq metres",
    }
    results = run_preflight([raster_a, raster_b, item], plan)
    ids = set(_ids(results))
    assert ids == {
        "preflight.metric_crs",
        "preflight.alignment",
        "preflight.categorical_resampling",
        "preflight.reflectance_decode",
        "preflight.temporal_scope",
        "preflight.output_units",
    }
    for r in results:
        assert r.status == PASS


# --- metric CRS ---


def test_metric_operation_on_geographic_crs_fails(make_vector):
    path = make_vector("lonlat.gpkg", [], crs="EPSG:4326")
    ds = inspect_dataset(path)
    results = run_preflight([ds], {"operation": "area"})

    assert _status(results, "preflight.metric_crs") == FAIL
    assert "geographic" in _message(results, "preflight.metric_crs")


def test_metric_operation_on_geocentric_crs_fails():
    ds = {
        "kind": "vector",
        "path": "geocentric.gpkg",
        "crs": crs_summary("EPSG:4978"),
        "feature_count": 1,
        "geometry_types": ["Point"],
    }
    results = run_preflight([ds], {"operation": "distance"})

    assert _status(results, "preflight.metric_crs") == FAIL
    assert "geocentric" in _message(results, "preflight.metric_crs")


def test_metric_operation_on_projected_metric_crs_passes(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight([ds], {"operation": "area"})

    assert _status(results, "preflight.metric_crs") == PASS


def test_metric_operation_uses_target_crs_when_reproject_declared(make_vector):
    path = make_vector("lonlat.gpkg", [], crs="EPSG:4326")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {"operation": "area", "target_crs": "EPSG:32636", "reproject": True},
    )

    assert _status(results, "preflight.metric_crs") == PASS


def test_metric_operation_still_fails_on_geographic_input_without_reproject(make_vector):
    path = make_vector("lonlat.gpkg", [], crs="EPSG:4326")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {"operation": "area", "target_crs": "EPSG:32636"},
    )

    assert _status(results, "preflight.metric_crs") == FAIL


def test_metric_operation_omitted_without_operation(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight([ds], {})

    assert "preflight.metric_crs" not in _ids(results)


# --- output units ---


def test_output_units_fail_when_target_crs_is_geographic(make_vector):
    path = make_vector("lonlat.gpkg", [], crs="EPSG:4326")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {"operation": "area", "target_crs": "EPSG:4326", "measurement_units": "sq metres"},
    )

    assert _status(results, "preflight.output_units") == FAIL
    assert "geographic" in _message(results, "preflight.output_units")


def test_output_units_pass_for_projected_target_crs(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {"operation": "area", "target_crs": "EPSG:32636", "measurement_units": "sq metres"},
    )

    assert _status(results, "preflight.output_units") == PASS


def test_output_units_fail_for_feet_target_with_metre_request(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {
            "operation": "area",
            "target_crs": "EPSG:32636",
            "measurement_units": "sq feet",
        },
    )

    assert _status(results, "preflight.output_units") == FAIL


def test_output_units_pass_for_feet_target_with_metre_request_if_conversion_declared(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {
            "operation": "area",
            "target_crs": "EPSG:32636",
            "measurement_units": "sq feet",
            "unit_conversion": True,
        },
    )

    assert _status(results, "preflight.output_units") == PASS


@pytest.mark.parametrize("requested", ["km", "miles"])
def test_linear_unit_conversion_must_be_declared(make_vector, requested):
    ds = inspect_dataset(make_vector("utm.gpkg", [], crs="EPSG:32636"))
    plan = {"operation": "length", "target_crs": "EPSG:32636", "measurement_units": requested}
    assert _status(run_preflight([ds], plan), "preflight.output_units") == FAIL
    plan["unit_conversion"] = True
    assert _status(run_preflight([ds], plan), "preflight.output_units") == PASS


@pytest.mark.parametrize("requested", ["hectares", "acres"])
def test_area_unit_conversion_must_be_declared(make_vector, requested):
    ds = inspect_dataset(make_vector("utm.gpkg", [], crs="EPSG:32636"))
    plan = {"operation": "area", "target_crs": "EPSG:32636", "measurement_units": requested}
    assert _status(run_preflight([ds], plan), "preflight.output_units") == FAIL
    plan["unit_conversion"] = True
    assert _status(run_preflight([ds], plan), "preflight.output_units") == PASS


def test_square_foot_is_not_linear_metres(make_vector):
    ds = inspect_dataset(make_vector("utm.gpkg", [], crs="EPSG:32636"))
    result = run_preflight([ds], {"operation": "length", "target_crs": "EPSG:32636", "measurement_units": "sq foot"})
    assert _status(result, "preflight.output_units") == WARN


def test_output_units_warns_for_area_operation_with_linear_units(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight(
        [ds],
        {"operation": "area", "target_crs": "EPSG:32636", "measurement_units": "metres"},
    )

    assert _status(results, "preflight.output_units") == WARN


def test_output_units_omitted_without_target_crs(make_vector):
    path = make_vector("utm.gpkg", [], crs="EPSG:32636")
    ds = inspect_dataset(path)
    results = run_preflight([ds], {"operation": "area"})

    assert "preflight.output_units" not in _ids(results)


# --- alignment ---


def test_combine_without_alignment_on_mismatched_crs_fails(make_vector):
    a = inspect_dataset(make_vector("a.gpkg", [], crs="EPSG:32636"))
    b = inspect_dataset(make_vector("b.gpkg", [], crs="EPSG:4326"))
    results = run_preflight([a, b], {"combine": True, "alignment": False})

    assert _status(results, "preflight.alignment") == FAIL
    assert "CRS" in _message(results, "preflight.alignment")


def test_combine_without_alignment_on_matching_rasters_passes(make_raster):
    a = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8")))
    b = inspect_dataset(make_raster("b.tif", np.full((8, 8), 2, dtype="uint8")))
    results = run_preflight([a, b], {"combine": True, "alignment": False})

    assert _status(results, "preflight.alignment") == PASS


def test_combine_with_alignment_declared_passes(make_raster):
    a = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8")))
    b = inspect_dataset(make_raster("b.tif", np.full((8, 8), 2, dtype="uint8")))
    results = run_preflight([a, b], {"combine": True, "alignment": True})

    assert _status(results, "preflight.alignment") == PASS


def test_alignment_checks_rasters_even_when_first_input_is_vector(make_vector, make_raster):
    vector = inspect_dataset(make_vector("ref.gpkg", [], crs="EPSG:32636"))
    raster_a = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8"), origin=(500000.0, 5000000.0), resolution=10.0))
    raster_b = inspect_dataset(make_raster("b.tif", np.full((8, 8), 2, dtype="uint8"), origin=(500000.0, 5000000.0), resolution=20.0))
    results = run_preflight([vector, raster_a, raster_b], {"combine": True, "alignment": False})

    assert _status(results, "preflight.alignment") == FAIL
    assert "pixel size" in _message(results, "preflight.alignment").lower()


def test_alignment_detects_rotation_shear(make_raster):
    a = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8")))
    # Sheared transform: same pixel size but off-diagonal terms differ.
    b = inspect_dataset(
        make_raster(
            "b.tif",
            np.full((8, 8), 2, dtype="uint8"),
            origin=(500000.0, 5000000.0),
        )
    )
    # Patch the inspected transform to introduce shear.
    b["transform"] = [10.0, 1.0, 500000.0, 0.0, -10.0, 5000000.0]
    results = run_preflight([a, b], {"combine": True, "alignment": False})

    assert _status(results, "preflight.alignment") == FAIL
    assert "rotation" in _message(results, "preflight.alignment").lower() or "shear" in _message(results, "preflight.alignment").lower()


def test_alignment_true_with_too_few_inputs_is_not_run(make_raster):
    raster = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8")))
    results = run_preflight([raster], {"combine": True, "alignment": True})

    assert _status(results, "preflight.alignment") == NOT_RUN


def test_alignment_true_with_missing_crs_is_not_run(make_vector, make_raster):
    vector_no_crs = inspect_dataset(make_vector("nocrs.gpkg", [], crs=None))
    raster = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8")))
    results = run_preflight([vector_no_crs, raster], {"combine": True, "alignment": True})

    assert _status(results, "preflight.alignment") == NOT_RUN


def test_alignment_omitted_when_combine_false(make_raster):
    a = inspect_dataset(make_raster("a.tif", np.full((8, 8), 1, dtype="uint8")))
    b = inspect_dataset(make_raster("b.tif", np.full((8, 8), 2, dtype="uint8")))
    results = run_preflight([a, b], {})

    assert "preflight.alignment" not in _ids(results)


# --- categorical resampling ---


def test_categorical_nearest_resampling_passes(make_raster):
    path = inspect_dataset(make_raster("cat.tif", np.full((8, 8), 1, dtype="uint8")))
    results = run_preflight([path], {"categorical": True, "resampling": "nearest"})

    assert _status(results, "preflight.categorical_resampling") == PASS


def test_categorical_bilinear_resampling_fails(make_raster):
    path = inspect_dataset(make_raster("cat.tif", np.full((8, 8), 1, dtype="uint8")))
    results = run_preflight([path], {"categorical": True, "resampling": "bilinear"})

    assert _status(results, "preflight.categorical_resampling") == FAIL


def test_categorical_resampling_not_run_without_method(make_raster):
    path = inspect_dataset(make_raster("cat.tif", np.full((8, 8), 1, dtype="uint8")))
    results = run_preflight([path], {"categorical": True})

    assert _status(results, "preflight.categorical_resampling") == NOT_RUN


# --- reflectance decode ---


def test_reflectance_integer_dn_without_decode_fails(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=0.0001, offset=-0.1))
    results = run_preflight([path], {"expect": "reflectance", "decode": False})

    assert _status(results, "preflight.reflectance_decode") == FAIL


def test_reflectance_integer_dn_with_decode_passes(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=0.0001, offset=-0.1))
    results = run_preflight([path], {"expect": "reflectance", "decode": True})

    assert _status(results, "preflight.reflectance_decode") == PASS


def test_reflectance_on_float_without_decode_is_not_run(make_raster):
    path = inspect_dataset(make_raster("refl.tif", np.full((8, 8), 0.1, dtype="float32")))
    results = run_preflight([path], {"expect": "reflectance", "decode": False})

    assert _status(results, "preflight.reflectance_decode") == NOT_RUN


def test_reflectance_identity_scale_offset_is_not_run(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=1.0, offset=0.0))
    results = run_preflight([path], {"expect": "reflectance", "decode": False})

    assert _status(results, "preflight.reflectance_decode") == NOT_RUN


def test_reflectance_encoding_without_decode_is_not_run(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=1.0, offset=0.0))
    results = run_preflight([path], {"expect": "reflectance", "decode": False, "encoding": "s2-l2a"})

    assert _status(results, "preflight.reflectance_decode") == NOT_RUN


def test_reflectance_nonfinite_metadata_warns(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=float("nan"), offset=0.0))
    results = run_preflight([path], {"expect": "reflectance", "decode": False})

    assert _status(results, "preflight.reflectance_decode") == WARN


# --- index inputs ---


def test_index_on_integer_dn_without_decode_fails(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=0.0001, offset=-0.1))
    results = run_preflight([path], {"expect": "index", "decode": False})

    assert _status(results, "preflight.index_inputs") == FAIL


def test_index_on_integer_dn_with_decode_passes(make_raster):
    path = inspect_dataset(make_raster("dn.tif", np.full((8, 8), 1500, dtype="uint16"), scale=0.0001, offset=-0.1))
    results = run_preflight([path], {"expect": "index", "decode": True})

    assert _status(results, "preflight.index_inputs") == PASS


def test_index_on_float_without_decode_is_not_run(make_raster):
    path = inspect_dataset(make_raster("refl.tif", np.full((8, 8), 0.1, dtype="float32")))
    results = run_preflight([path], {"expect": "index", "decode": False})

    assert _status(results, "preflight.index_inputs") == NOT_RUN


# --- temporal scope ---


def test_temporal_scope_passes_when_items_inside_range(make_stac_item):
    item = make_stac_item("in.json", {"datetime": "2024-06-15T00:00:00Z"})
    ds = inspect_dataset(item)
    results = run_preflight([ds], {"time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]})

    assert _status(results, "preflight.temporal_scope") == PASS


def test_temporal_scope_fails_when_item_outside_range(make_stac_item):
    item = make_stac_item("out.json", {"datetime": "2025-06-15T00:00:00Z"})
    ds = inspect_dataset(item)
    results = run_preflight([ds], {"time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]})

    assert _status(results, "preflight.temporal_scope") == FAIL


def test_temporal_scope_omitted_without_time_range(make_stac_item):
    item = make_stac_item("no_range.json", {"datetime": "2024-06-15T00:00:00Z"})
    ds = inspect_dataset(item)
    results = run_preflight([ds], {})

    assert "preflight.temporal_scope" not in _ids(results)


def test_temporal_scope_not_run_with_undated_item(make_stac_item):
    item = make_stac_item("undated.json", {"proj:epsg": 32636})
    ds = inspect_dataset(item)
    results = run_preflight([ds], {"time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]})

    assert _status(results, "preflight.temporal_scope") == NOT_RUN


# --- CLI-style integration: plan read from JSON file ---


def test_preflight_cli_json_plan_file(tmp_path, make_raster):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"operation": "area"}), encoding="utf-8")
    raster_path = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)

    from terraproof.cli import main

    assert main(["preflight", str(raster_path), "--plan", str(plan_path)]) == 0
