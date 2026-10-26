#!/usr/bin/env python3
"""Phase 5 real-host agent-lift driver. Prints a plan by default; model calls are opt-in.

Without `--approve-model-calls N` this script only prints the planned number of agent
invocations, the cost ceiling and the exact command to approve; it starts no host and
calls no model. `--preflight-only` prepares every project and runs the no-model host
preflight (sandboxed shell/Python/write probe, MCP registration and tools, skill and
instruction visibility) without starting any agent. With the approval, N must equal the
planned invocation count, and the paired with/without runs go through
`terraproof.evals.lift.run_lift` with the isolation, process-tree containment and auth
probes of `tests/release_validation.py`.

Only fixed labels and numbers leave a host stream: per call a tool label, category,
status, exit code and duration; per turn a status, reason and error-type labels. Prompts,
model text, command lines, arguments, environment and file contents are never written to
the report or recordings.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_validation as validation  # noqa: E402  (shared host isolation helpers)

from terraproof.evals.lift import (  # noqa: E402
    COHORTS, DEFAULT_COHORT, WITH, Adapter, AgentRequest, AgentResult, Budget, LiftError, lift_task, planned_calls,
    run_lift, to_json,
)

ROOT = validation.ROOT
TOOLS = validation.TOOLS
PROMPT = "Read TASK.md in the current directory and complete the task it describes."
# Pilot 1 disabled Codex's default execution features (unified_exec and friends) and no command
# ran in either condition. Lift runs keep Codex's own execution defaults and disable only
# capabilities outside the task (browser, computer use, apps, plugins, web, sub-agents, memory).
CODEX_EXECUTION_DEFAULTS = ("shell_tool", "unified_exec", "unified_exec_tty", "shell_snapshot", "workspace_dependencies")
CODEX_DISABLED = tuple(name for name in validation.CODEX_DISABLED if name not in CODEX_EXECUTION_DEFAULTS)
CODEX_ENABLED = ("skip_host_skill_discovery",)
CLAUDE_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill")
# Reading the harness, the oracles, the specs or the seeded-wrong fixtures is contamination.
FORBIDDEN = (
    ("harness-source", r"terraproof[\\/.]+evals|evals[\\/]+(?:tasks|recipes)|recipes[\\/]+\w+\.py"),
    ("oracle-source", r"oracles(?:\.py)?\b"),
    # Introspection is contamination only when it can reach harness or oracle code. The Antigravity
    # harder-cohort run (2026-10-26) read Terraproof's own product modules this way (checks, report,
    # mcp.server), which the documented tools already expose and which says nothing about grading.
    ("python-introspection", r"(?=[\s\S]*(?:inspect\.getsource|importlib\.resources))"
                             r"(?=[\s\S]*(?:\bevals\b|oracles?\b|\brecipes\b|\bspecs\b|\bfixtures\b))"),
    ("outside-project", r"agent-lift-recordings|\.\.[\\/]\.\."),
)
SANDBOX_DENIAL = r"access is denied|permission denied|operation not permitted|sandbox(?:ing)? (?:denied|blocked)"
PREFLIGHT_MARKERS = (("sandbox_shell", "SHELL-OK"), ("sandbox_python", "PYTHON-OK"),
                     ("sandbox_raster_libs", "RASTER-OK"), ("sandbox_read_inputs", "READ-OK"),
                     ("sandbox_write_outputs", "WRITE-OK"))
PREFLIGHT_SCRIPT = """import pathlib
print("PYTHON-OK", flush=True)
import numpy, rasterio
print("RASTER-OK", flush=True)
with rasterio.open(pathlib.Path("inputs") / {name!r}) as source:
    source.read(1)
print("READ-OK", flush=True)
probe = pathlib.Path("outputs") / ".preflight-probe"
probe.write_text("probe", encoding="utf-8")
probe.unlink()
print("WRITE-OK", flush=True)
"""


# Real Terraproof use in "without", each with a fixed reason sub-label. Main run 1 showed that a
# bare "terraproof" match also fires on path text: Claude Code's Read/Write tools take absolute
# paths, and the run projects then lived under %TEMP%\terraproof-lift-host-*.
TERRAPROOF_USE = (
    ("import", r"\b(?:import|from)\s+terraproof\b|import_module\(\s*['\"]terraproof|__import__\(\s*['\"]terraproof"),
    ("module-or-cli", r"-m\s+terraproof\b|(?:^|[\s;&|\"'])terraproof(?:\.exe)?\s+(?:check|preflight|inspect|route|manifest|install)\b"),
    ("mcp", r"mcp__terraproof|terraproof\.mcp\b"),
    ("package-query", r"pip3?(?:\.exe)?\s+(?:show|list|install|download|freeze|uninstall)\b[^\n]*terraproof"
                      r"|site-packages[\\/]+terraproof|terraproof[\w.-]*\.dist-info"),
    ("skill", r"(?:skills|\.agents|\.claude)[\\/][^\s\"']*terraproof"),
)
# Path-like tokens: drive or rooted paths and any token joined to a path separator.
PATH_TOKEN = r"(?:[A-Za-z]:)?(?:[\\/][^\s\"'<>|;,()]+)+|[^\s\"'<>|;,()]+[\\/][^\s\"'<>|;,()]*"


def terraproof_use_labels(text: str) -> set[str]:
    """Sub-labels for real Terraproof use; `mention` is a bare word left after removing paths."""
    labels = {f"terraproof-in-without:{name}" for name, pattern in TERRAPROOF_USE
              if re.search(pattern, text, re.IGNORECASE)}
    if not labels and re.search(r"terraproof", re.sub(PATH_TOKEN, " ", text), re.IGNORECASE):
        labels.add("terraproof-in-without:mention")
    return labels


def incidental_labels(text: str, condition: str) -> set[str]:
    """Diagnostics only: "terraproof" that appears solely inside path text is not use."""
    if condition == WITH or not re.search(r"terraproof", text, re.IGNORECASE) or terraproof_use_labels(text):
        return set()
    return {"terraproof-path-text"}


def contamination_labels(text: str, condition: str, seeded: tuple[str, ...]) -> set[str]:
    """Fixed labels for forbidden access in one tool call; the text itself is never kept."""
    labels = {label for label, pattern in FORBIDDEN if re.search(pattern, text, re.IGNORECASE)}
    if any(name in text for name in seeded):
        labels.add("seeded-fixture-name")
    if condition != WITH:
        labels |= terraproof_use_labels(text)
    return labels


def _seeded(task_id: str) -> tuple[str, ...]:
    return tuple(wrong for _, wrong in lift_task(task_id).seeded)


def _is_skill_read(text: str) -> bool:
    return bool(re.search(r"[\\/]skills[\\/][^\"']*SKILL\.md|\.agents[\\/]skills|\.claude[\\/]skills", text))


def _duration_ms(start: float | None, end: float | None) -> int | None:
    return None if start is None or end is None else max(0, int(round((end - start) * 1000)))


def run_contained(command: list[str], cwd: Path, env: dict, timeout: float):
    """One invocation, no retries; the owned process tree is killed on every exit.

    Returns (exit code or None, [(seconds since start, stdout line)], stderr, timed_out). The
    timestamps are local arrival times and only ever become call durations.
    """
    import signal

    job = validation.WindowsHostJob() if os.name == "nt" else None
    process = None
    lines: list[tuple[float, str]] = []
    errors: list[str] = []
    readers: list[threading.Thread] = []
    timed_out = False
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=0x4 if job else 0,  # CREATE_SUSPENDED
                                   start_new_session=not bool(job))
        readers = [
            threading.Thread(target=lambda: lines.extend((time.monotonic() - started, line) for line in process.stdout),
                             daemon=True),
            threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()
        if job:
            job.resume(process)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        if job:
            job.close()
        elif process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for reader in readers:
                reader.join(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()
    return (None if timed_out else process.returncode), lines, "".join(errors), timed_out


def host_env(condition: str = WITH, agent_python: str | None = None) -> dict:
    """The agent's interpreter directory first on PATH, so agents compute with numpy/rasterio.

    "with" uses this driver's interpreter (Terraproof installed, as the MCP server runs it).
    "without" uses `agent_python`, a dependency-only interpreter on a neutral path, and drops
    PYTHONPATH so a checkout's `src` cannot make Terraproof importable again.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", DISABLE_AUTOUPDATER="1",
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
    interpreter = sys.executable
    if condition != WITH:
        env.pop("PYTHONPATH", None)
        interpreter = agent_python or sys.executable
    env["PATH"] = str(Path(interpreter).parent) + os.pathsep + env.get("PATH", "")
    return env


