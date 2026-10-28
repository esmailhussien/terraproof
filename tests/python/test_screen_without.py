"""E4's without-only screen, exercised only with offline adapters: no model is ever called."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from terraproof.evals.lift import COHORTS, WITH, WITHOUT, Budget, LiftError, ScriptedAdapter, lift_task

SCREEN_PATH = Path(__file__).resolve().parents[1] / "screen_without.py"
SCREEN_SPEC = importlib.util.spec_from_file_location("screen_without", SCREEN_PATH)
screen = importlib.util.module_from_spec(SCREEN_SPEC)
SCREEN_SPEC.loader.exec_module(screen)

# Development tasks only: tests never generate or score the held-out confirmation set.
FAST = [lift_task("hr-sar-boxcar-db"), lift_task("hr-station-distance")]


class RecordingAdapter(ScriptedAdapter):
    """A scripted agent that claims to call a model and records every request it receives."""

    name = "recording"
    model_calls = True

    def __init__(self, behaviour: str):
        super().__init__({WITH: behaviour, WITHOUT: behaviour})
        self.requests = []

    def run(self, request):
        self.requests.append((request.task_id, request.condition, request.run_index))
        return super().run(request)


def test_registration_is_24_confirmation_tasks_twice_on_the_registered_host():
    assert [task.task_id for task in screen._select(None, screen.COHORT)] == [
        task.task_id for task in COHORTS["headroom-confirmation"]]
    assert len(COHORTS["headroom-confirmation"]) * screen.RUNS == 48
    assert (screen.MODEL, screen.HOST_VERSION, screen.TIMEOUT) == ("opencode-go/mimo-v2.6-flash", "1.19.4", 900.0)


def test_screen_runs_only_without_in_order_and_scores_merit_rejections(tmp_path):
    adapter = RecordingAdapter("seeded")
    report = screen.run_screen(adapter, FAST, runs=2, budget=Budget(max_runs=4), work_root=tmp_path,
                               allow_model_calls=True)
    assert adapter.requests == [(task.task_id, WITHOUT, run) for run in (0, 1) for task in FAST]
    assert report["design"]["started_agent_runs"] == 4
    assert all(run["condition"] == WITHOUT and run["treatment_used"] is None
               for task in report["tasks"] for run in task["runs"])
    summary = report["screen"]
    assert summary["retained_tasks"] == [task.task_id for task in FAST]
    assert summary["status"] == "stop" and summary["statement"] == screen.STOP_STATEMENT
    assert str(tmp_path) not in json.dumps(report)


def test_reference_outputs_are_accepted_and_not_retained(tmp_path):
    report = screen.run_screen(RecordingAdapter("reference"), FAST[:1], runs=2, budget=Budget(max_runs=2),
                               work_root=tmp_path, allow_model_calls=True)
    assert report["screen"]["per_task"] == [
        {"task": FAST[0].task_id, "runs": 2, "accepted": 2, "merit_rejections": 0, "unresolved": []}]


@pytest.mark.parametrize("max_runs", [None, 3])
def test_budget_below_the_plan_starts_nothing(tmp_path, max_runs):
    adapter = RecordingAdapter("reference")
    with pytest.raises(LiftError):
        screen.run_screen(adapter, FAST, runs=2, budget=Budget(max_runs=max_runs), work_root=tmp_path,
                          allow_model_calls=True)
    assert adapter.requests == []


def test_model_adapter_needs_explicit_opt_in(tmp_path):
    adapter = RecordingAdapter("reference")
    with pytest.raises(LiftError):
        screen.run_screen(adapter, FAST, runs=1, budget=Budget(max_runs=2), work_root=tmp_path)
    assert adapter.requests == []


def test_preflight_only_starts_no_agent(tmp_path):
    adapter = RecordingAdapter("reference")
    report = screen.run_screen(adapter, FAST, runs=1, budget=Budget(), work_root=tmp_path, preflight_only=True)
    assert adapter.requests == [] and report["design"]["started_agent_runs"] == 0
    assert {run["adapter_status"] for task in report["tasks"] for run in task["runs"]} == {"preflight_only"}


def _run(verdict, *, host="completed", contamination=(), accepted=None):
    return {"verdict": verdict, "accepted": verdict == "accepted" if accepted is None else accepted,
            "host_status": host, "adapter_status": host, "agent": {"contamination": list(contamination)}}


def test_only_clean_completed_rejections_count_as_headroom():
    assert screen.classify(_run("rejected")) == "merit"
    assert screen.classify(_run("error")) == "merit"  # an unreadable deliverable
    for run in (_run("rejected", host="timeout"), _run("rejected", host="failed"), _run("missing"),
                _run("invalid"), _run("rejected", contamination=["oracle-source"]),
                {"verdict": "not_run", "accepted": False, "adapter_status": "preflight_failed"}):
        assert screen.classify(run) == "unresolved"


def _tasks(*kinds):
    runs = {"merit": _run("rejected"), "accepted": _run("accepted"), "open": _run("missing")}
    return [{"id": f"t{index}", "runs": [runs[kind], runs["accepted"]]} for index, kind in enumerate(kinds)]


@pytest.mark.parametrize("kinds,status", [
    (["merit"] * 8 + ["accepted"] * 16, "go"),
    (["merit"] * 6 + ["accepted"] * 18, "stop"),
    (["merit"] * 6 + ["open"] * 2 + ["accepted"] * 16, "paused: unresolved screening coverage"),
    (["merit"] * 6 + ["open"] + ["accepted"] * 17, "stop"),
])
def test_go_no_go_pauses_only_when_unresolved_runs_could_change_it(kinds, status):
    summary = screen.screen_summary(_tasks(*kinds))
    assert summary["status"] == status
    assert ("statement" in summary) == (status == "stop")


def test_plan_prints_48_and_wrong_approval_probes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(screen, "probe_opencode", lambda *args: pytest.fail("the host was probed"))
    args = ["--opencode-executable", "opencode.exe", "--agent-python-without", "python.exe"]
    assert screen.main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_model_invocations"] == 48 and plan["condition"] == WITHOUT
    assert plan["command_to_approve"].endswith("--approve-model-calls 48")
    with pytest.raises(SystemExit):
        screen.main(args + ["--approve-model-calls", "47"])


def test_unregistered_host_version_starts_nothing(monkeypatch, capsys):
    monkeypatch.setattr(screen, "probe_opencode",
                        lambda *args: ("opencode.exe", "ok", "opencode 1.20.0 opencode-go/mimo-v2.6-flash"))
    monkeypatch.setattr(screen, "run_screen", lambda *args, **kwargs: pytest.fail("a screen was started"))
    assert screen.main(["--opencode-executable", "opencode.exe", "--agent-python-without", "python.exe",
                        "--approve-model-calls", "48"]) == 1
    assert "registered 1.19.4" in capsys.readouterr().out
