"""Phase 11 T2: snapshots record what each call showed; saves need a flagged failure; the reading is as registered."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))

import phase11_snapshot_server as server  # noqa: E402
import phase11_t2_agent as t2  # noqa: E402

S2 = t2.TASKS[0]


def test_snapshot_copies_outputs_and_project_file_and_records_what_was_shown(tmp_path):
    project, snapshots = tmp_path / "project", tmp_path / "snapshots"
    (project / "outputs").mkdir(parents=True)
    (project / "outputs" / "a.tif").write_text("first")
    (project / "terraproof.toml").write_text("schema = 1")
    shown = {"exit_code": 3, "deliverables": [{"name": "a", "status": "failed", "grade": "advisory-only",
                                              "outputs": ["outputs/a.tif"],
                                              "findings": [{"check": "rs.cloud_mask_applied", "status": "fail"}]}]}
    verify = server.snapshotting("verify_project", lambda **kw: shown, snapshots, project)
    assert verify(path=None, plan=True, only=None) is shown  # a plan judges no output: no snapshot
    assert not snapshots.exists()
    assert verify(path=None, plan=False, only=None) is shown
    (project / "outputs" / "a.tif").write_text("second")
    checks = server.snapshotting("run_checks", lambda **kw: {"grade": "decision-grade",
                                                             "report": {"verification": {"status": "verified"}}},
                                 snapshots, project)
    checks(paths=["outputs/a.tif"])
    first, second = sorted(snapshots.iterdir())
    assert first.name == "000-verify_project" and second.name == "001-run_checks"
    assert (first / "outputs" / "a.tif").read_text() == "first" and (first / "terraproof.toml").is_file()
    record = json.loads((first / "call.json").read_text())
    assert record["deliverables"][0]["outputs"] == ["a.tif"]
    assert record["deliverables"][0]["findings"] == ["rs.cloud_mask_applied:fail"]
    assert json.loads((second / "call.json").read_text())["verification_status"] == "verified"


def test_a_failing_call_is_still_snapshotted_and_recorded(tmp_path):
    def broken(**kw):
        raise ValueError("bad project file")
    call = server.snapshotting("verify_project", broken, tmp_path / "snaps", tmp_path)
    with pytest.raises(ValueError):
        call(path="elsewhere/terraproof.toml", plan=False, only=None)
    record = json.loads(next((tmp_path / "snaps").iterdir()).joinpath("call.json").read_text())
    assert record["outcome"] == "error" and record["error"] == "ValueError"


def _call(name, ok, status, grade="advisory-only"):
    return {"tool": "verify_project", "shown": {name: {"status": status, "grade": grade}}, "oracle": {name: ok}}


def test_a_save_needs_a_flagged_failure_and_a_correct_final_output():
    name = "nir_reflectance.tif"
    flagged = [_call(name, False, "failed"), _call(name, True, "review-required", "review-required")]
    found = t2.outcomes(flagged, {name: {"correct": True}})[name]
    assert found["saved"] and found["wrong_flagged_at_a_call"] == 1 and not found["certified_wrong_at_a_call"]
    # wrong but only held at review (the layout screen alone does that to every raster): not a save
    held = [_call(name, False, "review-required", "review-required"), _call(name, True, "review-required")]
    found = t2.outcomes(held, {name: {"correct": True}})[name]
    assert not found["saved"] and found["wrong_unflagged_at_a_call"] == 1


def test_false_assurance_and_false_alarms_are_counted_per_call():
    name = "usable_mask.tif"
    calls = [_call(name, True, "failed"), _call(name, False, "verified", "decision-grade")]
    found = t2.outcomes(calls, {name: {"correct": False}})[name]
    assert found["false_alarm_calls"] == 1 and found["certified_wrong_at_a_call"] == 1
    assert found["final_false_assurance"] and not found["shipped_wrong_flagged"]
    unchecked = t2.outcomes([], {name: {"correct": False}})[name]
    assert unchecked["shipped_wrong_unchecked"] and unchecked["last_status"] is None


def test_faithfulness_compares_goals_and_key_bindings_with_the_reference():
    declared = [{"name": "mask", "outputs": ["outputs/usable_mask.tif"], "goals": ["qa-masked"],
                 "qa_path": "inputs/scl.tif", "qa_kind": "keep-codes", "qa_keep_codes": [11, 6, 5, 4, 2]},
                {"name": "nir", "outputs": ["outputs/nir_reflectance.tif"], "goals": ["scaled-reflectance"],
                 "reference_input": "inputs/nir_dn.tif", "decode_scale": 1e-4, "decode_offset": -0.1}]
    found = t2.faithfulness(S2, declared)
    assert found["usable_mask.tif"]["goals_cover_reference"] and found["usable_mask.tif"]["qa_keep_codes"] == "differs"
    assert found["usable_mask.tif"]["qa_path"] == "match" and found["usable_mask.tif"]["output_form"] == "absent"
    assert found["nir_reflectance.tif"]["decode_scale"] == "match"
    assert found["nir_reflectance.tif"]["decode_offset"] == "differs"
    assert found["scene_summary.json"] == {"declared": False}


def test_project_file_states(tmp_path):
    assert t2.read_project_file(tmp_path) == ("none", [])
    (tmp_path / "terraproof.json").write_text(json.dumps({"schema": "terraproof.project/1", "deliverables": [
        {"name": "a", "outputs": ["x.tif"], "goals": ["no-such-goal"]}]}))
    state, declared = t2.read_project_file(tmp_path)
    assert state == "invalid" and declared[0]["name"] == "a"


def _tool(name, arguments):
    return (0.0, {"type": "tool_use", "part": {"tool": "terraproof_" + name, "state": {"input": arguments}}})


def test_trace_labels_order_plan_and_verify_calls():
    labels = t2.trace_labels([_tool("verify_project", {"plan": True}), _tool("run_checks", {"paths": []}),
                              _tool("verify_project", {})])
    assert labels["verify_project_calls"] == 2 and labels["verify_project_plan_calls"] == 1
    assert labels["plan_before_first_verify"]
    assert not t2.trace_labels([_tool("verify_project", {})])["plan_before_first_verify"]


def _summary(**values):
    base = {"false_assurance_any_call": 0, "false_assurance_final": 0, "adopted": 8, "saves": 2, "save_runs": 2,
            "wrong_snapshots": 5}
    return dict(base, **values)


def test_the_reading_applies_the_registered_bars_in_order():
    assert t2.reading(_summary()).startswith("adoption and value met")
    assert t2.reading(_summary(false_assurance_final=1, adopted=0)).startswith("false assurance")
    assert t2.reading(_summary(adopted=5)).startswith("adoption not met")
    assert t2.reading(_summary(saves=1, wrong_snapshots=1)).startswith("adoption met, fewer than 2")
    assert t2.reading(_summary(saves=2, save_runs=1)).startswith("adoption met, wrong snapshots not flagged")


def test_wrap_config_points_only_the_server_command_at_the_wrapper(tmp_path):
    config = {"$schema": "x", "mcp": {"terraproof": {"type": "local", "command": ["py.exe", "-I", "-m",
                                                                                  "terraproof.mcp"],
                                                     "environment": {"A": "1"}}}}
    (tmp_path / "opencode.json").write_text(json.dumps(config))
    stock = t2.wrap_config(tmp_path, Path("C:/w/server.py"), Path("C:/w/snaps"))
    entry = json.loads((tmp_path / "opencode.json").read_text())["mcp"]["terraproof"]
    assert stock == ("py.exe", ["-I", "-m", "terraproof.mcp"])
    assert entry["command"][:3] == ["py.exe", "-I", str(Path("C:/w/server.py"))]
    assert entry["environment"] == {"A": "1"} and entry["type"] == "local"


def test_the_wrapper_serves_exactly_the_stock_tools_and_instructions(tmp_path):
    pytest.importorskip("mcp")
    env = {"PYTHONPATH": os.pathsep.join(p for p in sys.path if p.endswith("src") or "site-packages" in p)}
    stock = t2.served(sys.executable, ["-m", "terraproof.mcp"], tmp_path, env=env)
    wrapped = t2.served(sys.executable, [str(t2.WRAPPER), str(tmp_path / "snaps"), str(tmp_path)], tmp_path, env=env)
    assert stock and stock["tools"] and "verify_project" in {tool["name"] for tool in stock["tools"]}
    assert wrapped == stock


class FakeAgent:
    """Writes each task's first trap, verifies through the snapshot wrapper, fixes it, verifies again."""

    agent_python_with = sys.executable

    def preflight(self, request):
        return {}

    def run(self, request):
        from terraproof import project as tp_project
        from terraproof.evals.lift import AgentResult

        task_id, project = request.task_id, request.project
        entry = next(e for e in t2.TASKS if e["task"].task_id == task_id)
        (project / "terraproof.json").write_text(json.dumps({"schema": tp_project.SCHEMA,
                                                             "deliverables": entry["reference"]}))
        verify = server.snapshotting("verify_project", lambda **kw: tp_project.verify(project / "terraproof.json"),
                                     project.parent / "snapshots", project)
        t2.write_outputs(task_id, project / "inputs", project / "outputs", trap=t2.TRAPS[task_id][0])
        verify(path=None, plan=False, only=None)
        t2.write_outputs(task_id, project / "inputs", project / "outputs")
        verify(path=None, plan=False, only=None)
        self.last_calls, self.last_lines = [], ['{"type": "step_start"}\n']
        self.last_trace = t2.trace_labels([])
        return AgentResult("completed")


