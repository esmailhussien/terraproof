"""Phase 8 P2: raster.categorical_codes, sar.filter_domain and rs.stack_window."""
from __future__ import annotations

import json

import numpy as np
import pytest

from terraproof.checks import run_checks
from terraproof.cli import main
from terraproof.evidence import build_report, input_record
from terraproof.inspect import inspect_dataset


def _only(results, check_id):
    found = [r for r in results if r.id == check_id]
    assert len(found) == 1, [r.id for r in results]
    return found[0]


def _run(output, **kwargs):
    return run_checks([inspect_dataset(output)], **kwargs)


# raster.categorical_codes


@pytest.fixture
def classes(make_raster):
    codes = np.random.default_rng(4).choice(np.array([0, 1, 2, 5], dtype="uint8"), size=(40, 40))
    codes[:4, :4] = 255  # nodata in the source
    return codes, make_raster("classes.tif", codes, nodata=255)


def test_nearest_resampled_classes_pass_including_class_zero(make_raster, classes):
    codes, source = classes
    nearest = make_raster("nearest.tif", np.repeat(np.repeat(codes, 2, axis=0), 2, axis=1), resolution=5.0, nodata=255)
    check = _only(_run(nearest, categorical_source=inspect_dataset(source)), "raster.categorical_codes")
    assert check.status == "pass"
    assert check.evidence["source_code_count"] == 4 and check.evidence["compared_cells"] == 80 * 80 - 8 * 8


def test_blended_classes_fail_with_the_invented_codes(make_raster, classes):
    codes, source = classes
    valid = np.where(codes == 255, 0, codes).astype("float32")
    blended = (valid[:, :-1] + valid[:, 1:]) / 2  # a two-tap linear blend
    output = make_raster("bilinear.tif", blended, nodata=-9999.0)
    check = _only(_run(output, categorical_source=inspect_dataset(source)), "raster.categorical_codes")
    assert check.status == "fail" and check.evidence["invented_cells"] > 0
    assert set(check.evidence["invented_examples"]) <= {0.5, 1.5, 2.5, 3.0, 3.5}


def test_categorical_codes_need_a_raster_source(make_raster, classes, make_geojson):
    _, source = classes
    vector = make_geojson("v.geojson", {"type": "FeatureCollection", "features": []})
    from terraproof.checks.categorical_codes import check_categorical_codes
    assert check_categorical_codes(inspect_dataset(source), None)[0].status == "not-run"
    assert check_categorical_codes(inspect_dataset(source), inspect_dataset(vector))[0].status == "not-run"


# sar.filter_domain


