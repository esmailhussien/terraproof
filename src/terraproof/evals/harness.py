"""The executable benchmark harness: run every task's recipe, compare checks with the spec.

For each task the harness builds generated fixtures, runs the real public checks (and, where
the task needs it, the provenance manifest round trip), and records:

* whether the **correct** control reproduces the spec's `expected_checks` statuses;
* whether its independent numeric oracle passes;
* whether each **seeded-wrong** control is rejected, either by the checks or by the oracle.

A wrong control that passes both layers is a false pass and fails the run. A wrong control
that passes the checks but fails the oracle is reported as a checker blind spot: the checks
alone would accept it, which is exactly the gap the task's acceptance criteria describe.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from terraproof._common import crs_summary
from terraproof.checks.base import CheckResult
from terraproof.checks.base import FAIL, NOT_RUN, WARN, PASS as CHECK_PASS
from terraproof.preflight import run_preflight
from terraproof.evidence.grade import ADVISORY, CHECKS_PASSED, REVIEW, grade_for
from terraproof.evals.oracles import Oracle
from terraproof.evals.specs import SpecError, TaskSpec, catalog_check_ids, load_specs

SCHEMA = "terraproof.evals/0.1"
CORRECT = "correct"
WRONG = "wrong"
PASS = "pass"
FAILED = "failed"
UNRUNNABLE = "unrunnable"

PREFLIGHT_CONTROL_IDS = (
    "preflight.metric_crs",
    "preflight.alignment",
    "preflight.categorical_resampling",
    "preflight.reflectance_decode",
    "preflight.temporal_scope",
    "preflight.index_inputs",
    "preflight.output_units",
)

LIMITATIONS = [
    "The harness checks whether a processing result satisfies named deterministic checks and numeric oracles. "
    "It does not execute an AI agent, so it measures check coverage and fixture correctness, not agent lift.",
    "No network access: STAC endpoints, cloud reads, SAS signing and online reference imagery are represented "
    "by local fixture files, so those parts of a task's acceptance remain human or external.",
    "A check pass is a measured relation (range, grid, calibration, manifest hash), not scientific certification "
    "or proof that every acceptance criterion in the spec was met.",
    "The graded evidence is produced by the public check and evidence APIs at the installed version; the harness "
    "does not grade free-text explanations in an agent answer.",
    "COG checks are the repository's heuristic layout screen. A full COG validator and a browser/HTTP read test "
    "are not available offline and are not claimed.",
]


@dataclass
class Step:
    """One modelled invocation of the public checks."""

    command: str
    results: list[CheckResult]


@dataclass
class Control:
    """One generated artifact set plus the independent oracle for its acceptance criteria."""

    name: str
    kind: str
    description: str
    steps: list[Step]
    oracle: Oracle
    notes: str = ""

    def __post_init__(self) -> None:
        if self.kind not in (CORRECT, WRONG):
            raise ValueError(f"unknown control kind: {self.kind!r}")
        if not self.steps:
            raise ValueError(f"control {self.name!r} has no check steps")


@dataclass
class TaskRecipe:
    """A task's correct control, its seeded-wrong controls, and its acceptance scope."""

    task_id: str
    correct: Control
    wrong: list[Control]
    automated_scope: list[str]
    remaining_requirements: list[str]
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.correct.kind != CORRECT:
            raise ValueError(f"recipe {self.task_id!r}: the first control must be the correct one")
        if not self.wrong:
            raise ValueError(f"recipe {self.task_id!r}: at least one seeded-wrong control is required")
        if any(control.kind != WRONG for control in self.wrong):
            raise ValueError(f"recipe {self.task_id!r}: every non-correct control must be seeded-wrong")


# -- status comparison -------------------------------------------------------------------
def _statuses(steps: list[Step]) -> dict[str, list[str]]:
    observed: dict[str, list[str]] = {}
    for step in steps:
        for result in step.results:
            observed.setdefault(result.id, []).append(result.status)
    return observed


def _compare(observed: dict[str, list[str]], expected: dict[str, str]) -> tuple[bool, list[str], list[dict]]:
    """Every result with an expected id must have exactly the expected status."""
    missing = sorted(check_id for check_id in expected if check_id not in observed)
    mismatched = [
        {
            "check": check_id,
            "expected": expected[check_id],
            "observed": observed[check_id],
        }
        for check_id in sorted(expected)
        if check_id in observed and any(status != expected[check_id] for status in observed[check_id])
    ]
    return (not missing and not mismatched), missing, mismatched


def _grade_from_statuses(statuses) -> str:
    """The documented grade rule, reimplemented so the public grade function is checked, not trusted."""
    values = set(statuses)
    if not values or values & {FAIL, NOT_RUN}:
        return ADVISORY
    if WARN in values:
        return REVIEW
    return CHECKS_PASSED


