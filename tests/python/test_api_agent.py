"""Offline tests for the OpenAI-compatible lift adapter (tests/api_agent.py). No request leaves the machine:
every model reply comes from a scripted fake transport, and a guard fails any real HTTP attempt."""

from __future__ import annotations

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
                              "max_tokens": payload.get("max_tokens")})
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
    (api_agent.ApiLimits(2.0, 8.0, max_tokens=2500), 1.0, "token cap reached", 3),
    (api_agent.ApiLimits(100.0, 400.0), 0.25, "per-run budget reached", 2),
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


def test_terraproof_use_in_without_is_labelled_contamination(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITHOUT)
    model = FakeModel([[("run_python", {"code": "import terraproof"})], []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITHOUT))
    assert "terraproof-in-without:import" in result.contamination


def test_with_condition_exposes_terraproof_tools_from_the_installed_server(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    project = _project(tmp_path, WITH)
    model = FakeModel([[("terraproof_list_skills", {})],
                       [("terraproof_load_section", {"skill": "spectral-indices", "section_id": "missing-section"})],
                       []])
    result = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model).run(_request(project, WITH))
    assert result.status == "completed"
    assert {f"terraproof_{name}" for name in driver.TOOLS} <= set(model.requests[0]["tools"])
    assert [c["tool"] for c in result.calls] == ["terraproof.list_skills", "terraproof.load_section"]
    assert result.calls[0]["status"] == "completed" and result.calls[0]["category"] == "mcp:list_skills"
    assert result.terraproof_tool_calls == 2 and result.skill_reads == 1
    assert not result.contamination


def test_run_lift_integration_with_a_fake_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    model = FakeModel([[("list_files", {})], []] * 2)
    adapter = api_agent.ApiAgentAdapter("openai", "gpt-4o", PRICES, transport=model)
    report = lift.run_lift(adapter, task_ids=[TASK], runs=1, agent="claude", allow_model_calls=True,
                           budget=Budget(max_runs=2, per_run_usd=1.0, total_usd=2.0), work_root=tmp_path / "work")
    assert report["adapter"] == {"name": "openai-api", "model_calls": True}
    runs = {run["condition"]: run for run in report["tasks"][0]["runs"]}
    # No dependency-only Python was given, so "without" must not start: the isolation gate holds for API hosts.
    assert runs[WITHOUT]["adapter_status"] == "preflight_failed"
    assert runs[WITHOUT]["preflight"]["checks"]["without_agent_python_set"] is False
    assert runs[WITH]["verdict"] == "missing" and runs[WITH]["preflight"]["checks"]["mcp_tools_served"] is True
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
