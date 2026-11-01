"""Phase 8 P4: the verification labels taken from an OpenCode trace are names and enums only."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase8_p4 import behaviour, verification_calls  # noqa: E402

DELIVERABLES = ("blue_reflectance.tif",)


def _tool(name, arguments, output, status="completed"):
    return (0.0, {"type": "tool_use", "part": {"tool": name, "state": {"status": status, "input": arguments,
                                                                     "output": output}}})


def test_labels_keep_argument_names_profiles_and_grades_but_no_values():
    events = [
        _tool("bash", {"command": "python make.py"}, "done"),
        _tool("terraproof_propose_contract", {"paths": ["outputs/blue_reflectance.tif"], "profiles": ["scaled-reflectance"],
                                              "arguments": {"reference_input": "inputs/blue_dn.tif"}}, "{}"),
        _tool("terraproof_run_checks", {"paths": ["C:\\work\\project\\outputs\\blue_reflectance.tif"],
                                        "profiles": ["scaled-reflectance"], "decode_scale": 0.0001},
              json.dumps({"grade": "advisory-only", "report": {"verification": {"status": "incomplete"}}})),
    ]
    calls = verification_calls(events, DELIVERABLES)
    assert [c["tool"] for c in calls] == ["propose_contract", "run_checks"]
    check = calls[1]
    assert check["argument_names"] == ["decode_scale", "paths", "profiles"]
    assert check["targets_deliverable"] and check["profiles"] == ["scaled-reflectance"] and not check["contract"]
    assert check["grade"] == "advisory-only" and check["verification_status"] == "incomplete"
    assert "0.0001" not in json.dumps(calls) and "blue_dn" not in json.dumps(calls)
    summary = behaviour(calls)
    assert summary["called_propose_contract"] and summary["declared_on_deliverable"]
    assert summary["last_grade"] == "advisory-only" and summary["last_coverage_assessed"]


def test_checks_of_inputs_only_do_not_count_and_unknown_grades_are_dropped():
    events = [
        _tool("terraproof_run_checks", {"paths": ["inputs/blue_dn.tif"]}, '{"grade": "checks-passed"}'),
        _tool("terraproof_run_checks", {"paths": ["outputs/blue_reflectance.tif"]}, '"grade": "excellent"'),
    ]
    calls = verification_calls(events, DELIVERABLES)
    assert [c["targets_deliverable"] for c in calls] == [False, True]
    assert calls[1]["grade"] is None
    summary = behaviour(calls)
    assert summary["checked_deliverable"] and not summary["declared_on_deliverable"]
    assert summary["last_grade"] is None and not summary["last_coverage_assessed"]


def test_a_grade_is_read_from_text_output_too():
    events = [_tool("terraproof_run_checks", {"paths": ["outputs/blue_reflectance.tif"], "contract": {"x": 1}},
                    'Result: {"grade": "decision-grade", "verification": {"status": "verified", "required": 2}}')]
    summary = behaviour(verification_calls(events, DELIVERABLES))
    assert summary["last_grade"] == "decision-grade" and summary["last_verification_status"] == "verified"
    assert summary["last_coverage_assessed"]
