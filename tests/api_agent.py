"""A small tool-calling agent for OpenAI-compatible chat APIs (OpenAI, Groq) in the lift harness.

Claude Code and Codex are complete agents; a chat API is not. This adapter supplies the
loop and a minimal tool set, so a plain model can work on a lift task the same way:

- `list_files`, `read_file`, `write_file`: confined to the run project (no absolute paths,
  no `..`, nothing outside it);
- `run_python`: one script per call, run with the condition's interpreter (the dependency-only
  Python in "without"), in the project directory, with a timeout and process-tree cleanup.
  This is not a sandbox: the script itself can reach anything the user can;
- in "with" only, Terraproof's six MCP tools, served by the installer-registered server.

Hard limits per run: model calls, total tokens and USD (computed from the usage the API
returns and the prices passed in; prices are never guessed). The API key is read from the
provider's environment variable only when a request is sent; it is never stored, logged or
reported. Error reports carry status codes only, never response bodies.

Like the other hosts, only fixed labels and numbers leave a run: per call a tool label,
category, status, exit code and duration. Prompts, model text and tool arguments are not kept.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import agent_lift as driver
from terraproof.evals.lift import WITH, Adapter, AgentRequest, AgentResult, lift_task

PROVIDERS = {
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "default_model": "gpt-4o"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "default_model": None},
}
SYSTEM_PROMPT = ("You are working in a project directory on a geospatial task. Use the tools to inspect the "
                 "files, compute with Python and write the required outputs. When you are done, reply with a "
                 "short summary and no tool call.")
READ_LIMIT = 20_000  # characters returned from a file or tool result
OUTPUT_LIMIT = 8_000  # characters returned from a Python run
PYTHON_TIMEOUT = 120.0
MAX_COMPLETION_TOKENS = 4096  # per model call
USER_AGENT = "terraproof-lift-harness"
RATE_LIMIT_RETRIES = 3  # default per run; every attempt counts against the model-call cap and the timeout
# Groq answers HTTP 400 "tool_use_failed" when it cannot parse the model's tool call; a fresh
# attempt often succeeds. Same accounting as rate-limit retries; no wait.
TOOL_USE_RETRIES = 2
MAX_RETRY_WAIT = 60.0  # default seconds, per wait


@dataclass(frozen=True)
class ApiLimits:
    """Per-run hard caps. Prices are USD per million tokens, as the provider bills them."""

    usd_per_million_input: float
    usd_per_million_output: float
    max_model_calls: int = 40
    max_tokens: int = 300_000
    rate_limit_retries: int = RATE_LIMIT_RETRIES
    max_retry_wait: float = MAX_RETRY_WAIT

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.usd_per_million_input + output_tokens * self.usd_per_million_output) / 1e6


class ApiError(RuntimeError):
    """A failed API request, described by fixed labels (never the response body or key).

    `status` is the HTTP status, `error_type` a sanitized code from the error body (for example
    `rate_limit_exceeded` or `tool_use_failed`), and `retry_after` the server's wait in seconds.
    """

    def __init__(self, label: str, *, status: int | None = None, error_type: str | None = None,
                 retry_after: float | None = None):
        super().__init__(f"{label} ({error_type})" if error_type else label)
        self.status = status
        self.error_type = error_type
        self.retry_after = retry_after


ERROR_TYPE = re.compile(r"^[a-z0-9_.-]{1,40}$")


def error_type_label(body: bytes) -> str | None:
    """A short, fixed-vocabulary error code from a JSON error body; never any free text."""
    try:
        error = json.loads(body.decode("utf-8")).get("error")
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    if not isinstance(error, dict):
        return None
    for key in ("code", "type"):
        value = error.get(key)
        if isinstance(value, str) and ERROR_TYPE.match(value):
            return value
    return None


def retry_after_seconds(value: str | None) -> float | None:
    """Retry-After as seconds: a number, or an HTTP date relative to now."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def http_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    """POST one chat-completions request with the standard library.

    An explicit User-Agent is required: Groq's edge rejects urllib's default one with HTTP 403.
    """
    headers = {"User-Agent": USER_AGENT, **headers}
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            body = error.read(65_536) if error.fp else b""
        except OSError:
            body = b""
        wait = retry_after_seconds(error.headers.get("Retry-After") if error.headers else None)
        raise ApiError(f"http {error.code}", status=error.code, error_type=error_type_label(body),
                       retry_after=wait) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ApiError(f"network error ({type(error).__name__})") from None
    except ValueError:
        raise ApiError("invalid JSON response") from None


FILE_TOOLS = [
    {"type": "function", "function": {
        "name": "list_files", "description": "List files under a directory of the project (default: the project).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file in the project. Use run_python for rasters.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Write a text file in the project, creating folders as needed.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Run a Python script in the project directory (numpy and rasterio are installed). "
                       "Returns the exit code, stdout and stderr.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
]
CATEGORIES = {"list_files": "file_read", "read_file": "file_read", "write_file": "file_edit", "run_python": "shell"}


def project_path(project: Path, relative: str | None) -> Path:
    """Resolve a model-supplied path inside the project, or refuse it."""
    # Same rules on every OS: backslashes separate folders, and drive or rooted paths are refused.
    text = (relative or ".").strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text) or Path(text).is_absolute():
        raise ValueError("use a path relative to the project")
    target = (project / text).resolve()
    root = project.resolve()
    if target != root and root not in target.parents:
        raise ValueError("path is outside the project")
    return target


class ApiAgentAdapter(Adapter):
    """Runs one lift task with an OpenAI-compatible chat model."""

    name = "api-agent"
    model_calls = True
    usd_capped = True

    def __init__(self, provider: str, model: str, limits: ApiLimits, agent_python_without: str | None = None,
                 transport=http_transport, base_url: str | None = None, sleep=None):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        if not model:
            raise ValueError("a model name is required")
        self.provider = provider
        self.model = model
        self.limits = limits
        self.agent_python_without = agent_python_without
        self.transport = transport
        self.sleep = sleep or asyncio.sleep
        self.base_url = base_url or PROVIDERS[provider]["base_url"]
        self.name = f"{provider}-api"

    @property
    def key_env(self) -> str:
        return PROVIDERS[self.provider]["key_env"]

    def key_present(self) -> bool:
        return bool(os.environ.get(self.key_env))

    # -- tools -----------------------------------------------------------------------
    def _file_tool(self, name: str, arguments: dict, project: Path, scripts: Path, env: dict,
                   deadline: float) -> tuple[str, str, int | None]:
        """Run one built-in tool. Returns (text for the model, status, exit code)."""
        if name == "list_files":
            base = project_path(project, arguments.get("path"))
            if not base.is_dir():
                return "not a directory", "failed", None
            entries = sorted(path.relative_to(project).as_posix() for path in base.rglob("*") if path.is_file())
            return "\n".join(entries[:500]) or "(empty)", "completed", None
        if name == "read_file":
            target = project_path(project, arguments.get("path"))
            if not target.is_file():
                return "no such file", "failed", None
            data = target.read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return "binary file; open it with run_python", "failed", None
            return text[:READ_LIMIT], "completed", None
        if name == "write_file":
            target = project_path(project, arguments.get("path"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(arguments.get("content", "")), encoding="utf-8")
            return "written", "completed", None
        if name == "run_python":
            scripts.mkdir(parents=True, exist_ok=True)
            script = scripts / f"step-{len(list(scripts.iterdir())) + 1:03d}.py"
            script.write_text(str(arguments.get("code", "")), encoding="utf-8")
            python = shutil.which("python", path=env["PATH"])
            if not python:
                return "python is not available", "failed", None
            budget = max(1.0, min(PYTHON_TIMEOUT, deadline - time.monotonic()))
            code, lines, stderr, timed_out = driver.run_contained([python, str(script)], project, env, budget)
            stdout = "".join(line for _, line in lines)
            if timed_out:
                return f"timed out after {budget:.0f} s", "failed", None
            text = f"exit code {code}\n--- stdout ---\n{stdout[-OUTPUT_LIMIT:]}\n--- stderr ---\n{stderr[-OUTPUT_LIMIT:]}"
            return text, "completed" if code == 0 else "failed", code
        return f"unknown tool {name}", "failed", None

    # -- loop ------------------------------------------------------------------------
    def run(self, request: AgentRequest) -> AgentResult:
        try:
            return asyncio.run(self._run(request))
        except Exception as error:  # an unexpected local failure ends the run, labelled, never raised
            return AgentResult(status="failed", turn={"status": "error", "reason": f"adapter error ({type(error).__name__})",
                                                      "error_types": [], "error_items": 0})

    async def _run(self, request: AgentRequest) -> AgentResult:
        if request.condition != WITH:
            return await self._loop(request, None)
        from mcp import Client, StdioServerParameters

        entry = json.loads((request.project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["terraproof"]
        params = StdioServerParameters(command=entry["command"], args=entry.get("args", []), cwd=str(request.project),
                                       env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        async with Client(params, raise_exceptions=False, read_timeout_seconds=PYTHON_TIMEOUT) as client:
            return await self._loop(request, client)

    async def _loop(self, request: AgentRequest, mcp_client) -> AgentResult:
        project = request.project
        scripts = project.parent / "agent-scripts"  # neutral name, outside the deliverables
        env = driver.host_env(request.condition, self.agent_python_without)
        seeded = driver._seeded(request.task_id)
        deadline = time.monotonic() + request.timeout_seconds
        per_run_usd = request.max_usd

        tools = list(FILE_TOOLS)
        mcp_names = {}
        if mcp_client is not None:
            for tool in (await mcp_client.list_tools()).tools:
                exposed = f"terraproof_{tool.name}"
                mcp_names[exposed] = tool.name
                tools.append({"type": "function", "function": {
                    "name": exposed, "description": tool.description or tool.name,
                    "parameters": tool.input_schema or {"type": "object", "properties": {}}}})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": driver.PROMPT}]
        calls: list[dict] = []
        labels: set[str] = set()
        incidental: set[str] = set()
        skill_reads = 0
        model_calls = input_tokens = output_tokens = retries = tool_retries = 0
        error_types: list[str] = []
        status, reason = "aborted", "loop ended without a final answer"

        while True:
            cost = self.limits.cost(input_tokens, output_tokens)
            if model_calls >= self.limits.max_model_calls:
                status, reason = "error", "model call cap reached"
                break
            if input_tokens + output_tokens >= self.limits.max_tokens:
                status, reason = "error", "token cap reached"
                break
            if per_run_usd is not None and cost >= per_run_usd:
                status, reason = "error", "per-run budget reached"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status, reason = "timeout", "per-run timeout"
                break
            key = os.environ.get(self.key_env)
            if not key:
                status, reason = "error", f"{self.key_env} is not set"
                break
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            # Spend is checked before each call, so one call can overshoot a cap by at most its own cost;
            # the completion cap bounds that.
            payload = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                       "temperature": 0, "max_tokens": MAX_COMPLETION_TOKENS}
            model_calls += 1  # every attempt counts, including rate-limited ones
            try:
                response = await asyncio.to_thread(self.transport, f"{self.base_url}/chat/completions", headers,
                                                   payload, min(remaining, 300.0))
            except ApiError as error:
                if error.error_type:
                    error_types.append(error.error_type)
                if error.status == 429 and retries < self.limits.rate_limit_retries:
                    retries += 1
                    wait = error.retry_after if error.retry_after is not None else 2.0 ** retries
                    wait = min(wait, self.limits.max_retry_wait)
                    if time.monotonic() + wait >= deadline:
                        status, reason = "error", f"{error}; retry wait exceeds the per-run timeout"
                        break
                    await self.sleep(wait)
                    continue
                if error.status == 400 and error.error_type == "tool_use_failed" and tool_retries < TOOL_USE_RETRIES:
                    tool_retries += 1
                    continue
                exhausted = {429: "; rate-limit retries exhausted"}.get(error.status, "")
                if error.error_type == "tool_use_failed":
                    exhausted = "; tool-use retries exhausted"
                status, reason = "error", str(error) + exhausted
                break
            finally:
                del key, headers
            usage = response.get("usage") or {}
            input_tokens += int(usage.get("prompt_tokens") or 0)
            output_tokens += int(usage.get("completion_tokens") or 0)
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            if choice.get("finish_reason") == "content_filter" or message.get("refusal"):
                status, reason = "refused", "model refused or content filtered"
                break
            if not tool_calls:
                status, reason = "completed", "ok" if calls else "no tool calls"
                break
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
            for call in tool_calls:
                function = call.get("function") or {}
                name = str(function.get("name", ""))
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError
                except ValueError:
                    arguments = None
                text = name + " " + json.dumps(arguments, default=str)
                labels |= driver.contamination_labels(text, request.condition, seeded)
                incidental |= driver.incidental_labels(text, request.condition)
                started = time.monotonic()
                exit_code = None
                if name in mcp_names:
                    tool, category = f"terraproof.{mcp_names[name]}", f"mcp:{mcp_names[name]}"
                    skill_reads += mcp_names[name] == "load_section"
                elif name in CATEGORIES:
                    tool, category = name, CATEGORIES[name]
                    skill_reads += name == "read_file" and driver._is_skill_read(str((arguments or {}).get("path", "")))
                else:
                    tool, category = "other", "other"
                if arguments is None:
                    reply, outcome = "arguments were not a JSON object", "failed"
                elif name in mcp_names:
                    result = await mcp_client.call_tool(mcp_names[name], arguments)
                    reply = "\n".join(getattr(part, "text", "") for part in result.content)[:READ_LIMIT]
                    outcome = "failed" if result.is_error else "completed"
                else:
                    try:
                        reply, outcome, exit_code = await asyncio.to_thread(
                            self._file_tool, name, arguments, project, scripts, env, deadline)
                    except (ValueError, OSError) as error:
                        reply, outcome = str(error) if isinstance(error, ValueError) else type(error).__name__, "failed"
                calls.append({"tool": tool, "category": category, "status": outcome, "exit_code": exit_code,
                              "duration_ms": driver._duration_ms(started, time.monotonic())})
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": reply})

        cost = round(self.limits.cost(input_tokens, output_tokens), 6)
        return AgentResult(
            status={"completed": "completed", "timeout": "timeout"}.get(status, "failed"),
            cost_usd=cost, tool_calls=len(calls),
            terraproof_tool_calls=sum(1 for c in calls if c["tool"].startswith("terraproof.")),
            skill_reads=skill_reads, input_tokens=input_tokens, output_tokens=output_tokens,
            contamination=sorted(labels), diagnostics=sorted(incidental), calls=calls,
            turn={"status": status, "reason": reason, "error_types": sorted(set(error_types)),
                  "error_items": len(error_types), "model_calls": model_calls, "rate_limit_retries": retries,
                  "tool_use_retries": tool_retries})

    def preflight(self, request: AgentRequest) -> dict:
        """No-model checks: the key variable is set, Python/IO work, and the isolation or MCP setup holds."""
        task = lift_task(request.task_id)
        script = request.project.parent / "preflight_probe.py"
        script.write_text(driver.PREFLIGHT_SCRIPT.format(name=task.inputs[0]), encoding="utf-8")
        env = driver.host_env(request.condition, self.agent_python_without)
        python = shutil.which("python", path=env["PATH"])
        stdout = ""
        if python:
            import subprocess

            stdout = subprocess.run([python, str(script)], cwd=request.project, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=120, check=False).stdout
        checks = {check.replace("sandbox_", "unsandboxed_"): marker in stdout
                  for check, marker in driver.PREFLIGHT_MARKERS if check != "sandbox_shell"}
        checks["api_key_set"] = self.key_present()
        if request.condition != WITH:
            checks.update(driver.without_isolation_checks(request.project, self.agent_python_without, env))
        else:
            entry = json.loads((request.project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["terraproof"]
            checks["mcp_tools_served"] = driver.mcp_tools_served(entry["command"], entry.get("args", []),
                                                                 request.project)
        return checks
