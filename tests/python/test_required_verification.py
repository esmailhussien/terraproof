"""Required output contracts and current-byte proof: offline fake provider only."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import urllib.request

import pytest

from test_api_agent import api_agent, driver, FakeModel, PRICES, FAKE_KEY, TASK, WITH, WITHOUT, _project, _request
from test_api_completion import setup_real_output, REPAIR
from output_verification import RequiredVerification, VerificationPlan, SCHEMA


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    def refuse(*args, **kwargs): raise AssertionError("Unexpected HTTP")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)


def group(paths=None):
    return {"paths": paths or ["outputs/ndvi.tif"], "checks": ["rs.index_formula"],
            "parameters": {"index_formula": "ndvi", "nir": "inputs/nir.tif", "red": "inputs/red.tif"}}


def plan_file(tmp_path, groups=None):
    path = tmp_path / "verification plan.json"
    path.write_text(json.dumps({"schema": SCHEMA, "tasks": {TASK: groups or [group()]}}), encoding="utf-8")
    return path


def data_case(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs").mkdir()
    for name in ("inputs/nir.tif", "inputs/red.tif", "outputs/ndvi.tif"):
        (tmp_path / name).write_bytes(name.encode())
    verifier = RequiredVerification(tmp_path, [group()], ["ndvi.tif"])
    return verifier, verifier.arguments(group())


def response(verifier, args, status="pass"):
    snapshot = verifier.snapshot()
    records = [{"path": path, **snapshot["files"][path]} for path in
               [*args["paths"], args["nir"], args["red"]]]
    return SimpleNamespace(is_error=False, structured_content={"report": {
        "schema_version": "terraproof.evidence/0.1", "inputs": records,
        "parameters": {key: value for key, value in args.items() if key != "paths"},
        "checks": [{"id": "rs.index_formula", "status": status, "evidence": {"output": args["paths"][0]}}]}})


@pytest.mark.parametrize("status,expected", [("pass", "verified"), ("warn", "review-required"),
                                           ("fail", "review-required"), ("not-run", "unverified")])
def test_distinct_states_require_actual_current_reports(tmp_path, status, expected):
    verifier, args = data_case(tmp_path)
    assert verifier.summary()["status"] == "unverified"
    verifier.observe(args, response(verifier, args, status), verifier.snapshot())
    summary = verifier.summary()
    assert summary["status"] == expected
    assert summary["outputs"][0]["status"] == expected
    assert str(tmp_path) not in json.dumps(summary)


@pytest.mark.parametrize("change", ["output", "source", "mask-created", "mask-modified", "file-deleted"])
def test_data_changes_make_pass_stale_even_with_restored_mtime(tmp_path, change):
    verifier, args = data_case(tmp_path)
    sidecar = tmp_path / "outputs/ndvi.tif.msk"
    if change == "mask-modified": sidecar.write_bytes(b"mask1")
    verifier.observe(args, response(verifier, args), verifier.snapshot())
    assert verifier.summary()["status"] == "verified"
    if change in ("output", "source"):
        path = tmp_path / ("outputs/ndvi.tif" if change == "output" else "inputs/nir.tif")
        stamp = path.stat()
        path.write_bytes(b"x" * path.stat().st_size)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif change == "mask-created": sidecar.write_bytes(b"new mask")
    elif change == "mask-modified": sidecar.write_bytes(b"mask2")
    else: (tmp_path / "outputs/ndvi.tif").unlink()
    assert verifier.summary()["status"] == "unverified"


@pytest.mark.parametrize("defect", ["hash", "bytes", "missing-input", "missing-check", "duplicate-check", "parameters", "error", "during-call"])
def test_invalid_or_stale_tool_reports_cannot_certify(tmp_path, defect):
    verifier, args = data_case(tmp_path)
    before = verifier.snapshot()
    reply = response(verifier, args)
    report = reply.structured_content["report"]
    if defect == "hash": report["inputs"][0]["sha256"] = "0" * 64
    elif defect == "bytes": report["inputs"][0]["bytes"] = True
    elif defect == "missing-input": report["inputs"].pop()
    elif defect == "missing-check": report["checks"] = []
    elif defect == "duplicate-check": report["checks"] *= 2
    elif defect == "parameters": report["parameters"]["nir"] = "inputs/red.tif"
    elif defect == "error": reply.is_error = True
    else:
        (tmp_path / "outputs/ndvi.tif").write_bytes(b"changed mid-check")
        reply = response(verifier, args)
    verifier.observe(args, reply, before)
    assert verifier.summary()["status"] == "unverified"


def test_an_input_audit_does_not_cover_required_output(tmp_path):
    verifier, args = data_case(tmp_path)
    args["paths"] = ["inputs/nir.tif"]
    verifier.observe(args, response(verifier, args), verifier.snapshot())
    assert verifier.summary()["status"] == "unverified"


def test_deadline_cannot_produce_verified_state(tmp_path):
    verifier, args = data_case(tmp_path)
    verifier.observe(args, response(verifier, args), verifier.snapshot())
    verifier.deadline = time.monotonic() - 1
    assert verifier.summary()["status"] == "unverified"


@pytest.mark.parametrize("defect", ["unknown-check", "escape", "absolute", "nul", "duplicate", "missing-field", "reserved"])
def test_invalid_plans_are_refused_before_inference(tmp_path, defect):
    document = {"schema": SCHEMA, "tasks": {TASK: [group()]}}
    item = document["tasks"][TASK][0]
    if defect == "unknown-check": item["checks"] = ["made.up"]
    elif defect == "escape": item["parameters"]["nir"] = "inputs/../outside.tif"
    elif defect == "absolute": item["paths"] = ["C:/private/file.tif"]
    elif defect == "nul": item["paths"] = ["outputs/a\0.tif"]
    elif defect == "duplicate": document["tasks"][TASK] *= 2
    elif defect == "missing-field": item.pop("checks")
    else: item["parameters"]["paths"] = []
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError): VerificationPlan(path)


def test_plan_is_frozen_and_requires_exact_deliverable_coverage(tmp_path):
    path = plan_file(tmp_path)
    policy = VerificationPlan(path)
    path.write_text("{}", encoding="utf-8")
    assert policy.groups(TASK, ["ndvi.tif"])[0]["checks"] == ["rs.index_formula"]
    with pytest.raises(ValueError): policy.groups(TASK, ["ndvi.tif", "audit.json"])
    with pytest.raises(ValueError): policy.groups("unknown-task", ["ndvi.tif"])
    path.write_text('{"schema":"x","schema":"y","tasks":{}}', encoding="utf-8")
    with pytest.raises(ValueError): VerificationPlan(path)


def strict_case(tmp_path):
    project, absolute = setup_real_output(tmp_path)
    args = {"paths": ["outputs/ndvi.tif"], "index_formula": "ndvi",
            "nir": "outputs/nir.tif", "red": "outputs/red.tif"}
    declared = {"paths": args["paths"], "checks": ["rs.index_formula"],
                "parameters": {key: value for key, value in args.items() if key != "paths"}}
    return project, args, plan_file(tmp_path, [declared])


def test_no_check_cannot_complete_under_a_declared_policy(tmp_path):
    project, args, policy = strict_case(tmp_path)
    model = FakeModel([[]])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model,
                                     verification_plan=policy).run(_request(project, WITH))
    assert result.status == "failed" and result.turn["verification_status"] == "unverified"
    assert result.turn["reason"] == "required output verification unverified"
    assert result.turn["completion_review_prompts"] == 2 and len(model.requests) == 3
    assert "Required output verification policy" in model.requests[0]["messages"][2]["content"]


def test_real_current_check_after_repair_allows_verified_completion(tmp_path):
    project, args, policy = strict_case(tmp_path)
    model = FakeModel([[('run_python', {'code': REPAIR})], [("terraproof_run_checks", args)], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model,
                                     verification_plan=policy).run(_request(project, WITH))
    assert result.status == "completed", result.turn
    assert result.turn["verification_status"] == "verified"
    assert result.turn["required_verification"]["checks"]["verified"] == 1
    assert str(project) not in json.dumps(result.turn)


def test_changing_data_after_real_check_blocks_completion_until_rechecked(tmp_path):
    project, args, policy = strict_case(tmp_path)
    model = FakeModel([[('run_python', {'code': REPAIR})], [("terraproof_run_checks", args)],
                       [("write_file", {"path": "outputs/mask-policy.txt", "content": "data membership changed"})], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model,
                                     verification_plan=policy).run(_request(project, WITH))
    assert result.status == "failed" and result.turn["verification_status"] == "unverified"
    assert result.turn["completion_review_prompts"] == 2


def test_without_condition_does_not_receive_policy(tmp_path):
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[]])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model,
                                     verification_plan=plan_file(tmp_path)).run(_request(project, WITHOUT))
    assert result.status == "completed" and result.turn["verification_status"] == "unverified"
    assert not result.turn["verification_policy_applied"]
    assert len(model.requests[0]["messages"]) == 2


def test_plan_only_cli_and_host_restriction(tmp_path, capsys):
    policy = plan_file(tmp_path)
    prices = ["--usd-per-million-input", "2", "--usd-per-million-output", "8"]
    assert driver.main(["--agent-host", "openai", "--task", TASK, "--runs", "1",
                        "--verification-plan", str(policy), *prices]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["required_verification"]["applies_to"] == "with-only"
    assert "--verification-plan" in planned["command_to_approve"]
    assert "'" in planned["command_to_approve"]  # filename contains spaces
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "claude", "--verification-plan", str(policy)])


def test_symlink_member_cannot_certify_data(tmp_path, monkeypatch):
    verifier, args = data_case(tmp_path)
    verifier.observe(args, response(verifier, args), verifier.snapshot())
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "ndvi.tif" or original(path))
    assert verifier.summary()["status"] == "unverified"


def test_constructor_refuses_uncovered_outputs(tmp_path):
    with pytest.raises(ValueError): RequiredVerification(tmp_path, [group()], ["ndvi.tif", "audit.json"])
    with pytest.raises(ValueError): RequiredVerification(tmp_path, [], [])


@pytest.mark.parametrize("defect", ["parameters", "coverage"])
def test_preflight_and_direct_run_refuse_bad_contract_before_provider(tmp_path, defect):
    project, args, policy = strict_case(tmp_path)
    document = json.loads(policy.read_text(encoding="utf-8"))
    if defect == "parameters": document["tasks"][TASK][0]["parameters"]["unknown_option"] = 1
    else: document["tasks"][TASK][0]["paths"] = ["outputs/other.tif"]
    policy.write_text(json.dumps(document), encoding="utf-8")
    model = FakeModel([[]])
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model, verification_plan=policy)
    checks = adapter.preflight(_request(project, WITH))
    assert not all(checks.values())
    result = adapter.run(_request(project, WITH))
    assert result.status == "failed" and not model.requests


def test_warn_and_fail_from_real_checker_never_label_verified(tmp_path):
    project, args, policy = strict_case(tmp_path)
    model = FakeModel([[("terraproof_run_checks", args)], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model,
                                     verification_plan=policy).run(_request(project, WITH))
    assert result.status == "failed" and result.turn["verification_status"] == "review-required"
    assert result.turn["reason"] == "required output verification needs review"


def test_rechecking_after_all_writes_restores_verified_state(tmp_path):
    project, args, policy = strict_case(tmp_path)
    model = FakeModel([[('run_python', {'code': REPAIR})], [("terraproof_run_checks", args)],
                       [("write_file", {"path": "outputs/note.txt", "content": "updated data tree"})], [],
                       [("terraproof_run_checks", args)], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model,
                                     verification_plan=policy).run(_request(project, WITH))
    assert result.status == "completed", result.turn
    assert result.turn["verification_status"] == "verified" and result.turn["completion_review_prompts"] == 1


def test_final_state_change_cannot_return_completed(tmp_path, monkeypatch):
    project, args, policy = strict_case(tmp_path)
    states = iter([{"status": "verified"}, {"status": "unverified"}])
    monkeypatch.setattr(RequiredVerification, "summary", lambda self: next(states))
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=FakeModel([[]]),
                                     verification_plan=policy).run(_request(project, WITH))
    assert result.status == "failed" and result.turn["verification_status"] == "unverified"


def test_required_context_is_admitted_under_original_token_cap(tmp_path):
    project, args, policy = strict_case(tmp_path)
    model = FakeModel([[]])
    limits = api_agent.ApiLimits(2, 8, max_tokens=100)
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", limits, transport=model,
                                     verification_plan=policy).run(_request(project, WITH))
    assert not model.requests and result.turn["reason"] == "insufficient token allowance for next request"


def test_approval_command_quotes_powershell_metacharacters_as_data(monkeypatch):
    monkeypatch.setattr(driver, "os", SimpleNamespace(name="nt"))
    rendered = driver.shell_command(["python", "--verification-plan", "x $(command) 'quoted'.json"])
    assert rendered == "python --verification-plan 'x $(command) ''quoted''.json'"


def test_mutated_input_cannot_be_recertified_as_the_original_source(tmp_path):
    verifier, args = data_case(tmp_path)
    verifier.observe(args, response(verifier, args), verifier.snapshot())
    (tmp_path / "inputs/nir.tif").write_bytes(b"changed source")
    assert verifier.snapshot() is None and verifier.summary()["status"] == "unverified"


def test_external_raster_dependency_cannot_be_certified(tmp_path, monkeypatch):
    import rasterio
    verifier, args = data_case(tmp_path)
    before = verifier.snapshot()
    reply = response(verifier, args)
    reply.structured_content["report"]["inputs"][0]["kind"] = "raster"
    class Dataset:
        files = [str(tmp_path.parent / "outside-source.tif")]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(rasterio, "open", lambda *args, **kwargs: Dataset())
    verifier.observe(args, reply, before)
    assert verifier.summary()["status"] == "unverified"


@pytest.mark.parametrize("defect", ["early-budget", "setup-error"])
def test_early_failures_explicitly_remain_unverified(tmp_path, monkeypatch, defect):
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[]])
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model)
    if defect == "setup-error":
        async def fail(request):
            raise OSError("private path must not be saved")
        monkeypatch.setattr(adapter, "_run", fail)
    result = adapter.run(_request(project, WITHOUT, max_usd=0))
    assert result.status == "failed" and result.turn["verification_status"] == "unverified"
    assert not model.requests and "private path" not in json.dumps(result.turn)


def test_grouped_outputs_each_require_current_scoped_evidence(tmp_path):
    verifier, args = data_case(tmp_path)
    (tmp_path / "outputs/second.tif").write_bytes(b"second output")
    declared = group(["outputs/ndvi.tif", "outputs/second.tif"])
    verifier = RequiredVerification(tmp_path, [declared], ["ndvi.tif", "second.tif"])
    args = verifier.arguments(declared)
    reply = response(verifier, args)
    verifier.observe(args, reply, verifier.snapshot())
    assert verifier.summary()["checks"] == {"verified": 1, "review-required": 0, "unverified": 1}
    checks = reply.structured_content["report"]["checks"]
    checks.append({"id": "rs.index_formula", "status": "fail", "evidence": {"output": "outputs/second.tif"}})
    verifier.observe(args, reply, verifier.snapshot())
    assert verifier.summary()["status"] == "review-required"
    checks[-1]["status"] = "pass"
    verifier.observe(args, reply, verifier.snapshot())
    assert verifier.summary()["status"] == "verified"
    (tmp_path / "outputs/second.tif").write_bytes(b"changed output")
    assert verifier.summary()["checks"]["unverified"] == 2