IMPORT_PROBE = "import importlib.util, sys; sys.exit(3 if importlib.util.find_spec('terraproof') else 0)"


def unsandboxed_probe(project: Path, task_id: str, env: dict) -> dict:
    """Run the Python/IO probe with the agent's PATH; the script is removed before any agent starts.

    It lives beside the project, which an agent can list, so it must not outlive the preflight
    (the Antigravity harder-cohort run read a left-over probe naming Terraproof in "without").
    """
    script = project.parent / "preflight_probe.py"
    script.write_text(PREFLIGHT_SCRIPT.format(name=lift_task(task_id).inputs[0]), encoding="utf-8")
    try:
        # Resolve `python` on the agent's PATH; Windows CreateProcess would use this process's PATH.
        python = shutil.which("python", path=env["PATH"])
        stdout = ""
        if python:
            stdout = subprocess.run([python, str(script)], cwd=project, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=120, check=False).stdout
    finally:
        script.unlink(missing_ok=True)
    return {check.replace("sandbox_", "unsandboxed_"): marker in stdout
            for check, marker in PREFLIGHT_MARKERS if check != "sandbox_shell"}


def without_isolation_checks(project: Path, agent_python: str | None, env: dict) -> dict:
    """No-model checks that the "without" agent can neither import Terraproof nor see its name in paths."""
    python = shutil.which("python", path=env["PATH"])
    importable = True
    if python:
        probe = subprocess.run([python, "-c", IMPORT_PROBE], cwd=project, env=env, capture_output=True,
                               timeout=60, check=False)
        importable = probe.returncode != 0
    first_path_entry = env["PATH"].split(os.pathsep)[0]
    return {"without_agent_python_set": bool(agent_python),
            "without_terraproof_not_importable": bool(python) and not importable,
            "without_paths_neutral": paths_neutral(str(project.resolve()), first_path_entry, str(python or ""))}


def paths_neutral(*paths: str) -> bool:
    """True when no agent-visible path (project, PATH head, interpreter) names Terraproof."""
    return not any("terraproof" in path.lower() for path in paths)


def _json_lines(lines) -> tuple[list[tuple[float, object]], int]:
    """Parse timestamped JSONL; plain strings are accepted with time 0 (tests, recordings)."""
    events, invalid = [], 0
    for entry in lines:
        stamp, line = entry if isinstance(entry, tuple) else (0.0, entry)
        if not line.strip():
            continue
        try:
            events.append((stamp, json.loads(line)))
        except ValueError:
            invalid += 1
    return events, invalid


def _timed(events) -> list[tuple[float, object]]:
    return [event if isinstance(event, tuple) else (0.0, event) for event in events]


async def _list_mcp_tools(command: str, args: list[str], cwd: Path, env: dict, timeout: float) -> list[str]:
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command=command, args=args, cwd=str(cwd), env=env)
    async with Client(params, raise_exceptions=False, read_timeout_seconds=timeout) as client:
        return sorted(tool.name for tool in (await client.list_tools()).tools)


def mcp_tools_served(command: str, args: list[str], cwd: Path, timeout: float = 60) -> bool:
    """Start the registered server with the official client (no model) and compare its tools."""
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        tools = asyncio.run(asyncio.wait_for(_list_mcp_tools(command, args, cwd, env, timeout), timeout))
    except Exception:
        return False
    return tools == sorted(TOOLS)


# -- Codex -------------------------------------------------------------------------------
CODEX_CATEGORIES = {"command_execution": "shell", "file_change": "file_edit", "web_search": "web",
                    "collab_tool_call": "agent"}
CODEX_NON_CALLS = {"agent_message", "reasoning", "todo_list", "error"}
CODEX_STATUSES = {"in_progress", "completed", "failed", "declined"}


def codex_mcp_value(condition: str) -> str:
    """The exact `mcp_servers` override: the Terraproof server in "with", explicitly none in "without"."""
    if condition != WITH:
        return "{}"
    tools = ",".join(json.dumps(name) for name in TOOLS)
    approvals = ",".join(f'{name}={{approval_mode="approve"}}' for name in TOOLS)
    return ("{terraproof={command=" + json.dumps(sys.executable)
            + ',args=["-m","terraproof.mcp"],enabled_tools=[' + tools + "],"
            + "tools={" + approvals + "},"
            + 'env={PYTHONUTF8="1",PYTHONIOENCODING="utf-8"},required=true,'
            + "startup_timeout_sec=30,tool_timeout_sec=120}}")


def codex_feature_args() -> list[str]:
    args = []
    for feature in CODEX_DISABLED:
        args.extend(["--disable", feature])
    for feature in CODEX_ENABLED:
        args.extend(["--enable", feature])
    return args


def codex_config_args(state: Path, condition: str, effort: str) -> list[str]:
    config = {
        "approval_policy": '"never"', "web_search": '"disabled"',
        "sandbox_workspace_write.network_access": "false",
        "model_reasoning_effort": json.dumps(effort),
        "skills.bundled.enabled": "false",
        "history.persistence": '"none"', "analytics.enabled": "false",
        "suppress_unstable_features_warning": "true",
        "check_for_update_on_startup": "false", "log_dir": json.dumps(str(state / "logs")),
        "sqlite_home": json.dumps(str(state / "sqlite")),
        "mcp_servers": codex_mcp_value(condition),
    }
    args = []
    for key, value in config.items():
        args.extend(["-c", f"{key}={value}"])
    return args


def codex_lift_command(executable: str, project: Path, state: Path, condition: str, effort: str) -> list[str]:
    """Reviewable argv: workspace-write sandbox, Codex's own exec tools, no network, MCP only in "with"."""
    command = [executable, "--no-daemon", "exec", "--ignore-user-config", "--ignore-rules",
               "--strict-config", "--ephemeral", "--sandbox", "workspace-write", "--json",
               "--skip-git-repo-check", "-C", str(project)]
    return command + codex_feature_args() + codex_config_args(state, condition, effort) + [PROMPT]


# Codex's built-in MCP *resource* tools are reported as mcp_tool_call items on server "codex"
# (core/src/tools/handlers/mcp_resource/*.rs, 0.163.0-alpha.11.2); they are not MCP servers.
CODEX_RESOURCE_TOOLS = ("list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource")


def _codex_label(item: dict) -> tuple[str, str]:
    kind = item.get("type")
    if kind == "mcp_tool_call":
        tool = item.get("tool")
        if item.get("server") == "terraproof" and tool in TOOLS:
            return f"terraproof.{tool}", f"mcp:{tool}"
        if tool in CODEX_RESOURCE_TOOLS:
            return f"codex.{tool}", "mcp:codex-resource"
        return "mcp", "mcp:other"
    if kind in CODEX_CATEGORIES:
        return kind, CODEX_CATEGORIES[kind]
    return "other", "other"