def _sanitize(value, root: Path):
    """Make paths in messages and evidence relative to the fixture root, so the report is deterministic."""
    if isinstance(value, str):
        for prefix in {str(root), root.as_posix()}:
            value = value.replace(prefix, "<fixtures>")
        return value
    if isinstance(value, dict):
        return {str(_sanitize(key, root)): _sanitize(item, root) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, root) for item in value]
    if isinstance(value, Path):
        return _sanitize(value.as_posix(), root)
    return value


def _control_record(control: Control, expected: dict[str, str], root: Path, public_grade: str) -> dict:
    observed = _statuses(control.steps)
    expected_ok, missing, mismatched = _compare(observed, expected)
    unexpected_failures = [
        {"check": result.id, "status": result.status}
        for step in control.steps
        for result in step.results
        if result.status == FAIL and expected.get(result.id) != FAIL
    ]
    # For a seeded-wrong artifact, any additional failing check also means the checks rejected it.
    checks_ok = expected_ok if control.kind == CORRECT else expected_ok and not unexpected_failures
    oracle_passed = control.oracle.passed
    if control.kind == CORRECT:
        verdict = "accepted" if checks_ok and oracle_passed else "rejected"
    elif checks_ok and oracle_passed:
        verdict = "false_pass"
    elif checks_ok:
        verdict = "rejected_by_oracle_only"
    elif oracle_passed:
        verdict = "check_status_changed"
    else:
        verdict = "rejected"
    return {
        "name": control.name,
        "kind": control.kind,
        "description": control.description,
        "checks_ok": checks_ok,
        "expected_status_ok": expected_ok,
        "oracle_ok": oracle_passed,
        "verdict": verdict,
        "missing_expected_checks": missing,
        "mismatched_checks": mismatched,
        "unexpected_failures": unexpected_failures,
        "evidence_grade": public_grade,
        "steps": [
            {
                "command": _sanitize(step.command, root),
                "results": [
                    {
                        "id": result.id,
                        "status": result.status,
                        "message": _sanitize(result.message, root),
                    }
                    for result in step.results
                ],
            }
            for step in control.steps
        ],
        "oracle": _sanitize(control.oracle.to_dict(), root),
        "notes": _sanitize(control.notes, root),
    }


def _run_task(spec: TaskSpec, recipe_function, workspace: Path) -> dict:
    base = {
        "id": spec.id,
        "skill": spec.skill,
        "spec_file": spec.spec_file,
        "prompt": spec.prompt,
        "pitfall": spec.pitfall,
        "expected_checks": dict(spec.expected_checks),
        "expected_grade": _grade_from_statuses(spec.expected_checks.values()),
    }
    if recipe_function is None:
        return {
            **base,
            "status": UNRUNNABLE,
            "error": f"no fixture recipe is registered for task '{spec.id}'",
            "controls": [],
            "automated_scope": [],
            "remaining_requirements": [],
        }
    task_root = workspace / spec.id
    try:
        task_root.mkdir(parents=True, exist_ok=True)
        recipe = recipe_function(task_root)
        if not isinstance(recipe, TaskRecipe):
            raise SpecError(f"recipe for '{spec.id}' did not return a TaskRecipe")
        if recipe.task_id != spec.id:
            raise SpecError(f"recipe task id {recipe.task_id!r} does not match spec id {spec.id!r}")
        if not recipe.automated_scope or not recipe.remaining_requirements:
            raise SpecError(f"recipe for '{spec.id}' must state its automated scope and remaining requirements")
        if not recipe.correct.oracle.assertions:
            raise SpecError(f"recipe for '{spec.id}' has no oracle assertions on the correct control")
    except Exception as error:  # a broken recipe is an unrunnable task, reported not skipped
        return {
            **base,
            "status": UNRUNNABLE,
            "error": _sanitize(f"{type(error).__name__}: {error}", workspace),
            "controls": [],
            "automated_scope": [],
            "remaining_requirements": [],
        }

    correct_results = [result for step in recipe.correct.steps for result in step.results]
    correct_grade = grade_for(correct_results)
    rule_grade = _grade_from_statuses(result.status for result in correct_results)
    correct_record = _control_record(recipe.correct, spec.expected_checks, workspace, correct_grade)
    wrong_records = [
        _control_record(control, spec.expected_checks, workspace, grade_for([r for s in control.steps for r in s.results]))
        for control in recipe.wrong
    ]
    problems = []
    if not correct_record["checks_ok"]:
        problems.append("the correct control does not reproduce the spec's expected_checks")
    if not correct_record["oracle_ok"]:
        problems.append("the correct control fails its independent numeric oracle")
    if correct_grade != rule_grade:
        problems.append("evidence grade does not match the documented status rule")
    for record in wrong_records:
        if record["oracle_ok"]:
            problems.append(f"seeded-wrong control '{record['name']}' still passes the oracle")
        if record["verdict"] == "false_pass":
            problems.append(f"seeded-wrong control '{record['name']}' is a false pass")
    return {
        **base,
        "status": PASS if not problems else FAILED,
        "problems": problems,
        "evidence_grade": correct_grade,
        "grade_rule_matches": correct_grade == rule_grade,
        "controls": [correct_record] + wrong_records,
        "automated_scope": list(recipe.automated_scope),
        "remaining_requirements": list(recipe.remaining_requirements),
        "notes": list(recipe.notes),
    }


