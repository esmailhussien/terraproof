#!/usr/bin/env python3
"""Independent CLI/official-SDK stdio release smoke; no model calls by default.

Fixtures and installer projects live only in a driver-owned temporary directory.
This is not the full eval, package, real-agent, or hosted OS/Python matrix gate.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["find_guidance", "inspect_dataset", "list_skills", "load_section", "preflight", "run_checks"]
REQUIRED = {
    "cli.help", "mcp.tools", "mcp.list_skills", "mcp.load_section", "parity.guidance",
    "parity.inspect", "parity.preflight", "evidence.0", "evidence.2", "evidence.3",
    "manifest.write", "manifest.verify", "manifest.required", "manifest.missing",
    "manifest.changed_bytes", "accuracy.numeric_zero", "output.arabic", "errors.transport",
    "install.claude", "install.codex",
}
LIMITATIONS = [
    "Synthetic local vector fixtures only; not exhaustive raster/optical/SAR or heldout evaluation.",
    "Installed editable Python checkout, not a built wheel or npm tarball smoke test.",
    "Only the reported actual platform/interpreter was executed; hosted CI matrix remains pending.",
    "SDK stdio and installer output do not prove real-agent tool use or authentication.",
    "No Linux container/package validation performed by this driver.",
]


class ValidationError(RuntimeError):
    pass


class Report:
    def __init__(self):
        versions = {}
        for name in ("terraproof", "mcp", "anyio", "numpy", "pyogrio", "pyproj", "rasterio", "shapely"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "not-installed"
        self.data = {
            "schema": "terraproof.release-validation/1", "status": "fail",
            "runtime": {"platform": platform.system(), "release": platform.release(),
                        "machine": platform.machine(), "python": platform.python_version(),
                        "executable": sys.executable, "versions": versions},
            "assertions": [], "limitations": list(LIMITATIONS),
            "agent_host": {"status": "not-requested", "model_called": False},
        }

    def check(self, name, condition, expected):
        passed = bool(condition)
        self.data["assertions"].append({"id": name, "status": "pass" if passed else "fail",
                                        "assertion": expected})
        if not passed:
            raise ValidationError(name)

    def finish(self):
        assertions = self.data["assertions"]
        names = [item["id"] for item in assertions]
        missing = sorted(REQUIRED - set(names))
        self.data["missing_assertions"] = missing
        host = self.data["agent_host"]["status"]
        passed = (not missing and len(names) == len(set(names))
                  and all(item["status"] == "pass" for item in assertions)
                  and "failure" not in self.data and host in {"not-requested", "pass"})
        self.data["status"] = "pass" if passed else "fail"
        return 0 if passed else 1

    def write(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2,
                                   allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def run(args, *, cwd=ROOT, timeout=45):
    """Never echo child output: error text/host streams may contain sensitive data."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="strict", timeout=timeout, check=False)


def cli(*args, code=0, module="terraproof", cwd=ROOT):
    result = run([sys.executable, "-m", module, *args], cwd=cwd)
    if result.returncode != code:
        raise ValidationError(f"{module} {args[0]}: expected exit {code}, got {result.returncode}")
    return result


def document(result):
    return json.loads(result.stdout)


def fixtures(work):
    polygon = {"type": "Polygon", "coordinates": [[[500000, 5000000], [500010, 5000000],
                [500010, 5000010], [500000, 5000010], [500000, 5000000]]]}
    paths = {}
    for name, geometries in (("clean", [polygon]), ("review", [polygon, None])):
        path = work / f"{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "crs": {
            "type": "name", "properties": {"name": "EPSG:32636"}}, "features": [
            {"type": "Feature", "properties": {"name": "اختبار"}, "geometry": geometry}
            for geometry in geometries]}), encoding="utf-8")
        paths[name] = str(path)
    for name, value in (("plan", {"operation": "area"}),
                        ("samples", [{"map_class": c, "ref_class": c} for c in (0, 1) for _ in range(4)]),
                        ("areas", {"0": 100.0, "1": 50.0})):
        path = work / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = str(path)
    return paths


def check_status(payload, check_id):
    return next((c["status"] for c in payload["checks"] if c["id"] == check_id), None)


