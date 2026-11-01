"""Phase 9 Q5.2: next-step labels taken from a trace are booleans; following means proposing after an offer."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase8_p4 import verification_calls  # noqa: E402
from phase9_q5_agent import behaviour  # noqa: E402

DELIVERABLES = ("clear_mask.tif",)


def _tool(name, arguments, output):
    return (0.0, {"type": "tool_use", "part": {"tool": name, "state": {"status": "completed", "input": arguments,
                                                                     "output": output}}})


def test_proposing_after_an_offered_next_step_counts_as_following_it():
    events = [
        _tool("terraproof_run_checks", {"paths": ["outputs/clear_mask.tif"], "qa_path": "inputs/scl.tif"},
              '{"grade": "checks-passed", "report": {"next_step": {"profiles": ["qa-masked"]}}}'),
        _tool("terraproof_propose_contract", {"paths": ["outputs/clear_mask.tif"], "profiles": ["qa-masked"]}, "{}"),
        _tool("terraproof_run_checks", {"paths": ["outputs/clear_mask.tif"], "contract": {"x": 1}},
              '{"grade": "decision-grade", "report": {"verification": {"status": "verified"}}}'),
    ]
    calls = verification_calls(events, DELIVERABLES)
    assert [c["next_step_offered"] for c in calls] == [True, False, False]
    found = behaviour(calls)
    assert found["next_step_offered"] and found["followed_next_step"] and found["last_grade"] == "decision-grade"


def test_proposing_before_any_offer_is_not_following():
    events = [_tool("terraproof_propose_contract", {"paths": ["outputs/clear_mask.tif"]}, "{}"),
              _tool("terraproof_run_checks", {"paths": ["outputs/clear_mask.tif"]}, '{"next_step": {}}')]
    found = behaviour(verification_calls(events, DELIVERABLES))
    assert found["next_step_offered"] and not found["followed_next_step"]
