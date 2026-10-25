"""A small tool-calling agent for OpenAI-compatible chat APIs (OpenAI, Groq) in the lift harness.

Claude Code and Codex are complete agents; a chat API is not. This adapter supplies the
loop and a minimal tool set, so a plain model can work on a lift task the same way:

- `list_files`, `read_file`, `write_file`: confined to the run project (no absolute paths,
  no `..`, nothing outside it);
- `run_python`: one script per call, run with the condition's interpreter (the dependency-only
  Python in "without"), in the project directory, with a timeout and process-tree cleanup.
  This is not a sandbox: the script itself can reach anything the user can;
- in "with" only, Terraproof's six MCP tools, served by the installer-registered server.

Local limits per run: model calls, reserved/reported tokens and USD at user-supplied
prices. Conservative request reservations and post-response checks stop further work;
these are not provider-side invoice caps or a guarantee of the provider's token accounting.
The API key is read from the provider's environment variable only when a request is sent; it is never stored, logged or
reported. Error reports carry status codes only, never response bodies.

Like the other hosts, only fixed labels and numbers leave a run: per call a tool label,
category, status, exit code and duration. Prompts, model text and tool arguments are not kept.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import agent_lift as driver
from output_verification import VerificationPlan, RequiredVerification
from terraproof.evals.lift import WITH, Adapter, AgentRequest, AgentResult, lift_task

PROVIDERS = {
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "default_model": "gpt-4o"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "default_model": None},
}
SYSTEM_PROMPT = ("You are working in a project directory on a geospatial task. Use the tools to inspect the "
                 "files, compute with Python and write the required outputs. Before finishing, verify the "
                 "saved outputs against the task and source data using the available tools: check values, "
                 "valid-data masks, grid and metadata. Correct problems and verify again after changes; "
                 "report any unresolved or unverified requirements. When you are done, reply with a "
                 "short summary and no tool call.")
MAX_COMPLETION_REVIEWS = 2  # further final answers fail if observed output checks remain unresolved
COMPLETION_REVIEW = (
    "Output verification still has unresolved failures. Review the run_checks results already in context, "
    "correct the declared outputs, and rerun the failed checks with the same sources and options after "
    "the last write. A warning, not-run result, inspection or unrelated passing check cannot resolve a "
    "failed requirement. If you cannot resolve it within the remaining limits, report the blocker; "
    "this run will remain unresolved."
)
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
    """Local admission limits; prices are supplied USD per million tokens."""

    usd_per_million_input: float
    usd_per_million_output: float
    max_model_calls: int = 40
    max_tokens: int = 300_000
    rate_limit_retries: int = RATE_LIMIT_RETRIES
    max_retry_wait: float = MAX_RETRY_WAIT

    def __post_init__(self):
        for name in ("usd_per_million_input", "usd_per_million_output", "max_retry_wait"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("max_model_calls", "max_tokens", "rate_limit_retries"):
            value = getattr(self, name)
            if type(value) is not int or value < (0 if name == "rate_limit_retries" else 1):
                raise ValueError(f"{name} must be a valid integer limit")

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.usd_per_million_input + output_tokens * self.usd_per_million_output) / 1e6


def prompt_reservation(messages: list, tools: list) -> int:
    """Conservative UTF-8 byte allowance plus framing; not a provider tokenizer.

    Includes the accumulated conversation and tool schemas, never just the last turn.
    Providers can add hidden tokens, so returned usage must still be verified.
    """
    body = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)
    return len(body.encode("utf-8")) + 1024 + 64 * (len(messages) + len(tools))


def valid_usage(usage) -> bool:
    if not isinstance(usage, dict):
        return False
    if any(type(usage.get(name)) is not int or usage[name] < 0
           for name in ("prompt_tokens", "completion_tokens")):
        return False
    return ("total_tokens" not in usage or
            (type(usage["total_tokens"]) is int and
             usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]))


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


def server_instructions(client) -> str:
    """Read bounded instructions from the configured server, never from project files."""
    text = client.instructions
    if not isinstance(text, str) or not text.strip() or len(text) > READ_LIMIT:
        raise ValueError("missing or invalid Terraproof MCP instructions")
    # Refuse malformed Unicode before it reaches request serialization or the provider.
    text.encode("utf-8")
    return text


def mcp_parameters(project: Path):
    from mcp import StdioServerParameters

    entry = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["terraproof"]
    return StdioServerParameters(command=entry["command"], args=entry.get("args", []), cwd=str(project),
                                 env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})


async def mcp_preflight(project: Path, verification=None) -> dict:
    """Probe tools and instructions on one connection; no model request is made."""
    from mcp import Client

    checks = {"mcp_tools_served": False, "mcp_instructions_available": False}
    if verification is not None:
        checks["required_verification_schema"] = False
    try:
        async with Client(mcp_parameters(project), raise_exceptions=False,
                          read_timeout_seconds=PYTHON_TIMEOUT) as client:
            tools = (await client.list_tools()).tools
            checks["mcp_tools_served"] = sorted(t.name for t in tools) == sorted(driver.TOOLS)
            if verification is not None:
                checker = next((tool for tool in tools if tool.name == "run_checks"), None)
                checks["required_verification_schema"] = checker is not None and verification.validate_schema(checker.input_schema)
            server_instructions(client)
            checks["mcp_instructions_available"] = True
    except Exception:
        pass  # fixed booleans only; no server output or configuration in reports
    return checks


class _OutputReview:
    """Track observed failed checks on declared deliverables, not on audit inputs.

    Only an explicit pass of that check in the same context resolves a failure.
    Writes conservatively invalidate prior resolutions, even after partial failure.
    This is a completion guard, not an independent grader or filesystem sandbox.
    """

    def __init__(self, project: Path, names):
        self.project = project
        self.outputs = {(project / "outputs" / name).resolve() for name in names}
        self.records: dict[tuple, bool] = {}

    def _path(self, value):
        if not isinstance(value, str) or "\0" in value:
            return None
        path = Path(value)
        try:
            return (path if path.is_absolute() else self.project / path).resolve()
        except (OSError, ValueError, RuntimeError):
            return None

    @property
    def unresolved(self) -> int:
        return sum(not resolved for resolved in self.records.values())

    def invalidate(self):
        for key in self.records:
            self.records[key] = False

    def observe(self, arguments, response):
        paths = arguments.get("paths", [])
        if not isinstance(paths, list):
            return
        targets = {self._path(path) for path in paths} & self.outputs
        if not targets:
            return  # a legitimate failed audit of originals must not block completion
        context = json.dumps({key: value for key, value in arguments.items() if key not in ("paths", "lang")},
                             sort_keys=True)
        group = tuple(sorted(str(path) for path in targets))
        payload = getattr(response, "structured_content", None)
        report = payload.get("report") if isinstance(payload, dict) else None
        checks = report.get("checks") if isinstance(report, dict) else None
        valid = (not response.is_error and isinstance(report, dict)
                 and report.get("schema_version") == "terraproof.evidence/0.1"
                 and isinstance(checks, list) and bool(checks)
                 and all(isinstance(check, dict) and isinstance(check.get("id"), str)
                         and re.fullmatch(r"[a-z_]+\.[a-z_]+", check["id"])
                         and check.get("status") in ("pass", "fail", "warn", "not-run")
                         and isinstance(check.get("evidence"), dict) for check in checks))
        for target in targets:
            key = (target, "report.valid", context, group)
            if not valid or key in self.records:
                self.records[key] = bool(valid)
        if not valid:
            return
        for check in checks:
            evidence = check["evidence"]
            references = [evidence.get("input"), evidence.get("output")]
            if isinstance(evidence.get("inputs"), list):
                references.extend(evidence["inputs"])
            referenced = {path for value in references if (path := self._path(value)) is not None}
            affected = targets & referenced if referenced else targets
            scope = tuple(sorted(str(path) for path in referenced)) if referenced else group
            for target in affected:
                key = (target, check["id"], context, scope)
                if check["status"] == "fail" or key in self.records:
                    self.records[key] = check["status"] == "pass"


class ApiAgentAdapter(Adapter):
    """Runs one lift task with an OpenAI-compatible chat model."""

    name = "api-agent"
    model_calls = True
    usd_capped = True

    def __init__(self, provider: str, model: str, limits: ApiLimits, agent_python_without: str | None = None,
                 transport=http_transport, base_url: str | None = None, sleep=None, verification_plan=None):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        if not model:
            raise ValueError("a model name is required")
        self.provider = provider
        self.model = model
        self.limits = limits
        self.agent_python_without = agent_python_without
        self.verification_plan = (verification_plan if isinstance(verification_plan, VerificationPlan)
                                  else VerificationPlan(verification_plan) if verification_plan is not None else None)
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
            result = asyncio.run(self._run(request))
        except Exception as error:  # an unexpected local failure ends the run, labelled, never raised
            result = AgentResult(status="failed", turn={"status": "error", "reason": f"adapter error ({type(error).__name__})",
                                                      "error_types": [], "error_items": 0})
        result.turn.setdefault("verification_status", "unverified")
        return result

    async def _run(self, request: AgentRequest) -> AgentResult:
        if request.condition != WITH:
            return await self._loop(request, None)
        from mcp import Client

        async with Client(mcp_parameters(request.project), raise_exceptions=False,
                          read_timeout_seconds=PYTHON_TIMEOUT) as client:
            return await self._loop(request, client)

    async def _loop(self, request: AgentRequest, mcp_client) -> AgentResult:
        project = request.project
        scripts = project.parent / "agent-scripts"  # neutral name, outside the deliverables
        env = driver.host_env(request.condition, self.agent_python_without)
        seeded = driver._seeded(request.task_id)
        deadline = time.monotonic() + request.timeout_seconds
        per_run_usd = request.max_usd
        if per_run_usd is None or not math.isfinite(per_run_usd) or per_run_usd <= 0:
            return AgentResult(status="failed", turn={"status": "error", "reason": "a finite positive USD budget is required"})

        required = None
        if self.verification_plan is not None and request.condition == WITH:
            try:
                names = lift_task(request.task_id).deliverable_names
                required = RequiredVerification(project, self.verification_plan.groups(request.task_id, names), names, deadline)
            except ValueError:
                return AgentResult(status="failed", turn={"status": "error", "reason": "invalid required verification coverage",
                                                          "model_calls": 0, "verification_status": "unverified"})
            if required.initial_inputs is None:
                return AgentResult(status="failed", turn={"status": "error", "reason": "unsafe required verification data",
                                                          "model_calls": 0, "verification_status": "unverified"})
            if mcp_client is None:
                return AgentResult(status="failed", turn={"status": "error", "reason": "required MCP verification unavailable",
                                                          "model_calls": 0, "verification_status": "unverified"})
        tools = list(FILE_TOOLS)
        mcp_names = {}
        instructions = None
        if mcp_client is not None:
            try:
                instructions = server_instructions(mcp_client)
            except (ValueError, AttributeError):
                return AgentResult(status="failed", turn={"status": "error",
                    "reason": "missing or invalid Terraproof MCP instructions", "model_calls": 0,
                    "mcp_instructions_delivered": False})
            served = (await mcp_client.list_tools()).tools
            if required is not None:
                checker = next((tool for tool in served if tool.name == "run_checks"), None)
                if checker is None or not required.validate_schema(checker.input_schema):
                    return AgentResult(status="failed", turn={"status": "error", "reason": "invalid required verification arguments",
                                                              "model_calls": 0, "verification_status": "unverified"})
            for tool in served:
                exposed = f"terraproof_{tool.name}"
                mcp_names[exposed] = tool.name
                tools.append({"type": "function", "function": {
                    "name": exposed, "description": tool.description or tool.name,
                    "parameters": tool.input_schema or {"type": "object", "properties": {}}}})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if instructions is not None:
            messages.append({"role": "system", "content": "Terraproof tool guidance from the configured MCP server:\n"
                             + instructions})
        if required is not None:
            messages.append({"role": "system", "content": required.prompt()})
        messages.append({"role": "user", "content": driver.PROMPT})
        calls: list[dict] = []
        labels: set[str] = set()
        incidental: set[str] = set()
        skill_reads = 0
        output_review = _OutputReview(project, lift_task(request.task_id).deliverable_names)
        completion_reviews = 0
        model_calls = input_tokens = output_tokens = retries = tool_retries = 0
        error_types: list[str] = []
        unreported_cost = 0.0
        unreported_tokens = 0
        status, reason = "aborted", "loop ended without a final answer"

        while True:
            cost = self.limits.cost(input_tokens, output_tokens) + unreported_cost
            if model_calls >= self.limits.max_model_calls:
                status, reason = "error", "model call cap reached"
                break
            if input_tokens + output_tokens + unreported_tokens >= self.limits.max_tokens:
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
            prompt_tokens_reserved = prompt_reservation(messages, tools)
            completion_limit = min(MAX_COMPLETION_TOKENS,
                                   self.limits.max_tokens - input_tokens - output_tokens - unreported_tokens
                                   - prompt_tokens_reserved)
            if completion_limit < 1:
                status, reason = "error", "insufficient token allowance for next request"
                break
            prompt_cost = self.limits.cost(prompt_tokens_reserved, 0)
            affordable_output = math.floor((per_run_usd - cost - prompt_cost) * 1e6
                                           / self.limits.usd_per_million_output)
            completion_limit = min(completion_limit, affordable_output)
            if completion_limit < 1:
                status, reason = "error", "insufficient budget for next request"
                break
            reserved_cost = self.limits.cost(prompt_tokens_reserved, completion_limit)
            payload = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                       "temperature": 0, "max_tokens": completion_limit}
            model_calls += 1  # every attempt counts, including rate-limited ones
            try:
                response = await asyncio.to_thread(self.transport, f"{self.base_url}/chat/completions", headers,
                                                   payload, min(remaining, 300.0))
            except ApiError as error:
                # Error responses do not establish that a generation was free. Reserve
                # the whole admitted request, including retries, rather than report $0.
                unreported_cost += reserved_cost
                unreported_tokens += prompt_tokens_reserved + completion_limit
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
            except Exception as error:
                unreported_cost += reserved_cost
                unreported_tokens += prompt_tokens_reserved + completion_limit
                status, reason = "error", f"transport error ({type(error).__name__})"
                break
            finally:
                del key, headers
            usage = response.get("usage") if isinstance(response, dict) else None
            if not valid_usage(usage):
                unreported_cost += reserved_cost
                unreported_tokens += prompt_tokens_reserved + completion_limit
                status, reason = "error", "missing or invalid usage; request reservation retained"
                break
            input_tokens += usage["prompt_tokens"]
            output_tokens += usage["completion_tokens"]
            if input_tokens + output_tokens + unreported_tokens > self.limits.max_tokens:
                status, reason = "error", "token cap exceeded"
                break
            if self.limits.cost(input_tokens, output_tokens) + unreported_cost > per_run_usd:
                status, reason = "error", "per-run budget exceeded"
                break
            if usage["prompt_tokens"] > prompt_tokens_reserved or usage["completion_tokens"] > completion_limit:
                status, reason = "error", "provider usage exceeded request reservation"
                break
            if time.monotonic() >= deadline:
                status, reason = "timeout", "per-run timeout"
                break
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            if choice.get("finish_reason") == "content_filter" or message.get("refusal"):
                status, reason = "refused", "model refused or content filtered"
                break
            if not tool_calls:
                verification_state = required.summary()["status"] if required is not None else None
                if output_review.unresolved or (verification_state is not None and verification_state != "verified"):
                    if completion_reviews >= MAX_COMPLETION_REVIEWS:
                        reason = ("required output verification unverified" if verification_state == "unverified" else
                                  "required output verification needs review" if verification_state == "review-required" else
                                  "output verification unresolved")
                        status = "error"
                        break
                    completion_reviews += 1
                    messages.append({"role": "assistant", "content": message.get("content")})
                    feedback = ("Required output verification is missing, stale, or needs review. Run every declared "
                                "check on the saved outputs using the policy arguments after all data writes. "
                                "Missing/not-run/stale checks are unverified; fail/warn requires review. "
                                "Resolve requirements or report the blocker within the remaining session limits."
                                if required is not None else COMPLETION_REVIEW)
                    messages.append({"role": "user", "content": feedback})
                    continue  # the normal request, time, token and USD admission checks still apply
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
                if name in ("run_python", "write_file") and arguments is not None:
                    output_review.invalidate()  # even a failed write/script may have changed artifacts
                if arguments is None:
                    reply, outcome = "arguments were not a JSON object", "failed"
                elif name in mcp_names:
                    before = required.snapshot() if required is not None and mcp_names[name] == "run_checks" else None
                    result = await mcp_client.call_tool(mcp_names[name], arguments)
                    if mcp_names[name] == "run_checks":
                        output_review.observe(arguments, result)
                        if required is not None:
                            required.observe(arguments, result, before)
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

        cost = round(self.limits.cost(input_tokens, output_tokens) + unreported_cost, 6)
        verification = required.summary() if required is not None else {"status": "unverified"}
        if verification["status"] == "verified" and output_review.unresolved:
            verification["status"] = "review-required"
        if required is not None and status == "completed" and verification["status"] != "verified":
            status, reason = "error", "required output verification changed before completion"
        return AgentResult(
            status={"completed": "completed", "timeout": "timeout"}.get(status, "failed"),
            cost_usd=cost, tool_calls=len(calls),
            terraproof_tool_calls=sum(1 for c in calls if c["tool"].startswith("terraproof.")),
            skill_reads=skill_reads, input_tokens=input_tokens, output_tokens=output_tokens,
            contamination=sorted(labels), diagnostics=sorted(incidental), calls=calls,
            turn={"status": status, "reason": reason, "error_types": sorted(set(error_types)),
                  "error_items": len(error_types), "model_calls": model_calls, "rate_limit_retries": retries,
                  "tool_use_retries": tool_retries,
                  "completion_review_prompts": completion_reviews,
                  "verification_status": verification["status"],
                  "required_verification": verification,
                  "verification_plan_sha256": self.verification_plan.sha256 if self.verification_plan is not None else None,
                  "verification_policy_applied": required is not None,
                  "output_review": ("unresolved" if output_review.unresolved else
                                    "resolved" if output_review.records else "no-failure-observed"),
                  "output_review_requirements": len(output_review.records),
                  "output_review_unresolved": output_review.unresolved,
                  "mcp_instructions_delivered": instructions is not None and model_calls > 0,
                  "mcp_instructions_chars": len(instructions) if instructions is not None else 0,
                  "mcp_instructions_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest()
                  if instructions is not None else None,
                  "unreported_tokens_reserved": unreported_tokens,
                  "unreported_usd_reserved": round(unreported_cost, 6),
                  "cost_basis": "reported-plus-reserved" if unreported_tokens else "reported",
                  "budget_enforcement": "local-reservation-not-provider-cap"})

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
            try:
                verification = None
                if self.verification_plan is not None:
                    try:
                        names = task.deliverable_names
                        verification = RequiredVerification(request.project, self.verification_plan.groups(request.task_id, names), names, time.monotonic() + PYTHON_TIMEOUT)
                        checks["required_verification_coverage"] = True
                        checks["required_verification_data"] = verification.initial_inputs is not None
                    except ValueError:
                        checks["required_verification_coverage"] = False
                checks.update(asyncio.run(asyncio.wait_for(mcp_preflight(request.project, verification), PYTHON_TIMEOUT)))
            except asyncio.TimeoutError:
                checks.update({"mcp_tools_served": False, "mcp_instructions_available": False})
                if self.verification_plan is not None:
                    checks["required_verification_schema"] = False
        return checks
