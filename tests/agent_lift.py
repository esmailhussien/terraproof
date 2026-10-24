#!/usr/bin/env python3
"""Phase 5 real-host agent-lift driver. Prints a plan by default; model calls are opt-in.

Without `--approve-model-calls N` this script only prints the planned number of agent
invocations, the cost ceiling and the exact command to approve; it starts no host and
calls no model. With the approval, N must equal the planned invocation count, and the
paired with/without runs go through `terraproof.evals.lift.run_lift` with the isolation,
process-tree containment and auth probes of `tests/release_validation.py`.

Only counts, tool names and fixed labels leave a host stream: prompts, model text, command
lines, arguments and environment are never written to the report or recordings.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_validation as validation  # noqa: E402  (shared host isolation helpers)

from terraproof.evals.lift import (  # noqa: E402
    LIFT_TASKS, WITH, Adapter, AgentRequest, AgentResult, Budget, LiftError, lift_task, planned_calls, run_lift, to_json,
)

ROOT = validation.ROOT
TOOLS = validation.TOOLS
PROMPT = "Read TASK.md in the current directory and complete the task it describes."
CODEX_ENABLED_FOR_LIFT = ("shell_tool",)
CODEX_DISABLED = tuple(name for name in validation.CODEX_DISABLED if name not in CODEX_ENABLED_FOR_LIFT)
CLAUDE_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill")
# Reading the harness, the oracles, the specs or the seeded-wrong fixtures is contamination.
FORBIDDEN = (
    ("harness-source", r"terraproof[\\/.]+evals|evals[\\/]+(?:tasks|recipes)|recipes[\\/]+\w+\.py"),
    ("oracle-source", r"oracles(?:\.py)?\b"),
    ("python-introspection", r"inspect\.getsource|importlib\.resources"),
    ("outside-project", r"agent-lift-recordings|\.\.[\\/]\.\."),
)


def contamination_labels(text: str, condition: str, seeded: tuple[str, ...]) -> set[str]:
    """Fixed labels for forbidden access in one tool call; the text itself is never kept."""
    labels = {label for label, pattern in FORBIDDEN if re.search(pattern, text, re.IGNORECASE)}
    if any(name in text for name in seeded):
        labels.add("seeded-fixture-name")
    if condition != WITH and re.search(r"terraproof", text, re.IGNORECASE):
        labels.add("terraproof-in-without")
    return labels


def _seeded(task_id: str) -> tuple[str, ...]:
    return tuple(wrong for _, wrong in lift_task(task_id).seeded)


def _is_skill_read(text: str) -> bool:
    return bool(re.search(r"[\\/]skills[\\/][^\"']*SKILL\.md|\.agents[\\/]skills|\.claude[\\/]skills", text))


def run_contained(command: list[str], cwd: Path, env: dict, timeout: float) -> tuple[int | None, str, str, bool]:
    """One invocation, no retries; the owned process tree is killed on every exit."""
    import signal

    job = validation.WindowsHostJob() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=0x4 if job else 0,  # CREATE_SUSPENDED
                                   start_new_session=not bool(job))
        if job:
            job.resume(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return process.returncode, stdout, stderr, False
        except subprocess.TimeoutExpired:
            return None, "", "", True
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
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()


def host_env() -> dict:
    """The task interpreter's directory first on PATH, so agents compute with numpy/rasterio."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", DISABLE_AUTOUPDATER="1",
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def _json_lines(stdout: str) -> tuple[list, int]:
    events, invalid = [], 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            invalid += 1
    return events, invalid


