"""Phase 11 T3: declarations are judged at every call; a wrong output certified on a faithful one is a check gap."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))

import phase11_snapshot_server as server  # noqa: E402
import phase11_t3_agent as t3  # noqa: E402

MIXED = next(e for e in t3.TASKS if e["task_id"] == "hr-elevation-change-mixed-units")
HEAT = next(e for e in t3.TASKS if e["task_id"] == "hr-reanalysis-air-temperature")


def test_a_declaration_is_faithful_when_its_checks_and_key_bindings_match_the_reference():
    same = dict(MIXED["reference"][0], vertical_sources=["C:/p/inputs/dem_2023.tif", "inputs\\dem_2015.tif"],
                vertical_source_units=["m", "ft"])  # other path forms and unit spellings
    assert t3.faithful(t3.declaration_row(MIXED, [same]))
    swapped = dict(same, vertical_sources=["inputs/dem_2015.tif", "inputs/dem_2023.tif"])  # order is the operation
    assert t3.declaration_row(MIXED, [swapped])["vertical_sources"] == "differs"
    belief = dict(same, vertical_source_units=["metre", "metre"])
    row = t3.declaration_row(MIXED, [belief])
    assert row["vertical_source_units"] == "differs" and not t3.faithful(row)
    # the reference names a check directly; a declaration may reach it through any goal or check
    named = dict(HEAT["reference"][0])
    assert t3.faithful(t3.declaration_row(HEAT, [named]))
    assert not t3.declaration_row(HEAT, [dict(named, checks=["raster.nodata_support"])])["goals_cover_reference"]
    assert t3.declaration_row(MIXED, []) == {"declared": False}


def _call(status, ok, *, faithful=True, conflict=False, grade="advisory-only"):
    findings = ["project.declaration:fail"] if conflict else []  # as the wrapper records them
    return {"tool": "verify_project", "shown": {t3.RESULT: {"status": status, "grade": grade, "findings": findings}},
            "oracle": {t3.RESULT: ok}, "declaration": {"project_file": "valid", "faithful": faithful}}


def test_wrong_snapshots_say_what_caught_them_and_what_was_declared():
    calls = [_call("failed", False, faithful=False, conflict=True), _call("verified", False, faithful=False,
                                                                          grade="decision-grade"),
             _call("failed", False), _call("review-required", False), _call("verified", True)]
    rows = t3.wrong_snapshots(calls)
    assert [(r["flagged"], r["by_declaration_conflict"], r["certified"], r["faithful"]) for r in rows] == [
        (True, True, False, False), (False, False, True, False), (True, False, False, True),
        (False, False, False, True)]


def _summary(**values):
    base = {"false_assurance_faithful": 0, "false_assurance_belief": 0, "adopted": 10, "saves": 3, "save_runs": 3,
            "wrong_snapshots": 4}
    return dict(base, **values)


def test_the_reading_applies_the_registered_bars_in_order():
    assert t3.reading(_summary()).startswith("adoption and value met")
    assert t3.reading(_summary(false_assurance_faithful=1)).startswith("false assurance on a faithful")
    assert t3.reading(_summary(adopted=6)).startswith("adoption not met")  # the bar is 7 of 14
    assert t3.reading(_summary(saves=0, save_runs=0, wrong_snapshots=1)).startswith("adoption met, fewer than 2")
    assert t3.reading(_summary(saves=1, save_runs=1)).startswith("adoption met, wrong snapshots not flagged")
    assert t3.reading(_summary(false_assurance_belief=2)).endswith("2 wrong call(s) certified on belief "
                                                                   "declarations, reported")


class FakeAgent:
    """Each task: writes a seeded wrong output, verifies, fixes it, verifies again. On the mixed-units task the
    first declaration repeats the mistake (both surveys in metres), as an agent that misread the units would."""

    agent_python_with = sys.executable

    def preflight(self, request):
        return {}

    def run(self, request):
        from terraproof import project as tp_project
        from terraproof.evals.lift import AgentResult

        project, task_id = request.project, request.task_id
        entry = next(e for e in t3.TASKS if e["task_id"] == task_id)
        generated = project.parents[1] / "calibration" / task_id / "generated"
        declaration = dict(entry["reference"][0])
        if task_id == MIXED["task_id"]:
            declaration["vertical_source_units"] = ["metre", "metre"]
        path = project / "terraproof.json"
        verify = server.snapshotting("verify_project", lambda **kw: tp_project.verify(path),
                                     project.parent / "snapshots", project)
        path.write_text(json.dumps({"schema": tp_project.SCHEMA, "deliverables": [declaration]}))
        shutil.copyfile(generated / t3.LIFT[task_id].seeded[0][1], project / "outputs" / t3.RESULT)
        verify(path=None, plan=False, only=None)
        path.write_text(json.dumps({"schema": tp_project.SCHEMA, "deliverables": entry["reference"]}))
        shutil.copyfile(generated / t3.RESULT, project / "outputs" / t3.RESULT)
        verify(path=None, plan=False, only=None)
        self.last_calls, self.last_lines, self.last_trace = [], ['{"type": "step_start"}\n'], \
            {"tools": [], "verify_project_calls": 2, "verify_project_plan_calls": 0, "plan_before_first_verify": False}
        return AgentResult("completed")


def test_the_whole_run_loop_scores_every_call_and_its_declaration(tmp_path, monkeypatch):
    monkeypatch.setattr(t3.t2, "identity_checks", lambda *a: {"wrapper_serves_stock_tools": True})
    checkpoints = []
    report = t3.run(FakeAgent(), tmp_path / "work", runs=1, mode="run", approved=7, checkpoint=checkpoints.append)
    assert len(checkpoints) == 7 and report["design"]["started"] == 7
    assert all(item["eligible"] for item in report["calibration"])
    summary = report["summary"]
    assert summary["adopted"] == 7 and summary["saves"] == 7 and summary["save_runs"] == 7
    assert summary["false_assurance_faithful"] == summary["false_assurance_belief"] == 0
    assert summary["final_correct"] == 7 and summary["false_alarm_calls"] == 0
    assert summary["wrong_snapshots_by_kind"]["flagged_by_declaration_conflict"] == 1  # the units misread
    assert summary["wrong_snapshots_by_kind"]["flagged_by_checks"] == 6
    mixed = next(r for r in report["runs"] if r["task"] == MIXED["task_id"])
    assert mixed["wrong_snapshots"][0]["faithful"] is False and mixed["final_declaration_faithful"]
    assert summary["reading"].startswith("adoption and value met")
