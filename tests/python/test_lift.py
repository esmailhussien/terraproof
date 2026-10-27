"""Phase 5 agent-lift harness, exercised only with offline adapters: no model is ever called."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import json
from pathlib import Path

import pytest

from terraproof.evals import lift
from terraproof.evals.__main__ import main as evals_main
from terraproof.evals.lift import (
    LIFT_TASKS, WITH, WITHOUT, AgentResult, Budget, LiftError, ReplayAdapter, ScriptedAdapter,
)
from terraproof.evals.recipes import REGISTRY
from terraproof.evals.specs import load_specs

FAST = ["indices-ndvi-physical-inputs", "stac-loader-double-decode"]
SPECS = {spec.id: spec for spec in load_specs()}

DRIVER_PATH = Path(__file__).resolve().parents[1] / "agent_lift.py"
DRIVER_SPEC = importlib.util.spec_from_file_location("agent_lift", DRIVER_PATH)
driver = importlib.util.module_from_spec(DRIVER_SPEC)
DRIVER_SPEC.loader.exec_module(driver)


class CountingAdapter(ScriptedAdapter):
    """A scripted agent that pretends to bill like a model host, for budget tests."""

    name = "counting"
    model_calls = True
    usd_capped = True

    def __init__(self, cost: float):
        super().__init__({WITH: "reference", WITHOUT: "seeded"})
        self.cost = cost
        self.calls = 0

    def run(self, request):
        self.calls += 1
        result = super().run(request)
        result.cost_usd = self.cost
        return result


def test_lift_tasks_are_real_specs_with_recipes_and_consistent_files():
    assert len(LIFT_TASKS) == 15
    for task in LIFT_TASKS:
        assert task.task_id in SPECS and task.task_id in REGISTRY
        names = set(task.inputs) | set(task.deliverable_names) | {wrong for _, wrong in task.seeded}
        assert len(names) == len(task.inputs) + len(task.deliverable_names) + len(task.seeded)
        assert all(target in task.deliverable_names for target, _ in task.seeded)


def test_calibration_accepts_references_and_rejects_seeded_echoed_and_missing(tmp_path):
    report = lift.calibrate(work_root=tmp_path)
    assert report["eligible"] is True
    for task in report["tasks"]:
        assert task["inputs_deterministic"] is True
        verdicts = {case["case"]: case["verdict"] for case in task["cases"]}
        assert verdicts["reference"] == "accepted"
        assert verdicts["missing"] == "missing"
        assert all(verdict == "rejected" for case, verdict in verdicts.items()
                   if case.startswith(("seeded:", "echo-input:")))


def test_brief_is_blind_to_pitfall_acceptance_and_seeded_outputs():
    for task in LIFT_TASKS:
        spec = SPECS[task.task_id]
        text = lift.brief(task, spec)
        assert spec.prompt in text
        assert spec.pitfall not in text and spec.inputs not in text
        assert not any(criterion in text for criterion in spec.acceptance)
        assert not any(wrong in text for _, wrong in task.seeded)
        assert all(name in text for name in task.inputs + task.deliverable_names)


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("condition", [WITHOUT, WITH])
def test_project_holds_only_inputs_brief_and_installer_files(tmp_path, condition):
    task = lift.lift_task("satellite-s2-baseline-offset-mask")
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    project = tmp_path / "project"
    installed = lift.prepare_project(task, SPECS[task.task_id], reference, project, condition=condition, agent="codex")
    files = _files(project)
    base = {"TASK.md"} | {f"inputs/{name}" for name in task.inputs}
    hidden = {(reference / name).read_bytes() for name in task.deliverable_names}
    hidden |= {(reference / wrong).read_bytes() for _, wrong in task.seeded}
    assert not hidden & set(files.values())
    assert not any(path.startswith("outputs/") for path in files)
    if condition == WITHOUT:
        assert set(files) == base and installed["skills"] == []
    else:
        extra = set(files) - base
        assert installed["install_exit"] == 0 and installed["skills"]
        assert "AGENTS.md" in extra
        assert all(path in {"AGENTS.md", ".codex/config.toml"} or path.startswith(".agents/skills/") for path in extra)
        assert "terraproof.mcp" in files["AGENTS.md"].decode("utf-8")


def test_scripted_run_scores_with_real_oracles_and_is_deterministic(tmp_path):
    adapter = ScriptedAdapter({WITH: "reference", WITHOUT: "seeded"})
    first = lift.run_lift(adapter, task_ids=FAST, runs=2, work_root=tmp_path / "a")
    second = lift.run_lift(adapter, task_ids=FAST, runs=2, work_root=tmp_path / "b")
    text = lift.to_json(first)
    assert text == lift.to_json(second)
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text
    summary = first["summary"]
    assert summary["complete_pairs"] == 4
    assert summary["pass_rate"] == {WITH: 1.0, WITHOUT: 0.0}
    assert summary["mcnemar"] == {"with_only": 4, "without_only": 0, "both": 0, "neither": 0, "exact_p": 0.125}
    assert summary["sign_flip_p"] == 0.5  # two tasks: the smallest exact p-value is 2/4
    runs = [run for task in first["tasks"] for run in task["runs"]]
    assert {run["verdict"] for run in runs if run["condition"] == WITHOUT} == {"rejected"}
    assert all(run["checks_ok"] and run["oracle_ok"] for run in runs if run["condition"] == WITH)
    assert first["calibration"]["eligible"] is True
    assert first["design"]["started_agent_runs"] == 8
    assert all(task["routed_skills"] for task in first["tasks"])
    # Projects are removed after scoring so a later agent cannot read an earlier run.
    assert not (tmp_path / "a" / "runs").exists() or not any((tmp_path / "a" / "runs").rglob("*.tif"))


def test_missing_and_echoed_outputs_fail(tmp_path):
    adapter = ScriptedAdapter({WITH: "echo-input", WITHOUT: "missing"})
    report = lift.run_lift(adapter, task_ids=FAST[:1], work_root=tmp_path)
    verdicts = {run["condition"]: run["verdict"] for run in report["tasks"][0]["runs"]}
    assert verdicts == {WITH: "rejected", WITHOUT: "missing"}
    assert report["summary"]["pass_rate"] == {WITH: 0.0, WITHOUT: 0.0}
    assert report["summary"]["secondary"][WITHOUT]["missing_or_error"] == 1


def test_recorded_outputs_replay_to_the_same_scores(tmp_path):
    recordings = tmp_path / "recordings"
    scripted = lift.run_lift(ScriptedAdapter({WITH: "reference", WITHOUT: "seeded"}), task_ids=FAST, runs=1,
                             work_root=tmp_path / "scripted", recordings_out=recordings)
    result = json.loads((recordings / FAST[0] / WITH / "run-0" / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    replayed = lift.run_lift(ReplayAdapter(recordings), task_ids=FAST, runs=1, work_root=tmp_path / "replay")
    assert replayed["summary"] == scripted["summary"]
    missing = lift.run_lift(ReplayAdapter(recordings), task_ids=FAST[:1], runs=2, work_root=tmp_path / "gap")
    second = [run for run in missing["tasks"][0]["runs"] if run["run"] == 1]
    assert {run["adapter_status"] for run in second} == {"failed"}


def test_model_adapters_need_opt_in_and_hard_budget_before_any_run(tmp_path):
    adapter = CountingAdapter(cost=0.1)
    with pytest.raises(LiftError, match="explicit opt-in"):
        lift.run_lift(adapter, task_ids=FAST, work_root=tmp_path, budget=Budget(max_runs=4, per_run_usd=1, total_usd=4))
    with pytest.raises(LiftError, match="approved run count"):
        lift.run_lift(adapter, task_ids=FAST, work_root=tmp_path, allow_model_calls=True)
    with pytest.raises(LiftError, match="per-run and a total USD cap"):
        lift.run_lift(adapter, task_ids=FAST, work_root=tmp_path, allow_model_calls=True, budget=Budget(max_runs=4))
    with pytest.raises(LiftError, match="exceed the approved maximum"):
        lift.run_lift(adapter, task_ids=FAST, runs=2, work_root=tmp_path, allow_model_calls=True,
                      budget=Budget(max_runs=4, per_run_usd=1, total_usd=8))
    assert adapter.calls == 0


def test_total_budget_stops_before_a_pair_that_could_overspend(tmp_path):
    adapter = CountingAdapter(cost=0.4)
    report = lift.run_lift(adapter, task_ids=FAST, runs=1, work_root=tmp_path, allow_model_calls=True,
                           budget=Budget(max_runs=4, per_run_usd=0.5, total_usd=1.5))
    assert adapter.calls == 2
    assert report["budget"]["spent_usd"] == 0.8
    statuses = [run["adapter_status"] for task in report["tasks"] for run in task["runs"]]
    assert statuses.count("not_run") == 2
    assert report["summary"]["complete_pairs"] == 1 and report["summary"]["incomplete_pairs"] == 1


def test_contaminated_runs_never_count_as_accepted(tmp_path):
    class Contaminated(ScriptedAdapter):
        def run(self, request):
            result = super().run(request)
            result.contamination = ["oracle-source"]
            return result

    report = lift.run_lift(Contaminated({WITH: "reference", WITHOUT: "reference"}), task_ids=FAST[:1],
                           work_root=tmp_path)
    assert {run["accepted"] for run in report["tasks"][0]["runs"]} == {False}
    assert report["summary"]["secondary"][WITH]["contaminated"] == 1


def test_schedule_is_paired_and_counterbalanced():
    tasks = [lift.lift_task(task_id) for task_id in FAST]
    order = lift.schedule(tasks, 2)
    assert [(run, task.task_id, pair[0]) for run, task, pair in order] == [
        (0, FAST[0], WITHOUT), (0, FAST[1], WITH), (1, FAST[0], WITH), (1, FAST[1], WITHOUT)]


def test_paired_statistics():
    assert lift.exact_mcnemar(0, 0) == 1.0
    assert lift.exact_mcnemar(5, 0) == pytest.approx(0.0625)
    assert lift.exact_mcnemar(3, 3) == 1.0
    assert lift.sign_flip_p([1.0, 1.0, 1.0]) == 0.25
    assert lift.sign_flip_p([0.5, -0.5]) == 1.0
    ci = lift.bootstrap_ci([0.0, 0.2, 0.4, 0.6])
    assert ci == lift.bootstrap_ci([0.0, 0.2, 0.4, 0.6]) and 0.0 <= ci[0] < ci[1] <= 0.6
    assert lift.bootstrap_ci([0.3]) is None
    small, large = lift.mcnemar_mde(54, 0.3), lift.mcnemar_mde(270, 0.3)
    assert 0 < large < small < 0.3 ** 0.5
    assert lift.mcnemar_mde(54, 0.3) == pytest.approx(0.2043, abs=0.001)  # Connor (1987): N=54, psi=0.3
    assert lift.mcnemar_mde(2, 0.01) is None


def test_scripted_behaviours_are_validated():
    with pytest.raises(LiftError):
        ScriptedAdapter({WITH: "reference"})
    with pytest.raises(LiftError):
        ScriptedAdapter({WITH: "reference", WITHOUT: "oracle"})
    with pytest.raises(LiftError):
        lift.lift_task("crs-axis-datum-control")


def test_cli_lift_is_offline_and_writes_a_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "lift.json"
    assert evals_main(["lift", "--task", FAST[0], "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["adapter"] == {"name": "scripted", "model_calls": False}
    assert evals_main(["lift", "--calibrate-only", "--task", FAST[0], "--out", str(out)]) == 0
    assert evals_main(["lift", "--adapter", "replay"]) == 2
    assert evals_main(["lift", "--task", "not-a-task"]) == 2


# -- real-host driver: only plan, argv and trace parsing are tested; no host is started ----
def test_driver_prints_a_plan_without_starting_any_host(capsys, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a host must not be probed or started without approval")

    monkeypatch.setattr(driver, "probe_codex", forbidden)
    monkeypatch.setattr(driver, "probe_claude", forbidden)
    monkeypatch.setattr(driver, "run_lift", forbidden)
    assert driver.main(["--agent-host", "claude", "--runs", "3", "--max-usd-per-run", "1", "--max-usd-total", "40"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_model_invocations"] == 54  # default cohort: the original nine
    assert plan["total_usd_ceiling"] == 40
    assert plan["command_to_approve"].endswith("--approve-model-calls 54")
    assert driver.main(["--agent-host", "codex", "--runs", "1", "--task", FAST[0]]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_model_invocations"] == 2 and plan["total_usd_ceiling"] is None
    with pytest.raises(SystemExit) as raised:
        driver.main(["--agent-host", "codex", "--runs", "1", "--approve-model-calls", "17"])
    assert raised.value.code == 2


def test_driver_host_commands_isolate_conditions(tmp_path):
    without = driver.codex_lift_command("codex.exe", tmp_path, tmp_path / "state", WITHOUT, "medium")
    with_mcp = driver.codex_lift_command("codex.exe", tmp_path, tmp_path / "state", WITH, "medium")
    for command in (without, with_mcp):
        assert command[command.index("--sandbox") + 1] == "workspace-write"
        assert "sandbox_workspace_write.network_access=false" in command
        disabled = [command[i + 1] for i, part in enumerate(command) if part == "--disable"]
        # Pilot 1 regression: Codex's own execution tools must stay at their defaults.
        assert not set(disabled) & set(driver.CODEX_EXECUTION_DEFAULTS)
        assert "browser_use" in disabled and "multi_agent" in disabled
        assert command[-1] == driver.PROMPT
    assert "mcp_servers={}" in without
    assert any(part.startswith("mcp_servers={terraproof=") for part in with_mcp)
    claude_without = driver.claude_lift_command("claude.exe", tmp_path, tmp_path / "e.json", WITHOUT, 1.0)
    claude_with = driver.claude_lift_command("claude.exe", tmp_path, tmp_path / "m.json", WITH, 1.0)
    assert "mcp__terraproof" not in claude_without[claude_without.index("--allowedTools") + 1]
    assert "mcp__terraproof__run_checks" in claude_with[claude_with.index("--allowedTools") + 1]
    assert claude_with[claude_with.index("--max-budget-usd") + 1] == "1.00"


def test_driver_traces_keep_counts_and_labels_only():
    seeded = ("ndvi_dn_ratio.tif",)
    codex_events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "python make_ndvi.py"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "type .agents/skills/x/SKILL.md"}},
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "terraproof", "tool": "run_checks",
                                            "arguments": {"paths": ["outputs/ndvi.tif"]}}},
        {"type": "item.completed", "item": {"type": "command_execution",
                                            "command": "python -c \"import terraproof.evals.oracles\""}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
    ]
    result = driver.codex_trace(codex_events, WITH, seeded)
    assert (result.status, result.tool_calls, result.terraproof_tool_calls, result.skill_reads) == ("completed", 4, 1, 1)
    assert result.contamination == ["harness-source", "oracle-source"]
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    assert "python" not in json.dumps(result.__dict__)
    leaked = driver.codex_trace(codex_events[:1] + [{"type": "turn.completed"}], WITHOUT, seeded)
    assert leaked.contamination == []
    assert driver.contamination_labels("python -m terraproof check x", WITHOUT, seeded) == {
        "terraproof-in-without:module-or-cli"}
    assert driver.contamination_labels("dir ndvi_dn_ratio.tif", WITH, seeded) == {"seeded-fixture-name"}
    claude_events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "spectral-indices"}},
            {"type": "tool_use", "name": "mcp__terraproof__inspect_dataset", "input": {"path": "inputs/red_dn.tif"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "python ndvi.py"}}]}},
        {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.42,
         "usage": {"input_tokens": 100, "output_tokens": 20}},
    ]
    claude = driver.claude_trace(claude_events, WITH, seeded)
    assert (claude.status, claude.cost_usd, claude.tool_calls, claude.terraproof_tool_calls, claude.skill_reads) == (
        "completed", 0.42, 3, 1, 1)
    assert driver.claude_trace([], WITH, seeded).status == "failed"


def test_agent_result_fields_round_trip_through_recordings():
    assert set(AgentResult.__dataclass_fields__) >= {"status", "cost_usd", "tool_calls", "terraproof_tool_calls",
                                                     "skill_reads", "contamination", "input_tokens", "output_tokens"}


# -- pilot 1 follow-up: sanitised per-call trace, preflight, no-attempt -------------------
SECRET = "python make_ndvi.py --token SECRET-ARG"


def _codex_item(kind, stamp, item):
    return (stamp, {"type": kind, "item": item})


def test_codex_trace_records_fixed_labels_numbers_and_turn_status_only():
    events = [
        (0.0, {"type": "turn.started"}),
        _codex_item("item.started", 1.0, {"id": "c1", "type": "command_execution", "command": SECRET,
                                          "status": "in_progress"}),
        _codex_item("item.completed", 3.5, {"id": "c1", "type": "command_execution", "command": SECRET,
                                            "aggregated_output": "SECRET-OUTPUT", "exit_code": 1, "status": "failed"}),
        _codex_item("item.completed", 4.0, {"id": "e1", "type": "error", "message": "SECRET warning"}),
        _codex_item("item.started", 5.0, {"id": "m1", "type": "mcp_tool_call", "server": "terraproof",
                                          "tool": "run_checks", "arguments": {"paths": ["SECRET.tif"]}}),
        _codex_item("item.completed", 5.25, {"id": "m1", "type": "mcp_tool_call", "server": "terraproof",
                                             "tool": "run_checks", "status": "completed"}),
        _codex_item("item.completed", 6.0, {"id": "m2", "type": "mcp_tool_call", "server": "evil", "tool": "SECRET"}),
        _codex_item("item.completed", 7.0, {"id": "f1", "type": "file_change", "changes": [{"path": "SECRET"}],
                                            "status": "completed"}),
        _codex_item("item.completed", 7.5, {"id": "a1", "type": "agent_message", "text": "SECRET prose"}),
        (8.0, {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}}),
    ]
    result = driver.codex_trace(events, WITH, ())
    assert result.calls == [
        {"tool": "command_execution", "category": "shell", "status": "failed", "exit_code": 1, "duration_ms": 2500},
        {"tool": "terraproof.run_checks", "category": "mcp:run_checks", "status": "completed", "exit_code": None,
         "duration_ms": 250},
        {"tool": "mcp", "category": "mcp:other", "status": "completed", "exit_code": None, "duration_ms": 0},
        {"tool": "file_change", "category": "file_edit", "status": "completed", "exit_code": None, "duration_ms": 0},
    ]
    assert (result.tool_calls, result.terraproof_tool_calls) == (4, 1)  # the error item is not a call
    assert result.turn == {"status": "completed", "reason": "ok", "error_types": ["unclassified"], "error_items": 1}
    assert "SECRET" not in json.dumps(result.__dict__)


@pytest.mark.parametrize("events, kwargs, status, turn_status", [
    ([(0.0, {"type": "turn.completed"})], {}, "completed", "completed"),
    ([(0.0, {"type": "turn.failed", "error": {"message": "unexpected argument --foo"}})], {}, "failed", "error"),
    ([(0.0, {"type": "error", "message": "Not logged in"})], {}, "failed", "error"),
    ([(0.0, {"type": "turn.started"})], {}, "failed", "aborted"),
    ([(0.0, {"type": "turn.started"})], {"timed_out": True}, "timeout", "timeout"),
    ([_codex_item("item.completed", 1.0, {"id": "c", "type": "command_execution", "command": "x",
                                          "status": "declined"}), (2.0, {"type": "turn.completed"})],
     {}, "completed", "sandbox-denial"),
    ([_codex_item("item.completed", 1.0, {"id": "c", "type": "command_execution", "command": "x", "exit_code": 1,
                                          "status": "failed", "aggregated_output": "Access is denied."}),
      (2.0, {"type": "turn.completed"})], {}, "completed", "sandbox-denial"),
])
def test_codex_turn_status_labels(events, kwargs, status, turn_status):
    result = driver.codex_trace(events, WITHOUT, (), **kwargs)
    assert (result.status, result.turn["status"]) == (status, turn_status)
    if turn_status == "completed":
        assert result.turn["reason"] == "no tool calls"
    if turn_status == "sandbox-denial":
        assert "sandbox_denied" in result.turn["error_types"]
    if "unexpected argument" in json.dumps(events):
        assert result.turn["error_types"] == ["unsupported_flag_or_config"]
    if "Not logged in" in json.dumps(events):
        assert result.turn["error_types"] == ["auth_unavailable"]


def test_claude_trace_pairs_results_and_labels_refusals_and_budget_stops():
    events = [
        (0.0, {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": SECRET}},
            {"type": "tool_use", "id": "t2", "name": "mcp__terraproof__preflight", "input": {"plan": "SECRET"}},
            {"type": "tool_use", "id": "t3", "name": "SECRET_TOOL", "input": {}}]}}),
        (1.5, {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "SECRET"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "SECRET"}]}}),
        (2.0, {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 1.01}),
    ]
    result = driver.claude_trace(events, WITH, ())
    assert result.calls == [
        {"tool": "Bash", "category": "shell", "status": "failed", "exit_code": None, "duration_ms": 1500},
        {"tool": "terraproof.preflight", "category": "mcp:preflight", "status": "completed", "exit_code": None,
         "duration_ms": 1500},
        {"tool": "other", "category": "other", "status": "started", "exit_code": None, "duration_ms": None},
    ]
    assert result.status == "failed" and result.cost_usd == 1.01
    assert result.turn["status"] == "error" and result.turn["error_types"] == ["error_max_budget_usd"]
    assert "SECRET" not in json.dumps(result.__dict__)
    refused = driver.claude_trace([(0.0, {"type": "assistant", "message": {"stop_reason": "refusal", "content": []}}),
                                   (0.1, {"type": "result", "subtype": "success", "is_error": False})], WITHOUT, ())
    assert (refused.status, refused.turn["status"]) == ("failed", "refused")


def test_no_attempt_is_classified_from_calls_and_deliverables():
    present = {"ndvi.tif": False}
    assert lift.classify_attempt(AgentResult(status="completed"), present) == lift.NO_ATTEMPT
    other_only = AgentResult(status="completed", calls=[{"category": "mcp:list_skills"}])
    assert lift.classify_attempt(other_only, present) == lift.NO_ATTEMPT
    tried = AgentResult(status="completed", calls=[{"category": "shell"}])
    assert lift.classify_attempt(tried, present) == "completed"
    assert lift.classify_attempt(AgentResult(status="completed"), {"ndvi.tif": True}) == "completed"
    assert lift.classify_attempt(AgentResult(status="timeout"), present) == "timeout"


class SilentAdapter(lift.Adapter):
    """Mimics pilot 1: the host completes a turn but runs nothing and writes nothing."""

    name = "silent"

    def __init__(self, checks=None):
        self.checks = checks or {}
        self.calls = 0

    def preflight(self, request):
        return dict(self.checks)

    def run(self, request):
        self.calls += 1
        return AgentResult(status="completed", input_tokens=37972, output_tokens=241,
                           calls=[{"tool": "mcp", "category": "mcp:other", "status": "completed",
                                   "exit_code": None, "duration_ms": 5}] if request.condition == WITH else [],
                           turn={"status": "completed", "reason": "no tool calls", "error_types": [], "error_items": 0})


def test_pilot1_shape_is_reported_as_no_attempt_and_unused_treatment(tmp_path):
    report = lift.run_lift(SilentAdapter(), task_ids=FAST[:1], work_root=tmp_path)
    runs = {run["condition"]: run for run in report["tasks"][0]["runs"]}
    assert {run["adapter_status"] for run in runs.values()} == {lift.NO_ATTEMPT}
    assert {run["host_status"] for run in runs.values()} == {"completed"}
    assert runs[WITH]["treatment_used"] is False and runs[WITHOUT]["treatment_used"] is None
    assert all(run["preflight"]["ok"] for run in runs.values())
    summary = report["summary"]
    assert summary["secondary"][WITH]["no_attempt"] == summary["secondary"][WITHOUT]["no_attempt"] == 1
    assert summary["secondary"][WITH]["treatment_not_used"] == 1
    assert summary["secondary"][WITH]["calls_by_category"] == {"mcp:other": 1}
    assert summary["treatment_delivery"]["with_runs_started"] == 1
    assert summary["treatment_delivery"]["with_runs_using_terraproof"] == 0


def test_failed_preflight_starts_no_agent(tmp_path):
    adapter = SilentAdapter({"sandbox_shell": False})
    report = lift.run_lift(adapter, task_ids=FAST[:1], work_root=tmp_path)
    assert adapter.calls == 0 and report["design"]["started_agent_runs"] == 0
    runs = report["tasks"][0]["runs"]
    assert {run["adapter_status"] for run in runs} == {lift.PREFLIGHT_FAILED}
    assert all(run["preflight"]["checks"]["sandbox_shell"] is False for run in runs)
    assert report["summary"]["complete_pairs"] == 0 and report["summary"]["incomplete_pairs"] == 1

    class Broken(SilentAdapter):
        def preflight(self, request):
            raise RuntimeError("probe crashed")

    broken = Broken()
    report = lift.run_lift(broken, task_ids=FAST[:1], work_root=tmp_path / "broken")
    assert broken.calls == 0
    assert report["tasks"][0]["runs"][0]["preflight"]["checks"]["adapter_preflight_error"] == "RuntimeError"


def test_preflight_only_needs_no_approval_and_starts_nothing(tmp_path):
    adapter = CountingAdapter(cost=1.0)
    report = lift.run_lift(adapter, task_ids=FAST[:1], work_root=tmp_path, preflight_only=True)
    assert adapter.calls == 0 and report["design"]["preflight_only"] is True
    assert {run["adapter_status"] for run in report["tasks"][0]["runs"]} == {lift.PREFLIGHT_ONLY}


def test_project_preflight_checks_treatment_files(tmp_path):
    task = lift.lift_task(FAST[0])
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    with_project, without_project = tmp_path / "with", tmp_path / "without"
    installed = lift.prepare_project(task, SPECS[task.task_id], reference, with_project, condition=WITH, agent="codex")
    lift.prepare_project(task, SPECS[task.task_id], reference, without_project, condition=WITHOUT, agent="codex")
    checks = lift.project_preflight(task, with_project, condition=WITH, agent="codex", routed=installed["skills"])
    assert checks == {"inputs_present": True, "outputs_writable": True, "skills_installed": True, "mcp_registered": True,
                      "routed_skill_count": len(installed["skills"])}
    assert lift.project_preflight(task, without_project, condition=WITHOUT, agent="codex", routed=[]) == {
        "inputs_present": True, "outputs_writable": True, "no_terraproof_files": True}
    (with_project / "AGENTS.md").unlink()
    assert lift.project_preflight(task, with_project, condition=WITH, agent="codex",
                                  routed=installed["skills"])["mcp_registered"] is False


def test_prompt_input_parser_reads_names_and_block_only():
    document = [{"role": "developer", "content": [{"type": "input_text", "text": "## Skills\n- gdal: SECRET\n- geomaster: x"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "<!-- terraproof:codex:begin --> SECRET"}]}]
    assert driver._prompt_input_names(document) == ({"gdal", "geomaster"}, True)
    assert driver._prompt_input_names({"not": "a list"}) == (set(), False)


def test_driver_preflight_only_starts_no_agent(tmp_path, monkeypatch):
    seen = {}

    def fake_run_lift(adapter, **kwargs):
        seen.update(kwargs)
        return {"tasks": [], "design": {"started_agent_runs": 0}, "budget": {"spent_usd": 0.0}}

    monkeypatch.setattr(driver, "probe_codex", lambda executable=None: ("codex.exe", "ok", "codex-cli test"))
    monkeypatch.setattr(driver, "run_lift", fake_run_lift)
    monkeypatch.setattr(driver, "to_json", lambda report: json.dumps(report))
    out = tmp_path / "lift.json"
    assert driver.main(["--agent-host", "codex", "--task", FAST[0], "--preflight-only", "--out", str(out)]) == 0
    assert seen["preflight_only"] is True and seen["allow_model_calls"] is False and seen["runs"] == 1
    assert seen["recordings_out"] is None
    assert json.loads((tmp_path / "lift-preflight.json").read_text())["host"]["version"] == "codex-cli test"
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "codex", "--preflight-only", "--approve-model-calls", "18"])


# -- pilot 2 follow-up: built-in resource tools, code-mode-only catalog, Claude MCP config --
def _pilot2_events():
    """The pilot 2 shape: two built-in resource calls on server "codex", 0 ms, then completion."""
    events = [(0.0, {"type": "turn.started"})]
    for index, tool in enumerate(("list_mcp_resources", "list_mcp_resource_templates")):
        item = {"id": f"r{index}", "type": "mcp_tool_call", "server": "codex", "tool": tool,
                "arguments": {"cursor": "SECRET"}}
        events.append(_codex_item("item.started", 2.0, dict(item, status="in_progress")))
        events.append(_codex_item("item.completed", 2.0, dict(item, status="completed")))
    events.append((3.0, {"type": "turn.completed", "usage": {"input_tokens": 40373, "output_tokens": 314}}))
    return events


def test_pilot2_resource_calls_are_labelled_and_are_not_an_attempt():
    result = driver.codex_trace(_pilot2_events(), WITHOUT, ())
    assert result.calls == [
        {"tool": "codex.list_mcp_resources", "category": "mcp:codex-resource", "status": "completed",
         "exit_code": None, "duration_ms": 0},
        {"tool": "codex.list_mcp_resource_templates", "category": "mcp:codex-resource", "status": "completed",
         "exit_code": None, "duration_ms": 0},
    ]
    assert result.terraproof_tool_calls == 0 and result.turn["status"] == "completed"
    assert lift.classify_attempt(result, {"ndvi.tif": False}) == lift.NO_ATTEMPT
    assert "SECRET" not in json.dumps(result.__dict__)
    # A third-party server that happens to reuse a Terraproof tool name is still not Terraproof.
    spoof = [_codex_item("item.completed", 1.0, {"id": "s", "type": "mcp_tool_call", "server": "other",
                                                 "tool": "run_checks", "status": "completed"}),
             (2.0, {"type": "turn.completed"})]
    assert driver.codex_trace(spoof, WITH, ()).calls[0]["category"] == "mcp:other"


class Pilot2Adapter(lift.Adapter):
    name = "pilot2-replay"

    def run(self, request):
        return driver.codex_trace(_pilot2_events(), request.condition, ())


def test_pilot2_shape_fails_the_main_run_gate(tmp_path):
    report = lift.run_lift(Pilot2Adapter(), task_ids=FAST[:1], work_root=tmp_path)
    runs = {run["condition"]: run for run in report["tasks"][0]["runs"]}
    assert {run["adapter_status"] for run in runs.values()} == {lift.NO_ATTEMPT}
    assert {run["verdict"] for run in runs.values()} == {"missing"}
    secondary = report["summary"]["secondary"]
    for condition in (WITH, WITHOUT):
        assert secondary[condition]["calls_by_category"] == {"mcp:codex-resource": 2}
        assert "shell" not in secondary[condition]["calls_by_category"]
        assert secondary[condition]["no_attempt"] == 1
    assert secondary[WITH]["treatment_not_used"] == 1
    assert report["summary"]["treatment_delivery"]["with_runs_using_terraproof"] == 0


def test_codex_catalog_check_refuses_code_mode_only_models():
    only = {"models": [{"slug": "a", "visibility": "list", "tool_mode": "code_mode_only", "shell_type": "unified_exec"},
                       {"slug": "h", "visibility": "hide", "tool_mode": None, "shell_type": "unified_exec"}]}
    assert driver.codex_model_tool_modes(only) == {"listed_models": 1, "tool_modes": ["code_mode_only"],
                                                   "shell_types": ["unified_exec"],
                                                   "direct_tool_model_available": False}
    mixed = {"models": only["models"] + [{"slug": "d", "visibility": "list", "tool_mode": None,
                                          "shell_type": "unified_exec"}]}
    assert driver.codex_model_tool_modes(mixed)["direct_tool_model_available"] is True
    assert driver.codex_model_tool_modes([])["direct_tool_model_available"] is False


def test_claude_mcp_config_is_explicit_and_outside_the_project(tmp_path):
    task = lift.lift_task(FAST[0])
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    adapter = driver.ClaudeHostAdapter("claude.exe")
    for condition in (WITH, WITHOUT):
        project = tmp_path / condition / "project"
        lift.prepare_project(task, SPECS[task.task_id], reference, project, condition=condition, agent="claude")
        request = lift.AgentRequest(task.task_id, condition, 0, project, "", 10, 1.0)
        config = adapter._config(request)
        assert project not in config.parents
        servers = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
        if condition == WITH:
            installed = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["terraproof"]
            assert servers == {"terraproof": installed}
        else:
            assert servers == {}


# -- pilot 3 follow-up: native Claude executable, ceiling flags ------------------------------
def test_claude_executable_option_refuses_wrappers_and_is_in_the_approved_command(tmp_path, capsys):
    wrapper = tmp_path / "claude.cmd"
    wrapper.write_text("@echo off\n", encoding="utf-8")
    if os.name == "nt":
        assert driver.probe_claude(str(wrapper))[0] is None
    assert driver.probe_claude(str(tmp_path / "missing.exe"))[:2] == (None, "claude executable not found")
    native = tmp_path / "claude.exe"
    assert driver.main(["--agent-host", "claude", "--runs", "3", "--claude-executable", str(native),
                        "--max-usd-per-run", "1", "--max-usd-total", "54"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert f"--claude-executable {native}" in plan["command_to_approve"]
    assert plan["planned_model_invocations"] == 54 and plan["total_usd_ceiling"] == 54


def test_ceiling_tasks_are_flagged_without_changing_the_primary_analysis(tmp_path):
    both = lift.run_lift(ScriptedAdapter({WITH: "reference", WITHOUT: "reference"}), task_ids=FAST[:1],
                         work_root=tmp_path / "both")
    summary = both["summary"]
    assert summary["per_task"][0]["baseline_pass_rate"] == 1.0 and summary["per_task"][0]["ceiling"] is True
    assert summary["ceiling_tasks"] == [FAST[0]] and summary["tasks_with_headroom"] == 0
    assert summary["mean_task_difference"] == 0.0 and summary["mcnemar"]["exact_p"] == 1.0
    lifted = lift.run_lift(ScriptedAdapter({WITH: "reference", WITHOUT: "seeded"}), task_ids=FAST[:1],
                           work_root=tmp_path / "lifted")
    assert lifted["summary"]["per_task"][0]["ceiling"] is False
    assert lifted["summary"]["ceiling_tasks"] == [] and lifted["summary"]["tasks_with_headroom"] == 1


# -- main run follow-up: path-text false positives, forced rejections, without isolation ------
MAIN_RUN_READ = {"file_path": "C:\\Users\\u\\AppData\\Local\\Temp\\terraproof-lift-host-ab12\\runs\\"
                              "sar-db-linear-monthly-mean\\run-1\\without\\project\\TASK.md"}


def test_main_run_read_tool_path_is_path_text_not_contamination():
    """Main run 1: every flagged without run, and only those, used Claude Code's Read tool,
    whose absolute file_path then contained the old terraproof-lift-host-* project prefix."""
    events = [
        (0.0, {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r", "name": "Read", "input": MAIN_RUN_READ},
            {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "python make_mean.py"}}]}}),
        (1.0, {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r"},
                                                       {"type": "tool_result", "tool_use_id": "b"}]}}),
        (2.0, {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.1}),
    ]
    result = driver.claude_trace(events, WITHOUT, ())
    assert result.contamination == [] and result.diagnostics == ["terraproof-path-text"]
    assert "terraproof-lift-host" not in json.dumps(result.__dict__)
    in_with = driver.claude_trace(events, WITH, ())
    assert in_with.contamination == [] and in_with.diagnostics == []


@pytest.mark.parametrize("text, labels", [
    ("python -m terraproof check outputs/x.tif", ["terraproof-in-without:module-or-cli"]),
    ("terraproof check outputs/x.tif", ["terraproof-in-without:module-or-cli"]),
    ('python -c "import terraproof"', ["terraproof-in-without:import"]),
    ("from terraproof.checks import run_checks", ["terraproof-in-without:import"]),
    ("pip list | findstr terraproof", ["terraproof-in-without:package-query"]),
    ("pip show terraproof", ["terraproof-in-without:package-query"]),
    ("dir C:/venv/Lib/site-packages/terraproof", ["terraproof-in-without:package-query"]),
    ("mcp__terraproof__run_checks", ["terraproof-in-without:mcp"]),
    ("cat .claude/skills/terraproof-x/SKILL.md", ["terraproof-in-without:skill"]),
    ("echo terraproof", ["terraproof-in-without:mention"]),
    ("C:\\Users\\u\\.venvs\\terraproof-py312\\Scripts\\python.exe make.py", []),
    ("cd /c/Temp/terraproof-lift-host-x/runs/001/project && python make.py", []),
    ("python make.py", []),
])
def test_terraproof_use_sub_labels_distinguish_use_from_paths(text, labels):
    assert sorted(driver.contamination_labels(text, WITHOUT, ())) == labels
    assert driver.incidental_labels(text, WITHOUT) == ({"terraproof-path-text"} if not labels and "terraproof" in text
                                                        else set())
    assert driver.contamination_labels(text, WITH, ()) == set()


def test_contamination_forced_rejection_keeps_the_underlying_verdict(tmp_path):
    class Flagged(ScriptedAdapter):
        def run(self, request):
            result = super().run(request)
            if request.condition == WITHOUT:
                result.contamination = ["terraproof-in-without:import"]
            return result

    report = lift.run_lift(Flagged({WITH: "reference", WITHOUT: "reference"}), task_ids=FAST[:1], work_root=tmp_path)
    runs = {run["condition"]: run for run in report["tasks"][0]["runs"]}
    assert runs[WITHOUT]["accepted"] is False and runs[WITHOUT]["accepted_before_contamination"] is True
    assert runs[WITHOUT]["contamination_forced_rejection"] is True
    summary = report["summary"]
    assert summary["pass_rate"] == {WITH: 1.0, WITHOUT: 0.0}  # the pre-specified rule is unchanged
    assert summary["secondary"][WITHOUT]["forced_rejections"] == 1
    sensitivity = summary["sensitivity_contamination_ignored"]
    assert sensitivity["label"].startswith("not pre-specified")
    assert sensitivity["pass_rate"] == {WITH: 1.0, WITHOUT: 1.0} and sensitivity["mean_task_difference"] == 0.0
    clean = lift.run_lift(ScriptedAdapter({WITH: "reference", WITHOUT: "seeded"}), task_ids=FAST[:1],
                          work_root=tmp_path / "clean")
    assert clean["summary"]["sensitivity_contamination_ignored"] is None


def _main_run_reports():
    """Synthetic replay of main run 1's per-task shape (9 tasks x 3 pairs), labels only."""
    shape = {  # task: (without accepted per run, without runs flagged although checks+oracle passed, flagged+oracle-rejected)
        "ceiling-1": ({0, 1, 2}, set(), set()), "ceiling-2": ({0, 1, 2}, set(), set()),
        "ceiling-3": ({0, 1, 2}, set(), set()), "ceiling-4": ({0, 1, 2}, set(), set()),
        "ceiling-5": ({0, 1, 2}, set(), set()),
        "landsat": (set(), set(), {0, 1, 2}),
        "sar": ({0, 2}, {1}, set()), "s2": ({0, 2}, {1}, set()), "ts": ({0, 2}, {1}, set()),
    }
    reports = []
    for task, (accepted, forced, oracle_rejected) in shape.items():
        runs = []
        for run in range(3):
            runs.append({"run": run, "condition": WITH, "verdict": "accepted", "accepted": True, "caught_by": [],
                         "adapter_status": "completed", "treatment_used": True, "checks_ok": True, "oracle_ok": True,
                         "agent": {"contamination": [], "calls": []}})
            flagged = run in forced or run in oracle_rejected
            runs.append({"run": run, "condition": WITHOUT, "verdict": "accepted" if run in accepted else "rejected",
                         "accepted": run in accepted, "caught_by": ["oracle"] if run in oracle_rejected else [],
                         "adapter_status": "completed", "treatment_used": None, "checks_ok": True,
                         "oracle_ok": run not in oracle_rejected,
                         "agent": {"contamination": ["terraproof-in-without"] if flagged else [], "calls": []}})
        reports.append({"id": task, "runs": runs})
    return reports


