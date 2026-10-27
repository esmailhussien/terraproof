"""Antigravity (agy) host for the lift driver: command, trace, global isolation and wiring. Offline only."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from terraproof.evals import lift
from terraproof.evals.lift import WITH, WITHOUT, Budget
from terraproof.evals.specs import load_specs

DRIVER_PATH = Path(__file__).resolve().parents[1] / "agent_lift.py"
DRIVER_SPEC = importlib.util.spec_from_file_location("agent_lift_antigravity", DRIVER_PATH)
driver = importlib.util.module_from_spec(DRIVER_SPEC)
DRIVER_SPEC.loader.exec_module(driver)

TASK = "indices-ndvi-physical-inputs"
SPECS = {spec.id: spec for spec in load_specs()}
SEEDED = ("ndvi_dn_ratio.tif",)


def _step(index, state, name, parameters=None, error=None, seconds=None, conversation="c1"):
    info = {"name": name, "parameters": parameters or {}, "output": "SECRET OUTPUT TEXT"}
    if error:
        info["error"] = error
    payload = {"conversation_id": conversation, "step_index": index, "state": state, "step_type": "tool",
               "tool_name": name, "tool_info": info}
    if seconds is not None:
        payload["duration_seconds"] = seconds
    return {"event": "step_update", "step_update": payload}


def _init(project, tools):
    return {"event": "init", "conversation_id": "c1", "init": {"cwd": str(project), "tools": tools}}


def _result(status="SUCCESS", **extra):
    return {"event": "result", "result": {"conversation_id": "c1", "status": status, "response": "MODEL TEXT",
                                          "usage": {"input_tokens": 120, "output_tokens": 30}, **extra}}


def test_command_puts_flags_first_and_the_prompt_last():
    command = driver.antigravity_lift_command("agy.exe", "gemini-x", "high")
    assert command[-2:] == ["--print", driver.PROMPT]
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--model") + 1] == "gemini-x"
    assert command[command.index("--effort") + 1] == "high"
    assert "--dangerously-skip-permissions" in command
    assert "--effort" not in driver.antigravity_lift_command("agy.exe", "gemini-x", None)
    # Isolation lives in the workspace files, never in per-condition flags.
    assert not any("terraproof" in part.lower() or "mcp" in part.lower() for part in command)


@pytest.mark.parametrize("name, label", [
    ("terraproof_run_checks", ("terraproof.run_checks", "mcp:run_checks")),
    ("mcp_terraproof_inspect_dataset", ("terraproof.inspect_dataset", "mcp:inspect_dataset")),
    ("terraproof/find_guidance", ("terraproof.find_guidance", "mcp:find_guidance")),
    ("mcp(terraproof/load_section)", ("terraproof.load_section", "mcp:load_section")),
    ("run_checks", ("terraproof.run_checks", "mcp:run_checks")),
    ("mcp_sqlite_query", ("mcp", "mcp:other")),
    ("run_command", ("run_command", "shell")),
    ("search_web", ("search_web", "web")),
    ("write_to_file", ("write_to_file", "file_edit")),
    ("replace_file_content", ("replace_file_content", "file_edit")),
    ("view_file", ("view_file", "file_read")),
    ("list_dir", ("list_dir", "file_read")),
    ("weird name with spaces", ("other", "other")),
])
def test_tool_names_map_to_fixed_labels(name, label):
    assert driver._antigravity_label(name) == label


def test_trace_keeps_labels_and_numbers_only(tmp_path):
    events = [
        _init(tmp_path, ["run_command", "view_file", "terraproof_run_checks"]),
        _step(1, "ACTIVE", "view_file", {"AbsolutePath": ".agents/skills/spectral-indices/SKILL.md"}),
        _step(1, "DONE", "view_file", {"AbsolutePath": ".agents/skills/spectral-indices/SKILL.md"}, seconds=0.25),
        _step(2, "DONE", "run_command", {"CommandLine": "python make_ndvi.py"}, error={"type": "x", "message": "boom"}),
        _step(3, "DONE", "terraproof_run_checks", {"paths": ["outputs/ndvi.tif"]}),
        _step(4, "DONE", "run_command", {"CommandLine": "python -c \"import terraproof.evals.oracles\""}),
        _result(),
    ]
    result = driver.antigravity_trace(events, WITH, SEEDED, project=tmp_path)
    assert (result.status, result.tool_calls, result.terraproof_tool_calls, result.skill_reads) == ("completed", 4, 1, 1)
    assert [call["status"] for call in result.calls] == ["completed", "failed", "completed", "completed"]
    assert result.calls[0]["duration_ms"] == 250
    assert result.contamination == ["harness-source", "oracle-source"]
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (120, 30, None)
    assert result.turn == {"status": "completed", "reason": "ok", "error_types": [], "error_items": 0}
    dumped = json.dumps(result.__dict__)
    for secret in ("SECRET OUTPUT TEXT", "MODEL TEXT", "make_ndvi", "boom", "AbsolutePath"):
        assert secret not in dumped


def test_trace_flags_terraproof_tools_offered_in_without_and_missing_in_with(tmp_path):
    leaked = driver.antigravity_trace([_init(tmp_path, [{"name": "terraproof_run_checks"}]), _result()],
                                      WITHOUT, SEEDED, project=tmp_path)
    assert leaked.contamination == ["terraproof-in-without:mcp"]
    missing = driver.antigravity_trace([_init(tmp_path, ["run_command"]), _result()], WITH, SEEDED, project=tmp_path)
    assert missing.contamination == [] and missing.diagnostics == ["terraproof-tools-not-listed"]
    used = driver.antigravity_trace([_init(tmp_path, []), _step(1, "DONE", "run_command",
                                                                {"CommandLine": "python -m terraproof check x"}),
                                     _result()], WITHOUT, SEEDED, project=tmp_path)
    assert used.contamination == ["terraproof-in-without:module-or-cli"]


@pytest.mark.parametrize("events, kwargs, status, turn", [
    ([_result("ERROR", error={"type": "RESOURCE_EXHAUSTED", "message": "quota text"})], {},
     "failed", ("error", "result status error", ["resource_exhausted"])),
    ([_result("WAITING")], {}, "failed", ("error", "waiting for approval", [])),
    ([_result("SOMETHING")], {}, "failed", ("error", "unclassified result", [])),
    ([_result("ERROR", error={"type": "free text with spaces"})], {}, "failed", ("error", "result status error", [])),
    ([], {}, "failed", ("aborted", "stream ended without a result event", [])),
    ([_result()], {"timed_out": True}, "timeout", ("timeout", "per-run timeout; owned process tree terminated", [])),
])
def test_turn_status_labels(tmp_path, events, kwargs, status, turn):
    result = driver.antigravity_trace(events, WITH, SEEDED, project=tmp_path, **kwargs)
    assert result.status == status
    assert (result.turn["status"], result.turn["reason"], result.turn["error_types"]) == turn
    assert "quota text" not in json.dumps(result.__dict__)


def test_a_host_workspace_other_than_the_run_project_fails_the_run(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = driver.antigravity_trace([_init(elsewhere, []), _result()], WITH, SEEDED, project=tmp_path)
    assert result.status == "failed" and result.turn["reason"] == "host workspace is not the run project"


def _home(tmp_path) -> Path:
    home = tmp_path / ".gemini"
    (home / "config").mkdir(parents=True)
    (home / "config" / "mcp_config.json").write_text("", encoding="utf-8")
    (home / "GEMINI.md").write_text("Be concise.\n", encoding="utf-8")
    (home / "antigravity-cli" / "skills" / "my-own-skill").mkdir(parents=True)
    return home


def test_global_checks_pass_on_a_clean_home(tmp_path):
    home = _home(tmp_path)
    (home / "config" / "mcp_config.json").write_text(json.dumps({"mcpServers": {"sqlite": {"command": "x"}}}),
                                                    encoding="utf-8")
    assert driver.antigravity_global_checks(home) == {
        "no_terraproof_in_global_mcp": True, "no_terraproof_in_global_skills": True,
        "no_terraproof_in_global_rules": True, "no_terraproof_in_plugins": True}
    assert all(driver.antigravity_global_checks(tmp_path / "missing-home").values())


@pytest.mark.parametrize("pollute, failing", [
    (lambda h: (h / "config" / "mcp_config.json").write_text(
        json.dumps({"mcpServers": {"tp": {"command": "python", "args": ["-m", "terraproof.mcp"]}}}), encoding="utf-8"),
     "no_terraproof_in_global_mcp"),
    (lambda h: (h / "config" / "mcp_config.json").write_text("{not json", encoding="utf-8"),
     "no_terraproof_in_global_mcp"),
    (lambda h: (h / "config" / "skills" / "gdal").mkdir(parents=True), "no_terraproof_in_global_skills"),
    (lambda h: (h / "antigravity-cli" / "plugins" / "p" / "skills" / "terraproof-x").mkdir(parents=True),
     "no_terraproof_in_global_skills"),
    (lambda h: (h / "GEMINI.md").write_text("Always use Terraproof.\n", encoding="utf-8"),
     "no_terraproof_in_global_rules"),
    (lambda h: ((h / "config" / "rules").mkdir(), (h / "config" / "rules" / "r.md").write_text(
        "---\n---\nterraproof check\n", encoding="utf-8")), "no_terraproof_in_global_rules"),
    (lambda h: ((h / "antigravity-cli" / "plugins" / "p").mkdir(parents=True),
                (h / "antigravity-cli" / "plugins" / "p" / "plugin.json").write_text(
                    '{"mcp": "terraproof"}', encoding="utf-8")), "no_terraproof_in_plugins"),
])
def test_global_checks_fail_when_terraproof_is_visible_to_every_workspace(tmp_path, pollute, failing):
    home = _home(tmp_path)
    pollute(home)
    checks = driver.antigravity_global_checks(home)
    assert [name for name, ok in checks.items() if not ok] == [failing]


def _prepared(tmp_path, condition):
    task = lift.lift_task(TASK)
    reference = tmp_path / "reference"
    if not reference.exists():
        lift._generate(task, reference)
    project = tmp_path / condition / "project"
    installed = lift.prepare_project(task, SPECS[task.task_id], reference, project, condition=condition,
                                     agent="antigravity")
    return task, project, installed


def test_with_project_gets_workspace_skills_rules_and_mcp_and_without_gets_none(tmp_path):
    task, project, installed = _prepared(tmp_path, WITH)
    assert installed["install_exit"] == 0 and installed["skills"]
    servers = json.loads((project / ".agents" / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["terraproof"]["args"] == ["-m", "terraproof.mcp"]
    assert "<!-- terraproof:antigravity:begin -->" in (project / "AGENTS.md").read_text(encoding="utf-8")
    checks = lift.project_preflight(task, project, condition=WITH, agent="antigravity", routed=installed["skills"])
    assert checks["skills_installed"] and checks["mcp_registered"]
    task, project, installed = _prepared(tmp_path, WITHOUT)
    checks = lift.project_preflight(task, project, condition=WITHOUT, agent="antigravity", routed=[])
    assert checks["no_terraproof_files"]


def test_adapter_preflight_checks_workspace_and_global_state_without_a_model(tmp_path):
    home = _home(tmp_path)
    adapter = driver.AntigravityHostAdapter("agy.exe", "gemini-x", home=home)
    task, project, _ = _prepared(tmp_path, WITH)
    checks = adapter.preflight(lift.AgentRequest(task.task_id, WITH, 0, project, "", 10, 1.0))
    assert not checks["mcp_tools_served"] and checks["agents_md_block_written"]
    assert checks['mcp_python_matches_agent'] is False
    assert checks["no_terraproof_in_global_mcp"] and checks["unsandboxed_python"]
    (home / "GEMINI.md").write_text("use terraproof\n", encoding="utf-8")
    task, project, _ = _prepared(tmp_path, WITHOUT)
    checks = adapter.preflight(lift.AgentRequest(task.task_id, WITHOUT, 0, project, "", 10, 1.0))
    assert checks["no_terraproof_in_global_rules"] is False
    assert "mcp_tools_served" not in checks and "without_terraproof_not_importable" in checks


def test_adapter_run_sanitises_the_host_stream_and_marks_bad_exits(tmp_path, monkeypatch):
    seen = {}

    def fake_run_contained(command, cwd, env, timeout):
        seen["command"], seen["cwd"] = command, cwd
        lines = [json.dumps(_init(cwd, ["terraproof_run_checks"])),
                 json.dumps(_step(1, "DONE", "terraproof_run_checks", {"paths": ["outputs/x.tif"]})),
                 json.dumps(_result())]
        return 0, [(0.1 * i, line + "\n") for i, line in enumerate(lines)], "stderr text", False

    monkeypatch.setattr(driver, "run_contained", fake_run_contained)
    adapter = driver.AntigravityHostAdapter("agy.exe", "gemini-x", "low", home=tmp_path)
    request = lift.AgentRequest(TASK, WITH, 0, tmp_path, "", 30, 1.0)
    result = adapter.run(request)
    assert result.status == "completed" and result.terraproof_tool_calls == 1
    assert seen["cwd"] == tmp_path and seen["command"][-1] == driver.PROMPT

    monkeypatch.setattr(driver, "run_contained", lambda *a: (1, [(0.0, json.dumps(_result()) + "\n"),
                                                                 (0.1, "not json\n")], "", False))
    failed = adapter.run(request)
    assert failed.status == "failed" and failed.turn["reason"] == "nonzero host exit or invalid JSONL"


def test_model_listing_parser_and_probe_refusals(tmp_path):
    listing = ("Fetching available models...\n"
               "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\nclaude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n")
    assert driver.antigravity_models(listing) == ["gemini-3.8-flash-high", "claude-sonnet-4-6"]
    assert driver.probe_antigravity(str(tmp_path / "missing.exe"), "m")[:2] == (None, "agy executable not found")
    if os.name == "nt":
        wrapper = tmp_path / "agy.cmd"
        wrapper.write_text("@echo off\n", encoding="utf-8")
        assert driver.probe_antigravity(str(wrapper), "m")[1] == "Antigravity CLI must be a native .exe"


def test_driver_plans_antigravity_and_requires_a_model(capsys, tmp_path):
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "antigravity", "--runs", "1", "--task", TASK])
    capsys.readouterr()
    agy = tmp_path / "agy.exe"
    assert driver.main(["--agent-host", "antigravity", "--runs", "2", "--task", TASK, "--antigravity-model",
                        "gemini-3.8-flash-high", "--antigravity-effort", "high",
                        "--antigravity-executable", str(agy)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_model_invocations"] == 4 and plan["per_run_usd_cap"] is None
    assert plan["total_usd_ceiling"] is None and "no USD cap" in plan["billing"]
    for part in ("--antigravity-model gemini-3.8-flash-high", "--antigravity-effort high",
                 f"--antigravity-executable {agy}", "--approve-model-calls 4"):
        assert part in plan["command_to_approve"]


def test_driver_reports_unavailable_without_starting_anything(capsys, monkeypatch):
    monkeypatch.setattr(driver, "probe_antigravity", lambda *a: (None, "agy executable not found", None))
    monkeypatch.setattr(driver, "run_lift", lambda *a, **k: pytest.fail("no run may start"))
    assert driver.main(["--agent-host", "antigravity", "--runs", "1", "--task", TASK,
                        "--antigravity-model", "m", "--approve-model-calls", "2"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "unavailable", "reason": "agy executable not found",
                                                   "model_called": False}


def test_run_lift_drives_the_adapter_end_to_end_with_a_fake_stream(tmp_path, monkeypatch):
    def fake_run_contained(command, cwd, env, timeout):
        lines = [json.dumps(_init(cwd, [])), json.dumps(_step(1, "DONE", "run_command", {"CommandLine": "dir"})),
                 json.dumps(_result())]
        return 0, [(0.0, line + "\n") for line in lines], "", False

    monkeypatch.setattr(driver, "run_contained", fake_run_contained)
    adapter = driver.AntigravityHostAdapter("agy.exe", "gemini-x", home=tmp_path)
    monkeypatch.setattr(adapter, "preflight", lambda request: {})
    report = lift.run_lift(adapter, task_ids=[TASK], runs=1, agent="antigravity", budget=Budget(max_runs=2),
                           work_root=tmp_path / "work", allow_model_calls=True)
    runs = report["tasks"][0]["runs"]
    assert sorted(run["condition"] for run in runs) == [WITH, WITHOUT]
    assert all(run["adapter_status"] == "completed" and run["verdict"] == "missing" for run in runs)
    assert report["design"]["started_agent_runs"] == 2


# -- shape seen in the 2026-10-26 pilot (agy 1.4.7): one generic MCP tool, server/tool in its arguments --
def _mcp_step(index, state, server, tool, *, key="parameters", as_string=False, conversation="c1"):
    arguments = {"ServerName": server, "ToolName": tool, "Arguments": {"paths": ["outputs/slope.tif"]}}
    info = {"name": "call_mcp_tool", key: json.dumps(arguments) if as_string else arguments,
            "output": "SECRET OUTPUT TEXT"}
    return {"event": "step_update", "step_update": {"conversation_id": conversation, "step_index": index,
                                                    "state": state, "step_type": "tool",
                                                    "tool_name": "call_mcp_tool", "tool_info": info}}


def test_call_mcp_tool_steps_are_labelled_by_server_and_tool(tmp_path):
    events = [_init(tmp_path, ["run_command", "read_file", "call_mcp_tool"]),
              _mcp_step(1, "DONE", "terraproof", "run_checks"),
              _mcp_step(2, "DONE", "terraproof", "inspect_dataset", key="args"),
              _mcp_step(3, "DONE", "terraproof", "run_checks", as_string=True),
              _mcp_step(4, "DONE", "sqlite", "query"),
              _mcp_step(5, "DONE", "terraproof", "not_a_terraproof_tool"),
              _result()]
    result = driver.antigravity_trace(events, WITH, SEEDED, project=tmp_path)
    assert [(call["tool"], call["category"]) for call in result.calls] == [
        ("terraproof.run_checks", "mcp:run_checks"), ("terraproof.inspect_dataset", "mcp:inspect_dataset"),
        ("terraproof.run_checks", "mcp:run_checks"), ("mcp", "mcp:other"), ("mcp", "mcp:other")]
    assert result.terraproof_tool_calls == 3
    assert result.diagnostics == [] and result.contamination == []
    assert "SECRET OUTPUT TEXT" not in json.dumps(result.__dict__)


def test_call_mcp_tool_arguments_arriving_on_a_later_update_relabel_the_step(tmp_path):
    started = {"event": "step_update", "step_update": {"conversation_id": "c1", "step_index": 7, "state": "ACTIVE",
                                                       "step_type": "tool", "tool_name": "call_mcp_tool",
                                                       "tool_info": {"name": "call_mcp_tool"}}}
    result = driver.antigravity_trace([started, _mcp_step(7, "DONE", "terraproof", "run_checks"), _result()],
                                      WITH, SEEDED, project=tmp_path)
    assert result.calls == [{"tool": "terraproof.run_checks", "category": "mcp:run_checks", "status": "completed",
                             "exit_code": None, "duration_ms": result.calls[0]["duration_ms"]}]


def test_a_terraproof_mcp_call_in_without_is_contamination(tmp_path):
    result = driver.antigravity_trace([_init(tmp_path, ["call_mcp_tool"]),
                                       _mcp_step(1, "DONE", "terraproof", "run_checks"), _result()],
                                      WITHOUT, SEEDED, project=tmp_path)
    assert "terraproof-in-without:mcp" in result.contamination


def test_init_listing_only_the_generic_mcp_tool_is_not_a_missing_treatment(tmp_path):
    listed = driver.antigravity_trace([_init(tmp_path, ["run_command", "call_mcp_tool"]), _result()],
                                      WITH, SEEDED, project=tmp_path)
    assert listed.diagnostics == []
    unlisted = driver.antigravity_trace([_init(tmp_path, ["run_command"]), _result()], WITH, SEEDED, project=tmp_path)
    assert unlisted.diagnostics == ["terraproof-tools-not-listed"]