def codex_trace(events, condition: str, seeded: tuple[str, ...], *, timed_out: bool = False) -> AgentResult:
    """Sanitise Codex exec JSONL into per-call labels, a turn status and counts."""
    calls: dict[str, dict] = {}
    order: list[str] = []
    labels: set[str] = set()
    incidental: set[str] = set()
    error_texts: list[str] = []
    error_items = 0
    completed = failed = invalid = False
    denied = False
    skill_reads = 0
    input_tokens = output_tokens = 0
    for stamp, event in _timed(events):
        if not isinstance(event, dict):
            invalid = True
            continue
        kind = event.get("type")
        if kind == "error":
            failed = True
            error_texts.append(str(event.get("message", "")))
        elif kind == "turn.failed":
            failed = True
            error = event.get("error")
            error_texts.append(str(error.get("message", "")) if isinstance(error, dict) else "")
        elif kind == "turn.completed":
            completed = True
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
        if kind not in {"item.started", "item.updated", "item.completed"} or not isinstance(event.get("item"), dict):
            continue
        item = event["item"]
        if item.get("type") == "error":
            if kind == "item.completed":
                error_items += 1
                error_texts.append(str(item.get("message", "")))
            continue
        if item.get("type") in CODEX_NON_CALLS:
            continue
        identifier = str(item.get("id") or f"anonymous-{len(order)}")
        if identifier not in calls:
            tool, category = _codex_label(item)
            calls[identifier] = {"tool": tool, "category": category, "status": "started", "exit_code": None,
                                 "duration_ms": None, "_start": stamp, "_text": ""}
            order.append(identifier)
        record = calls[identifier]
        text = json.dumps({key: item.get(key) for key in ("command", "arguments", "changes", "tool")}, default=str)
        record["_text"] = text
        if kind == "item.completed":
            status = item.get("status")
            record["status"] = status if status in CODEX_STATUSES else "completed"
            record["exit_code"] = item.get("exit_code") if type(item.get("exit_code")) is int else None
            record["duration_ms"] = _duration_ms(record["_start"], stamp)
            output = str(item.get("aggregated_output") or "")
            if record["status"] == "declined" or (record["status"] == "failed" and re.search(SANDBOX_DENIAL, output, re.I)):
                denied = True
    public = []
    for identifier in order:
        record = calls[identifier]
        skill_reads += record["category"] == "shell" and _is_skill_read(record["_text"])
        labels |= contamination_labels(record["_text"], condition, seeded)
        incidental |= incidental_labels(record["_text"], condition)
        public.append({key: value for key, value in record.items() if not key.startswith("_")})
    error_types = sorted(set(validation.codex_diagnostics("\n".join(error_texts), [], 0)["labels"]) - {"unclassified"})
    if error_texts and not error_types:
        error_types = ["unclassified"]
    if denied:
        error_types = sorted(set(error_types) | {"sandbox_denied"})
    if timed_out:
        turn_status, reason = "timeout", "per-run timeout; owned process tree terminated"
    elif failed or invalid:
        turn_status, reason = "error", "turn failed or error event" if failed else "invalid JSONL"
    elif denied:
        turn_status, reason = "sandbox-denial", "a command was declined or denied by the sandbox"
    elif completed:
        turn_status, reason = "completed", "no tool calls" if not public else "ok"
    else:
        turn_status, reason = "aborted", "stream ended without turn completion"
    terraproof_calls = sum(1 for call in public if call["tool"].startswith("terraproof."))
    return AgentResult(status="completed" if turn_status in {"completed", "sandbox-denial"} else
                       ("timeout" if timed_out else "failed"),
                       cost_usd=None, tool_calls=len(public), terraproof_tool_calls=terraproof_calls,
                       skill_reads=skill_reads, input_tokens=input_tokens, output_tokens=output_tokens,
                       contamination=sorted(labels), diagnostics=sorted(incidental), calls=public,
                       turn={"status": turn_status, "reason": reason, "error_types": error_types,
                             "error_items": error_items})


def _prompt_input_names(document) -> tuple[set[str], bool]:
    """Skill names and whether the Terraproof AGENTS.md block is in the rendered prompt."""
    names: set[str] = set()
    block = False
    for message in document if isinstance(document, list) else []:
        content = message.get("content", []) if isinstance(message, dict) else []
        text = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        names |= set(re.findall(r"^- ([\w:.-]+):", text, re.M))
        block |= "terraproof:codex:begin" in text
    return names, block


class CodexHostAdapter(Adapter):
    name = "codex-host"
    model_calls = True
    usd_capped = False

    def __init__(self, executable: str, effort: str, agent_python_without: str | None = None):
        self.executable = executable
        self.effort = effort
        self.agent_python_without = agent_python_without

    def run(self, request: AgentRequest) -> AgentResult:
        state = request.project.parent / "host-state"
        state.mkdir(exist_ok=True)
        command = codex_lift_command(self.executable, request.project, state, request.condition, self.effort)
        env = host_env(request.condition, self.agent_python_without)
        code, lines, stderr, timed_out = run_contained(command, request.project, env, request.timeout_seconds)
        events, invalid = _json_lines(lines)
        result = codex_trace(events, request.condition, _seeded(request.task_id), timed_out=timed_out)
        if invalid:
            result.status = "failed"
            result.turn["status"], result.turn["reason"] = "error", "invalid JSONL"
        if code not in (0, None) and result.status == "completed":
            result.status = "failed"
            result.turn["reason"] = "nonzero host exit"
        if result.status != "completed":
            result.diagnostics = sorted(set(result.diagnostics) | set(
                validation.codex_diagnostics(stderr, [event for _, event in events], invalid)["labels"]))
        return result

    def preflight(self, request: AgentRequest) -> dict:
        """No-model checks: sandboxed shell/Python/IO, MCP registration and tools, prompt-visible skills."""
        task = lift_task(request.task_id)
        state = request.project.parent / "host-state"
        state.mkdir(exist_ok=True)
        env = host_env(request.condition, self.agent_python_without)
        checks: dict = {}
        if request.condition != WITH:
            checks.update(without_isolation_checks(request.project, self.agent_python_without, env))
        script = request.project.parent / "preflight_probe.py"
        script.write_text(PREFLIGHT_SCRIPT.format(name=task.inputs[0]), encoding="utf-8")
        probe = [self.executable, "sandbox", "-P", ":workspace", "-C", str(request.project),
                 "-c", "sandbox_workspace_write.network_access=false", "powershell.exe", "-NoProfile",
                 "-NonInteractive", "-Command", f"Write-Output SHELL-OK; python '{script}'; exit $LASTEXITCODE"]
        try:
            code, lines, _stderr, timed_out = run_contained(probe, request.project, env, 120)
        finally:
            script.unlink(missing_ok=True)
        seen = " ".join(line for _, line in lines)
        for check, marker in PREFLIGHT_MARKERS:
            checks[check] = marker in seen
        checks["sandbox_exit_zero"] = code == 0 and not timed_out
        listed = subprocess.run([self.executable, "mcp", "list", "--json", "-c",
                                 f"mcp_servers={codex_mcp_value(request.condition)}"],
                                cwd=request.project, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60, check=False)
        try:
            servers = {entry.get("name"): entry for entry in json.loads(listed.stdout)}
        except (ValueError, AttributeError, TypeError):
            servers = None
        rendered = subprocess.run([self.executable, "debug", "prompt-input", *codex_feature_args(),
                                   *codex_config_args(state, request.condition, self.effort), PROMPT],
                                  cwd=request.project, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60, check=False)
        try:
            names, block = _prompt_input_names(json.loads(rendered.stdout))
            checks["prompt_rendered"] = rendered.returncode == 0
        except ValueError:
            names, block = set(), False
            checks["prompt_rendered"] = False
        models = subprocess.run([self.executable, "debug", "models"], cwd=request.project, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=60, check=False)
        try:
            catalog = codex_model_tool_modes(json.loads(models.stdout))
        except ValueError:
            catalog = {"direct_tool_model_available": False}
        # A shell tool cannot be shown to exist before a turn; refuse rather than guess.
        checks["codex_direct_tool_model_available"] = catalog["direct_tool_model_available"]
        checks["codex_model_tool_modes"] = ",".join(catalog.get("tool_modes", [])) or "unknown"
        registry = {skill for skill in _registry_names()}
        if request.condition == WITH:
            entry = (servers or {}).get("terraproof") or {}
            transport = entry.get("transport") or {}
            checks["mcp_registered_in_codex"] = bool(entry.get("enabled")) and transport.get("args") == ["-m", "terraproof.mcp"]
            checks["mcp_tools_served"] = mcp_tools_served(sys.executable, ["-m", "terraproof.mcp"], request.project)
            routed = set(_routed_skills(request.project))
            checks["skills_visible_to_codex"] = bool(routed) and routed <= names
            checks["agents_md_visible_to_codex"] = block
        else:
            checks["no_terraproof_mcp_in_codex"] = servers is not None and "terraproof" not in servers
            checks["no_terraproof_skills_visible"] = not (names & registry)
            checks["no_terraproof_instructions_visible"] = not block
        return checks


