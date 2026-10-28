"""Tests for the executable benchmark harness (`python -m terraproof.evals run`).

The full run is exercised: all 33 task specs, their generated fixtures, the real checks and
provenance APIs, and the oracle controls. No fixture binary is committed; everything is
generated inside pytest's temporary directories.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from terraproof.checks.base import result
from terraproof.evals import SpecError, load_specs, run_benchmark, to_json
from terraproof.evals import recipes as recipes_package
from terraproof.evals.harness import (
    Control,
    Oracle,
    Step,
    _compare,
    _control_record,
    _grade_from_statuses,
    _summary,
)
from terraproof.evals.recipes import REGISTRY, build_registry, validate_registry
from terraproof.evals.specs import catalog_check_ids, default_spec_dir

EVALS_DIR = Path(__file__).resolve().parents[2] / "src" / "terraproof" / "evals"


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    return run_benchmark(work_root=tmp_path_factory.mktemp("evals-full"))


@pytest.fixture(scope="module")
def specs() -> list:
    return load_specs()


def test_specs_load_and_validate(specs):
    assert len({spec.path for spec in specs}) == 11
    assert len(specs) == 33
    assert len({spec.id for spec in specs}) == 33
    for spec in specs:
        assert spec.skill == spec.path.stem
        assert set(spec.expected_checks.values()) <= {"pass", "warn", "fail"}
        assert set(spec.expected_checks) <= catalog_check_ids()


def test_registry_covers_every_spec_and_has_no_orphans(specs):
    spec_ids = {spec.id for spec in specs}
    assert set(REGISTRY) == spec_ids
    validate_registry(spec_ids)
    with pytest.raises(SpecError):
        validate_registry(spec_ids - {specs[0].id})


def test_duplicate_recipe_is_rejected(monkeypatch):
    from terraproof.evals.recipes import accuracy

    duplicate_id = next(iter(recipes_package.crs.RECIPES))
    monkeypatch.setitem(accuracy.RECIPES, duplicate_id, accuracy.accuracy_stratified_area)
    monkeypatch.setattr(recipes_package, "_MODULES", (accuracy, recipes_package.crs))
    with pytest.raises(SpecError, match="duplicate recipe"):
        build_registry()


def test_full_report_passes(report):
    summary = report["summary"]
    assert summary["tasks"] == 33
    assert summary["tasks_passed"] == 33
    assert summary["tasks_failed"] == 0
    assert summary["tasks_unrunnable"] == 0
    assert summary["false_passes"] == 0
    assert summary["missing_expected_checks"] == 0
    assert summary["exit_code"] == 0
    assert summary["controls_correct"] == 33
    assert summary["controls_wrong"] >= 27


def test_every_wrong_control_is_rejected(report):
    for task in report["tasks"]:
        controls = task["controls"]
        assert controls, task["id"]
        correct = next(control for control in controls if control["kind"] == "correct")
        assert correct["verdict"] == "accepted", task["id"]
        assert correct["expected_status_ok"] and correct["oracle_ok"], task["id"]
        for control in controls:
            if control["kind"] != "wrong":
                continue
            assert control["verdict"] != "false_pass", (task["id"], control["name"])
            assert control["oracle_ok"] is False, (task["id"], control["name"])
            assert control["verdict"] in {"rejected", "rejected_by_oracle_only", "check_status_changed"}


def test_report_records_automated_scope_and_remaining_requirements(report):
    assert report["limitations"]
    for task in report["tasks"]:
        assert task["automated_scope"], task["id"]
        assert task["remaining_requirements"], task["id"]
        assert task["evidence_grade"] in {"checks-passed", "review-required", "advisory-only"}
        assert task["grade_rule_matches"] is True, task["id"]


def test_exercised_checks_are_catalog_ids_and_preflight_is_reported(report):
    summary = report["summary"]
    catalog = catalog_check_ids()
    assert set(summary["checks_exercised"]) <= catalog
    assert summary["spec_check_ids_not_in_catalog"] == []
    group = summary["preflight_control_group"]
    assert group["controls"] == 7
    assert group["correct_controls_passed"] == 7
    assert group["seeded_failures_rejected"] == 7
    assert set(group["checks_exercised"]) == {check_id for check_id in catalog if check_id.startswith("preflight.")}


def test_report_is_deterministic_and_path_free(tmp_path):
    first = to_json(run_benchmark(work_root=tmp_path / "a"))
    second = to_json(run_benchmark(work_root=tmp_path / "b"))
    assert first == second
    assert str(tmp_path) not in first
    assert "terraproof-evals-" not in first
    assert "<fixtures>" in first


def test_missing_recipe_is_unrunnable_not_skipped(monkeypatch, tmp_path):
    task_id = sorted(REGISTRY)[0]
    monkeypatch.delitem(REGISTRY, task_id)
    report = run_benchmark(only=[task_id], work_root=tmp_path / "missing")
    task = report["tasks"][0]
    assert task["status"] == "unrunnable"
    assert "no fixture recipe" in task["error"]
    assert report["summary"]["tasks_unrunnable"] == 1
    assert report["summary"]["exit_code"] == 1


def test_spec_validation_rejects_unknown_check_id(tmp_path):
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    document = json.loads((default_spec_dir() / "crs-and-units.json").read_text(encoding="utf-8"))
    document["tasks"][0]["expected_checks"] = {"crs.not_a_real_check": "pass"}
    (spec_dir / "crs-and-units.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SpecError, match="not registered"):
        load_specs(spec_dir)


def test_spec_validation_rejects_duplicate_ids(tmp_path):
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    document = json.loads((default_spec_dir() / "crs-and-units.json").read_text(encoding="utf-8"))
    second = json.loads((default_spec_dir() / "vector-quality.json").read_text(encoding="utf-8"))
    document["tasks"][0]["id"] = second["tasks"][0]["id"]
    (spec_dir / "crs-and-units.json").write_text(json.dumps(document), encoding="utf-8")
    (spec_dir / "vector-quality.json").write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(SpecError, match="duplicate task id"):
        load_specs(spec_dir)


def test_spec_validation_rejects_bad_status(tmp_path):
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    document = json.loads((default_spec_dir() / "crs-and-units.json").read_text(encoding="utf-8"))
    first_check = next(iter(document["tasks"][0]["expected_checks"]))
    document["tasks"][0]["expected_checks"][first_check] = "not-run"
    (spec_dir / "crs-and-units.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SpecError, match="status"):
        load_specs(spec_dir)


def test_control_classification_distinguishes_false_passes(tmp_path):
    expected = {"crs.defined": "pass"}

    def _control(oracle_passes: bool) -> Control:
        oracle = Oracle("classification")
        oracle.equal("synthetic assertion", 1 if oracle_passes else 2, 1)
        return Control(
            name="synthetic",
            kind="wrong",
            description="synthetic control",
            steps=[Step("synthetic step", [result("crs.defined", "pass", "ok")])],
            oracle=oracle,
        )

    false_pass = _control_record(_control(True), expected, tmp_path, "advisory-only")
    assert false_pass["verdict"] == "false_pass"
    assert false_pass["checks_ok"] and false_pass["oracle_ok"]

    blind_spot = _control_record(_control(False), expected, tmp_path, "advisory-only")
    assert blind_spot["verdict"] == "rejected_by_oracle_only"


def test_summary_requires_all_preflight_controls_to_pass_and_reject():
    from terraproof.evals.harness import PREFLIGHT_CONTROL_IDS

    controls = [
        {"check": check_id, "correct_status": "pass", "seeded_status": "fail"}
        for check_id in PREFLIGHT_CONTROL_IDS
    ]
    assert _summary([], controls)["exit_code"] == 0

    assert _summary([], controls[:-1])["exit_code"] == 1

    bad_correct = [dict(control) for control in controls]
    bad_correct[0]["correct_status"] = "warn"
    assert _summary([], bad_correct)["exit_code"] == 1

    bad_seed = [dict(control) for control in controls]
    bad_seed[0]["seeded_status"] = "warn"
    assert _summary([], bad_seed)["exit_code"] == 1


def test_summary_counts_false_passes():
    task = {
        "id": "synthetic-task",
        "spec_file": "synthetic.json",
        "status": "failed",
        "controls": [
            {
                "kind": "correct",
                "name": "correct",
                "missing_expected_checks": [],
                "steps": [{"results": [{"id": "crs.defined", "status": "pass"}]}],
            },
            {"kind": "wrong", "name": "w", "verdict": "false_pass", "checks_ok": True, "steps": [{"results": []}]},
        ],
    }
    summary = _summary([task])
    assert summary["false_passes"] == 1
    assert summary["exit_code"] == 1


def test_status_comparison_requires_every_result_of_a_multi_input_check():
    expected = {"rs.reflectance_range": "pass"}
    balanced, _missing, mismatched = _compare({"rs.reflectance_range": ["pass", "pass"]}, expected)
    assert balanced and not mismatched
    unbalanced, _missing, mismatched = _compare({"rs.reflectance_range": ["pass", "fail"]}, expected)
    assert not unbalanced and mismatched


def test_grade_rule_matches_public_grade_for(report):
    from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN
    from terraproof.evidence import grade_for

    for statuses in ([PASS], [WARN], [FAIL], [NOT_RUN], []):
        assert _grade_from_statuses(statuses) == grade_for(
            [result("crs.defined", status, "synthetic") for status in statuses]
        )
    for task in report["tasks"]:
        assert task["grade_rule_matches"] is True


def test_production_module_does_not_import_tests():
    pattern = re.compile(r"^\s*(from|import)\s+tests\b", re.MULTILINE)
    for path in sorted(EVALS_DIR.rglob("*.py")):
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_cli_reports_exit_code_and_json(tmp_path):
    from terraproof.evals.__main__ import main

    output = tmp_path / "report.json"
    task_id = sorted(REGISTRY)[0]
    code = main(["run", "--only", task_id, "--out", str(output)])
    assert code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["summary"]["tasks"] == 1
    assert document["tasks"][0]["id"] == task_id
    assert document["tasks"][0]["status"] == "pass"
