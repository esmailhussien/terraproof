"""Phase 7: raster.vertical_units, raster.nodata_support and declared goal profiles."""
from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio

from terraproof.checks import run_checks
from terraproof.cli import main
from terraproof.evidence import build_report, input_record
from terraproof.evidence.contract import load_contract, profile_contract
from terraproof._common import InputError
from terraproof.inspect import inspect_dataset

FT = 0.3048
SHAPE = (32, 32)


def _surface(seed, low, high):
    return np.random.default_rng(seed).uniform(low, high, SHAPE).astype("float32")


def _vertical(paths, operation, units, unit, output):
    sources = [inspect_dataset(path) for path in paths]
    return run_checks([inspect_dataset(output)], vertical_operation=operation, vertical_sources=sources,
                      vertical_source_units=units, vertical_unit=unit)


def _only(results, check_id):
    found = [r for r in results if r.id == check_id]
    assert len(found) == 1
    return found[0]


@pytest.fixture
def surfaces(make_raster):
    after_m = _surface(1, 100, 200)
    before_ft = _surface(2, 300, 600)
    return {"after_m": make_raster("after_m.tif", after_m), "before_ft": make_raster("before_ft.tif", before_ft),
            "arrays": (after_m, before_ft)}


def test_difference_in_declared_units_passes(make_raster, surfaces):
    after_m, before_ft = surfaces["arrays"]
    right = make_raster("change.tif", (after_m - before_ft * FT).astype("float32"))
    check = _only(_vertical([surfaces["after_m"], surfaces["before_ft"]], "difference", ["metre", "foot"], "m", right),
                  "raster.vertical_units")
    assert check.status == "pass" and check.evidence["compared_cells"] == SHAPE[0] * SHAPE[1]


def test_mixed_units_fail(make_raster, surfaces):
    after_m, before_ft = surfaces["arrays"]
    mixed = make_raster("change.tif", (after_m - before_ft).astype("float32"))  # feet subtracted as metres
    check = _only(_vertical([surfaces["after_m"], surfaces["before_ft"]], "difference", ["metre", "foot"], "metre",
                            mixed), "raster.vertical_units")
    assert check.status == "fail" and check.evidence["mismatched_cells"] > 0


def test_feet_values_declared_as_metres_fail_and_show_the_factor(make_raster, surfaces):
    _, before_ft = surfaces["arrays"]
    unconverted = make_raster("depth.tif", before_ft)  # still in feet
    check = _only(_vertical([surfaces["before_ft"]], "convert", ["ft"], "metre", unconverted), "raster.vertical_units")
    assert check.status == "fail"
    assert check.evidence["median_observed_to_expected"] == pytest.approx(1 / FT, rel=1e-3)
    converted = make_raster("depth_m.tif", (before_ft * FT).astype("float32"))
    assert _only(_vertical([surfaces["before_ft"]], "convert", ["ft"], "metre", converted),
                 "raster.vertical_units").status == "pass"


def test_a_contradicting_unit_label_fails(make_raster, surfaces):
    _, before_ft = surfaces["arrays"]
    path = make_raster("depth_m.tif", (before_ft * FT).astype("float32"))
    with rasterio.open(path, "r+") as dst:
        dst.units = ("ft",)
    check = _only(_vertical([surfaces["before_ft"]], "convert", ["foot"], "metre", path), "raster.vertical_units")
    assert check.status == "fail" and check.evidence["output_unit_label"] == "ft"


def test_undeclared_units_are_not_run_and_never_inferred(make_raster, surfaces):
    path = make_raster("out.tif", surfaces["arrays"][0])
    results = run_checks([inspect_dataset(path)], vertical_operation="convert")
    check = _only(results, "raster.vertical_units")
    assert check.status == "not-run"
    assert check.evidence["missing_bindings"] == ["vertical_unit", "vertical_sources", "vertical_source_units"]


def _support(make_raster, sources, fills, rule, output):
    layers = [inspect_dataset(path) for path in sources]
    return _only(run_checks([inspect_dataset(output)], support_sources=layers, support_source_nodata=fills,
                            support_rule=rule), "raster.nodata_support")


@pytest.fixture
def rain(make_raster):
    first = _surface(3, 0.5, 9).copy()
    second = _surface(4, 0.5, 9).copy()
    first[:4] = 0.0   # undeclared zero fill in the file
    second[:, :4] = 0.0
    return first, second, make_raster("a.tif", first, nodata=None), make_raster("b.tif", second, nodata=None)