def codex_model_tool_modes(catalog) -> dict:
    """Fixed labels from `codex debug models`: listed slugs' tool modes and shell types.

    Every listed model being `code_mode_only` means the model sees only the JavaScript
    `exec`/`wait` entry points; whether a shell is reachable from there cannot be rendered
    without a model turn, and pilots 1 and 2 used none.
    """
    models = catalog.get("models", []) if isinstance(catalog, dict) else []
    listed = [model for model in models if isinstance(model, dict) and model.get("visibility") == "list"]
    modes = sorted({str(model.get("tool_mode") or "direct") for model in listed})
    shells = sorted({str(model.get("shell_type")) for model in listed})
    direct = [model for model in listed if (model.get("tool_mode") or "direct") != "code_mode_only"]
    return {"listed_models": len(listed), "tool_modes": modes, "shell_types": shells,
            "direct_tool_model_available": bool(direct)}


def _registry_names() -> list[str]:
    return sorted(json.loads((ROOT / "routing" / "registry.json").read_text(encoding="utf-8"))["skills"])


def _routed_skills(project: Path) -> list[str]:
    root = project / ".agents" / "skills"
    return sorted(path.name for path in root.iterdir() if (path / "SKILL.md").is_file()) if root.is_dir() else []


def probe_codex(executable: str | None = None) -> tuple[str | None, str, str | None]:
    executable = executable or validation.codex_executable()
    if not executable:
        return None, "no supported native Codex executable; shell/Node wrappers are not invoked", None
    if os.name == "nt" and Path(executable).suffix.lower() != ".exe":
        return None, "Codex executable must be a native .exe", None
    with tempfile.TemporaryDirectory(prefix="terraproof-lift-probe-") as directory:
        cwd = Path(directory)
        version = validation.run([executable, "--version"], cwd=cwd)
        help_result = validation.run([executable, "exec", "--help"], cwd=cwd)
        required = ("--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral",
                    "--sandbox", "workspace-write", "--json", "--skip-git-repo-check", "--disable", "--config")
        if version.returncode or help_result.returncode or not all(flag in help_result.stdout for flag in required):
            return None, "Codex exec lacks a required isolation flag", None
        features = validation.run([executable, "features", "list"], cwd=cwd)
        supported = {line.split()[0] for line in features.stdout.splitlines()
                     if len(line.split()) >= 3 and "removed" not in line.split()[1:-1]}
        if features.returncode or not set(CODEX_DISABLED + CODEX_ENABLED) <= supported:
            return None, "required Codex feature controls unavailable", None
        if not validation.codex_subscription_auth(validation.run([executable, "login", "status"], cwd=cwd)):
            return None, "Codex login status did not confirm ChatGPT subscription auth; no API-paid fallback", None
    return executable, "ok", version.stdout.strip()


# -- Claude Code -------------------------------------------------------------------------
CLAUDE_CATEGORIES = {"Bash": "shell", "PowerShell": "shell", "Write": "file_edit", "Edit": "file_edit",
                     "NotebookEdit": "file_edit", "Read": "file_read", "Glob": "file_read", "Grep": "file_read",
                     "Skill": "skill"}
CLAUDE_RESULT_REASONS = {"success": "ok", "error_max_budget_usd": "per-run budget reached",
                         "error_max_turns": "turn limit reached", "error_during_execution": "error during execution"}


def claude_lift_command(executable: str, project: Path, mcp_config: Path, condition: str, per_run_usd: float) -> list[str]:
    allowed = list(CLAUDE_TOOLS)
    if condition == WITH:
        allowed += [f"mcp__terraproof__{name}" for name in TOOLS]
    return [executable, "--print", "--restricted", "--tools", ",".join(CLAUDE_TOOLS),
            "--allowedTools", ",".join(allowed), "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--strict-mcp-config", "--mcp-config", str(mcp_config),
            "--no-session-persistence", "--no-chrome", "--settings", '{"disableAllHooks":true}',
            "--max-budget-usd", f"{per_run_usd:.2f}", "--output-format", "stream-json", "--verbose", PROMPT]


def _claude_label(name: str) -> tuple[str, str]:
    if name.startswith("mcp__terraproof__") and name.removeprefix("mcp__terraproof__") in TOOLS:
        tool = name.removeprefix("mcp__terraproof__")
        return f"terraproof.{tool}", f"mcp:{tool}"
    if name.startswith("mcp__"):
        return "mcp", "mcp:other"
    if name in CLAUDE_CATEGORIES:
        return name, CLAUDE_CATEGORIES[name]
    return "other", "other"


def claude_trace(events, condition: str, seeded: tuple[str, ...], *, timed_out: bool = False) -> AgentResult:
    calls: dict[str, dict] = {}
    order: list[str] = []
    labels: set[str] = set()
    incidental: set[str] = set()
    skill_reads = 0
    refused = False
    for stamp, event in _timed(events):
        message = event.get("message", {}) if isinstance(event, dict) else {}
        if not isinstance(message, dict):
            continue
        refused |= message.get("stop_reason") == "refusal"
        for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                identifier = str(block.get("id") or f"anonymous-{len(order)}")
                name = str(block.get("name", ""))
                tool, category = _claude_label(name)
                text = json.dumps(block.get("input"), default=str)
                skill_reads += name == "Skill" or _is_skill_read(text)
                labels |= contamination_labels(name + " " + text, condition, seeded)
                incidental |= incidental_labels(name + " " + text, condition)
                calls[identifier] = {"tool": tool, "category": category, "status": "started", "exit_code": None,
                                     "duration_ms": None, "_start": stamp}
                order.append(identifier)
            elif block.get("type") == "tool_result" and str(block.get("tool_use_id")) in calls:
                record = calls[str(block.get("tool_use_id"))]
                record["status"] = "failed" if block.get("is_error") else "completed"
                record["duration_ms"] = _duration_ms(record["_start"], stamp)
    final = next((e for _, e in reversed(_timed(events)) if isinstance(e, dict) and e.get("type") == "result"), {})
    usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
    cost = final.get("total_cost_usd")
    subtype = final.get("subtype")
    ok = bool(final) and not final.get("is_error", True) and subtype == "success"
    if timed_out:
        turn_status, reason = "timeout", "per-run timeout; owned process tree terminated"
    elif refused:
        turn_status, reason = "refused", "model stop reason was refusal"
    elif ok:
        turn_status, reason = "completed", "no tool calls" if not order else "ok"
    elif final:
        turn_status, reason = "error", CLAUDE_RESULT_REASONS.get(subtype, "unclassified result")
    else:
        turn_status, reason = "aborted", "stream ended without a result event"
    public = [{key: value for key, value in calls[i].items() if not key.startswith("_")} for i in order]
    return AgentResult(status="completed" if ok and not refused else ("timeout" if timed_out else "failed"),
                       cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
                       tool_calls=len(public),
                       terraproof_tool_calls=sum(1 for c in public if c["tool"].startswith("terraproof.")),
                       skill_reads=skill_reads,
                       input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                       contamination=sorted(labels), diagnostics=sorted(incidental), calls=public,
                       turn={"status": turn_status, "reason": reason,
                             "error_types": [subtype] if subtype in CLAUDE_RESULT_REASONS and subtype != "success" else [],
                             "error_items": 0})