# -- Codex -------------------------------------------------------------------------------
def codex_lift_command(executable: str, project: Path, state: Path, condition: str, effort: str) -> list[str]:
    """Reviewable argv: workspace-write sandbox, shell enabled, no network, MCP only in "with"."""
    command = [executable, "--no-daemon", "exec", "--ignore-user-config", "--ignore-rules",
               "--strict-config", "--ephemeral", "--sandbox", "workspace-write", "--json",
               "--skip-git-repo-check", "-C", str(project)]
    for feature in CODEX_DISABLED:
        command.extend(["--disable", feature])
    command.extend(["--enable", "code_mode_host", "--enable", "skip_host_skill_discovery"])
    for feature in CODEX_ENABLED_FOR_LIFT:
        command.extend(["--enable", feature])
    config = {
        "approval_policy": '"never"', "web_search": '"disabled"',
        "sandbox_workspace_write.network_access": "false",
        "model_reasoning_effort": json.dumps(effort),
        "skills.bundled.enabled": "false",
        "history.persistence": '"none"', "analytics.enabled": "false",
        "suppress_unstable_features_warning": "true",
        "check_for_update_on_startup": "false", "log_dir": json.dumps(str(state / "logs")),
        "sqlite_home": json.dumps(str(state / "sqlite")),
    }
    if condition == WITH:
        tools = ",".join(json.dumps(name) for name in TOOLS)
        approvals = ",".join(f'{name}={{approval_mode="approve"}}' for name in TOOLS)
        config["mcp_servers"] = ("{terraproof={command=" + json.dumps(sys.executable)
                                 + ',args=["-m","terraproof.mcp"],enabled_tools=[' + tools + "],"
                                 + "tools={" + approvals + "},"
                                 + 'env={PYTHONUTF8="1",PYTHONIOENCODING="utf-8"},required=true,'
                                 + "startup_timeout_sec=30,tool_timeout_sec=120}}")
    for key, value in config.items():
        command.extend(["-c", f"{key}={value}"])
    command.append(PROMPT)
    return command


def codex_trace(events: list, condition: str, seeded: tuple[str, ...]) -> AgentResult:
    calls = terraproof_calls = skill_reads = 0
    labels: set[str] = set()
    completed = failed = False
    input_tokens = output_tokens = 0
    for event in events:
        if not isinstance(event, dict):
            failed = True
            continue
        kind = event.get("type")
        if kind in {"error", "turn.failed"}:
            failed = True
        if kind == "turn.completed":
            completed = True
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
        if kind != "item.completed" or not isinstance(event.get("item"), dict):
            continue
        item = event["item"]
        if item.get("type") in {"agent_message", "reasoning", "todo_list"}:
            continue
        calls += 1
        text = json.dumps({key: item.get(key) for key in ("command", "arguments", "changes", "tool")}, default=str)
        if item.get("type") == "mcp_tool_call" and item.get("server") == "terraproof":
            terraproof_calls += 1
        skill_reads += _is_skill_read(text)
        labels |= contamination_labels(text, condition, seeded)
    return AgentResult(status="completed" if completed and not failed else "failed", cost_usd=None,
                       tool_calls=calls, terraproof_tool_calls=terraproof_calls, skill_reads=skill_reads,
                       input_tokens=input_tokens, output_tokens=output_tokens, contamination=sorted(labels))


class CodexHostAdapter(Adapter):
    name = "codex-host"
    model_calls = True
    usd_capped = False

    def __init__(self, executable: str, effort: str):
        self.executable = executable
        self.effort = effort

    def run(self, request: AgentRequest) -> AgentResult:
        state = request.project.parent / "host-state"
        state.mkdir(exist_ok=True)
        command = codex_lift_command(self.executable, request.project, state, request.condition, self.effort)
        code, stdout, stderr, timed_out = run_contained(command, request.project, host_env(), request.timeout_seconds)
        if timed_out:
            return AgentResult(status="timeout", cost_usd=None, diagnostics=["timeout; owned process tree terminated"])
        events, invalid = _json_lines(stdout)
        result = codex_trace(events, request.condition, _seeded(request.task_id))
        diagnostics = validation.codex_diagnostics(stderr, events, invalid)["labels"]
        if code != 0 or invalid:
            result.status = "failed"
        result.diagnostics = diagnostics if result.status != "completed" else []
        return result


def probe_codex() -> tuple[str | None, str]:
    executable = validation.codex_executable()
    if not executable:
        return None, "no supported native Codex executable; shell/Node wrappers are not invoked"
    with tempfile.TemporaryDirectory(prefix="terraproof-lift-probe-") as directory:
        cwd = Path(directory)
        help_result = validation.run([executable, "exec", "--help"], cwd=cwd)
        required = ("--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral",
                    "--sandbox", "workspace-write", "--json", "--skip-git-repo-check", "--disable", "--config")
        if help_result.returncode or not all(flag in help_result.stdout for flag in required):
            return None, "Codex exec lacks a required isolation flag"
        features = validation.run([executable, "features", "list"], cwd=cwd)
        supported = {line.split()[0] for line in features.stdout.splitlines()
                     if len(line.split()) >= 3 and "removed" not in line.split()[1:-1]}
        needed = set(CODEX_DISABLED + CODEX_ENABLED_FOR_LIFT + ("code_mode_host", "skip_host_skill_discovery"))
        if features.returncode or not needed <= supported:
            return None, "required Codex feature controls unavailable"
        if not validation.codex_subscription_auth(validation.run([executable, "login", "status"], cwd=cwd)):
            return None, "Codex login status did not confirm ChatGPT subscription auth; no API-paid fallback"
    return executable, "ok"