def _run_preflight_control_group() -> list[dict]:
    """Exercise each preflight rule with a passing and seeded-failing plan.

    These controls are deliberately separate from the 27 task recipes: they verify
    plan-level wiring without pretending that an oracle-only rejection is a checker
    rejection. Profiles are synthetic API dictionaries; this group does not exercise
    dataset inspection or filesystem inspection.
    """
    projected = {"kind": "raster", "path": "projected.tif", "crs": crs_summary("EPSG:32636"),
                 "transform": [10, 0, 500000, 0, -10, 5000000], "width": 8, "height": 8,
                 "bands": [{"index": 1, "dtype": "uint16", "scale": 0.0001, "offset": -0.1}]}
    geographic = {**projected, "path": "geographic.tif", "crs": crs_summary("EPSG:4326")}
    shifted = {**projected, "path": "shifted.tif", "transform": [10, 0, 500005, 0, -10, 5000000]}
    stac = {"kind": "stac", "path": "item.json", "datetime": "2024-06-15T00:00:00Z"}
    cases = [
        ("preflight.metric_crs", [geographic], {"operation": "area"}, {"operation": "area", "target_crs": "EPSG:32636", "reproject": True}),
        ("preflight.alignment", [projected, shifted], {"combine": True}, {"combine": True, "alignment": True}),
        ("preflight.categorical_resampling", [projected], {"categorical": True, "resampling": "bilinear"}, {"categorical": True, "resampling": "nearest"}),
        ("preflight.reflectance_decode", [projected], {"expect": "reflectance"}, {"expect": "reflectance", "decode": True}),
        ("preflight.temporal_scope", [stac], {"time_range": ["2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"]}, {"time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]}),
        ("preflight.index_inputs", [projected], {"expect": "index"}, {"expect": "index", "decode": True}),
        ("preflight.output_units", [projected], {"operation": "area", "target_crs": "EPSG:4326", "measurement_units": "sq metres"}, {"operation": "area", "target_crs": "EPSG:32636", "measurement_units": "sq metres"}),
    ]
    controls = []
    for check_id, datasets, wrong_plan, right_plan in cases:
        right = {item.id: item.status for item in run_preflight(datasets, right_plan)}.get(check_id)
        wrong = {item.id: item.status for item in run_preflight(datasets, wrong_plan)}.get(check_id)
        controls.append({"check": check_id, "correct_status": right, "seeded_status": wrong,
                         "correct_passed": right == CHECK_PASS, "seeded_rejected": wrong == FAIL})
    return controls


def _summary(task_records: list[dict], preflight_controls: list[dict] | None = None) -> dict:
    exercised: set[str] = set()
    wrong_records = []
    missing_expected = 0
    for record in task_records:
        for control in record.get("controls", []):
            for step in control["steps"]:
                for result in step["results"]:
                    exercised.add(result["id"])
            if control["kind"] == WRONG:
                wrong_records.append((record["id"], control))
        correct = next((c for c in record.get("controls", []) if c["kind"] == CORRECT), None)
        if correct is not None:
            missing_expected += len(correct["missing_expected_checks"])
    false_passes = [{"task": task, "control": control["name"]} for task, control in wrong_records if control["verdict"] == "false_pass"]
    blind_spots = [{"task": task, "control": control["name"]} for task, control in wrong_records if control["verdict"] == "rejected_by_oracle_only"]
    preflight_controls = preflight_controls or []
    preflight_ids = [control.get("check") for control in preflight_controls]
    preflight_missing = sorted(set(PREFLIGHT_CONTROL_IDS) - set(preflight_ids))
    preflight_duplicates = sorted({item for item in preflight_ids if preflight_ids.count(item) > 1})
    preflight_correct_failures = [
        control.get("check") for control in preflight_controls
        if control.get("correct_status") != CHECK_PASS
    ]
    preflight_unrejected = [
        control.get("check") for control in preflight_controls
        if control.get("seeded_status") != FAIL
    ]
    preflight_valid = (
        len(preflight_controls) == len(PREFLIGHT_CONTROL_IDS)
        and set(preflight_ids) == set(PREFLIGHT_CONTROL_IDS)
        and not preflight_duplicates
        and not preflight_correct_failures
        and not preflight_unrejected
    )
    exercised.update(item for item in preflight_ids if item)
    catalog = catalog_check_ids()
    failed = [record["id"] for record in task_records if record["status"] == FAILED]
    unrunnable = [record["id"] for record in task_records if record["status"] == UNRUNNABLE]
    summary = {
        "spec_files": len({record["spec_file"] for record in task_records}),
        "tasks": len(task_records),
        "tasks_passed": sum(1 for record in task_records if record["status"] == PASS),
        "tasks_failed": len(failed),
        "tasks_unrunnable": len(unrunnable),
        "failed_tasks": failed,
        "unrunnable_tasks": unrunnable,
        "controls_correct": len(task_records),
        "controls_wrong": len(wrong_records),
        "wrong_controls_rejected_by_checks": sum(
            1 for _, control in wrong_records if not control["checks_ok"]
        ),
        "wrong_controls_checker_blind_spots": len(blind_spots),
        "checker_blind_spots": blind_spots,
        "false_passes": len(false_passes),
        "false_pass_details": false_passes,
        "missing_expected_checks": missing_expected,
        "checks_exercised": sorted(exercised),
        "catalog_not_exercised": sorted(catalog - exercised),
        "spec_check_ids_not_in_catalog": [],
        "preflight_control_group": {
            "controls": len(preflight_controls),
            "checks_exercised": sorted({control["check"] for control in preflight_controls}),
            "correct_controls_passed": sum(1 for control in preflight_controls if control.get("correct_status") == CHECK_PASS),
            "seeded_failures_rejected": sum(1 for control in preflight_controls if control.get("seeded_status") == FAIL),
            "seeded_failures": len(preflight_controls),
            "missing_rules": preflight_missing,
            "duplicate_rules": preflight_duplicates,
            "correct_control_failures": preflight_correct_failures,
            "unrejected_seeded_failures": preflight_unrejected,
            "valid": preflight_valid,
            "oracle_rejections": 0,
        },
    }
    summary["exit_code"] = 0 if (
        summary["tasks_passed"] == summary["tasks"]
        and not summary["false_passes"]
        and not summary["missing_expected_checks"]
        and summary["preflight_control_group"]["valid"]
    ) else 1
    return summary


def run_benchmark(
    *,
    spec_dir: Path | str | None = None,
    only: list[str] | None = None,
    work_root: Path | str | None = None,
    keep: bool = False,
) -> dict:
    """Run every task recipe and return a deterministic JSON report.

    `only` is a diagnostic filter (a list of task ids); the default runs every spec. A task
    with no registered recipe is reported as unrunnable, never silently skipped.
    """
    from terraproof.evals.recipes import REGISTRY, validate_registry

    specs = load_specs(spec_dir)
    validate_registry({spec.id for spec in specs})
    if only:
        requested = set(only)
        unknown = requested - {spec.id for spec in specs}
        if unknown:
            raise SpecError(f"--only ids are not in the specs: {sorted(unknown)}")
        specs = [spec for spec in specs if spec.id in requested]
    if not specs:
        raise SpecError("no benchmark tasks selected")

    own_root = work_root is None
    if work_root is not None:
        base = Path(work_root)
    else:
        # Keep generated fixtures in the working project's cache; installed
        # package assets may be read-only. Each run gets a fresh owned root.
        local_tmp = Path.cwd() / ".terracache" / "evals"
        local_tmp.mkdir(parents=True, exist_ok=True)
        base = Path(tempfile.mkdtemp(prefix="terraproof-evals-", dir=local_tmp))
    base.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        for spec in sorted(specs, key=lambda item: item.id):
            records.append(_run_task(spec, REGISTRY.get(spec.id), base))
    finally:
        if own_root and not keep:
            shutil.rmtree(base, ignore_errors=True)

    preflight_controls = _run_preflight_control_group()
    summary = _summary(records, preflight_controls)
    return {
        "schema": SCHEMA,
        "command": "python -m terraproof.evals run",
        "spec_dir": _relative_spec_dir(spec_dir),
        "summary": summary,
        "tasks": records,
        "preflight_controls": preflight_controls,
        "limitations": LIMITATIONS + [
            "The separate preflight control group counts deterministic check rejection only; it does not claim that every seeded defect is caught, and oracle-only rejection is not counted as checker rejection."
        ],
    }


def _relative_spec_dir(spec_dir: Path | str | None) -> str:
    path = Path(spec_dir) if spec_dir is not None else Path("evals") / "tasks"
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def to_json(report: dict) -> str:
    from terraproof._common import jsonable

    return json.dumps(jsonable(report), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