class ClaudeHostAdapter(Adapter):
    name = "claude-host"
    model_calls = True
    usd_capped = True

    def __init__(self, executable: str, agent_python_without: str | None = None):
        self.executable = executable
        self.agent_python_without = agent_python_without

    def _config(self, request: AgentRequest) -> Path:
        """An explicit --mcp-config outside the project.

        Claude Code leaves a project `.mcp.json` server "pending approval" (`claude mcp list`),
        so "with" passes a copy of exactly the installer-written entry instead.
        """
        servers = {}
        if request.condition == WITH:
            installed = json.loads((request.project / ".mcp.json").read_text(encoding="utf-8"))
            servers = {"terraproof": installed["mcpServers"]["terraproof"]}
        config = request.project.parent / "host.mcp.json"  # neutral name: no condition in any path
        config.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        return config

    def run(self, request: AgentRequest) -> AgentResult:
        command = claude_lift_command(self.executable, request.project, self._config(request), request.condition,
                                      request.max_usd)
        env = host_env(request.condition, self.agent_python_without)
        code, lines, _stderr, timed_out = run_contained(command, request.project, env, request.timeout_seconds)
        events, invalid = _json_lines(lines)
        # A timeout reports no spend; the harness charges the full per-run cap.
        result = claude_trace(events, request.condition, _seeded(request.task_id), timed_out=timed_out)
        if (code not in (0, None) or invalid) and result.status == "completed":
            result.status = "failed"
            result.turn["reason"] = "nonzero host exit or invalid JSONL"
        return result

    def preflight(self, request: AgentRequest) -> dict:
        """Claude Code has no model-free sandbox runner; Python/IO are probed directly instead."""
        env = host_env(request.condition, self.agent_python_without)
        checks = unsandboxed_probe(request.project, request.task_id, env)
        if request.condition != WITH:
            checks.update(without_isolation_checks(request.project, self.agent_python_without, env))
        config = self._config(request)
        if request.condition == WITH:
            entry = json.loads(config.read_text(encoding="utf-8")).get("mcpServers", {}).get("terraproof", {})
            checks["mcp_tools_served"] = bool(entry) and mcp_tools_served(entry["command"], entry.get("args", []),
                                                                         request.project)
        return checks


def probe_claude(executable: str | None = None) -> tuple[str | None, str, str | None]:
    """Resolve a native Claude Code binary. On Windows npm puts a `claude.cmd` wrapper first on
    PATH; pass `--claude-executable` (for example `...\\@anthropic-ai\\claude-code\\bin\\claude.exe`)."""
    executable = executable or shutil.which("claude")
    if not executable or not Path(executable).is_file():
        return None, "claude executable not found", None
    if os.name == "nt" and Path(executable).suffix.lower() != ".exe":
        return None, "Windows shell wrapper cannot guarantee bounded process cleanup; native executable required", None
    with tempfile.TemporaryDirectory(prefix="terraproof-lift-probe-") as directory:
        cwd = Path(directory)
        version = validation.run([executable, "--version"], cwd=cwd)
        help_result = validation.run([executable, "--help"], cwd=cwd)
        required = ["--restricted", "--strict-mcp-config", "--no-session-persistence", "--tools",
                    "--allowedTools", "--max-budget-usd", "--permission-prompts"]
        if help_result.returncode or not all(flag in help_result.stdout for flag in required):
            return None, "installed host lacks required isolation/budget controls", None
        auth = validation.run([executable, "auth", "status", "--json"], cwd=cwd)
        try:
            logged_in = json.loads(auth.stdout).get("loggedIn") is True
        except (ValueError, AttributeError):
            logged_in = False
        if auth.returncode or not logged_in:
            return None, "noninteractive claude auth status did not confirm loggedIn; no credentials logged", None
    return executable, "ok", version.stdout.strip()


# -- Antigravity -------------------------------------------------------------------------
# agy 1.3.0, https://antigravity.google/docs/cli/headless: `--output-format stream-json` emits one
# `init`, then `step_update` events (tool steps carry `tool_name` and `tool_info`), then one `result`
# whose `status` is SUCCESS, ERROR, CANCELED, INTERRUPTED, INVALID, WAITING or RUNNING.
ANTIGRAVITY_REQUIRED_FLAGS = ("--print", "--output-format", "--dangerously-skip-permissions", "--model")
ANTIGRAVITY_RESULT_REASONS = {"ERROR": "result status error", "CANCELED": "result status canceled",
                              "INTERRUPTED": "result status interrupted", "INVALID": "result status invalid",
                              "WAITING": "waiting for approval", "RUNNING": "result status running"}
# Built-in tool names are matched by keyword, first match wins; names are not a stable contract.
ANTIGRAVITY_CATEGORIES = (("shell", ("command", "terminal", "shell", "bash", "powershell")),
                          ("web", ("url", "web", "browser", "http")),
                          ("agent", ("subagent", "agent")),
                          ("skill", ("skill",)),
                          ("file_edit", ("write", "replace", "edit", "create", "delete", "move")),
                          ("file_read", ("view", "read", "list", "find", "grep", "search", "glob", "file")))
# Global locations every workspace sees, so both conditions see them
# (https://antigravity.google/docs/{mcp,skills,rules}). Terraproof must be absent from all of them.
ANTIGRAVITY_GLOBAL_MCP = ("config/mcp_config.json",)
ANTIGRAVITY_GLOBAL_SKILLS = ("antigravity-cli/skills", "config/skills", "antigravity/skills")
ANTIGRAVITY_GLOBAL_RULES = ("GEMINI.md", "AGENTS.md", "config/rules", "antigravity-cli/rules")
ANTIGRAVITY_PLUGINS = "antigravity-cli/plugins"
SHORT_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


def antigravity_lift_command(executable: str, model: str, effort: str | None) -> list[str]:
    """Flags first and the prompt last, so `--print` works whether it takes a value or not."""
    command = [executable, "--output-format", "stream-json", "--dangerously-skip-permissions", "--model", model]
    if effort:
        command += ["--effort", effort]
    return command + ["--print", PROMPT]


# agy 1.4.7 routes every MCP call through one built-in tool; the server and tool are in its
# arguments (`{"ServerName": ..., "ToolName": ..., "Arguments": ...}`), seen in the 2026-10-26 pilot.
ANTIGRAVITY_MCP_TOOL = "call_mcp_tool"


def _antigravity_parameters(info: dict) -> dict:
    """The tool step's arguments: `parameters` per the docs, `args` in agy's own transcripts."""
    params = info.get("parameters", info.get("args"))
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            return {}
    return params if isinstance(params, dict) else {}


def _antigravity_mcp_label(params: dict) -> tuple[str, str] | None:
    """Label a call_mcp_tool step by its ServerName/ToolName, or None when they are absent."""
    server = next((params[key] for key in ("ServerName", "serverName", "server_name") if key in params), None)
    tool = next((params[key] for key in ("ToolName", "toolName", "tool_name") if key in params), None)
    if not isinstance(server, str) or not isinstance(tool, str):
        return None
    if server.lower() == "terraproof" and tool in TOOLS:
        return f"terraproof.{tool}", f"mcp:{tool}"
    return "mcp", "mcp:other"


def _antigravity_label(name: str) -> tuple[str, str]:
    match = re.fullmatch(r"(?:mcp[_:/.]+)?terraproof(?:__|[_:/.])(\w+)|mcp\(terraproof/(\w+)\)", name, re.IGNORECASE)
    tool = (match.group(1) or match.group(2)) if match else (name if name in TOOLS else None)
    if tool in TOOLS:
        return f"terraproof.{tool}", f"mcp:{tool}"
    if re.search(r"mcp", name, re.IGNORECASE):
        return "mcp", "mcp:other"
    label = name if SHORT_LABEL.fullmatch(name) else "other"
    lowered = name.lower()
    for category, words in ANTIGRAVITY_CATEGORIES:
        if any(word in lowered for word in words):
            return label, category
    return label, "other"


def _same_path(first, second: Path) -> bool:
    try:
        return os.path.normcase(str(Path(str(first)).resolve())) == os.path.normcase(str(second.resolve()))
    except (OSError, ValueError):
        return False


