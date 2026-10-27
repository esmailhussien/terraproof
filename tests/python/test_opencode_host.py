"""OpenCode host for the lift driver: command, trace, isolation checks and wiring. Offline only.

Event shapes follow opencode-ai 1.19.4 `run --format json` (packages/cli/src/run/noninteractive.ts).
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile

import pytest

from terraproof.evals import lift
from terraproof.evals.lift import WITH, WITHOUT, Budget
from terraproof.evals.specs import load_specs

DRIVER_PATH = Path(__file__).resolve().parents[1] / "agent_lift.py"
DRIVER_SPEC = importlib.util.spec_from_file_location("agent_lift_opencode", DRIVER_PATH)
driver = importlib.util.module_from_spec(DRIVER_SPEC)
DRIVER_SPEC.loader.exec_module(driver)

TASK = "indices-ndvi-physical-inputs"
SPECS = {spec.id: spec for spec in load_specs()}
SEEDED = ("ndvi_dn_ratio.tif",)


def _tool(name, tool_input, status="completed", start=1000, end=1250):
    state = {"status": status, "input": tool_input, "output": "SECRET OUTPUT TEXT",
             "time": {"start": start, "end": end}}
    if status == "error":
        state["error"] = "boom"
    return {"type": "tool_use", "timestamp": end, "sessionID": "s1",
            "part": {"id": "p", "type": "tool", "tool": name, "state": state}}


def _step(tokens=(100, 20, 5), reason="stop"):
    return {"type": "step_finish", "timestamp": 2000, "sessionID": "s1",
            "part": {"type": "step-finish", "reason": reason, "cost": 0.0,
                     "tokens": {"input": tokens[0], "output": tokens[1], "reasoning": tokens[2],
                                "cache": {"read": 0, "write": 0}}}}


def _text():
    return {"type": "text", "timestamp": 1500, "sessionID": "s1", "part": {"type": "text", "text": "MODEL TEXT"}}


def test_command_is_headless_pure_auto_and_pinned_to_the_model_and_project(tmp_path):
    command = driver.opencode_lift_command("opencode.exe", tmp_path, "opencode-go/glm-5.3", "high")
    assert command[:2] == ["opencode.exe", "run"] and command[-1] == driver.PROMPT
    assert command[command.index("--format") + 1] == "json"
    assert command[command.index("--model") + 1] == "opencode-go/glm-5.3"
    assert command[command.index("--dir") + 1] == str(tmp_path)
    assert command[command.index("--variant") + 1] == "high"
    assert "--pure" in command and "--auto" in command
    assert "--variant" not in driver.opencode_lift_command("opencode.exe", tmp_path, "m/x", None)
    # The condition lives in the workspace files, never in per-condition flags (the --dir value is
    # the run project's own path).
    flags = [part for part in command if part != str(tmp_path)]
    assert not any("terraproof" in part.lower() for part in flags)


@pytest.mark.parametrize("name, label", [
    ("terraproof_run_checks", ("terraproof.run_checks", "mcp:run_checks")),
    ("terraproof_inspect_dataset", ("terraproof.inspect_dataset", "mcp:inspect_dataset")),
    ("terraproof_not_a_tool", ("mcp", "mcp:other")),
    ("sqlite_query", ("mcp", "mcp:other")),
    ("bash", ("bash", "shell")),
    ("write", ("write", "file_edit")),
    ("edit", ("edit", "file_edit")),
    ("read", ("read", "file_read")),
    ("glob", ("glob", "file_read")),
    ("webfetch", ("webfetch", "web")),
    ("skill", ("skill", "skill")),
    ("task", ("task", "agent")),
    ("todowrite", ("todowrite", "other")),
])
def test_tool_names_map_to_fixed_labels(name, label):
    assert driver._opencode_label(name) == label


def test_trace_keeps_labels_and_numbers_only():
    events = [_text(),
              _tool("read", {"filePath": "inputs/red.tif"}),
              _tool("skill", {"name": "spectral-indices"}),
              _tool("bash", {"command": "python make_ndvi.py"}, status="error"),
              _tool("terraproof_run_checks", {"paths": ["outputs/ndvi.tif"]}),
              _tool("bash", {"command": "python -c \"import terraproof.evals.oracles\""}),
              _step(), _step((50, 10, 0))]
    result = driver.opencode_trace(events, WITH, SEEDED)
    assert (result.status, result.tool_calls, result.terraproof_tool_calls, result.skill_reads) == ("completed", 5, 1, 1)
    assert [call["status"] for call in result.calls] == ["completed", "completed", "failed", "completed", "completed"]
    assert result.calls[0]["duration_ms"] == 250
    assert result.contamination == ["harness-source", "oracle-source"]
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (150, 35, None)
    assert result.turn == {"status": "completed", "reason": "ok", "error_types": [], "error_items": 0}
    dumped = json.dumps(result.__dict__)
    for secret in ("SECRET OUTPUT TEXT", "MODEL TEXT", "make_ndvi", "filePath", "boom"):
        assert secret not in dumped


def test_terraproof_use_in_without_is_contamination():
    mcp = driver.opencode_trace([_tool("terraproof_run_checks", {"paths": ["x.tif"]}), _step()], WITHOUT, SEEDED)
    cli = driver.opencode_trace([_tool("bash", {"command": "python -m terraproof check x.tif"}), _step()],
                                WITHOUT, SEEDED)
    assert mcp.contamination == ["terraproof-in-without:mcp"]
    assert cli.contamination == ["terraproof-in-without:module-or-cli"]


@pytest.mark.parametrize("events, kwargs, status, turn", [
    ([{"type": "error", "sessionID": "s1", "error": {"name": "ProviderRateLimitError", "data": {"message": "quota text"}}}],
     {}, "failed", ("error", "session error event", ["providerratelimiterror"])),
    ([{"type": "error", "sessionID": "s1", "error": {"name": "free text with spaces"}}, _step()],
     {}, "failed", ("error", "session error event", ["unclassified"])),
    ([_text()], {}, "failed", ("aborted", "stream ended without a finished step", [])),
    ([_step()], {"timed_out": True}, "timeout", ("timeout", "per-run timeout; owned process tree terminated", [])),
    ([_step()], {}, "completed", ("completed", "no tool calls", [])),
])
def test_turn_status_labels(events, kwargs, status, turn):
    result = driver.opencode_trace(events, WITH, SEEDED, **kwargs)
    assert result.status == status
    assert (result.turn["status"], result.turn["reason"], result.turn["error_types"]) == turn
    assert "quota text" not in json.dumps(result.__dict__)


def test_global_and_ancestor_checks():
    # Real runs live outside the checkout; pytest's tmp_path may sit inside it, below this
    # repository's own AGENTS.md, so this test uses the system temp directory.
    with tempfile.TemporaryDirectory(prefix="opencode-ancestors-") as directory:
        _global_and_ancestor_checks(Path(directory))


def _global_and_ancestor_checks(tmp_path):
    home = tmp_path / "config"
    project = tmp_path / "work" / "run" / "project"
    project.mkdir(parents=True)
    assert all(driver.opencode_global_checks(home, project).values())
    home.mkdir()
    (home / "opencode.jsonc").write_text('{"$schema": "https://opencode.ai/config.json"}', encoding="utf-8")
    (home / "skills" / "my-own-skill").mkdir(parents=True)
    (tmp_path / "work" / "AGENTS.md").write_text("Be concise.\n", encoding="utf-8")
    assert all(driver.opencode_global_checks(home, project).values())
    (home / "opencode.jsonc").write_text('{"mcp": {"tp": {"command": ["python", "-m", "terraproof.mcp"]}}}',
                                        encoding="utf-8")
    (home / "skills" / "gdal").mkdir()
    (tmp_path / "work" / "AGENTS.md").write_text("Always use Terraproof.\n", encoding="utf-8")
    assert driver.opencode_global_checks(home, project) == {
        "no_terraproof_in_opencode_global_config": False, "no_terraproof_in_opencode_global_dirs": False,
        "no_terraproof_in_opencode_config_above_project": False}


def _prepared(tmp_path, condition):
    task = lift.lift_task(TASK)
    reference = tmp_path / "reference"
    if not reference.exists():
        lift._generate(task, reference)
    project = tmp_path / condition / "project"
    installed = lift.prepare_project(task, SPECS[task.task_id], reference, project, condition=condition,
                                     agent="opencode")
    return task, project, installed


def test_with_project_gets_agents_md_and_opencode_mcp_and_without_gets_none(tmp_path):
    task, project, installed = _prepared(tmp_path, WITH)
    assert installed["install_exit"] == 0 and installed["skills"]
    server = json.loads((project / "opencode.json").read_text(encoding="utf-8"))["mcp"]["terraproof"]
    assert server["type"] == "local" and server["command"][1:] == ["-m", "terraproof.mcp"]
    checks = lift.project_preflight(task, project, condition=WITH, agent="opencode", routed=installed["skills"])
    assert checks["skills_installed"] and checks["mcp_registered"]
    task, project, _ = _prepared(tmp_path, WITHOUT)
    assert lift.project_preflight(task, project, condition=WITHOUT, agent="opencode", routed=[])["no_terraproof_files"]


def test_adapter_preflight_serves_the_installed_mcp_without_a_model(tmp_path):
    adapter = driver.OpenCodeHostAdapter("opencode.exe", "m/x", config_home=tmp_path / "config")
    task, project, _ = _prepared(tmp_path, WITH)
    checks = adapter.preflight(lift.AgentRequest(task.task_id, WITH, 0, project, "", 10, 1.0))
    assert checks["mcp_tools_served"] and checks["unsandboxed_python"]
    assert checks["no_terraproof_in_opencode_global_config"] and "with_evals_not_importable" in checks
    task, project, _ = _prepared(tmp_path, WITHOUT)
    checks = adapter.preflight(lift.AgentRequest(task.task_id, WITHOUT, 0, project, "", 10, 1.0))
    assert "mcp_tools_served" not in checks and "without_terraproof_not_importable" in checks
    assert not (project.parent / "preflight_probe.py").exists()


def test_adapter_run_isolates_opencode_and_marks_bad_exits(tmp_path, monkeypatch):
    seen = {}

    def fake_run_contained(command, cwd, env, timeout):
        seen["command"], seen["env"] = command, env
        lines = [json.dumps(_tool("terraproof_run_checks", {"paths": ["outputs/x.tif"]})), json.dumps(_step())]
        return 0, [(0.1, line + "\n") for line in lines], "stderr", False

    monkeypatch.setattr(driver, "run_contained", fake_run_contained)
    adapter = driver.OpenCodeHostAdapter("opencode.exe", "opencode-go/glm-5.3", config_home=tmp_path)
    request = lift.AgentRequest(TASK, WITH, 0, tmp_path, "", 30, 1.0)
    result = adapter.run(request)
    assert result.status == "completed" and result.terraproof_tool_calls == 1
    assert {key: seen["env"][key] for key in driver.OPENCODE_ENV} == driver.OPENCODE_ENV
    monkeypatch.setattr(driver, "run_contained", lambda *a: (1, [(0.0, json.dumps(_step()) + "\n")], "", False))
    failed = adapter.run(request)
    assert failed.status == "failed" and failed.turn["reason"] == "nonzero host exit or invalid JSONL"


def test_model_listing_parser_and_probe_refusals(tmp_path):
    listing = "opencode-go/glm-5.3\nopencode-go/deepseek-v4.1-flash\nnot a model line\n"
    assert driver.opencode_models(listing) == ["opencode-go/glm-5.3", "opencode-go/deepseek-v4.1-flash"]
    assert driver.probe_opencode(str(tmp_path / "missing.exe"), "m/x")[:2] == (None, "opencode executable not found")
    if os.name == "nt":
        wrapper = tmp_path / "opencode.cmd"
        wrapper.write_text("@echo off\n", encoding="utf-8")
        assert "native .exe" in driver.probe_opencode(str(wrapper), "m/x")[1]


def test_driver_plans_opencode_and_requires_a_model(capsys, tmp_path):
    with pytest.raises(SystemExit):
        driver.main(["--agent-host", "opencode", "--runs", "1", "--task", TASK])
    capsys.readouterr()
    exe = tmp_path / "opencode.exe"
    assert driver.main(["--agent-host", "opencode", "--runs", "2", "--task", TASK, "--opencode-model",
                        "opencode-go/glm-5.3", "--opencode-variant", "high", "--opencode-executable", str(exe)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_model_invocations"] == 4 and plan["total_usd_ceiling"] is None
    for part in ("--opencode-model opencode-go/glm-5.3", "--opencode-variant high",
                 f"--opencode-executable {exe}", "--approve-model-calls 4"):
        assert part in plan["command_to_approve"]


def test_run_lift_drives_the_adapter_end_to_end_with_a_fake_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "run_contained", lambda command, cwd, env, timeout: (
        0, [(0.0, json.dumps(_tool("bash", {"command": "dir"})) + "\n"), (0.1, json.dumps(_step()) + "\n")], "", False))
    adapter = driver.OpenCodeHostAdapter("opencode.exe", "m/x", config_home=tmp_path / "config")
    monkeypatch.setattr(adapter, "preflight", lambda request: {})
    report = lift.run_lift(adapter, task_ids=[TASK], runs=1, agent="opencode", budget=Budget(max_runs=2),
                           work_root=tmp_path / "work", allow_model_calls=True)
    runs = report["tasks"][0]["runs"]
    assert sorted(run["condition"] for run in runs) == [WITH, WITHOUT]
    assert all(run["adapter_status"] == "completed" and run["verdict"] == "missing" for run in runs)