# -- Claude Code -------------------------------------------------------------------------
def claude_lift_command(executable: str, project: Path, mcp_config: Path, condition: str, per_run_usd: float) -> list[str]:
    allowed = list(CLAUDE_TOOLS)
    if condition == WITH:
        allowed += [f"mcp__terraproof__{name}" for name in TOOLS]
    return [executable, "--print", "--restricted", "--tools", ",".join(CLAUDE_TOOLS),
            "--allowedTools", ",".join(allowed), "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--strict-mcp-config", "--mcp-config", str(mcp_config),
            "--no-session-persistence", "--no-chrome", "--settings", '{"disableAllHooks":true}',
            "--max-budget-usd", f"{per_run_usd:.2f}", "--output-format", "stream-json", "--verbose", PROMPT]


def claude_trace(events: list, condition: str, seeded: tuple[str, ...]) -> AgentResult:
    calls = terraproof_calls = skill_reads = 0
    labels: set[str] = set()
    for event in events:
        message = event.get("message", {}) if isinstance(event, dict) else {}
        for block in message.get("content", []) if isinstance(message, dict) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            calls += 1
            name = str(block.get("name", ""))
            text = json.dumps(block.get("input"), default=str)
            terraproof_calls += name.startswith("mcp__terraproof__")
            skill_reads += name == "Skill" or _is_skill_read(text)
            labels |= contamination_labels(name + " " + text, condition, seeded)
    final = next((e for e in reversed(events) if isinstance(e, dict) and e.get("type") == "result"), {})
    usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
    cost = final.get("total_cost_usd")
    ok = bool(final) and not final.get("is_error", True) and final.get("subtype") == "success"
    return AgentResult(status="completed" if ok else "failed",
                       cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
                       tool_calls=calls, terraproof_tool_calls=terraproof_calls, skill_reads=skill_reads,
                       input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                       contamination=sorted(labels))


class ClaudeHostAdapter(Adapter):
    name = "claude-host"
    model_calls = True
    usd_capped = True

    def __init__(self, executable: str):
        self.executable = executable

    def run(self, request: AgentRequest) -> AgentResult:
        if request.condition == WITH:
            config = request.project / ".mcp.json"  # written by the Terraproof installer
        else:
            config = request.project.parent / "empty.mcp.json"
            config.write_text('{"mcpServers": {}}', encoding="utf-8")
        command = claude_lift_command(self.executable, request.project, config, request.condition, request.max_usd)
        code, stdout, _stderr, timed_out = run_contained(command, request.project, host_env(), request.timeout_seconds)
        if timed_out:
            # The spend is unknown; the harness charges the full per-run cap.
            return AgentResult(status="timeout", cost_usd=None, diagnostics=["timeout; owned process tree terminated"])
        events, invalid = _json_lines(stdout)
        result = claude_trace(events, request.condition, _seeded(request.task_id))
        if code != 0 or invalid:
            result.status = "failed"
        return result


def probe_claude() -> tuple[str | None, str]:
    executable = shutil.which("claude")
    if not executable:
        return None, "claude executable not found"
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        return None, "Windows shell wrapper cannot guarantee bounded process cleanup; native executable required"
    with tempfile.TemporaryDirectory(prefix="terraproof-lift-probe-") as directory:
        cwd = Path(directory)
        help_result = validation.run([executable, "--help"], cwd=cwd)
        required = ["--restricted", "--strict-mcp-config", "--no-session-persistence", "--tools",
                    "--allowedTools", "--max-budget-usd", "--permission-prompts"]
        if help_result.returncode or not all(flag in help_result.stdout for flag in required):
            return None, "installed host lacks required isolation/budget controls"
        auth = validation.run([executable, "auth", "status", "--json"], cwd=cwd)
        try:
            logged_in = json.loads(auth.stdout).get("loggedIn") is True
        except (ValueError, AttributeError):
            logged_in = False
        if auth.returncode or not logged_in:
            return None, "noninteractive claude auth status did not confirm loggedIn; no credentials logged"
    return executable, "ok"