def antigravity_trace(events, condition: str, seeded: tuple[str, ...], *, project: Path | None = None,
                      timed_out: bool = False) -> AgentResult:
    """Sanitise agy stream-json into per-call labels, a turn status and counts."""
    calls: dict[str, dict] = {}
    order: list[str] = []
    labels: set[str] = set()
    incidental: set[str] = set()
    workspace_ok = True
    final: dict = {}
    for stamp, event in _timed(events):
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        payload = event.get(kind) if isinstance(event.get(kind), dict) else event
        if kind == "init":
            tools = json.dumps(payload.get("tools"), default=str)
            if condition != WITH and re.search(r"terraproof", tools, re.IGNORECASE):
                labels.add("terraproof-in-without:mcp")
            # init lists the generic MCP tool, not server or tool names (2026-10-26 pilot).
            if condition == WITH and not re.search(r"terraproof|" + ANTIGRAVITY_MCP_TOOL, tools, re.IGNORECASE):
                incidental.add("terraproof-tools-not-listed")
            if project is not None and payload.get("cwd") and not _same_path(payload["cwd"], project):
                workspace_ok = False
        elif kind == "result":
            final = payload
        elif kind == "step_update":
            info = payload.get("tool_info") if isinstance(payload.get("tool_info"), dict) else {}
            kind_of_step = str(payload.get("step_type") or "")
            if kind_of_step != "tool" and not info and not payload.get("subagent_info"):
                continue
            identifier = f"{payload.get('conversation_id')}:{payload.get('step_index')}"
            if identifier not in calls:
                name = str(payload.get("tool_name") or info.get("name") or "")
                tool, category = _antigravity_label(name) if name else ("subagent", "agent")
                calls[identifier] = {"tool": tool, "category": category, "status": "started", "exit_code": None,
                                     "duration_ms": None, "_start": stamp, "_text": ""}
                order.append(identifier)
            record = calls[identifier]
            params = _antigravity_parameters(info)
            if str(payload.get("tool_name") or info.get("name") or "") == ANTIGRAVITY_MCP_TOOL:
                # Arguments may arrive only on a later update of the same step.
                mcp_label = _antigravity_mcp_label(params)
                if mcp_label:
                    record["tool"], record["category"] = mcp_label
                    if condition != WITH and mcp_label[0].startswith("terraproof."):
                        labels.add("terraproof-in-without:mcp")
            text = json.dumps({"name": payload.get("tool_name") or info.get("name"), "parameters": params},
                              default=str)
            record["_text"] = record["_text"] + " " + text if text not in record["_text"] else record["_text"]
            if payload.get("state") == "DONE":
                record["status"] = "failed" if info.get("error") else "completed"
                seconds = payload.get("duration_seconds")
                record["duration_ms"] = (max(0, int(round(seconds * 1000))) if isinstance(seconds, (int, float))
                                         else _duration_ms(record["_start"], stamp))
    public = []
    skill_reads = 0
    for identifier in order:
        record = calls[identifier]
        skill_reads += record["category"] == "skill" or _is_skill_read(record["_text"])
        labels |= contamination_labels(record["_text"], condition, seeded)
        incidental |= incidental_labels(record["_text"], condition)
        public.append({key: value for key, value in record.items() if not key.startswith("_")})
    status = str(final.get("status") or "")
    error = final.get("error") if isinstance(final.get("error"), dict) else {}
    error_type = str(error.get("type") or "").lower()
    error_types = [error_type] if re.fullmatch(r"[a-z0-9_.-]{1,40}", error_type) else []
    usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
    if timed_out:
        turn_status, reason = "timeout", "per-run timeout; owned process tree terminated"
    elif not workspace_ok:
        turn_status, reason = "error", "host workspace is not the run project"
    elif status == "SUCCESS":
        turn_status, reason = "completed", "no tool calls" if not public else "ok"
    elif final:
        turn_status, reason = "error", ANTIGRAVITY_RESULT_REASONS.get(status, "unclassified result")
    else:
        turn_status, reason = "aborted", "stream ended without a result event"
    return AgentResult(status="completed" if turn_status == "completed" else ("timeout" if timed_out else "failed"),
                       cost_usd=None, tool_calls=len(public),
                       terraproof_tool_calls=sum(1 for call in public if call["tool"].startswith("terraproof.")),
                       skill_reads=skill_reads,
                       input_tokens=usage.get("input_tokens") if type(usage.get("input_tokens")) is int else None,
                       output_tokens=usage.get("output_tokens") if type(usage.get("output_tokens")) is int else None,
                       contamination=sorted(labels), diagnostics=sorted(incidental), calls=public,
                       turn={"status": turn_status, "reason": reason, "error_types": error_types, "error_items": 0})


def _mentions_terraproof(path: Path) -> bool:
    try:
        return "terraproof" in path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return True  # unreadable: cannot show it is clean


def antigravity_global_checks(home: Path) -> dict:
    """No-model checks that nothing global to every agy workspace carries Terraproof.

    Only booleans are returned; no file content leaves this function.
    """
    registry = set(_registry_names())
    servers_clean = True
    for relative in ANTIGRAVITY_GLOBAL_MCP:
        path = home / relative
        if path.is_file() and path.read_text(encoding="utf-8", errors="replace").strip():
            try:
                servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers") or {}
            except (ValueError, AttributeError):
                servers_clean = False
                continue
            servers_clean &= not any("terraproof" in (name + json.dumps(entry, default=str)).lower()
                                     for name, entry in servers.items())
    plugins = home / ANTIGRAVITY_PLUGINS
    skill_roots = [home / relative for relative in ANTIGRAVITY_GLOBAL_SKILLS]
    skill_roots += sorted(plugins.glob("*/skills")) if plugins.is_dir() else []
    skills_clean = not any(child.is_dir() and (child.name in registry or "terraproof" in child.name.lower())
                           for root in skill_roots if root.is_dir() for child in root.iterdir())
    rule_files = []
    for relative in ANTIGRAVITY_GLOBAL_RULES:
        path = home / relative
        rule_files += sorted(path.glob("*.md")) if path.is_dir() else ([path] if path.is_file() else [])
    rule_files += sorted(plugins.glob("*/rules/*.md")) if plugins.is_dir() else []
    plugin_configs = sorted(plugins.glob("**/*.json")) if plugins.is_dir() else []
    return {"no_terraproof_in_global_mcp": servers_clean,
            "no_terraproof_in_global_skills": skills_clean,
            "no_terraproof_in_global_rules": not any(_mentions_terraproof(path) for path in rule_files),
            "no_terraproof_in_plugins": not any(_mentions_terraproof(path) for path in plugin_configs)}


class AntigravityHostAdapter(Adapter):
    name = "antigravity-host"
    model_calls = True
    usd_capped = False

    def __init__(self, executable: str, model: str, effort: str | None = None,
                 agent_python_without: str | None = None, home: Path | None = None):
        self.executable = executable
        self.model = model
        self.effort = effort
        self.agent_python_without = agent_python_without
        self.home = home or Path.home() / ".gemini"

    def run(self, request: AgentRequest) -> AgentResult:
        command = antigravity_lift_command(self.executable, self.model, self.effort)
        env = host_env(request.condition, self.agent_python_without)
        code, lines, _stderr, timed_out = run_contained(command, request.project, env, request.timeout_seconds)
        events, invalid = _json_lines(lines)
        result = antigravity_trace(events, request.condition, _seeded(request.task_id), project=request.project,
                                   timed_out=timed_out)
        if (code not in (0, None) or invalid) and result.status == "completed":
            result.status = "failed"
            result.turn["reason"] = "nonzero host exit or invalid JSONL"
        return result

    def preflight(self, request: AgentRequest) -> dict:
        """agy has no model-free sandbox runner; Python/IO are probed directly, as for Claude Code."""
        env = host_env(request.condition, self.agent_python_without)
        checks = unsandboxed_probe(request.project, request.task_id, env)
        checks.update(antigravity_global_checks(self.home))
        if request.condition == WITH:
            config = request.project / ".agents" / "mcp_config.json"
            entry = (json.loads(config.read_text(encoding="utf-8")).get("mcpServers", {}).get("terraproof", {})
                     if config.is_file() else {})
            checks["mcp_tools_served"] = bool(entry) and mcp_tools_served(entry["command"], entry.get("args", []),
                                                                         request.project)
            agents_md = request.project / "AGENTS.md"
            checks["agents_md_block_written"] = (agents_md.is_file() and "terraproof:antigravity:begin"
                                                 in agents_md.read_text(encoding="utf-8"))
        else:
            checks.update(without_isolation_checks(request.project, self.agent_python_without, env))
        return checks


def antigravity_models(output: str) -> list[str]:
    """Model ids from `agy models` (one `<id>\\t<display name>` per line)."""
    return [line.split("\t", 1)[0].strip() for line in output.splitlines()
            if "\t" in line and re.fullmatch(r"[\w.:-]+", line.split("\t", 1)[0].strip())]