def _boxcar(values, size):
    """Mean of every complete size x size window by summed-area table; NaN where incomplete."""
    half = size // 2
    table = np.pad(values, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = table[size:, size:] - table[:-size, size:] - table[size:, :-size] + table[:-size, :-size]
    out = np.full(values.shape, np.nan)
    out[half:-half, half:-half] = sums / size ** 2
    return out


@pytest.fixture
def backscatter():
    return np.random.default_rng(7).gamma(1.0, 0.05, (300, 300))  # speckled linear power, crossing 256-cell windows


@pytest.mark.parametrize("domain", ["sigma0-db", "sigma0-linear"])
def test_boxcar_in_linear_power_passes_and_in_db_fails(make_raster, backscatter, domain):
    to_db = lambda x: 10 * np.log10(x)  # noqa: E731
    source_values = to_db(backscatter) if domain == "sigma0-db" else backscatter
    right = _boxcar(backscatter, 5)
    wrong = 10 ** (_boxcar(to_db(backscatter), 5) / 10)
    if domain == "sigma0-db":
        right, wrong = to_db(right), to_db(wrong)
    source = make_raster("source.tif", source_values.astype("float32"), nodata=-9999.0)
    results = {}
    for name, values in (("right", right), ("wrong", wrong)):
        output = make_raster(f"{name}.tif", np.nan_to_num(values, nan=-9999.0).astype("float32"), nodata=-9999.0)
        results[name] = _only(_run(output, sar_expect=domain, sar_filter="boxcar", sar_filter_size=5,
                                   sar_filter_source=inspect_dataset(source)), "sar.filter_domain")
    assert results["right"].status == "pass" and results["right"].evidence["compared_cells"] == 296 * 296
    assert results["wrong"].status == "fail"
    assert results["wrong"].evidence["cells_matching_db_average"] == results["wrong"].evidence["mismatched_cells"] > 0


def test_filter_declarations_are_required_and_validated(make_raster, backscatter):
    source = make_raster("source.tif", backscatter.astype("float32"), nodata=-9999.0)
    missing = _only(_run(source, sar_filter="boxcar", sar_filter_source=inspect_dataset(source)), "sar.filter_domain")
    assert missing.status == "not-run" and missing.evidence["missing_bindings"] == ["sar_filter_size", "sar_expect"]
    even = _only(_run(source, sar_expect="sigma0-linear", sar_filter="boxcar", sar_filter_size=4,
                      sar_filter_source=inspect_dataset(source)), "sar.filter_domain")
    assert even.status == "not-run"


# rs.stack_window

JULY = ["2024-07-01T00:00:00Z", "2024-08-01T00:00:00Z"]


def _days(first, count):
    return [f"2024-07-{d:02d}T00:00:00Z/2024-07-{d + 1:02d}T00:00:00Z" if d < 31
            else "2024-07-31T00:00:00Z/2024-08-01T00:00:00Z" for d in range(first, first + count)]


def _window(output, times, window=JULY, reduction="weighted-sum", weights="hours"):
    stack = [inspect_dataset(output)] * len(times)
    if weights == "hours":
        weights = [24.0] * len(times)
    return _only(_run(output, stack=stack, stack_times=times, stack_window=window, stack_reduction=reduction,
                      stack_weights=weights), "rs.stack_window")


@pytest.fixture
def total(make_raster):
    return make_raster("total.tif", np.ones((8, 8), dtype="float32"))


def test_a_complete_daily_accumulation_passes(total):
    check = _window(total, _days(1, 31))
    assert check.status == "pass" and check.evidence["uncovered_hours"] == 0


def test_a_layer_outside_the_label_fails(total):
    times = _days(1, 31)[1:] + ["2024-08-01T00:00:00Z/2024-08-02T00:00:00Z"]
    check = _window(total, times)
    assert check.status == "fail" and check.evidence["layers_outside"] == [30]


def test_a_missing_day_fails_an_accumulation_but_not_a_median(total):
    times = _days(1, 14) + _days(16, 16)
    assert _window(total, times).status == "fail"
    assert _window(total, times).evidence["uncovered_hours"] == 24
    assert _window(total, times, reduction="median", weights=None).status == "pass"


def test_overlapping_layers_fail(total):
    times = _days(1, 31) + ["2024-07-10T12:00:00Z/2024-07-11T12:00:00Z"]
    check = _window(total, times, reduction="median", weights=None)
    assert check.status == "fail" and check.evidence["overlapping_layers"]


def test_weights_must_be_the_layer_hours(total):
    check = _window(total, _days(1, 31), weights=[1.0] * 31)
    assert check.status == "fail" and check.evidence["weights_not_matching_hours"] == list(range(31))


def test_malformed_times_are_not_run(total):
    assert _window(total, ["2024-07-01"] + _days(2, 30)).status == "not-run"
    assert _window(total, _days(1, 31), window=["2024-08-01", "2024-07-01"]).status == "not-run"


# Contracts and CLI/MCP parity


def test_a_contract_names_the_missing_window_bindings(total, tmp_path):
    results = _run(total, stack=[inspect_dataset(total)], stack_window=JULY)
    contract = {"schema": "terraproof.verification-contract/1", "requirements": [
        {"paths": [total], "checks": ["rs.stack_window"], "parameters": {"stack_window": JULY}}]}
    report = build_report(inputs=[input_record(total, "input", "raster")], results=results,
                          parameters={"stack_window": JULY}, contract=contract)
    row = report["verification"]["requirements"][0]
    assert row["status"] == "missing" and row["missing_bindings"] == ["stack", "stack_times"]


def test_new_checks_cli_mcp_parity(make_raster, classes, capsys):
    pytest.importorskip("mcp", reason="the mcp extra is not installed")
    from test_mcp import call

    codes, source = classes
    output = make_raster("nearest.tif", codes, nodata=255)
    times = _days(1, 31)
    assert main(["check", output, "--categorical-source", source,
                 *[part for _ in times for part in ("--stack", output)], "--stack-reduction", "median",
                 *[part for t in times for part in ("--stack-time", t)], "--stack-window", *JULY]) in (0, 2, 3)
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [output], "categorical_source": source, "stack": [output] * 31,
                                  "stack_reduction": "median", "stack_times": times,
                                  "stack_window": JULY}).structured_content
    for check_id in ("raster.categorical_codes", "rs.stack_window"):
        a = next(c for c in cli["checks"] if c["id"] == check_id)
        b = next(c for c in payload["report"]["checks"] if c["id"] == check_id)
        assert a == b and a["status"] == "pass"