def installers(report, work):
    import tomllib

    for agent in ("claude", "codex"):
        project = work / agent
        project.mkdir()
        if agent == "claude":
            config = project / ".mcp.json"
            config.write_text('{"keep": true, "mcpServers": {"other": {"command": "untouched"}}}', encoding="utf-8")
        else:
            (project / "AGENTS.md").write_text("User instructions\n", encoding="utf-8")
            config = project / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text('[user_owned]\nkeep = true\n', encoding="utf-8")
        args = ["--agent", agent, "--skills", "gdal", "--target", str(project), "--with-mcp"]
        before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        cli(*args, "--dry-run", module="terraproof.install", cwd=project)
        unchanged = before == {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        cli(*args, module="terraproof.install", cwd=project)
        installed = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        cli(*args, module="terraproof.install", cwd=project)
        stable = installed == {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        if agent == "claude":
            data = json.loads(config.read_text(encoding="utf-8"))
            entry = data["mcpServers"]["terraproof"]
            preserved = data["keep"] and data["mcpServers"]["other"]["command"] == "untouched"
            skill = project / ".claude" / "skills" / "gdal" / "SKILL.md"
        else:
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            entry = data["mcp_servers"]["terraproof"]
            preserved = data["user_owned"]["keep"] and (project / "AGENTS.md").read_text(encoding="utf-8").startswith("User instructions\n")
            skill = project / ".agents" / "skills" / "gdal" / "SKILL.md"
        report.check(f"install.{agent}", unchanged and stable and preserved and skill.is_file()
                     and bool(skill.read_text(encoding="utf-8"))
                     and entry["command"] == sys.executable and entry["args"] == ["-m", "terraproof.mcp"],
                     "isolated native config, current interpreter, preserved user content, dry-run and idempotent writes")


async def validate_stdio(report, work, paths, timeout):
    # Deliberately import only the installed official client, never the server object.
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "terraproof.mcp"],
                                   cwd=str(ROOT), env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    async with Client(params, raise_exceptions=False, read_timeout_seconds=timeout) as client:
        async def call(name, args=None, error=False):
            result = await client.call_tool(name, args or {})
            if bool(result.is_error) != error:
                raise ValidationError(f"MCP {name}: unexpected is_error")
            return result if error else result.structured_content

        tools = await client.list_tools()
        report.check("mcp.tools", sorted(t.name for t in tools.tools) == TOOLS,
                     "actual stdio child advertises exactly six tools")
        skills = await call("list_skills")
        report.check("mcp.list_skills", any(s["name"] == "gdal" and s["sections"] for s in skills["result"]),
                     "registry has gdal with loadable sections")
        section = await call("load_section", {"skill": "gdal", "section_id": "quick-reference"})
        report.check("mcp.load_section", section["source"] == "SKILL.md#quick-reference" and "gdalinfo" in section["text"],
                     "real skill section returned over stdio")
        task = "Compute polygon area with a projected CRS"
        guidance = await call("find_guidance", {"task": task, "data_paths": [paths["clean"]]})
        report.check("parity.guidance", bool(guidance["skills"]) and guidance == document(cli("route", task, "--data", paths["clean"])),
                     "non-semantic CLI and stdio guidance match exactly")
        inspected = await call("inspect_dataset", {"path": paths["clean"]})
        report.check("parity.inspect", inspected == document(cli("inspect", paths["clean"]))
                     and inspected["feature_count"] == 1 and inspected["crs"]["epsg"] == 32636,
                     "CLI/stdio profiles match, one projected feature")
        payload = await call("preflight", {"paths": [paths["clean"]], "plan": paths["plan"]})
        report.check("parity.preflight", payload["report"] == document(cli("preflight", paths["clean"], "--plan", paths["plan"]))
                     and payload["exit_code"] == 0, "CLI/stdio preflight reports match with exit 0")
        for name, code, grade, extra in (("clean", 0, "checks-passed", []),
                                         ("review", 2, "review-required", []),
                                         ("clean", 3, "advisory-only", ["--require-provenance"])):
            options = {"paths": [paths[name]], "operation": "area"}
            if extra:
                options["require_provenance"] = True
            payload = await call("run_checks", options)
            evidence = document(cli("check", paths[name], "--operation", "area", *extra, code=code))
            report.data["runtime"]["evidence_tool_versions"] = evidence["tool_versions"]
            report.check(f"evidence.{code}", payload["report"] == evidence and payload["exit_code"] == code
                         and payload["grade"] == evidence["grade"] == grade and bool(evidence["checks"]),
                         f"CLI/stdio exact evidence parity, exit {code}, {grade}")
        report.check("manifest.missing", check_status(evidence, "provenance.reproducible") == "fail",
                     "require-provenance without manifest fails")
        manifest = str(work / "run.manifest.json")
        cli("manifest", "write", "--inputs", paths["clean"], "--outputs", paths["clean"], "--out", manifest)
        report.check("manifest.write", Path(manifest).is_file() and bool(json.loads(Path(manifest).read_text(encoding="utf-8"))),
                     "CLI writes a nonempty manifest")
        verified = document(cli("manifest", "verify", manifest, "--format", "json"))
        report.check("manifest.verify", verified["status"] == "pass", "CLI verifies original bytes")
        options = {"paths": [paths["clean"]], "operation": "area", "manifest": manifest, "require_provenance": True}
        payload = await call("run_checks", options)
        evidence = document(cli("check", paths["clean"], "--operation", "area", "--manifest", manifest, "--require-provenance"))
        report.check("manifest.required", payload["report"] == evidence and payload["exit_code"] == 0
                     and check_status(evidence, "provenance.reproducible") == "pass",
                     "verified provenance permits a clean exit in both transports")
        samples, areas = paths["samples"], paths["areas"]
        evidence = document(cli("check", paths["clean"], "--accuracy-samples", samples,
                                "--class-areas", areas, "--min-per-class", "4", "--estimates-requested"))
        payload = await call("run_checks", {"paths": [paths["clean"]], "accuracy_samples": samples,
                             "class_areas": areas, "min_per_class": 4, "estimates_requested": True})
        estimate = next(c for c in evidence["checks"] if c["id"] == "accuracy.estimates")
        report.check("accuracy.numeric_zero", payload["report"] == evidence and payload["exit_code"] == 0
                     and check_status(evidence, "accuracy.sample_design") == "pass" and estimate["status"] == "pass"
                     and estimate["evidence"]["overall_accuracy"] == 1.0
                     and estimate["evidence"]["area_estimated"]["0"] == 100.0,
                     "numeric class 0 retained; perfect accuracy and class-0 area 100; CLI/stdio parity")
        arabic = cli("check", paths["clean"], "--format", "md", "--lang", "ar").stdout
        payload = await call("run_checks", {"paths": [paths["clean"]], "lang": "ar"})
        report.check("output.arabic", arabic == payload["markdown"] and arabic.startswith("# تقرير أدلة Terraproof"),
                     "UTF-8 Arabic Markdown matches across child transports")
        errors = []
        for tool, args in (("inspect_dataset", {"path": str(work / "missing.geojson")}),
                           ("run_checks", {"paths": []}),
                           ("run_checks", {"paths": [paths["clean"]], "lang": "fr"}),
                           ("load_section", {"skill": "gdal", "section_id": "../AGENTS.md"})):
            result = await call(tool, args, error=True)
            errors.append(bool(result.content) and "Traceback" not in " ".join(getattr(c, "text", "") for c in result.content))
        bad_cli = cli("inspect", str(work / "missing.geojson"), code=1)
        recovered = await call("inspect_dataset", {"path": paths["clean"]})
        report.check("errors.transport", all(errors) and "error:" in bad_cli.stderr and "Traceback" not in bad_cli.stderr
                     and recovered == inspected, "tool errors stay protocol errors; CLI exit 1; same stdio session recovers")
        # Change bytes while keeping valid, inspectable data; rejection must be provenance, not parse failure.
        clean = Path(paths["clean"])
        clean.write_bytes(clean.read_bytes() + b"\n")
        verified = document(cli("manifest", "verify", manifest, "--format", "json", code=3))
        payload = await call("run_checks", options)
        evidence = document(cli("check", paths["clean"], "--operation", "area", "--manifest", manifest,
                                "--require-provenance", code=3))
        report.check("manifest.changed_bytes", verified["status"] == "fail" and bool(verified["evidence"]["changed"])
                     and payload["report"] == evidence and payload["exit_code"] == 3
                     and check_status(evidence, "provenance.reproducible") == "fail",
                     "changed but valid dataset bytes rejected by manifest verify and CLI/stdio checks")


def host_trace(events):
    """Require successful tool-result evidence, not a model's prose assertion."""
    calls, successful = {}, set()
    for event in events:
        message = event.get("message", {})
        for block in message.get("content", []) if isinstance(message, dict) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block.get("id")] = block.get("name")
            elif block.get("type") == "tool_result" and not block.get("is_error", False):
                successful.add(block.get("tool_use_id"))
    names = sorted({calls[key] for key in successful if key in calls})
    expected = {"mcp__terraproof__list_skills", "mcp__terraproof__inspect_dataset"}
    allowed = {f"mcp__terraproof__{name}" for name in TOOLS}
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    passed = (expected <= set(names) and set(calls.values()) <= allowed and bool(result)
              and not result.get("is_error", True) and result.get("subtype") == "success")
    return passed, names