def probe_antigravity(executable: str | None = None, model: str | None = None) -> tuple[str | None, str, str | None]:
    """Resolve a native agy binary; `agy models` (no inference) confirms cached sign-in and the model."""
    executable = executable or shutil.which("agy")
    if not executable or not Path(executable).is_file():
        return None, "agy executable not found", None
    if os.name == "nt" and Path(executable).suffix.lower() != ".exe":
        return None, "Antigravity CLI must be a native .exe", None
    with tempfile.TemporaryDirectory(prefix="terraproof-lift-probe-") as directory:
        cwd = Path(directory)
        version = validation.run([executable, "--version"], cwd=cwd)
        help_result = validation.run([executable, "--help"], cwd=cwd)
        if version.returncode or not all(flag in help_result.stdout + help_result.stderr
                                         for flag in ANTIGRAVITY_REQUIRED_FLAGS):
            return None, "agy lacks a required headless flag", None
        listed = validation.run([executable, "models"], cwd=cwd, timeout=120)
        models = antigravity_models(listed.stdout) if listed.returncode == 0 else []
        if not models:
            return None, "agy models listed none; sign in with an interactive agy session; no credentials logged", None
        if model not in models:
            return None, "the requested model is not listed by agy models", None
    return executable, "ok", f"agy {version.stdout.strip()} {model}"


# -- plan and main -----------------------------------------------------------------------
def total_usd_cap(args, calls: int) -> float:
    """An explicit --max-usd-total, or by default every planned run at its full per-run cap."""
    return args.max_usd_total if args.max_usd_total is not None else round(calls * args.max_usd_per_run, 2)


API_HOSTS = ("openai", "groq")  # plain chat APIs driven by tests/api_agent.py
USD_CAPPED_HOSTS = ("claude", *API_HOSTS)
BILLING = {
    "codex": "ChatGPT subscription usage; Codex exposes no USD cap, so the approved invocation count and timeout "
             "are the hard limits",
    "claude": "Claude API spend, capped per run by --max-budget-usd and in total by the harness",
    "antigravity": "Antigravity (Google account) quota; agy exposes no USD cap, so the approved invocation count "
                   "and timeout are the hard limits",
    "openai": "OpenAI API spend from OPENAI_API_KEY, computed from returned token usage at the given prices; "
              "locally limited by conservative request reservations and reported usage, not a provider-side invoice cap",
    "groq": "Groq API spend from GROQ_API_KEY, computed from returned token usage at the given prices; "
            "locally limited by conservative request reservations and reported usage, not a provider-side invoice cap",
}


def api_model(args) -> str | None:
    from api_agent import PROVIDERS

    return args.api_model or PROVIDERS[args.agent_host]["default_model"]


def shell_command(parts) -> str:
    """Render approval commands for PowerShell on Windows and POSIX shells elsewhere."""
    if os.name != "nt":
        import shlex
        return shlex.join(parts)
    return " ".join(part if re.fullmatch(r"[A-Za-z0-9_./:\\=-]+", part)
                    else "'" + part.replace("'", "''") + "'" for part in parts)


