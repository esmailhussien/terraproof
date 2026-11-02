"""Phase 11 T2: the stock Terraproof MCP server, snapshotting the project before each verification call.

    python -I phase11_snapshot_server.py SNAPSHOT_DIR PROJECT_DIR

Before every `run_checks` call, and every `verify_project` call without `plan`, it copies the project's
`outputs/` and project file to `SNAPSHOT_DIR/NNN-TOOL/`, calls the unchanged tool, and records what the
call returned in `call.json`. Only each tool's function is replaced, so names, descriptions, schemas and
instructions stay byte-identical to `python -m terraproof.mcp` (the T2 preflight compares them).
The driver copies this file outside the checkout, so the agent's MCP config never points into the repo.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import threading
import time

PROJECT_FILES = ("terraproof.toml", "terraproof.json")
_lock = threading.Lock()


def _labels(tool: str, output) -> dict:
    """What the agent was shown, reduced to names and enums."""
    if not isinstance(output, dict):
        return {}
    if tool == "run_checks":
        report = output.get("report") if isinstance(output.get("report"), dict) else {}
        verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
        return {"grade": output.get("grade"), "verification_status": verification.get("status")}
    rows = output.get("deliverables") if isinstance(output.get("deliverables"), list) else []
    return {"exit_code": output.get("exit_code"),
            "deliverables": [{"name": row.get("name"), "status": row.get("status"), "grade": row.get("grade"),
                              "outputs": [Path(str(o)).name for o in row.get("outputs") or []],
                              "findings": [f"{f.get('check')}:{f.get('status')}" for f in row.get("findings") or []
                                           if isinstance(f, dict)]}
                             for row in rows if isinstance(row, dict)]}


def _snapshot(target: Path, project: Path, path: str | None) -> None:
    target.mkdir(parents=True)
    if (project / "outputs").is_dir():
        shutil.copytree(project / "outputs", target / "outputs")
    for name in PROJECT_FILES:
        if (project / name).is_file():
            shutil.copyfile(project / name, target / name)
    if path:  # a project file the agent named elsewhere
        given = Path(path) if Path(path).is_absolute() else project / path
        for source in ([given / name for name in PROJECT_FILES] if given.is_dir() else [given]):
            if source.is_file():
                shutil.copyfile(source, target / f"given-{source.name}")


def snapshotting(tool: str, fn, snapshots: Path, project: Path):
    def call(**kwargs):
        if tool == "verify_project" and kwargs.get("plan"):
            return fn(**kwargs)
        with _lock:
            snapshots.mkdir(parents=True, exist_ok=True)
            target = snapshots / f"{len(list(snapshots.iterdir())):03d}-{tool}"
            _snapshot(target, project, kwargs.get("path") if tool == "verify_project" else None)
        record = {"tool": tool, "time": time.time(), "arguments": kwargs}
        try:
            output = fn(**kwargs)
            record.update(outcome="returned", **_labels(tool, output))
            return output
        except Exception as error:
            record.update(outcome="error", error=type(error).__name__)
            raise
        finally:
            (target / "call.json").write_text(json.dumps(record, default=str, indent=1), encoding="utf-8")
    return call


def main(argv: list[str]) -> None:
    snapshots, project = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    from terraproof.mcp.server import mcp

    for tool in ("run_checks", "verify_project"):
        registered = mcp._tool_manager.get_tool(tool)
        registered.fn = snapshotting(tool, registered.fn, snapshots, project)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main(sys.argv[1:])