def test_main_run_shape_reproduces_primary_and_sensitivity_numbers():
    summary = lift.summarize(_main_run_reports())
    assert summary["pass_rate"] == {WITH: 1.0, WITHOUT: 0.777778}
    assert summary["mean_task_difference"] == 0.222222 and summary["sign_flip_p"] == 0.125
    assert summary["mcnemar"] == {"with_only": 6, "without_only": 0, "both": 21, "neither": 0, "exact_p": 0.03125}
    assert len(summary["ceiling_tasks"]) == 5 and summary["tasks_with_headroom"] == 4
    assert summary["secondary"][WITHOUT]["forced_rejections"] == 3  # inferred from checks_ok and oracle_ok
    sensitivity = summary["sensitivity_contamination_ignored"]
    assert sensitivity["pass_rate"] == {WITH: 1.0, WITHOUT: 0.888889}
    assert sensitivity["mean_task_difference"] == 0.111111 and sensitivity["sign_flip_p"] == 1.0
    assert sensitivity["mcnemar"] == {"with_only": 3, "without_only": 0, "both": 24, "neither": 0, "exact_p": 0.25}


def test_run_directories_reveal_neither_task_nor_condition(tmp_path):
    seen = []

    class Recording(ScriptedAdapter):
        def run(self, request):
            seen.append(str(request.project))
            return super().run(request)

    lift.run_lift(Recording({WITH: "reference", WITHOUT: "reference"}), task_ids=FAST, work_root=tmp_path)
    assert len(seen) == 4
    for path in seen:
        relative = Path(path).relative_to(tmp_path).as_posix()
        assert re.fullmatch(r"runs/\d{3}/project", relative), relative
        assert not any(word in relative for word in ("with", "ndvi", "stac", "decode"))