# -- plan and main -----------------------------------------------------------------------
def plan(args) -> dict:
    tasks = args.task or [task.task_id for task in LIFT_TASKS]
    calls = planned_calls(len(set(tasks)), args.runs)
    ceiling = None if args.agent_host == "codex" else round(min(calls * args.max_usd_per_run, args.max_usd_total), 2)
    approve = ["python", "tests/agent_lift.py", "--agent-host", args.agent_host, "--runs", str(args.runs)]
    for task_id in args.task or []:
        approve += ["--task", task_id]
    if args.agent_host == "claude":
        approve += ["--max-usd-per-run", f"{args.max_usd_per_run:g}", "--max-usd-total", f"{args.max_usd_total:g}"]
    approve += ["--timeout", f"{args.timeout:g}", "--approve-model-calls", str(calls)]
    return {
        "status": "plan-only (no host started, no model called)",
        "agent_host": args.agent_host,
        "tasks": sorted(set(tasks)),
        "runs_per_condition": args.runs,
        "planned_model_invocations": calls,
        "per_run_timeout_seconds": args.timeout,
        "per_run_usd_cap": args.max_usd_per_run if args.agent_host == "claude" else None,
        "total_usd_ceiling": ceiling,
        "billing": ("ChatGPT subscription usage; Codex exposes no USD cap, so the approved invocation count and "
                    "timeout are the hard limits" if args.agent_host == "codex"
                    else "Claude API spend, capped per run by --max-budget-usd and in total by the harness"),
        "command_to_approve": " ".join(approve),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-host", choices=["codex", "claude"], required=True)
    parser.add_argument("--runs", type=int, default=3, help="runs per condition and task (default 3)")
    parser.add_argument("--task", action="append", help="lift task id (repeatable; default all nine)")
    parser.add_argument("--timeout", type=float, default=900, help="per-run timeout in seconds (default 900)")
    parser.add_argument("--max-usd-per-run", type=float, default=1.0, help="Claude per-run USD cap (default 1)")
    parser.add_argument("--max-usd-total", type=float, default=54.0, help="Claude total USD cap (default 54)")
    parser.add_argument("--codex-reasoning-effort", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--approve-model-calls", type=int, metavar="N",
                        help="explicit approval: N must equal the planned invocation count")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "agent-lift.json")
    parser.add_argument("--recordings", type=Path, default=ROOT / ".terracache" / "agent-lift-recordings")
    args = parser.parse_args(argv)
    if args.runs < 1 or args.timeout <= 0 or args.max_usd_per_run <= 0 or args.max_usd_total <= 0:
        parser.error("--runs, --timeout and the USD caps must be positive")
    try:
        for task_id in args.task or []:
            lift_task(task_id)
    except LiftError as error:
        parser.error(str(error))
    summary = plan(args)
    if args.approve_model_calls is None:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.approve_model_calls != summary["planned_model_invocations"]:
        parser.error(f"--approve-model-calls {args.approve_model_calls} does not equal the planned "
                     f"{summary['planned_model_invocations']} invocations; nothing was started")
    if args.agent_host == "codex":
        executable, reason = probe_codex()
        adapter = CodexHostAdapter(executable, args.codex_reasoning_effort) if executable else None
        budget = Budget(max_runs=args.approve_model_calls, timeout_seconds=args.timeout)
    else:
        executable, reason = probe_claude()
        adapter = ClaudeHostAdapter(executable) if executable else None
        budget = Budget(max_runs=args.approve_model_calls, per_run_usd=args.max_usd_per_run,
                        total_usd=args.max_usd_total, timeout_seconds=args.timeout)
    if adapter is None:
        print(json.dumps({"status": "unavailable", "reason": reason, "model_called": False}, sort_keys=True))
        return 1
    # Outside the checkout: no ancestral AGENTS.md/CLAUDE.md/config, and no repository source to read.
    work = Path(tempfile.mkdtemp(prefix="terraproof-lift-host-")).resolve()
    if ROOT.resolve() in work.parents:
        shutil.rmtree(work, ignore_errors=True)
        print(json.dumps({"status": "refused", "reason": "work directory inside the checkout"}))
        return 1
    try:
        report = run_lift(adapter, task_ids=args.task, runs=args.runs, agent=args.agent_host, budget=budget,
                          work_root=work, allow_model_calls=True, recordings_out=args.recordings)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    report["command"] = summary["command_to_approve"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_json(report), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "complete", "report": str(args.out),
                      "started_agent_runs": report["design"]["started_agent_runs"],
                      "spent_usd": report["budget"]["spent_usd"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
