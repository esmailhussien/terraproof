"""Offline tests for the OpenAI-compatible lift adapter (tests/api_agent.py). No request leaves the machine:
every model reply comes from a scripted fake transport, and a guard fails any real HTTP attempt."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

import pytest

from terraproof.evals import lift
from terraproof.evals.lift import WITH, WITHOUT, AgentRequest, Budget

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
DRIVER_SPEC = importlib.util.spec_from_file_location("agent_lift", TESTS / "agent_lift.py")
driver = importlib.util.module_from_spec(DRIVER_SPEC)
sys.modules.setdefault("agent_lift", driver)
DRIVER_SPEC.loader.exec_module(driver)
import api_agent  # noqa: E402

FAKE_KEY = "sk-test-not-a-real-key"
TASK = "indices-ndvi-physical-inputs"
PRICES = api_agent.ApiLimits(usd_per_million_input=2.0, usd_per_million_output=8.0)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):  # pragma: no cover - a test reaching here is a bug
        raise AssertionError("a real HTTP request was attempted")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


class FakeModel:
    """Replays scripted assistant turns and records what each request carried."""

    def __init__(self, turns, usage=(1000, 200)):
        self.turns = list(turns)
        self.usage = usage
        self.requests = []

    def __call__(self, url, headers, payload, timeout):
        self.requests.append({"url": url, "auth": headers.get("Authorization"),
                              "tools": [tool["function"]["name"] for tool in payload["tools"]],
                              "max_tokens": payload.get("max_tokens"),
                              "messages": copy.deepcopy(payload["messages"])})
        turn = self.turns.pop(0) if self.turns else []
        message = {"role": "assistant", "content": None if turn else "done"}
        if turn:
            message["tool_calls"] = [{"id": f"call-{len(self.requests)}-{i}", "type": "function",
                                      "function": {"name": name, "arguments": json.dumps(arguments)}}
                                     for i, (name, arguments) in enumerate(turn)]
        return {"choices": [{"message": message, "finish_reason": "tool_calls" if turn else "stop"}],
                "usage": {"prompt_tokens": self.usage[0], "completion_tokens": self.usage[1]}}


def _project(tmp_path, condition, task_id=TASK):
    task = lift.lift_task(task_id)
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    project = tmp_path / "run" / "project"
    lift.prepare_project(task, lift._specs()[task_id], reference, project, condition=condition, agent="claude")
    return project


def _request(project, condition, *, max_usd=1.0, timeout=120.0):
    return AgentRequest(TASK, condition, 0, project, "brief", timeout, max_usd)


def test_loop_runs_confined_tools_and_reports_labels_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([
        [("list_files", {})],
        [("read_file", {"path": "TASK.md"})],
        [("run_python", {"code": "import pathlib; pathlib.Path('outputs/note.txt').write_text('42'); print('ok')"})],
        [("write_file", {"path": "outputs/summary.txt", "content": "secret-model-text"})],
        [],
    ])
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model)
    result = adapter.run(_request(project, WITHOUT))
    assert result.status == "completed" and result.turn["reason"] == "ok" and result.turn["model_calls"] == 5
    assert [(c["tool"], c["category"], c["status"]) for c in result.calls] == [
        ("list_files", "file_read", "completed"), ("read_file", "file_read", "completed"),
        ("run_python", "shell", "completed"), ("write_file", "file_edit", "completed")]
    assert result.calls[2]["exit_code"] == 0
    assert (project / "outputs" / "note.txt").read_text() == "42"
    assert result.input_tokens == 5000 and result.output_tokens == 1000
    assert result.cost_usd == pytest.approx(5000 * 2.0 / 1e6 + 1000 * 8.0 / 1e6)
    assert model.requests[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert model.requests[0]["auth"] == f"Bearer {FAKE_KEY}"
    assert model.requests[0]["max_tokens"] == api_agent.MAX_COMPLETION_TOKENS
    assert not any(name.startswith("terraproof_") for name in model.requests[0]["tools"])  # without: no treatment
    report = json.dumps(asdict(result))
    assert FAKE_KEY not in report and "secret-model-text" not in report and "write_text" not in report
    assert not result.contamination
    assert result.turn["mcp_instructions_delivered"] is False
    assert result.turn["mcp_instructions_sha256"] is None
    assert model.requests[0]["messages"] == [
        {"role": "system", "content": api_agent.SYSTEM_PROMPT}, {"role": "user", "content": driver.PROMPT}]


@pytest.mark.parametrize("path", ["../escape.txt", "..\\escape.txt", "/tmp/escape.txt", "C:\\escape.txt",
                                  "inputs/../../escape.txt"])
def test_file_tools_refuse_paths_outside_the_project(tmp_path, monkeypatch, path):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[("write_file", {"path": path, "content": "x"}), ("read_file", {"path": path})], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITHOUT))
    assert [c["status"] for c in result.calls] == ["failed", "failed"]
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "run" / "escape.txt").exists()


@pytest.mark.parametrize("limits,max_usd,reason,calls", [
    (api_agent.ApiLimits(2.0, 8.0, max_model_calls=3), 1.0, "model call cap reached", 3),
    (api_agent.ApiLimits(2.0, 8.0, max_tokens=100), 1.0, "insufficient token allowance for next request", 0),
    (api_agent.ApiLimits(100.0, 400.0), 0.01, "insufficient budget for next request", 0),
])
def test_caps_stop_the_loop_before_the_next_call(tmp_path, monkeypatch, limits, max_usd, reason, calls):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[("list_files", {})]] * 50)
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", limits, transport=model).run(
        _request(project, WITHOUT, max_usd=max_usd))
    assert result.status == "failed" and result.turn["reason"] == reason
    assert len(model.requests) == calls == result.turn["model_calls"]


def test_missing_key_sends_nothing_and_api_errors_carry_no_body(tmp_path, monkeypatch):
    project = _project(tmp_path, WITHOUT)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    model = FakeModel([[]])
    adapter = api_agent.ApiAgentAdapter("groq", "some-model", PRICES, transport=model)
    result = adapter.run(_request(project, WITHOUT))
    assert result.status == "failed" and result.turn["reason"] == "GROQ_API_KEY is not set" and not model.requests
    assert not adapter.key_present()

    def unauthorized(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", unauthorized)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    with pytest.raises(api_agent.ApiError) as raised:
        api_agent.http_transport("https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {FAKE_KEY}"},
                                 {"model": "m"}, 5)
    assert str(raised.value) == "http 401" and FAKE_KEY not in str(raised.value)
    errored = api_agent.ApiAgentAdapter("groq", "some-model", PRICES).run(_request(project, WITHOUT))
    assert errored.status == "failed" and errored.turn["reason"] == "http 401"
    assert FAKE_KEY not in json.dumps(asdict(errored))


def test_http_transport_sends_an_explicit_user_agent(monkeypatch):
    seen = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"choices": []}'

    def capture(request, timeout):
        seen.update({key.lower(): value for key, value in request.header_items()})
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    api_agent.http_transport("https://api.groq.com/openai/v1/chat/completions", {"Authorization": "Bearer x"}, {}, 5)
    # Groq's edge answers urllib's default "Python-urllib/3.x" agent with HTTP 403.
    assert seen["user-agent"] == api_agent.USER_AGENT and not seen["user-agent"].startswith("Python-urllib")


def test_terraproof_use_in_without_is_labelled_contamination(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[("run_python", {"code": "import terraproof"})], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITHOUT))
    assert "terraproof-in-without:import" in result.contamination


def test_with_condition_exposes_terraproof_tools_from_the_installed_server(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITH)
    (project / "CLAUDE.md").write_text("unrelated-local-instructions", encoding="utf-8")
    model = FakeModel([[("terraproof_list_skills", {})],
                       [("terraproof_load_section", {"skill": "spectral-indices", "section_id": "missing-section"})],
                       []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITH))
    assert result.status == "completed", result.turn
    assert {f"terraproof_{name}" for name in driver.TOOLS} <= set(model.requests[0]["tools"])
    assert [c["tool"] for c in result.calls] == ["terraproof.list_skills", "terraproof.load_section"]
    assert result.calls[0]["status"] == "completed" and result.calls[0]["category"] == "mcp:list_skills"
    assert result.terraproof_tool_calls == 2 and result.skill_reads == 1
    assert not result.contamination
    from terraproof.mcp.server import INSTRUCTIONS
    expected = {"role": "system", "content": "Terraproof tool guidance from the configured MCP server:\n" + INSTRUCTIONS}
    assert model.requests[0]["messages"] == [
        {"role": "system", "content": api_agent.SYSTEM_PROMPT}, expected, {"role": "user", "content": driver.PROMPT}]
    assert all(request["messages"][1] == expected for request in model.requests)
    assert "unrelated-local-instructions" not in json.dumps(model.requests)
    assert result.turn["mcp_instructions_delivered"] is True
    assert result.turn["mcp_instructions_chars"] == len(INSTRUCTIONS)
    assert result.turn["mcp_instructions_sha256"] == hashlib.sha256(INSTRUCTIONS.encode("utf-8")).hexdigest()
    # Delivery is not compliance: the scripted model called no run_checks and read no valid section.
    assert not any(call["tool"] == "terraproof.run_checks" for call in result.calls)
    assert INSTRUCTIONS not in json.dumps(asdict(result))


def test_run_lift_integration_with_a_fake_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    model = FakeModel([[("list_files", {})], []] * 2)
    # The "with" interpreter is product-only in real runs (Phase 6 B6); its probe is tested in
    # test_lift.py, so here it is stubbed as passing to reach the rest of the "with" preflight.
    seen = []
    monkeypatch.setattr(api_agent.driver, "with_isolation_checks", lambda project, python, env: (
        seen.append(python) or {"with_agent_python_set": True, "with_terraproof_importable": True,
                                "with_evals_not_importable": True}))
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model, agent_python_with=sys.executable)
    report = lift.run_lift(adapter, task_ids=[TASK], runs=1, agent="claude", allow_model_calls=True,
                           budget=Budget(max_runs=2, per_run_usd=1.0, total_usd=2.0), work_root=tmp_path / "work")
    assert report["adapter"] == {"name": "openai-api", "model_calls": True}
    runs = {run["condition"]: run for run in report["tasks"][0]["runs"]}
    # No dependency-only Python was given, so "without" must not start: the isolation gate holds for API hosts.
    assert runs[WITHOUT]["adapter_status"] == "preflight_failed"
    assert runs[WITHOUT]["preflight"]["checks"]["without_agent_python_set"] is False
    assert runs[WITH]["verdict"] == "missing" and runs[WITH]["preflight"]["checks"]["mcp_tools_served"] is True, runs[WITH]
    assert runs[WITH]["preflight"]["checks"]["mcp_instructions_available"] is True
    assert seen == [sys.executable] and runs[WITH]["preflight"]["checks"]["with_evals_not_importable"] is True
    assert report["design"]["started_agent_runs"] == 1
    assert 0 < report["budget"]["spent_usd"] <= 1.0
    assert FAKE_KEY not in lift.to_json(report)


def test_driver_plans_api_hosts_and_refuses_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    prices = ["--usd-per-million-input", "2", "--usd-per-million-output", "8"]
    assert driver.main(["--agent-host", "openai", "--runs", "1", "--task", TASK, *prices]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_model_invocations"] == 2 and plan["total_usd_ceiling"] == 2.0
    assert plan["api"]["model"] == "gpt-4o" and plan["api"]["max_model_calls_per_run"] == 40
    assert "--api-model gpt-4o" in plan["command_to_approve"]
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "groq", "--runs", "1", "--task", TASK, *prices])  # no default model
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "openai", "--runs", "1", "--task", TASK])  # prices are required
    assert driver.main(["--agent-host", "openai", "--runs", "1", "--task", TASK, *prices,
                        "--approve-model-calls", "2"]) == 1
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert refused == {"model_called": False, "reason": "OPENAI_API_KEY is not set; no request was sent",
                       "status": "unavailable"}


def _http_error(code, body=b"", headers=None):
    from email.message import Message
    import io

    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError("https://api.example/v1/chat/completions", code, "error", message,
                                  io.BytesIO(body))


def test_error_labels_are_short_codes_and_never_body_text(monkeypatch):
    secret = b'{"error": {"code": "tool_use_failed", "message": "Failed to call a function: secret-model-text"}}'
    assert api_agent.error_type_label(secret) == "tool_use_failed"
    assert api_agent.error_type_label(b'{"error": {"type": "rate_limit_exceeded"}}') == "rate_limit_exceeded"
    assert api_agent.error_type_label(b'{"error": {"code": "has spaces and free text"}}') is None
    assert api_agent.error_type_label(b"<html>secret</html>") is None
    assert api_agent.retry_after_seconds("7") == 7.0 and api_agent.retry_after_seconds(None) is None
    assert api_agent.retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # a past date waits 0 s

    def bad_request(request, timeout):
        raise _http_error(400, secret)

    monkeypatch.setattr(urllib.request, "urlopen", bad_request)
    with pytest.raises(api_agent.ApiError) as raised:
        api_agent.http_transport("https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {FAKE_KEY}"},
                                 {}, 5)
    assert str(raised.value) == "http 400 (tool_use_failed)" and raised.value.status == 400
    assert "secret" not in str(raised.value) and FAKE_KEY not in str(raised.value)

    def limited(request, timeout):
        raise _http_error(429, b'{"error": {"code": "rate_limit_exceeded"}}', {"Retry-After": "2"})

    monkeypatch.setattr(urllib.request, "urlopen", limited)
    with pytest.raises(api_agent.ApiError) as raised:
        api_agent.http_transport("https://api.groq.com/openai/v1/chat/completions", {}, {}, 5)
    assert (raised.value.status, raised.value.error_type, raised.value.retry_after) == (429, "rate_limit_exceeded", 2.0)


class FlakyModel(FakeModel):
    """Raises scripted ApiErrors before replying like FakeModel."""

    def __init__(self, errors, turns=((),)):
        super().__init__([list(turn) for turn in turns])
        self.errors = list(errors)

    def __call__(self, url, headers, payload, timeout):
        if self.errors:
            self.requests.append({"error": True})
            raise self.errors.pop(0)
        return super().__call__(url, headers, payload, timeout)


def _rate_limited(retry_after=None):
    return api_agent.ApiError("http 429", status=429, error_type="rate_limit_exceeded", retry_after=retry_after)


def _recording_sleep():
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    return waits, sleep


def test_rate_limits_are_retried_with_retry_after_then_backoff(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    model = FlakyModel([_rate_limited(5.0), _rate_limited(None)])
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert waits == [5.0, 4.0]  # Retry-After first, then exponential backoff (2 ** retry)
    assert result.status == "completed" and result.turn["model_calls"] == 3 and result.turn["rate_limit_retries"] == 2
    assert result.turn["error_types"] == ["rate_limit_exceeded"] and result.turn["error_items"] == 2


def test_rate_limit_retries_are_bounded_and_count_against_the_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    model = FlakyModel([_rate_limited(0.0)] * 10)
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert result.status == "failed" and result.turn["reason"] == "http 429 (rate_limit_exceeded); rate-limit retries exhausted"
    assert len(waits) == api_agent.RATE_LIMIT_RETRIES and result.turn["model_calls"] == api_agent.RATE_LIMIT_RETRIES + 1

    capped = api_agent.ApiLimits(2.0, 8.0, max_model_calls=2)
    model = FlakyModel([_rate_limited(0.0)] * 10)
    result = api_agent.ApiAgentAdapter("groq", "m", capped, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert result.turn["reason"] == "model call cap reached" and len(model.requests) == 2


def test_rate_limit_waits_respect_the_timeout_and_the_wait_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    model = FlakyModel([_rate_limited(50.0)])
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(
        _request(project, WITHOUT, timeout=10.0))
    assert waits == [] and result.turn["reason"].endswith("retry wait exceeds the per-run timeout")

    model = FlakyModel([_rate_limited(600.0)])
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(
        _request(project, WITHOUT, timeout=900.0))
    assert waits == [api_agent.MAX_RETRY_WAIT] and result.status == "completed"


def test_rate_limit_retries_and_wait_cap_are_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    patient = api_agent.ApiLimits(2.0, 8.0, rate_limit_retries=5, max_retry_wait=120.0)
    model = FlakyModel([_rate_limited(600.0)] * 5)
    result = api_agent.ApiAgentAdapter("groq", "m", patient, transport=model, sleep=sleep).run(
        _request(project, WITHOUT, timeout=900.0))
    assert waits == [120.0] * 5 and result.status == "completed" and result.turn["rate_limit_retries"] == 5


def _tool_use_failed():
    return api_agent.ApiError("http 400", status=400, error_type="tool_use_failed")


def test_tool_use_failed_is_retried_twice_without_waiting(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    model = FlakyModel([_tool_use_failed(), _tool_use_failed()])
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert waits == [] and result.status == "completed"
    assert result.turn["tool_use_retries"] == 2 and result.turn["model_calls"] == 3
    assert result.turn["error_types"] == ["tool_use_failed"] and result.turn["error_items"] == 2


def test_tool_use_retries_are_bounded_and_count_against_the_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    model = FlakyModel([_tool_use_failed()] * 10)
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert result.status == "failed"
    assert result.turn["reason"] == "http 400 (tool_use_failed); tool-use retries exhausted"
    assert result.turn["model_calls"] == api_agent.TOOL_USE_RETRIES + 1 and waits == []

    capped = api_agent.ApiLimits(2.0, 8.0, max_model_calls=2)
    model = FlakyModel([_tool_use_failed()] * 10)
    result = api_agent.ApiAgentAdapter("groq", "m", capped, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert result.turn["reason"] == "model call cap reached" and len(model.requests) == 2


def test_other_client_errors_are_labelled_and_not_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    waits, sleep = _recording_sleep()
    model = FlakyModel([api_agent.ApiError("http 400", status=400, error_type="invalid_request_error"),
                        _tool_use_failed()])
    result = api_agent.ApiAgentAdapter("groq", "m", PRICES, transport=model, sleep=sleep).run(_request(project, WITHOUT))
    assert waits == [] and result.status == "failed" and result.turn["model_calls"] == 1
    assert result.turn["reason"] == "http 400 (invalid_request_error)"


@pytest.mark.parametrize("tokens,usd,usage,reason", [
    (300000, 0.10, (1000, 20000), "per-run budget exceeded"),
    (20000, 1.0, (25000, 200), "token cap exceeded"),
    (300000, 1.0, (1000, 5000), "provider usage exceeded request reservation"),
])
def test_terminal_reply_cannot_bypass_limits(tmp_path, monkeypatch, tokens, usd, usage, reason):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    model = FakeModel([[]], usage=usage)
    adapter = api_agent.ApiAgentAdapter("openai", "fake", api_agent.ApiLimits(2, 8, max_tokens=tokens), transport=model)
    result = adapter.run(_request(_project(tmp_path, WITHOUT), WITHOUT, max_usd=usd))
    assert len(model.requests) == 1
    assert result.status == "failed" and result.turn["reason"] == reason
    assert result.cost_usd == pytest.approx((usage[0] * 2 + usage[1] * 8) / 1e6)
    assert result.tool_calls == 0


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": -1, "completion_tokens": 2},
    {"prompt_tokens": True, "completion_tokens": 2},
    {"prompt_tokens": "10", "completion_tokens": 2},
    {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 99}])
def test_unknown_usage_is_not_free_or_successful(tmp_path, monkeypatch, usage):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    def response(*args):
        return {"usage": usage, "choices": [{"message": {"content": "done"}}]}
    adapter = api_agent.ApiAgentAdapter("openai", "fake", PRICES, transport=response)
    result = adapter.run(_request(_project(tmp_path, WITHOUT), WITHOUT))
    assert result.status == "failed" and "invalid usage" in result.turn["reason"]
    assert result.cost_usd > 0 and result.input_tokens == result.output_tokens == 0
    assert result.turn["unreported_tokens_reserved"] > 0
    assert result.turn["cost_basis"] == "reported-plus-reserved"


def test_requested_output_shrinks_to_remaining_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    model = FakeModel([[]], usage=(1, 1))
    result = api_agent.ApiAgentAdapter("openai", "fake", PRICES, transport=model).run(
        _request(_project(tmp_path, WITHOUT), WITHOUT, max_usd=0.025))
    assert result.status == "completed" and len(model.requests) == 1
    assert 0 < model.requests[0]["max_tokens"] < api_agent.MAX_COMPLETION_TOKENS


def test_over_budget_tool_reply_cannot_write(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[('write_file', {'path': 'outputs/forbidden.txt', 'content': 'x'})]], usage=(1000, 20000))
    result = api_agent.ApiAgentAdapter("openai", "fake", PRICES, transport=model).run(
        _request(project, WITHOUT, max_usd=0.1))
    assert result.status == "failed" and result.tool_calls == 0
    assert not (project / 'outputs/forbidden.txt').exists()


def test_failed_transport_reserves_the_admitted_request(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    def failed(*args):
        raise OSError("private response text")
    result = api_agent.ApiAgentAdapter("openai", "fake", PRICES, transport=failed).run(
        _request(_project(tmp_path, WITHOUT), WITHOUT))
    assert result.status == "failed" and result.cost_usd > 0
    assert result.turn["reason"] == "transport error (OSError)"
    assert 'private response text' not in json.dumps(asdict(result))


@pytest.mark.parametrize('field,value', [('usd_per_million_input', float('nan')),
    ('usd_per_million_output', float('inf')), ('max_tokens', -1), ('max_model_calls', 0)])
def test_invalid_api_limits_are_rejected(field, value):
    args = {'usd_per_million_input': 2.0, 'usd_per_million_output': 8.0, field: value}
    with pytest.raises(ValueError):
        api_agent.ApiLimits(**args)


@pytest.mark.parametrize("option,value", [("--max-usd-per-run", "nan"), ("--max-usd-total", "inf"),
    ("--usd-per-million-input", "inf"), ("--max-retry-wait", "nan")])
def test_driver_rejects_nonfinite_limits_before_planning(option, value):
    prices = ["--usd-per-million-input", "2", "--usd-per-million-output", "8"]
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "openai", "--runs", "1", "--task", TASK, *prices, option, value])


class StubMcpClient:
    """Exercise missing instructions without launching a replacement server or model."""

    def __init__(self, instructions):
        self.instructions = instructions

    async def list_tools(self):
        from types import SimpleNamespace
        return SimpleNamespace(tools=[])


@pytest.mark.parametrize("instructions", [None, "", "  ", 42, "x" * (api_agent.READ_LIMIT + 1), "\ud800"])
def test_invalid_server_instructions_stop_before_model_request(tmp_path, monkeypatch, instructions):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    model = FakeModel([[]])
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model)
    request = _request(_project(tmp_path, WITH), WITH)
    result = asyncio.run(adapter._loop(request, StubMcpClient(instructions)))
    assert result.status == "failed" and not model.requests and result.cost_usd == 0.0
    assert result.turn["reason"] == "missing or invalid Terraproof MCP instructions"
    assert result.turn["model_calls"] == 0 and result.turn["mcp_instructions_delivered"] is False


def test_instructions_consume_the_request_allowance(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITH)
    instructions = "guidance-" * 2000  # valid size but larger than this run's allowance
    model = FakeModel([[]])
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", api_agent.ApiLimits(2, 8, max_tokens=12000), transport=model)
    # The same base prompt and file schemas fit without the server text.
    assert api_agent.prompt_reservation([
        {"role": "system", "content": api_agent.SYSTEM_PROMPT}, {"role": "user", "content": driver.PROMPT}],
        api_agent.FILE_TOOLS) + 1 < 12000
    result = asyncio.run(adapter._loop(_request(project, WITH), StubMcpClient(instructions)))
    assert not model.requests and result.turn["reason"] == "insufficient token allowance for next request"
    assert result.turn["mcp_instructions_delivered"] is False


def test_preflight_rejects_missing_instructions_even_when_tools_are_served(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import mcp

    class Client:
        instructions = None

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in driver.TOOLS])

    monkeypatch.setattr(mcp, "Client", Client)
    checks = asyncio.run(api_agent.mcp_preflight(_project(tmp_path, WITH)))
    assert checks == {"mcp_tools_served": True, "mcp_instructions_available": False}


def test_agent_receives_source_check_results_without_automatic_repair(tmp_path, monkeypatch):
    from test_index_formula import _case, GRID
    from terraproof.evals.fixtures import write_raster_grid

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITH)
    (project / "verification").mkdir()
    out, nir, red, values = _case(project / "verification")
    bad = project / "verification" / "bad-mask.tif"
    values[2, 3] = 0  # numerically plausible but unsupported by the source nodata mask
    write_raster_grid(bad, values, transform=GRID)
    before = bad.read_bytes()
    model = FakeModel([[('terraproof_run_checks', {
        'paths': [str(path)], 'index_formula': 'ndvi', 'nir': str(nir), 'red': str(red)})
        for path in (out, bad)], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITH))
    replies = [json.loads(message['content']) for message in model.requests[1]['messages'] if message['role'] == 'tool']
    checks = [next(check for check in reply['report']['checks'] if check['id'] == 'rs.index_formula')
              for reply in replies]
    assert [check['status'] for check in checks] == ['pass', 'fail']
    assert checks[1]['evidence']['unsupported_output_cells'] == 1
    assert result.terraproof_tool_calls == 2 and all(call['status'] == 'completed' for call in result.calls)
    # A completed tool/agent is not an accepted deliverable; no hidden repair or forced retry occurs.
    assert result.status == 'completed' and bad.read_bytes() == before