def plan(args) -> dict:
    cohort = None if args.task else (args.cohort or DEFAULT_COHORT)
    tasks = args.task or [task.task_id for task in COHORTS[cohort]]
    calls = planned_calls(len(set(tasks)), args.runs)
    capped = args.agent_host in USD_CAPPED_HOSTS
    ceiling = round(min(calls * args.max_usd_per_run, total_usd_cap(args, calls)), 2) if capped else None
    approve = ["python", "tests/agent_lift.py", "--agent-host", args.agent_host, "--runs", str(args.runs)]
    for task_id in args.task or []:
        approve += ["--task", task_id]
    if cohort:
        approve += ["--cohort", cohort]
    if args.agent_host == "codex" and args.codex_executable:
        approve += ["--codex-executable", str(args.codex_executable)]
    if args.agent_host == "claude" and args.claude_executable:
        approve += ["--claude-executable", str(args.claude_executable)]
    if args.agent_host == "antigravity":
        if args.antigravity_executable:
            approve += ["--antigravity-executable", str(args.antigravity_executable)]
        approve += ["--antigravity-model", str(args.antigravity_model)]
        if args.antigravity_effort:
            approve += ["--antigravity-effort", args.antigravity_effort]
    if args.agent_python_without:
        approve += ["--agent-python-without", str(args.agent_python_without)]
    if args.agent_host in API_HOSTS:
        approve += ["--api-model", str(api_model(args)),
                    "--usd-per-million-input", f"{args.usd_per_million_input:g}",
                    "--usd-per-million-output", f"{args.usd_per_million_output:g}",
                    "--max-model-calls-per-run", str(args.max_model_calls_per_run),
                    "--max-tokens-per-run", str(args.max_tokens_per_run),
                    "--rate-limit-retries", str(args.rate_limit_retries),
                    "--max-retry-wait", f"{args.max_retry_wait:g}"]
    if getattr(args, "verification_plan", None):
        approve += ["--verification-plan", str(args.verification_plan)]
    if capped:
        approve += ["--max-usd-per-run", f"{args.max_usd_per_run:g}", "--max-usd-total", f"{total_usd_cap(args, calls):g}"]
    approve += ["--timeout", f"{args.timeout:g}", "--approve-model-calls", str(calls)]
    return {
        "status": "plan-only (no host started, no model called)",
        "agent_host": args.agent_host,
        "cohort": cohort,
        "tasks": sorted(set(tasks)),
        "runs_per_condition": args.runs,
        "planned_model_invocations": calls,
        "per_run_timeout_seconds": args.timeout,
        "per_run_usd_cap": args.max_usd_per_run if capped else None,
        "total_usd_ceiling": ceiling,
        "billing": BILLING[args.agent_host],
        **({"api": {"model": api_model(args), "usd_per_million_input": args.usd_per_million_input,
                    "usd_per_million_output": args.usd_per_million_output,
                    "max_model_calls_per_run": args.max_model_calls_per_run,
                    "max_tokens_per_run": args.max_tokens_per_run,
                    "rate_limit_retries": args.rate_limit_retries,
                    "max_retry_wait_seconds": args.max_retry_wait,
                    "budget_enforcement": "local-reservation-not-provider-cap"}} if args.agent_host in API_HOSTS else {}),
        **({"required_verification": {"plan_sha256": args.verification_policy.sha256,
                                     "applies_to": "with-only", "task_coverage": "all-declared-outputs"}}
           if getattr(args, "verification_policy", None) is not None else {}),
        "command_to_approve": shell_command(approve),
        "preflight_command": shell_command(approve[:-2] + ["--preflight-only"]),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-host", choices=["codex", "claude", "antigravity", *API_HOSTS], required=True,
                        help="openai/groq use tests/api_agent.py; keys come only from OPENAI_API_KEY / GROQ_API_KEY")
    parser.add_argument("--runs", type=int, default=3, help="runs per condition and task (default 3)")
    parser.add_argument("--task", action="append", help="lift task id (repeatable; not with --cohort)")
    parser.add_argument("--cohort", choices=sorted(COHORTS),
                        help=f"task cohort to run (default {DEFAULT_COHORT}); cohorts are separate experiments")
    parser.add_argument("--timeout", type=float, default=900, help="per-run timeout in seconds (default 900)")
    parser.add_argument("--max-usd-per-run", type=float, default=1.0,
                        help="per-run USD cap for claude/openai/groq (default 1)")
    parser.add_argument("--max-usd-total", type=float, default=None,
                        help="total USD cap for claude/openai/groq (default: planned runs x --max-usd-per-run)")
    parser.add_argument("--api-model", help="model for openai/groq (openai default gpt-4o; groq has no default)")
    parser.add_argument("--verification-plan", type=Path,
                        help="explicit required MCP checks for every declared output; API with-condition only")
    parser.add_argument("--usd-per-million-input", type=float,
                        help="openai/groq price per million input tokens (required; prices are never guessed)")
    parser.add_argument("--usd-per-million-output", type=float,
                        help="openai/groq price per million output tokens (required)")
    parser.add_argument("--max-model-calls-per-run", type=int, default=40, help="openai/groq call cap per run")
    parser.add_argument("--max-tokens-per-run", type=int, default=300_000, help="openai/groq token cap per run")
    parser.add_argument("--rate-limit-retries", type=int, default=3,
                        help="openai/groq HTTP 429 retries per run (default 3; each counts against the caps)")
    parser.add_argument("--max-retry-wait", type=float, default=60.0,
                        help="openai/groq longest wait per 429 retry in seconds (default 60)")
    parser.add_argument("--codex-reasoning-effort", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--codex-executable", type=Path,
                        help="native codex.exe to use (default: the PATH-resolved native binary)")
    parser.add_argument("--claude-executable", type=Path,
                        help="native claude.exe to use (default: PATH; the npm claude.cmd wrapper is refused)")
    parser.add_argument("--antigravity-executable", type=Path,
                        help="native agy.exe to use (default: the PATH-resolved agy)")
    parser.add_argument("--antigravity-model", help="agy model id from `agy models` (required for antigravity)")
    parser.add_argument("--antigravity-effort", choices=["low", "medium", "high", "xhigh", "max"],
                        help="agy reasoning effort (default: the host's own)")
    parser.add_argument("--agent-python-without", type=Path,
                        help="dependency-only Python (numpy, rasterio, pyogrio, shapely, pyproj; no Terraproof) "
                             "on a path without 'terraproof', first on PATH for the without agent; required by preflight")
    parser.add_argument("--preflight-only", action="store_true",
                        help="prepare every project and run the no-model host preflight; start no agent")
    parser.add_argument("--approve-model-calls", type=int, metavar="N",
                        help="explicit approval: N must equal the planned invocation count")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "agent-lift.json")
    parser.add_argument("--recordings", type=Path, default=ROOT / ".terracache" / "agent-lift-recordings")
    args = parser.parse_args(argv)
    if (args.runs < 1 or not math.isfinite(args.timeout) or args.timeout <= 0
            or not math.isfinite(args.max_usd_per_run) or args.max_usd_per_run <= 0
            or (args.max_usd_total is not None and
                (not math.isfinite(args.max_usd_total) or args.max_usd_total <= 0))):
        parser.error("--runs, --timeout and the USD caps must be positive")
    if args.task and args.cohort:
        parser.error("--task and --cohort select tasks in different ways; give one of them")
    if args.agent_host == "antigravity" and not args.antigravity_model:
        parser.error("--antigravity-model is required for antigravity (see `agy models`)")
    if args.agent_host in API_HOSTS:
        if not api_model(args):
            parser.error(f"--api-model is required for {args.agent_host}")
        if not (args.usd_per_million_input and math.isfinite(args.usd_per_million_input)
                and args.usd_per_million_input > 0 and args.usd_per_million_output
                and math.isfinite(args.usd_per_million_output) and args.usd_per_million_output > 0):
            parser.error("--usd-per-million-input and --usd-per-million-output are required and must be positive")
        if args.max_model_calls_per_run < 1 or args.max_tokens_per_run < 1:
            parser.error("--max-model-calls-per-run and --max-tokens-per-run must be positive")
        if args.rate_limit_retries < 0 or not math.isfinite(args.max_retry_wait) or args.max_retry_wait <= 0:
            parser.error("--rate-limit-retries must be non-negative and --max-retry-wait positive")
    args.verification_policy = None
    if args.verification_plan is not None:
        if args.agent_host not in API_HOSTS:
            parser.error("--verification-plan is supported only by API hosts")
        try:
            from output_verification import VerificationPlan
            args.verification_policy = VerificationPlan(args.verification_plan)
            selected = args.task or [task.task_id for task in COHORTS[args.cohort or DEFAULT_COHORT]]
            for task_id in selected:
                args.verification_policy.groups(task_id, lift_task(task_id).deliverable_names)
        except (OSError, ValueError):
            parser.error("invalid verification plan or incomplete declared-output coverage")
    if args.preflight_only and args.approve_model_calls is not None:
        parser.error("--preflight-only starts no agent; do not combine it with --approve-model-calls")
    try:
        for task_id in args.task or []:
            lift_task(task_id)
    except LiftError as error:
        parser.error(str(error))
    summary = plan(args)
    if args.approve_model_calls is None and not args.preflight_only:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.approve_model_calls is not None and args.approve_model_calls != summary["planned_model_invocations"]:
        parser.error(f"--approve-model-calls {args.approve_model_calls} does not equal the planned "
                     f"{summary['planned_model_invocations']} invocations; nothing was started")
    agent_python = str(args.agent_python_without) if args.agent_python_without else None
    if args.agent_host == "codex":
        executable, reason, version = probe_codex(str(args.codex_executable) if args.codex_executable else None)
        adapter = (CodexHostAdapter(executable, args.codex_reasoning_effort, agent_python) if executable
                   else None)
        budget = Budget(max_runs=args.approve_model_calls, timeout_seconds=args.timeout)
    elif args.agent_host == "antigravity":
        executable, reason, version = probe_antigravity(
            str(args.antigravity_executable) if args.antigravity_executable else None, args.antigravity_model)
        adapter = (AntigravityHostAdapter(executable, args.antigravity_model, args.antigravity_effort, agent_python)
                   if executable else None)
        budget = Budget(max_runs=args.approve_model_calls, timeout_seconds=args.timeout)
    elif args.agent_host in API_HOSTS:
        from api_agent import ApiAgentAdapter, ApiLimits

        limits = ApiLimits(usd_per_million_input=args.usd_per_million_input,
                           usd_per_million_output=args.usd_per_million_output,
                           max_model_calls=args.max_model_calls_per_run, max_tokens=args.max_tokens_per_run,
                           rate_limit_retries=args.rate_limit_retries, max_retry_wait=args.max_retry_wait)
        adapter = ApiAgentAdapter(args.agent_host, api_model(args), limits, agent_python,
                                  verification_plan=args.verification_policy)
        version = f"{args.agent_host} {adapter.model}"
        reason = "ok" if adapter.key_present() else f"{adapter.key_env} is not set; no request was sent"
        adapter = adapter if adapter.key_present() else None
        budget = Budget(max_runs=args.approve_model_calls, per_run_usd=args.max_usd_per_run,
                        total_usd=total_usd_cap(args, summary["planned_model_invocations"]),
                        timeout_seconds=args.timeout)
    else:
        executable, reason, version = probe_claude(str(args.claude_executable) if args.claude_executable else None)
        adapter = ClaudeHostAdapter(executable, agent_python) if executable else None
        budget = Budget(max_runs=args.approve_model_calls, per_run_usd=args.max_usd_per_run,
                        total_usd=total_usd_cap(args, summary["planned_model_invocations"]),
                        timeout_seconds=args.timeout)
    if adapter is None:
        print(json.dumps({"status": "unavailable", "reason": reason, "model_called": False}, sort_keys=True))
        return 1
    # Outside the checkout: no ancestral AGENTS.md/CLAUDE.md/config, and no repository source to read.
    # Neutral prefix: agents see absolute paths (Claude Code's Read/Write take them).
    work = Path(tempfile.mkdtemp(prefix="paired-run-")).resolve()
    if ROOT.resolve() in work.parents:
        shutil.rmtree(work, ignore_errors=True)
        print(json.dumps({"status": "refused", "reason": "work directory inside the checkout"}))
        return 1
    try:
        report = run_lift(adapter, task_ids=args.task, cohort=summary["cohort"] or DEFAULT_COHORT,
                          runs=1 if args.preflight_only else args.runs,
                          # API agents read the claude-format install: .mcp.json and .claude/skills/.
                          agent="claude" if args.agent_host in API_HOSTS else args.agent_host,
                          budget=budget, work_root=work,
                          allow_model_calls=not args.preflight_only, preflight_only=args.preflight_only,
                          recordings_out=None if args.preflight_only else args.recordings)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    report["command"] = summary["preflight_command" if args.preflight_only else "command_to_approve"]
    report["host"] = {"name": args.agent_host, "version": version}
    out = args.out.with_name(args.out.stem + "-preflight" + args.out.suffix) if args.preflight_only else args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(report), encoding="utf-8", newline="\n")
    failed = [f"{task['id']}:{run['condition']}" for task in report["tasks"] for run in task["runs"]
              if run["adapter_status"] == "preflight_failed"]
    print(json.dumps({"status": "preflight complete" if args.preflight_only else "complete", "report": str(out),
                      "host_version": version, "preflight_failures": failed,
                      "started_agent_runs": report["design"]["started_agent_runs"],
                      "spent_usd": report["budget"]["spent_usd"]}, sort_keys=True))
    return 1 if args.preflight_only and failed else 0


if __name__ == "__main__":
    sys.exit(main())