def test_host_env_without_uses_the_agent_python_and_drops_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", "src")
    agent_python = tmp_path / "neutral" / "python.exe"
    without = driver.host_env(WITHOUT, str(agent_python))
    assert "PYTHONPATH" not in without and without["PATH"].split(os.pathsep)[0] == str(agent_python.parent)
    with_env = driver.host_env(WITH, str(agent_python))
    assert "PYTHONPATH" not in with_env and with_env["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)


def _python_shim(directory: Path, *flags: str) -> Path:
    directory.mkdir(parents=True)
    if os.name == "nt":
        shim = directory / "python.bat"
        shim.write_text(f'@"{sys.executable}" {" ".join(flags)} %*\r\n', encoding="utf-8")
    else:
        shim = directory / "python"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" {" ".join(flags)} "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return shim


def test_without_isolation_checks_detect_importable_terraproof_and_named_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(Path(lift.__file__).resolve().parents[2]))
    project = tmp_path / "runs" / "001" / "project"
    project.mkdir(parents=True)
    isolated = _python_shim(tmp_path / "isolated-bin", "-I", "-S")  # no site-packages, no PYTHONPATH
    env = driver.host_env(WITHOUT, str(isolated))
    # tmp_path lives inside the checkout (pytest --basetemp), whose path may itself contain
    # "terraproof" (CI: .../terraproof/terraproof/...); the neutral rule is tested on strings below.
    base_neutral = "terraproof" not in str(tmp_path.resolve()).lower()
    assert driver.without_isolation_checks(project, str(isolated), env) == {
        "without_agent_python_set": True, "without_terraproof_not_importable": True,
        "without_paths_neutral": base_neutral}
    leaky = _python_shim(tmp_path / "leaky-bin")
    env = driver.host_env(WITHOUT, str(leaky))
    env["PYTHONPATH"] = str(Path(lift.__file__).resolve().parents[2])  # e.g. a checkout's src
    assert driver.without_isolation_checks(project, str(leaky), env)["without_terraproof_not_importable"] is False
    named = _python_shim(tmp_path / "terraproof-venv", "-I", "-S")
    env = driver.host_env(WITHOUT, str(named))
    assert driver.without_isolation_checks(project, str(named), env)["without_paths_neutral"] is False
    assert driver.without_isolation_checks(project, None, driver.host_env(WITHOUT, str(isolated)))[
        "without_agent_python_set"] is False