def test_support_follows_declared_fill(make_raster, rain):
    first, second, a, b = rain
    valid = (first != 0) & (second != 0)
    right = make_raster("mean.tif", np.where(valid, (first + second) / 2, -9999).astype("float32"), nodata=-9999.0)
    assert _support(make_raster, [a, b], [0, 0], "all", right).status == "pass"
    averaged = make_raster("mean_bad.tif", ((first + second) / 2).astype("float32"), nodata=-9999.0)
    check = _support(make_raster, [a, b], [0, 0], "all", averaged)
    assert check.status == "fail" and check.evidence["fill_treated_as_data_cells"] > 0


def test_valid_zeros_masked_as_fill_fail(make_raster):
    dry = np.zeros(SHAPE, dtype="float32")
    dry[8:, :] = 2.0
    source = make_raster("rain.tif", dry, nodata=-9999.0)  # zeros are real dry days, fill is declared
    masked = make_raster("out.tif", np.where(dry == 0, -9999, dry).astype("float32"), nodata=-9999.0)
    check = _support(make_raster, [source], None, "all", masked)
    assert check.status == "fail" and check.evidence["valid_treated_as_fill_cells"] == 8 * SHAPE[1]
    assert _support(make_raster, [source], None, "all", make_raster("same.tif", dry, nodata=-9999.0)).status == "pass"


def test_any_rule_keeps_cells_with_one_valid_source(make_raster, rain):
    first, second, a, b = rain
    any_valid = (first != 0) | (second != 0)
    out = make_raster("any.tif", np.where(any_valid, np.maximum(first, second), -9999).astype("float32"), nodata=-9999.0)
    assert _support(make_raster, [a, b], [0, 0], "any", out).status == "pass"
    assert _support(make_raster, [a, b], [0, 0], "all", out).status == "fail"


def test_profiles_expand_to_checks_and_stay_in_the_contract(tmp_path):
    contract = profile_contract([str(tmp_path / "out.tif")], ["vertical-units", "nodata-support"], {})
    normalized = load_contract(contract)
    group = normalized["requirements"][0]
    assert group["profiles"] == ["nodata-support", "vertical-units"]
    assert group["checks"] == ["raster.nodata_support", "raster.vertical_units"]
    with pytest.raises(InputError):
        profile_contract([str(tmp_path / "out.tif")], ["guess-the-goal"], {})


def test_profile_without_its_bindings_is_incomplete_and_names_them(make_raster, capsys):
    path = make_raster("out.tif", _surface(5, 1, 2))
    assert main(["check", path, "--profile", "vertical-units"]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["grade"] == "advisory-only" and report["verification"]["status"] == "incomplete"
    assert report["diagnostics"][0]["missing_bindings"] == ["vertical_operation", "vertical_sources",
                                                            "vertical_source_units", "vertical_unit"]


def test_profile_with_bindings_can_be_decision_grade(make_raster, surfaces, capsys):
    after_m, before_ft = surfaces["arrays"]
    right = make_raster("change.tif", (after_m - before_ft * FT).astype("float32"))
    arguments = ["check", right, "--profile", "vertical-units", "--vertical-operation", "difference",
                 "--vertical-source", surfaces["after_m"], "--vertical-source", surfaces["before_ft"],
                 "--vertical-source-unit", "metre", "--vertical-source-unit", "foot", "--vertical-unit", "metre"]
    assert main(arguments) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["grade"] == "decision-grade" and report["coverage"]["assessed"] is True


def test_profile_and_contract_together_are_refused(make_raster):
    path = make_raster("out.tif", _surface(6, 1, 2))
    with pytest.raises(SystemExit):
        main(["check", path, "--profile", "nodata-support", "--contract", "contract.json"])


def test_new_checks_appear_in_not_checked_until_enabled(make_raster):
    path = make_raster("out.tif", _surface(7, 1, 2))
    report = build_report(inputs=[input_record(path, "input", "raster")], results=run_checks([inspect_dataset(path)]),
                          parameters={})
    names = {item["check"]: item["enabled_by"] for item in report["coverage"]["not_checked"]}
    assert names["raster.vertical_units"][0] == "vertical_operation"
    assert names["raster.nodata_support"] == ["support_sources", "support_rule"]
