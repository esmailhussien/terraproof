"""The independent release gate must never turn omissions/errors into success.

These unit tests do not start an MCP server or contact any model.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / "release_validation.py"
SPEC = importlib.util.spec_from_file_location("release_validation", PATH)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


def complete_report():
    report = validation.Report()
    for name in sorted(validation.REQUIRED):
        report.check(name, True, "explicit assertion")
    return report


def test_complete_explicit_assertions_pass_and_json_is_stable(tmp_path):
    report = complete_report()
    assert report.finish() == 0
    out = tmp_path / "report.json"
    report.write(out)
    first = out.read_bytes()
    report.write(out)
    assert out.read_bytes() == first
    data = json.loads(first)
    assert data["status"] == "pass"
    assert data["runtime"]["python"]
    assert data["runtime"]["platform"]
    assert data["runtime"]["executable"] == sys.executable
    assert data["agent_host"] == {"status": "not-requested", "model_called": False}
    assert data["limitations"]


def test_empty_or_missing_assertions_cannot_pass():
    report = validation.Report()
    assert report.finish() == 1
    report = complete_report()
    report.data["assertions"].pop()
    assert report.finish() == 1
    assert report.data["missing_assertions"]


def test_failed_assertion_is_recorded_before_raising():
    report = complete_report()
    with pytest.raises(validation.ValidationError):
        report.check("negative", False, "must fail")
    assert report.data["assertions"][-1]["status"] == "fail"
    assert report.finish() == 1


@pytest.mark.parametrize("mutation", ["duplicate", "exception", "host-unavailable", "host-fail"])
def test_failure_gates(mutation):
    report = complete_report()
    if mutation == "duplicate":
        report.data["assertions"].append(dict(report.data["assertions"][0]))
    elif mutation == "exception":
        report.data["failure"] = {"type": "TimeoutError"}
    else:
        report.data["agent_host"]["status"] = mutation.removeprefix("host-")
    assert report.finish() == 1


def test_wrong_child_exit_is_never_accepted(monkeypatch):
    monkeypatch.setattr(validation, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, "{}", ""))
    with pytest.raises(validation.ValidationError, match="expected exit 3, got 0"):
        validation.cli("check", "fixture", code=3)


@pytest.mark.parametrize("exception", [subprocess.TimeoutExpired("child", 1), RuntimeError("PRIVATE_TOKEN")])
def test_main_writes_failed_report_on_abort_without_leaking_output(monkeypatch, tmp_path, exception):
    monkeypatch.setattr(validation, "ROOT", tmp_path)
    monkeypatch.setattr(validation, "fixtures", lambda work: {})
    def fail(*args, **kwargs):
        raise exception
    monkeypatch.setattr(validation, "cli", fail)
    out = tmp_path / "result.json"
    assert validation.main(["--out", str(out)]) == 1
    text = out.read_text(encoding="utf-8")
    assert "PRIVATE_TOKEN" not in text
    assert json.loads(text)["status"] == "fail"
    assert not list((tmp_path / ".terracache").iterdir())


def test_unauthenticated_host_is_unavailable_without_model_call(monkeypatch, tmp_path):
    monkeypatch.setattr(validation.shutil, "which", lambda name: "claude")
    commands = []
    def probe(args, **kwargs):
        commands.append(args)
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, "2.1.292", "")
        if "--help" in args:
            return subprocess.CompletedProcess(args, 0, "--restricted --strict-mcp-config --no-session-persistence --tools --allowedTools --max-budget-usd --permission-prompts --setting-sources", "")
        assert args == ["claude", "auth", "status", "--json"]
        return subprocess.CompletedProcess(args, 1, '{"loggedIn":false}', "PRIVATE_TOKEN")
    monkeypatch.setattr(validation, "run", probe)
    report = complete_report()
    validation.agent_host(report, tmp_path, {})
    assert report.finish() == 1
    assert report.data["agent_host"]["status"] == "unavailable"
    assert report.data["agent_host"]["model_called"] is False
    assert "PRIVATE_TOKEN" not in json.dumps(report.data)
    assert len(commands) == 3


def test_host_prose_and_tool_calls_without_results_are_not_success():
    assert validation.host_trace([{"type": "result", "subtype": "success", "is_error": False,
                                   "result": "I called list_skills and inspect_dataset"}])[0] is False
    assert validation.host_trace(trace()[:1])[0] is False


def trace():
    names = ["mcp__terraproof__list_skills", "mcp__terraproof__inspect_dataset"]
    return [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": str(i), "name": name} for i, name in enumerate(names)]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": str(i), "content": "ok"} for i in range(2)]}},
        {"type": "result", "subtype": "success", "is_error": False},
    ]


def test_host_requires_successful_permitted_trace_and_final_result():
    events = trace()
    assert validation.host_trace(events)[0] is True
    events[1]["message"]["content"][0]["is_error"] = True
    assert validation.host_trace(events)[0] is False
    events = trace()
    events[0]["message"]["content"].append({"type": "tool_use", "id": "3", "name": "Bash"})
    assert validation.host_trace(events)[0] is False
    events = trace()
    events[-1]["is_error"] = True
    assert validation.host_trace(events)[0] is False


def test_default_main_never_calls_real_host(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "ROOT", tmp_path)
    monkeypatch.setattr(validation, "fixtures", lambda work: {})
    monkeypatch.setattr(validation, "cli", lambda *a: subprocess.CompletedProcess([], 0, "COMMAND", ""))
    monkeypatch.setattr(validation, "installers", lambda *a: None)
    async def validated(report, *args):
        for name in sorted(validation.REQUIRED - {"cli.help"}):
            report.check(name, True, "mock assertion; no subprocess/model")
    monkeypatch.setattr(validation, "validate_stdio", validated)
    monkeypatch.setattr(validation, "agent_host", lambda *a: pytest.fail("default must not call a model"))
    monkeypatch.setattr(validation, "codex_host", lambda *a: pytest.fail("default must not call Codex"))
    out = tmp_path / "result.json"
    assert validation.main(["--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["agent_host"]["model_called"] is False


def codex_events(fixture):
    events = []
    for index, tool in enumerate(validation.CODEX_TOOLS):
        item = {"id": str(index), "type": "mcp_tool_call", "server": "terraproof", "tool": tool,
                "arguments": {} if tool == "list_skills" else {"path": str(fixture)}, "status": "in_progress"}
        events.append({"type": "item.started", "item": dict(item)})
        payload = ({"result": [{"name": "gdal"}]} if tool == "list_skills" else
                   {"kind": "vector", "feature_count": 1, "crs": {"epsg": 32636}})
        item.update(status="completed", error=None, result={"structured_content": payload})
        events.append({"type": "item.completed", "item": item})
    events.append({"type": "turn.completed", "usage": {}})
    return events


def test_codex_trace_requires_calls_and_real_successful_results(tmp_path):
    fixture = tmp_path / "fixture.geojson"
    assert validation.codex_trace(codex_events(fixture), fixture) == (True, sorted(validation.CODEX_TOOLS))
    prose = [{"type": "item.completed", "item": {"type": "agent_message", "text": "Tools passed"}},
             {"type": "turn.completed"}]
    assert validation.codex_trace(prose, fixture)[0] is False


@pytest.mark.parametrize("problem", ["missing-start", "missing-result", "tool-error", "wrong-path", "empty-profile",
                                    "builtin", "other-server", "failed-turn", "no-completion", "duplicate", "after-turn"])
def test_codex_trace_rejects_false_positives(tmp_path, problem):
    fixture = tmp_path / "fixture.geojson"
    events = codex_events(fixture)
    if problem == "missing-start":
        events.pop(0)
    elif problem == "missing-result":
        events[3]["item"]["result"] = None
    elif problem == "tool-error":
        events[3]["item"]["result"]["isError"] = True
    elif problem == "wrong-path":
        events[2]["item"]["arguments"] = events[3]["item"]["arguments"] = {"path": "other"}
    elif problem == "empty-profile":
        events[3]["item"]["result"]["structured_content"] = {}
    elif problem == "builtin":
        events.insert(0, {"type": "item.started", "item": {"type": "command_execution"}})
    elif problem == "other-server":
        events[0]["item"]["server"] = events[1]["item"]["server"] = "other"
    elif problem == "failed-turn":
        events.append({"type": "turn.failed"})
    elif problem == "no-completion":
        events.pop()
    elif problem == "duplicate":
        events.insert(2, events[1])
    else:
        events.insert(0, {"type": "turn.completed"})
    assert validation.codex_trace(events, fixture)[0] is False


CODEX_STARTUP_WARNINGS = (
    "WARNING: failed to clean up stale arg0 temp dirs: Access is denied. (os error 5)\n"
    "WARNING: proceeding, even though we could not create PATH aliases: "
    'Access is denied. (os error 5) at path "C:\\synthetic\\temp"\n'
)


@pytest.mark.parametrize("stdout,stderr", [
    ("Logged in using ChatGPT\n", ""),
    ("", "Logged in using ChatGPT\n"),
    ("", CODEX_STARTUP_WARNINGS + "Logged in using ChatGPT\n"),
    ("Logged in using ChatGPT\n", CODEX_STARTUP_WARNINGS),
    ("", "\x1b[32mLogged in using ChatGPT\x1b[0m\r\n"),
])
def test_codex_auth_accepts_explicit_status_with_confirmed_startup_warnings(stdout, stderr):
    assert validation.codex_subscription_auth(subprocess.CompletedProcess([], 0, stdout, stderr))


@pytest.mark.parametrize("code,stdout,stderr", [
    (1, "", "Logged in using ChatGPT"),
    (0, "", ""),
    (0, "", CODEX_STARTUP_WARNINGS),
    (0, "", "Not logged in"),
    (0, "", "Logged in using an API key"),
    (0, "Logged in using ChatGPT", "Logged in using an API key"),
    (0, "Logged in using ChatGPT", "API-paid provider active"),
    (0, "", "Possibly Logged in using ChatGPT"),
    (0, "", "Logged in using ChatGPT\nPRIVATE_TOKEN"),
    (0, "", "Logged in using ChatGPT\nWARNING: arbitrary ambiguous output"),
    (0, "Logged in using ChatGPT", "Logged in using ChatGPT"),
    (0, "", "\x1b[2JLogged in using ChatGPT"),
    (0, "Logged in using ChatGPT", CODEX_STARTUP_WARNINGS.replace("Access is denied", "API key active")),
])
def test_codex_auth_rejects_errors_conflicts_and_unknown_output(code, stdout, stderr):
    assert not validation.codex_subscription_auth(subprocess.CompletedProcess([], code, stdout, stderr))


def mock_codex_probes(monkeypatch, *, auth="Logged in using ChatGPT", help_ok=True):
    monkeypatch.setattr(validation, "codex_executable", lambda: "native-codex")
    def probe(args, **kwargs):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, "codex-cli 0.160.1", "")
        if "--help" in args:
            return subprocess.CompletedProcess(args, 0, "--ignore-user-config --ignore-rules --strict-config --ephemeral --sandbox --json --skip-git-repo-check --disable --config" if help_ok else "", "")
        if "features" in args:
            return subprocess.CompletedProcess(args, 0, "\n".join(name + " stable true" for name in
                validation.CODEX_DISABLED + ("code_mode_host", "skip_host_skill_discovery")), "")
        assert args[-2:] == ["login", "status"]
        return subprocess.CompletedProcess(args, 0, "", auth)
    monkeypatch.setattr(validation, "run", probe)


@pytest.mark.parametrize("auth,help_ok", [("Logged in using an API key", True), ("PRIVATE_TOKEN", True),
                                         ("Logged in using ChatGPT", False)])
def test_codex_unavailable_does_not_call_model_or_log_auth(monkeypatch, tmp_path, auth, help_ok):
    mock_codex_probes(monkeypatch, auth=auth, help_ok=help_ok)
    monkeypatch.setattr(validation, "run_codex_model", lambda *a: pytest.fail("unsafe invocation"))
    fixture = tmp_path / "clean.geojson"
    fixture.write_text("{}", encoding="utf-8")
    report = complete_report()
    validation.codex_host(report, tmp_path, {"clean": str(fixture)})
    assert report.finish() == 1
    assert report.data["agent_host"]["status"] == "unavailable"
    assert report.data["agent_host"]["model_called"] is False
    assert "PRIVATE_TOKEN" not in json.dumps(report.data)


@pytest.mark.parametrize("outcome", ["pass", "bad-json", "exit-error", "timeout", "isolation-error"])
def test_codex_runner_gates_exit_trace_timeout_and_isolation(monkeypatch, tmp_path, outcome):
    mock_codex_probes(monkeypatch)
    fixture = tmp_path / "clean.geojson"
    fixture.write_text("{}", encoding="utf-8")
    def model(command, project, started):
        if outcome == "isolation-error":
            raise validation.ValidationError("cannot contain suspended host process; model not started")
        started()
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 120, output="PRIVATE_TOKEN")
        events = codex_events(project / "fixture.geojson")
        text = "PRIVATE_TOKEN invalid JSON" if outcome == "bad-json" else "\n".join(json.dumps(e) for e in events)
        return subprocess.CompletedProcess(command, 1 if outcome == "exit-error" else 0, text, "PRIVATE_TOKEN")
    monkeypatch.setattr(validation, "run_codex_model", model)
    report = complete_report()
    validation.codex_host(report, tmp_path, {"clean": str(fixture)})
    assert report.finish() == (0 if outcome == "pass" else 1)
    assert report.data["agent_host"]["usd_cap"] is None
    assert report.data["agent_host"]["model_called"] is (outcome != "isolation-error")
    assert "PRIVATE_TOKEN" not in json.dumps(report.data)


@pytest.mark.parametrize("message,label", [
    ("error: unexpected argument '--secret-flag'", "unsupported_flag_or_config"),
    ("Error parsing config: PRIVATE_TOKEN", "unsupported_flag_or_config"),
    ("MCP startup failed: PRIVATE_TOKEN", "mcp_startup_failed"),
    ("Failed to initialize MCP client", "mcp_startup_failed"),
    ("Authentication failed: PRIVATE_TOKEN", "auth_unavailable"),
    ("stream disconnected before completion: PRIVATE_TOKEN", "connection_unavailable"),
    ("Failed to initialize model PRIVATE_TOKEN", "model_startup_failed"),
    ("PRIVATE_TOKEN C:\\private\\host https://secret.invalid/token", "unclassified"),
])
@pytest.mark.parametrize("source", ["stderr", "error", "turn.failed"])
def test_codex_diagnostics_fixed_labels_without_text_leakage(message, label, source):
    events = ([] if source == "stderr" else
              [{"type": "error", "message": message}] if source == "error" else
              [{"type": "turn.failed", "error": {"message": message}}])
    diagnostic = validation.codex_diagnostics(message if source == "stderr" else "", events)
    assert diagnostic["labels"] == [label]
    assert "PRIVATE_TOKEN" not in json.dumps(diagnostic)
    assert "secret.invalid" not in json.dumps(diagnostic)
    assert "private" not in json.dumps(diagnostic)
    assert not diagnostic["turn_started_observed"]
    assert not diagnostic["usage_present"]
    assert not diagnostic["positive_output_tokens_observed"]


def test_codex_diagnostics_retains_conflicting_hints_and_allowlists_event_types():
    diagnostic = validation.codex_diagnostics("Authentication failed; connection refused", [
        {"type": "turn.started"}, {"type": "PRIVATE_TOKEN"}, {"type": ["PRIVATE_TOKEN"]}, None,
        {"type": "item.completed", "item": {"type": "agent_message",
                                                "text": "model unavailable PRIVATE_TOKEN"}},
    ])
    assert diagnostic["labels"] == ["auth_unavailable", "connection_unavailable"]
    assert diagnostic["event_counts"]["other"] == 3
    assert diagnostic["event_counts"]["item.completed"] == 1
    assert diagnostic["turn_started_observed"]
    assert not diagnostic["turn_completed_observed"]
    assert "PRIVATE_TOKEN" not in json.dumps(diagnostic)


@pytest.mark.parametrize("usage,present,positive", [
    (None, False, False), ({}, True, False), ({"input_tokens": 12}, True, False),
    ({"output_tokens": 0}, True, False), ({"output_tokens": 2}, True, True),
    ({"output_tokens": True}, True, False), ({"output_tokens": "PRIVATE_TOKEN"}, True, False),
])
def test_codex_diagnostics_distinguishes_turn_and_usage_observations(usage, present, positive):
    diagnostic = validation.codex_diagnostics("", [{"type": "turn.completed", "usage": usage}])
    assert diagnostic["turn_completed_observed"]
    assert not diagnostic["turn_started_observed"]
    assert diagnostic["usage_present"] is present
    assert diagnostic["positive_output_tokens_observed"] is positive
    assert "PRIVATE_TOKEN" not in json.dumps(diagnostic)


@pytest.mark.parametrize("failure", ["startup", "malformed-with-valid-trace"])
def test_codex_host_reports_diagnostics_without_claiming_inference(monkeypatch, tmp_path, failure):
    mock_codex_probes(monkeypatch)
    fixture = tmp_path / "clean.geojson"
    fixture.write_text("{}", encoding="utf-8")
    def model(command, project, started):
        started()
        text = "PRIVATE_TOKEN\n"
        if failure == "malformed-with-valid-trace":
            text += "\n".join(json.dumps(e) for e in codex_events(project / "fixture.geojson"))
        return subprocess.CompletedProcess(command, 0 if failure == "malformed-with-valid-trace" else 1,
                                           text, "error: unexpected argument 'PRIVATE_TOKEN'")
    monkeypatch.setattr(validation, "run_codex_model", model)
    report = complete_report()
    validation.codex_host(report, tmp_path, {"clean": str(fixture)})
    host = report.data["agent_host"]
    assert report.finish() == 1
    assert host["process_started"] is host["model_called"] is True
    assert host["exit_code"] == (0 if failure == "malformed-with-valid-trace" else 1)
    assert host["diagnostics"]["labels"] == ["unsupported_flag_or_config", "invalid_jsonl"]
    assert host["diagnostics"]["invalid_json_lines"] == 1
    assert not host["diagnostics"]["positive_output_tokens_observed"]
    assert "PRIVATE_TOKEN" not in json.dumps(report.data)
    assert str(tmp_path) not in json.dumps(host)


def test_codex_command_has_isolation_no_provider_or_model_choice(tmp_path):
    command = validation.codex_command("native-codex", tmp_path, tmp_path / "fixture.geojson")
    for flag in ("--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral", "--no-daemon", "--json"):
        assert flag in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    for feature in validation.CODEX_DISABLED:
        assert command[command.index(feature) - 1] == "--disable"
    assert command[command.index("code_mode_host") - 1] == "--enable"
    assert "code_mode" in validation.CODEX_DISABLED
    configs = [command[i + 1] for i, arg in enumerate(command) if arg == "-c"]
    assert 'approval_policy="never"' in configs and 'web_search="disabled"' in configs
    server = next(c for c in configs if c.startswith("mcp_servers="))
    assert 'enabled_tools=["list_skills","inspect_dataset"]' in server
    assert sys.executable.replace("\\", "\\\\") in server
    assert not {"--model", "-m", "--oss", "--local-provider", "--search", "--dangerously-bypass-approvals-and-sandbox"}.intersection(command)
    assert not any(c.startswith(("model=", "model_provider=")) for c in configs)


@pytest.mark.parametrize("directory", [r"C:\tests\new\router\fixture", "C:\\اختبار\\release smoke"])
def test_codex_windows_config_values_round_trip_as_toml(monkeypatch, directory):
    from pathlib import PureWindowsPath
    import tomllib

    project = PureWindowsPath(directory)
    executable = str(project / "Scripts" / "python.exe")
    monkeypatch.setattr(validation.sys, "executable", executable)
    command = validation.codex_command("native-codex", project, project / "fixture.geojson")
    configs = dict(command[i + 1].split("=", 1) for i, arg in enumerate(command) if arg == "-c")
    # Parse values independently: CLI -c arguments are separate dotted-key overrides.
    parsed = {key: tomllib.loads("value=" + value)["value"] for key, value in configs.items()}
    assert parsed["log_dir"] == str(project / "logs")
    assert parsed["sqlite_home"] == str(project / "state")
    server = parsed["mcp_servers"]["terraproof"]
    assert server["command"] == executable
    assert server["args"] == ["-m", "terraproof.mcp"]
    assert server["enabled_tools"] == validation.CODEX_TOOLS
    assert server["required"] is True
    assert server["tools"] == {name: {"approval_mode": "approve"} for name in validation.CODEX_TOOLS}
    assert parsed["suppress_unstable_features_warning"] is True
    assert parsed["approval_policy"] == "never"
    assert parsed["web_search"] == "disabled"
    assert parsed["model_reasoning_effort"] == "low"
    assert parsed["skills.bundled.enabled"] is False
    assert parsed["skills.include_instructions"] is False
    assert parsed["history.persistence"] == "none"


def test_codex_process_timeout_closes_owned_tree(monkeypatch, tmp_path):
    calls = []
    class Job:
        def resume(self, process):
            calls.append("resume")
        def close(self):
            calls.append("close-tree")
    class Process:
        stdout = stderr = None
        def communicate(self, timeout):
            assert timeout == 120
            raise subprocess.TimeoutExpired("native", timeout)
        def poll(self):
            return None
        def kill(self):
            calls.append("kill")
        def wait(self, timeout):
            calls.append("wait")
    # Simulate Windows without starting any process or contacting any model.
    monkeypatch.setattr(validation, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(validation, "WindowsHostJob", Job)
    def popen(*args, **kwargs):
        assert kwargs["creationflags"] == 4
        return Process()
    monkeypatch.setattr(validation.subprocess, "Popen", popen)
    with pytest.raises(subprocess.TimeoutExpired):
        validation.run_codex_model(["native"], tmp_path, lambda: calls.append("started"))
    assert calls == ["resume", "started", "close-tree", "kill", "wait"]


def test_help_does_not_start_validation_or_model(monkeypatch):
    monkeypatch.setattr(validation, "agent_host", lambda *a: pytest.fail("host must not run"))
    with pytest.raises(SystemExit) as exc:
        validation.main(["--help"])
    assert exc.value.code == 0