def test_driver_carries_the_agent_python_into_the_approved_command(capsys, tmp_path):
    agent_python = tmp_path / "geo-agent" / "python.exe"
    assert driver.main(["--agent-host", "claude", "--runs", "1", "--task", FAST[0],
                        "--agent-python-without", str(agent_python)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert f"--agent-python-without {agent_python}" in plan["command_to_approve"]


def test_paths_neutral_rule_is_independent_of_the_checkout_location():
    assert driver.paths_neutral(r"C:\Temp\paired-run-ab12\runs\001\project",
                                r"C:\venvs\geo-agent-py312\Scripts", r"C:\venvs\geo-agent-py312\Scripts\python.exe")
    assert driver.paths_neutral("/tmp/paired-run-x/runs/002/project", "/opt/geo/bin", "/opt/geo/bin/python")
    assert not driver.paths_neutral(r"C:\Temp\terraproof-lift-host-ab12\runs\001\project", r"C:\venvs\geo")
    assert not driver.paths_neutral("/tmp/paired-run-x/project", "/home/u/.venvs/TerraProof-py312/bin")
    assert not driver.paths_neutral("/tmp/paired-run-x/project", "/opt/geo/bin", "/home/runner/work/terraproof/python")
    assert driver.paths_neutral()


def test_cohorts_partition_the_registry_and_runs_default_to_the_original_nine():
    assert set(lift.COHORTS) == {"original", "harder", "headroom-development", "headroom-confirmation"}
    assert lift.DEFAULT_COHORT == "original"
    original, harder = lift.COHORTS["original"], lift.COHORTS["harder"]
    assert len(original) == 9 and len(harder) == 6
    assert not {t.task_id for t in original} & {t.task_id for t in harder}
    assert original + harder == LIFT_TASKS
    assert lift._select(None, "original") == list(original)
    assert lift._select(None, "harder") == list(harder)
    assert lift._select(None) == list(LIFT_TASKS)  # calibration covers every task
    assert [t.task_id for t in lift._select([harder[0].task_id], "original")] == [harder[0].task_id]
    with pytest.raises(LiftError):
        lift._select(None, "everything")


def test_driver_derives_the_total_usd_cap_from_the_selected_cohort(capsys, monkeypatch):
    def forbidden(*args, **kwargs):  # pragma: no cover - the plan must not start anything
        raise AssertionError("a host must not be probed or started without approval")

    monkeypatch.setattr(driver, "probe_claude", forbidden)
    monkeypatch.setattr(driver, "run_lift", forbidden)
    assert driver.main(["--agent-host", "claude", "--runs", "3"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["cohort"] == "original" and len(plan["tasks"]) == 9
    assert plan["planned_model_invocations"] == 54 and plan["total_usd_ceiling"] == 54
    assert "--cohort original" in plan["command_to_approve"] and "--max-usd-total 54" in plan["command_to_approve"]
    assert driver.main(["--agent-host", "claude", "--runs", "3", "--cohort", "harder", "--max-usd-per-run", "2"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["cohort"] == "harder" and len(plan["tasks"]) == 6
    assert plan["planned_model_invocations"] == 36 and plan["total_usd_ceiling"] == 72
    assert plan["command_to_approve"].endswith("--max-usd-total 72 --timeout 900 --approve-model-calls 36")
    assert driver.main(["--agent-host", "claude", "--runs", "1", "--task", FAST[0]]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["cohort"] is None and "--cohort" not in plan["command_to_approve"]
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "claude", "--cohort", "harder", "--task", FAST[0]])


def test_offline_cli_refuses_task_with_cohort(capsys):
    assert evals_main(["lift", "--cohort", "harder", "--task", FAST[0]]) == 2
    assert "give one of them" in capsys.readouterr().err


# -- Antigravity harder-cohort follow-up (2026-10-26): probe leak and introspection scope ----------
@pytest.mark.parametrize("command, labels", [
    ("import inspect, terraproof.checks.raster as r\nprint(inspect.getsource(r.check_cog_layout))", set()),
    ("from terraproof import evidence\nimport inspect\nprint(inspect.getsource(evidence.grade_for))", set()),
    ("import inspect, numpy\nprint(inspect.getsource(numpy.gradient))", set()),
    ("from terraproof import evals; import inspect; print(inspect.getsource(evals))", {"python-introspection"}),
    ("import importlib.resources as r; print(r.files('terraproof') / 'evals' / 'recipes')", {"python-introspection"}),
    ("import inspect, terraproof.evals.harder_oracles as h; print(inspect.getsource(h))",
     {"harness-source", "oracle-source", "python-introspection"}),
])
def test_introspection_is_contamination_only_when_it_can_reach_harness_or_oracle_code(command, labels):
    text = json.dumps({"CommandLine": f'python -c "{command}"'})
    assert driver.contamination_labels(text, WITH, ()) == labels


def test_preflight_probe_leaves_nothing_beside_the_project_and_names_no_terraproof(tmp_path):
    task = lift.lift_task(FAST[0])
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    project = tmp_path / "run" / "project"
    lift.prepare_project(task, SPECS[task.task_id], reference, project, condition=WITHOUT, agent="claude")
    before = sorted(path.name for path in project.parent.iterdir())
    checks = driver.unsandboxed_probe(project, task.task_id, driver.host_env(WITH))
    assert checks["unsandboxed_python"] and checks["unsandboxed_write_outputs"]
    assert sorted(path.name for path in project.parent.iterdir()) == before
    assert "terraproof" not in driver.PREFLIGHT_SCRIPT.lower()
    lift.project_preflight(task, project, condition=WITHOUT, agent="claude", routed=[])
    assert not any("terraproof" in path.name.lower() for path in project.rglob("*"))


def test_host_preflights_remove_their_probe_scripts(tmp_path):
    task = lift.lift_task(FAST[0])
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    for adapter in (driver.ClaudeHostAdapter("claude.exe"),
                    driver.AntigravityHostAdapter("agy.exe", "m", home=tmp_path / "home")):
        project = tmp_path / adapter.name / "project"
        lift.prepare_project(task, SPECS[task.task_id], reference, project, condition=WITHOUT, agent="claude")
        adapter.preflight(lift.AgentRequest(task.task_id, WITHOUT, 0, project, "", 10, 1.0))
        assert not (project.parent / "preflight_probe.py").exists()


# -- Phase 6 B6: the "with" agent gets a product-only interpreter -----------------------------------
def test_with_isolation_probe_needs_terraproof_without_its_evals(tmp_path):
    env = driver.host_env(WITH)
    checkout = driver.with_isolation_checks(tmp_path, None, env)
    # This test environment has the whole checkout, oracles included.
    assert checkout == {"with_agent_python_set": False, "with_terraproof_importable": True,
                        "with_evals_not_importable": False}
    product = tmp_path / "product-only"
    (product / "terraproof").mkdir(parents=True)
    (product / "terraproof" / "__init__.py").write_text("", encoding="utf-8")
    shadowed = dict(env, PYTHONPATH=str(product))
    assert driver.with_isolation_checks(tmp_path, sys.executable, shadowed) == {
        "with_agent_python_set": True, "with_terraproof_importable": True, "with_evals_not_importable": True}


def test_host_env_puts_the_with_interpreter_first_and_drops_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "checkout-src")
    with_python = tmp_path / "with-venv" / "Scripts" / "python.exe"
    env = driver.host_env(WITH, None, str(with_python))
    assert env["PATH"].split(os.pathsep)[0] == str(with_python.parent) and "PYTHONPATH" not in env
    default = driver.host_env(WITH)
    assert default["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)
    assert "PYTHONPATH" not in default


def test_driver_carries_the_with_python_into_the_approved_command(capsys, tmp_path):
    with_python = tmp_path / "with-venv" / "python.exe"
    assert driver.main(["--agent-host", "codex", "--runs", "1", "--task", FAST[0],
                        "--agent-python-with", str(with_python)]) == 0
    assert f"--agent-python-with {with_python}" in json.loads(capsys.readouterr().out)["command_to_approve"]


def test_preflight_probe_reads_a_raster_input_even_when_a_catalog_comes_first():
    assert lift.lift_task("hr-dekad-rainfall").inputs[0] == "catalog.json"
    assert driver._probe_input("hr-dekad-rainfall").endswith(".tif")


def test_with_project_for_an_unrouted_task_still_needs_the_checks(tmp_path):
    task = lift.lift_task("hr-elevation-change-mixed-units")
    from terraproof.evals import headroom
    spec = headroom.specs()[task.task_id]
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    project = tmp_path / "with" / "project"
    installed = lift.prepare_project(task, spec, reference, project, condition=WITH, agent="opencode")
    assert installed == {"install_exit": 0, "skills": []}
    checks = lift.project_preflight(task, project, condition=WITH, agent="opencode", routed=[])
    assert checks["skills_installed"] and checks["mcp_registered"] and checks["routed_skill_count"] == 0