def agent_host(report, work, paths):
    """Explicit opt-in: one default-model invocation, budget $1, no built-in tools."""
    host = report.data["agent_host"] = {"name": "claude", "status": "unavailable", "model_called": False}
    executable = shutil.which("claude")
    if not executable:
        host["reason"] = "claude executable not found"
        return
    version = run([executable, "--version"], cwd=work)
    if version.returncode != 0:
        host["reason"] = "claude --version failed"
        return
    host["version"] = version.stdout.strip()
    help_result = run([executable, "--help"], cwd=work)
    required = ["--restricted", "--strict-mcp-config", "--no-session-persistence", "--tools",
                "--allowedTools", "--max-budget-usd", "--permission-prompts", "--setting-sources"]
    if help_result.returncode or not all(flag in help_result.stdout for flag in required):
        host["reason"] = "installed host lacks required isolation/budget controls"
        return
    auth = run([executable, "auth", "status", "--json"], cwd=work)
    try:
        logged_in = json.loads(auth.stdout).get("loggedIn") is True
    except (ValueError, AttributeError):
        logged_in = False
    if auth.returncode or not logged_in:
        host["reason"] = "noninteractive claude auth status did not confirm loggedIn; no credentials logged"
        return
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        host["reason"] = "Windows shell wrapper cannot guarantee bounded model-process cleanup; native executable required"
        return
    config = work / "host.mcp.json"
    config.write_text(json.dumps({"mcpServers": {"terraproof": {"type": "stdio", "command": sys.executable,
                      "args": ["-m", "terraproof.mcp"], "env": {"PYTHONUTF8": "1"}}}}), encoding="utf-8")
    prompt = ("Use only the Terraproof MCP tools. Call list_skills and inspect_dataset on "
              + paths["clean"] + ". Briefly report the feature count. Do not edit files or run commands.")
    command = [executable, "--print", "--restricted", "--tools", "", "--allowedTools",
               ",".join(f"mcp__terraproof__{name}" for name in TOOLS), "--permission-mode", "dontAsk",
               "--permission-prompts", "none", "--strict-mcp-config", "--mcp-config", str(config),
               "--no-session-persistence", "--disable-slash-commands", "--no-chrome", "--setting-sources", "",
               "--settings", '{"disableAllHooks":true}', "--max-budget-usd", "1",
               "--output-format", "stream-json", "--verbose", prompt]
    host["model_called"] = True
    result = run(command, cwd=work, timeout=120)
    # Never persist raw auth/model streams, prompts, environment or provider metadata.
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    passed, names = host_trace(events)
    host.update(status="pass" if passed and result.returncode == 0 else "fail",
                successful_tools=names, exit_code=result.returncode)
    if host["status"] != "pass":
        host["reason"] = "host did not return successful permitted tool-result trace and final result"