@pytest.mark.skipif(not (t2.CACHE / "q0").is_dir() or not (t2.CACHE / "s0b-seal-fetch").is_dir(),
                    reason="needs the local Q0 and S0b source caches")
def test_the_whole_run_loop_scores_snapshots_and_checkpoints_every_run(tmp_path, monkeypatch):
    monkeypatch.setattr(t2, "identity_checks", lambda *a: {"wrapper_serves_stock_tools": True})
    checkpoints = []
    report = t2.run(FakeAgent(), t2.CACHE, tmp_path / "work", runs=1, mode="run", approved=3,
                    checkpoint=checkpoints.append)
    assert len(checkpoints) == 3 and report["design"]["started"] == 3
    summary = report["summary"]
    # S2's offset and SoCal's dropped zeros also make each summary wrong: 2 + 1 + 2 saves
    assert summary["adopted"] == 3 and summary["saves"] == 5 and summary["save_runs"] == 3
    assert summary["false_assurance_any_call"] == 0 and summary["false_alarm_calls"] == 0
    assert summary["final_correct"] == summary["deliverables"] == 8
    assert summary["reference_agrees_with_oracle"] == 8
    assert summary["reading"].startswith("adoption not met")  # 3 of the registered 6
    assert (tmp_path / "work" / "t2-s2-pipeline-0" / "trace.jsonl").read_text() == '{"type": "step_start"}\n'
