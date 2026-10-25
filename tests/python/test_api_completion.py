"""Offline completion-guard regressions: fake model, real local MCP, no HTTP."""
import json
from dataclasses import asdict
from types import SimpleNamespace
import urllib.request

import pytest

from test_api_agent import api_agent, FakeModel, PRICES, FAKE_KEY, _project, _request, WITH


@pytest.fixture(autouse=True)
def no_model_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("A real HTTP request was attempted")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)


def response(status="fail", path="outputs/a.tif", check_id="rs.index_formula", **kwargs):
    check = {"id": check_id, "status": status, "evidence": {"output": path, **kwargs}}
    return SimpleNamespace(is_error=False, structured_content={"report": {
        "schema_version": "terraproof.evidence/0.1", "checks": [check]}})


def review_case(tmp_path):
    return api_agent._OutputReview(tmp_path, ("a.tif", "b.tif")), {
        "paths": ["outputs/a.tif"], "index_formula": "ndvi", "nir": "inputs/n.tif", "red": "inputs/r.tif"}


@pytest.mark.parametrize("status", ["warn", "not-run"])
def test_warnings_and_not_run_do_not_resolve_failures(tmp_path, status):
    review, args = review_case(tmp_path)
    review.observe(args, response(status))
    assert not review.records  # this guard does not invent failures from optional checks
    review.observe(args, response())
    review.observe(args, response(status))
    assert review.unresolved == 1
    review.observe(args, response("pass"))
    assert review.unresolved == 0 and len(review.records) == 1
    review.invalidate()
    assert review.unresolved == 1


@pytest.mark.parametrize("change", ["sources", "omit-option", "check-id", "other-output"])
def test_unrelated_pass_cannot_clear_failed_requirement(tmp_path, change):
    review, args = review_case(tmp_path)
    review.observe(args, response())
    altered, passed = dict(args), response("pass")
    if change == "sources": altered["red"] = "inputs/other.tif"
    elif change == "omit-option": altered.pop("index_formula")
    elif change == "check-id": passed = response("pass", check_id="rs.value_range")
    else:
        altered["paths"] = ["outputs/b.tif"]
        passed = response("pass", path="outputs/b.tif")
    review.observe(altered, passed)
    assert review.unresolved == 1


def test_failed_original_audit_is_excluded_from_output_review(tmp_path):
    review, args = review_case(tmp_path)
    args["paths"] += ["inputs/original.tif"]
    review.observe(args, response(path="inputs/original.tif"))
    review.observe({"paths": ["inputs/original.tif"]}, response(path="inputs/original.tif"))
    assert not review.records
    review.observe(args, response())
    assert review.unresolved == 1


def test_grouped_checks_require_the_original_path_group(tmp_path):
    review, args = review_case(tmp_path)
    args["paths"] = ["outputs/a.tif", "outputs/b.tif"]
    review.observe(args, response(path=None, check_id="crs.consistent", inputs=args["paths"]))
    assert review.unresolved == 2
    review.observe({**args, "paths": ["outputs/a.tif"]},
                   response("pass", path=None, check_id="crs.consistent", inputs=["outputs/a.tif"]))
    assert review.unresolved == 2
    review.observe(args, response("pass", path=None, check_id="crs.consistent", inputs=args["paths"]))
    assert review.unresolved == 0


@pytest.mark.parametrize("defect", ["tool-error", "payload", "schema", "empty", "bad-id", "evidence"])
def test_invalid_output_report_requires_a_valid_same_context_report(tmp_path, defect):
    review, args = review_case(tmp_path)
    bad = response("pass")
    report = bad.structured_content["report"]
    if defect == "tool-error": bad.is_error = True
    elif defect == "payload": bad.structured_content = None
    elif defect == "schema": report["schema_version"] = "unknown"
    elif defect == "empty": report["checks"] = []
    elif defect == "bad-id": report["checks"][0]["id"] = "untrusted text"
    else: report["checks"][0]["evidence"] = None
    review.observe(args, bad)
    assert review.unresolved == 1
    review.observe({**args, "red": "other.tif"}, response("pass"))
    assert review.unresolved == 1
    review.observe(args, response("pass"))
    assert review.unresolved == 0