# Supported controls are checked at runtime; never silently ignore an unknown flag.
# Config field reference: https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/config.schema.json
CODEX_DISABLED = (
    "shell_tool", "unified_exec", "unified_exec_tty", "hooks", "apps", "browser_use",
    "browser_use_external", "browser_use_full_cdp_access", "computer_use", "image_generation",
    "multi_agent", "multi_agent_v2", "workspace_dependencies", "code_mode",
    "plugins", "remote_plugin", "skill_search", "skill_mcp_dependency_install", "view_image",
    "shell_snapshot", "daemon_auto_start", "unbounded_connection_retries", "realtime_conversation",
    "goals", "tool_suggest", "tool_call_mcp_elicitation", "request_permissions_tool", "sleep_tool",
    "in_app_browser", "in_app_local_automation", "memories",
)
CODEX_TOOLS = ["list_skills", "inspect_dataset"]


def codex_executable():
    """Resolve only a native binary, including the inspected official npm layout.

    Never execute a shell/Node shim or search unrelated installations. Missing native
    payloads are unavailable, not an invitation to install/download anything.
    """
    executable = shutil.which("codex")
    if not executable:
        return None
    path = Path(executable).resolve()
    if os.name == "nt":
        if path.suffix.lower() == ".exe":
            return str(path)
        if path.suffix.lower() != ".cmd":
            return None
        wrapper = path.read_text(encoding="utf-8")
        if r'node_modules\@openai\codex\bin\codex.js' not in wrapper:
            return None
        architecture = {"amd64": "x64", "arm64": "arm64"}.get(platform.machine().lower())
        if not architecture:
            return None
        triple = "x86_64-pc-windows-msvc" if architecture == "x64" else "aarch64-pc-windows-msvc"
        package = path.parent / "node_modules" / "@openai" / "codex"
        candidates = [package / "node_modules" / "@openai" / f"codex-win32-{architecture}" / "vendor",
                      package.parent / f"codex-win32-{architecture}" / "vendor", package / "vendor"]
        for vendor in candidates:
            binary = vendor / triple / "bin" / "codex.exe"
            if binary.is_file():
                return str(binary.resolve())
        return None
    # Non-Windows optional support requires a native ELF/Mach-O executable already on PATH.
    with path.open("rb") as stream:
        magic = stream.read(4)
    return str(path) if magic in {b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"} else None


class WindowsHostJob:
    """Own a kill-on-close job; assign a suspended native child before it can run."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                        ("Flags", wintypes.DWORD), ("Minimum", ctypes.c_size_t), ("Maximum", ctypes.c_size_t),
                        ("Active", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", Counters), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t),
                        ("PeakJobMemory", ctypes.c_size_t)]

        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.native = ctypes.WinDLL("ntdll")
        self.native.NtResumeProcess.argtypes = [wintypes.HANDLE]
        self.native.NtResumeProcess.restype = ctypes.c_long
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ValidationError("cannot allocate Windows host process job")
        limits = Extended()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ValidationError("cannot enforce Windows host process-tree cleanup")

    def resume(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ValidationError("cannot contain suspended host process; model not started")
        if self.native.NtResumeProcess(int(process._handle)) != 0:
            raise ValidationError("cannot resume contained host process")

    def close(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_codex_model(command, work, started):
    """One invocation, no runner retries; kill the entire owned tree on every exit."""
    import signal

    job = WindowsHostJob() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(command, cwd=work, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="strict",
                                   creationflags=0x4 if job else 0,  # CREATE_SUSPENDED
                                   start_new_session=not bool(job))
        if job:
            job.resume(process)
        started()
        stdout, stderr = process.communicate(timeout=120)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
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
                process.kill()  # Includes a suspended child rejected before job assignment.
            process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()


def codex_command(executable, project, fixture):
    """Reviewable argv: no model/provider choice and only two read-only MCP tools."""
    command = [executable, "--no-daemon", "exec", "--ignore-user-config", "--ignore-rules",
               "--strict-config", "--ephemeral", "--sandbox", "read-only", "--json",
               "--skip-git-repo-check", "-C", str(project)]
    for feature in CODEX_DISABLED:
        command.extend(["--disable", feature])
    # Current native clients require the local host even with code_mode disabled.
    # This enables transport, while the MCP allowlist and trace gate stay unchanged.
    command.extend(["--enable", "code_mode_host", "--enable", "skip_host_skill_discovery"])
    config = {
        "approval_policy": '"never"', "web_search": '"disabled"', "project_doc_max_bytes": "0",
        "model_reasoning_effort": '"low"',
        "skills.bundled.enabled": "false", "skills.include_instructions": "false",
        "history.persistence": '"none"', "analytics.enabled": "false",
        "suppress_unstable_features_warning": "true",
        "check_for_update_on_startup": "false", "log_dir": json.dumps(str(project / "logs")),
        "sqlite_home": json.dumps(str(project / "state")),
        "mcp_servers": '{terraproof={command=' + json.dumps(sys.executable)
            + ',args=["-m","terraproof.mcp"],enabled_tools=["list_skills","inspect_dataset"],'
              'tools={list_skills={approval_mode="approve"},inspect_dataset={approval_mode="approve"}},'
              'env={PYTHONUTF8="1",PYTHONIOENCODING="utf-8"},required=true,startup_timeout_sec=20,tool_timeout_sec=30}}',
    }
    for key, value in config.items():
        command.extend(["-c", f"{key}={value}"])
    command.append("Use only Terraproof MCP. Call list_skills, then inspect_dataset with path "
                   + json.dumps(str(fixture)) + ". Briefly report the feature count. No other tools, edits, commands or network actions.")
    return command


def codex_trace(events, fixture):
    """Codex exec JSONL: require started calls and completed real MCP result payloads."""
    started, successful, failed = {}, set(), False
    finished = False
    for event in events:
        if not isinstance(event, dict):
            return False, []
        kind = event.get("type")
        if kind in {"error", "turn.failed"}:
            failed = True
        if kind == "turn.completed":
            finished = True
        if kind not in {"item.started", "item.completed", "item.updated"}:
            continue
        item = event.get("item", {})
        if not isinstance(item, dict):
            return False, []
        if item.get("type") in {"agent_message", "reasoning"}:
            continue
        if item.get("type") != "mcp_tool_call" or item.get("server") != "terraproof" or item.get("tool") not in CODEX_TOOLS:
            failed = True
            continue
        identity = (item.get("server"), item.get("tool"), item.get("arguments"))
        identifier = item.get("id")
        if kind == "item.started":
            if not identifier or identifier in started or finished:
                failed = True
            started[identifier] = identity
            continue
        if kind != "item.completed":
            continue
        result = item.get("result")
        if (finished or not identifier or started.get(identifier) != identity or identifier in successful
                or item.get("status") != "completed" or item.get("error") is not None
                or not isinstance(result, dict) or result.get("isError") or result.get("is_error")):
            failed = True
            continue
        payload = result.get("structured_content", result.get("structuredContent"))
        if payload is None:
            try:
                payload = json.loads(next(c["text"] for c in result.get("content", []) if c.get("type") == "text"))
            except (ValueError, KeyError, StopIteration, TypeError):
                failed = True
                continue
        tool = item["tool"]
        if tool == "inspect_dataset":
            valid = (isinstance(payload, dict) and item.get("arguments") == {"path": str(fixture)}
                     and payload.get("kind") == "vector" and payload.get("feature_count") == 1
                     and isinstance(payload.get("crs"), dict) and payload["crs"].get("epsg") == 32636)
        else:
            skills = payload.get("result") if isinstance(payload, dict) else payload
            valid = isinstance(skills, list) and any(isinstance(s, dict) and s.get("name") == "gdal" for s in skills)
        if valid:
            successful.add(identifier)
        else:
            failed = True
    names = sorted({started[key][1] for key in successful})
    return finished and not failed and set(names) == set(CODEX_TOOLS) and set(started) == successful, names


def codex_diagnostics(stderr, events, invalid_json_lines=0):
    """Diagnostic hints only: emit fixed labels/counts, never stream-derived text.

    Conflicting hints are retained, not resolved into a claimed root cause. These
    observations never authorize an invocation or weaken the successful trace gate.
    """
    counts = dict.fromkeys(("thread.started", "turn.started", "turn.completed", "turn.failed",
                            "error", "item.started", "item.updated", "item.completed", "other"), 0)
    errors = [stderr]
    usage_present = output_tokens = False
    for event in events:
        if not isinstance(event, dict):
            counts["other"] += 1
            continue
        kind = event.get("type")
        counts[kind if isinstance(kind, str) and kind in counts else "other"] += 1
        if kind == "error" and isinstance(event.get("message"), str):
            errors.append(event["message"])
        if kind == "turn.failed":
            error = event.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                errors.append(error["message"])
        if kind == "turn.completed" and isinstance(event.get("usage"), dict):
            usage_present = True
            value = event["usage"].get("output_tokens")
            output_tokens |= type(value) is int and value > 0
    patterns = {
        "unsupported_flag_or_config": r"unexpected argument|unrecognized option|unknown option|"
            r"error (?:parsing|loading).*config|failed to load (?:configuration|config)|invalid.*config|unknown feature",
        "mcp_startup_failed": r"mcp.*(?:startup failed|failed to start|failed to initialize)|"
            r"(?:failed to start|failed to initialize).*mcp|mcp startup.*(?:failed|interrupted)|mcp.*handshak.*failed",
        "auth_unavailable": r"not logged in|authentication failed|unauthorized|"
            r"invalid (?:api key|authentication)|refresh.*token.*failed",
        "connection_unavailable": r"error sending request|connection refused|connection reset|"
            r"failed to connect|stream disconnected|network is unreachable|dns error|tls.*failed",
        "model_startup_failed": r"model.*(?:not found|not supported|unavailable)|"
            r"(?:failed to load|failed to initialize).*model",
    }
    text = re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(errors))
    labels = sorted(label for label, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE))
    if invalid_json_lines:
        labels.append("invalid_jsonl")
    return {"labels": labels or ["unclassified"], "event_counts": counts,
            "invalid_json_lines": invalid_json_lines,
            "stderr_nonempty_lines": sum(bool(line.strip()) for line in stderr.splitlines()),
            "turn_started_observed": counts["turn.started"] > 0,
            "turn_completed_observed": counts["turn.completed"] > 0,
            "usage_present": usage_present, "positive_output_tokens_observed": output_tokens}


def codex_subscription_auth(result):
    """Accept one explicit ChatGPT status, not arbitrary output or paid-API auth.

    Native 0.160.1 can emit these two startup warnings even on successful probes.
    Only those confirmed warning forms and ANSI SGR styling are ignored; never
    log the streams (the PATH warning includes a user-specific temporary path).
    """
    if result.returncode != 0:
        return False
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + "\n" + result.stderr)
    if re.search(r"\bapi\b", text, re.IGNORECASE):
        return False
    warnings = (
        r"WARNING: failed to clean up stale arg0 temp dirs: Access is denied\. \(os error 5\)",
        r'WARNING: proceeding, even though we could not create PATH aliases: '
        r'Access is denied\. \(os error 5\) at path "[^"\r\n]+"',
    )
    statuses = []
    for line in text.splitlines():
        line = line.strip()
        if not line or any(re.fullmatch(pattern, line) for pattern in warnings):
            continue
        statuses.append(line)
    return statuses == ["Logged in using ChatGPT"]


def codex_host(report, work, paths):
    host = report.data["agent_host"] = {"name": "codex", "status": "unavailable", "model_called": False,
                                       "process_started": False,
                                       "model_called_semantics": "legacy process-start flag; not proof of inference",
                                       "timeout_seconds": 120, "usd_cap": None}
    try:
        executable = codex_executable()
        if not executable:
            host["reason"] = "no supported installed native Codex executable; shell/Node wrappers are not invoked"
            return
        project = work / "codex-host"
        project.mkdir()
        fixture = project / "fixture.geojson"
        shutil.copyfile(paths["clean"], fixture)
        version = run([executable, "--version"], cwd=project)
        help_result = run([executable, "exec", "--help"], cwd=project)
        required = ("--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral",
                    "--sandbox", "--json", "--skip-git-repo-check", "--disable", "--config")
        if version.returncode or help_result.returncode or not all(flag in help_result.stdout for flag in required):
            host["reason"] = "native Codex version/help probe failed or required isolation flags unavailable"
            return
        host["version"] = version.stdout.strip()
        features = run([executable, "features", "list"], cwd=project)
        supported = {line.split()[0] for line in features.stdout.splitlines()
                     if len(line.split()) >= 3 and "removed" not in line.split()[1:-1]}
        if features.returncode or not set(CODEX_DISABLED + ("code_mode_host", "skip_host_skill_discovery")) <= supported:
            host["reason"] = "required Codex isolation feature controls unavailable; refusing model invocation"
            return
        auth = run([executable, "login", "status"], cwd=project)
        if not codex_subscription_auth(auth):
            host["reason"] = "Codex login status did not confirm ChatGPT subscription auth; no API-paid fallback"
            return
        host["auth"] = "ChatGPT subscription (login status only; credentials not inspected)"
        host["limitations"] = ["No Codex USD budget cap; one 120-second subscription invocation, no runner retries.",
                               "CLI read-only sandbox and feature controls, not an OS-wide inference network block.",
                               "Untoggleable edit tools must be blocked by read-only sandbox; any observed non-MCP tool attempt fails the trace gate."]
        command = codex_command(executable, project, fixture)
        def started():
            host["process_started"] = host["model_called"] = True
        result = run_codex_model(command, project, started)
        events, invalid_json_lines = [], 0
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                invalid_json_lines += 1
        host["diagnostics"] = codex_diagnostics(result.stderr, events, invalid_json_lines)
        passed, tools = codex_trace(events, fixture)
        host.update(status="pass" if passed and not invalid_json_lines and result.returncode == 0 else "fail",
                    successful_tools=tools, exit_code=result.returncode)
        if host["status"] != "pass":
            host["reason"] = "Codex did not provide successful allowed MCP call/result events and turn completion"
    except Exception as exc:
        host["status"] = "fail" if host["model_called"] else "unavailable"
        host["reason"] = ("Codex host timed out; owned process tree terminated" if isinstance(exc, subprocess.TimeoutExpired)
                          else str(exc) if isinstance(exc, ValidationError)
                          else "Codex host isolation/probe/trace failed: " + type(exc).__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "release-validation.json")
    parser.add_argument("--timeout", type=float, default=120, help="total stdio validation timeout in seconds")
    parser.add_argument("--agent-host", choices=["claude", "codex"],
                        help="opt in to ONE real default-model call: Claude <= USD1; Codex ChatGPT subscription, no USD cap; never run by tests/CI")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    report = Report()
    try:
        cache = ROOT / ".terracache"
        cache.mkdir(exist_ok=True)
        # TemporaryDirectory owns exactly this newly allocated path; no user path is deleted.
        with tempfile.TemporaryDirectory(prefix="release-validation-", dir=cache) as directory:
            work = Path(directory).resolve()
            if work.parent != cache.resolve() or not work.name.startswith("release-validation-"):
                raise ValidationError("unexpected temporary directory ownership")
            paths = fixtures(work)
            report.check("cli.help", "COMMAND" in cli("--help").stdout, "python -m terraproof --help exits 0")
            installers(report, work)
            asyncio.run(asyncio.wait_for(validate_stdio(report, work, paths, min(args.timeout, 45)), args.timeout))
            if args.agent_host == "codex":
                # Outside the checkout: no ancestral project MCP config/rules to merge.
                with tempfile.TemporaryDirectory(prefix="terraproof-codex-host-") as host_directory:
                    host_work = Path(host_directory).resolve()
                    if host_work.parent != Path(tempfile.gettempdir()).resolve() or not host_work.name.startswith("terraproof-codex-host-"):
                        raise ValidationError("unexpected Codex temporary directory ownership")
                    codex_host(report, host_work, paths)
            elif args.agent_host == "claude":
                agent_host(report, work, paths)
    except Exception as exc:
        # Only known validation messages are safe to expose; arbitrary transport exceptions may carry env/streams.
        report.data["failure"] = {"type": type(exc).__name__,
                                  "message": str(exc) if isinstance(exc, ValidationError) else "validation aborted; no child output logged"}
    code = report.finish()
    report.write(args.out)
    print(json.dumps({"status": report.data["status"], "assertions": len(report.data["assertions"]),
                      "report": str(args.out)}, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
