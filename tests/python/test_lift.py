"""Phase 5 agent-lift harness, exercised only with offline adapters: no model is ever called."""

from __future__ import annotations

import importlib.util
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
    assert len(LIFT_TASKS) == 9
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
    assert plan["planned_model_invocations"] == 54
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
        assert "shell_tool" not in [command[i + 1] for i, part in enumerate(command) if part == "--disable"]
        assert command[-1] == driver.PROMPT
    assert not any(part.startswith("mcp_servers=") for part in without)
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
    assert driver.contamination_labels("python -m terraproof check x", WITHOUT, seeded) == {"terraproof-in-without"}
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