def setup_real_output(tmp_path):
    from test_index_formula import _case, GRID
    from terraproof.evals.fixtures import write_raster_grid
    project = _project(tmp_path, WITH)
    out, nir, red, values = _case(project / "outputs")
    values[2, 3] = 0  # wrong support, despite a plausible value
    write_raster_grid(out, values, transform=GRID)
    return project, {"paths": [str(out)], "index_formula": "ndvi", "nir": str(nir), "red": str(red)}


REPAIR = "import rasterio; p='outputs/ndvi.tif'\nwith rasterio.open(p,'r+') as d:\n v=d.read(1); v[2,3]=-9999; d.write(v,1)"


@pytest.mark.parametrize("repair", [False, True])
def test_real_ndvi_failure_is_repaired_and_rechecked_or_ends_unresolved(tmp_path, repair):
    project, args = setup_real_output(tmp_path)
    original = (project / "outputs/ndvi.tif").read_bytes()
    turns = [[("terraproof_run_checks", args)], []]
    if repair:
        turns += [[("run_python", {"code": REPAIR})], [("terraproof_run_checks", args)], []]
    model = FakeModel(turns)
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITH))
    assert result.status == ("completed" if repair else "failed"), result.turn
    assert result.turn["output_review"] == ("resolved" if repair else "unresolved")
    assert result.turn["output_review_unresolved"] == (0 if repair else 1)
    assert result.turn["completion_review_prompts"] == (1 if repair else 2)
    assert model.requests[2]["messages"][-1] == {"role": "user", "content": api_agent.COMPLETION_REVIEW}
    assert result.terraproof_tool_calls == (2 if repair else 1)  # no hidden host check
    if not repair:
        assert result.turn["reason"] == "output verification unresolved"
        assert (project / "outputs/ndvi.tif").read_bytes() == original
    saved = json.dumps(asdict(result))
    assert str(project) not in saved and FAKE_KEY not in saved and api_agent.COMPLETION_REVIEW not in saved


def test_review_requests_share_the_original_model_call_cap(tmp_path):
    project, args = setup_real_output(tmp_path)
    model = FakeModel([[("terraproof_run_checks", args)], []])
    limits = api_agent.ApiLimits(2, 8, max_model_calls=2)
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", limits, transport=model).run(_request(project, WITH))
    assert result.status == "failed" and result.turn["reason"] == "model call cap reached"
    assert len(model.requests) == 2 and result.turn["completion_review_prompts"] == 1
    assert result.turn["output_review"] == "unresolved"


@pytest.mark.parametrize("write", [
    ("write_file", {"path": "outputs/note.txt", "content": "an unrelated note still invalidates resolution"}),
    ("run_python", {"code": REPAIR.replace("v[2,3]=-9999", "v[2,3]=0") + "\nraise RuntimeError('partial write')"}),
])
def test_post_pass_write_attempt_requires_another_check(tmp_path, write):
    project, args = setup_real_output(tmp_path)
    model = FakeModel([[("terraproof_run_checks", args)], [("run_python", {"code": REPAIR})],
                       [("terraproof_run_checks", args)], [write], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITH))
    assert result.status == "failed" and result.turn["output_review"] == "unresolved"
    assert result.turn["completion_review_prompts"] == 2


@pytest.mark.parametrize("reservation,reason", [
    (300001, "insufficient token allowance for next request"),
    (200000, "insufficient budget for next request"),
])
def test_review_prompt_cost_is_admitted_before_another_request(tmp_path, reservation, reason):
    project, args = setup_real_output(tmp_path)
    model = FakeModel([[("terraproof_run_checks", args)], []])
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model)
    reserve = api_agent.prompt_reservation
    def limited_after_review(messages, tools):
        return reservation if messages[-1].get("content") == api_agent.COMPLETION_REVIEW else reserve(messages, tools)
    from unittest.mock import patch
    with patch.object(api_agent, "prompt_reservation", side_effect=limited_after_review):
        result = adapter.run(_request(project, WITH, max_usd=0.2))
    assert len(model.requests) == 2
    assert result.turn["reason"] == reason
    assert result.turn["output_review"] == "unresolved"


@pytest.mark.parametrize("reference", [None, "\0"])
def test_unscoped_or_unresolvable_failure_is_conservative(tmp_path, reference):
    review, args = review_case(tmp_path)
    review.observe(args, response(path=reference))
    assert review.unresolved == 1
    review.observe(args, response("pass"))
    assert review.unresolved == 0
