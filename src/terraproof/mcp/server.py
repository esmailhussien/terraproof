"""The Terraproof MCP server: read-only tools over stdio.

The server exposes the same inspectors, checks, evidence report, skill sections, and
router that the command line uses, so an agent gets identical results whichever way
it calls them. It never writes files and never uses the network.

The official Python SDK's current stable line is 2.x, which serves both protocol
revisions; `FastMCP` was renamed to `MCPServer` in that release
(https://py.sdk.modelcontextprotocol.io/whats-new/#fastmcp-is-now-mcpserver).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from terraproof import __version__
from terraproof._common import InputError, jsonable
from terraproof.checks import run_checks as _run_checks
from terraproof.evidence import EXIT_CODES, build_report, input_record, render_markdown, to_json
from terraproof.inspect import inspect_dataset as _inspect_dataset
from terraproof.mcp.skills import SectionError, list_skills as _list_skills, load_section as _load_section

LANGUAGES = ("en", "ar")

INSTRUCTIONS = (
    "Terraproof provides evidence-graded geospatial checks. Before you claim a mapping or "
    "remote-sensing result is correct, call `run_checks` on the outputs and report the grade. "
    "Call `inspect_dataset` on unfamiliar inputs, `find_guidance` at the start of a task to "
    "retrieve the relevant skill sections, and `load_section` to read one of those sections in "
    "full. All tools are read-only: they never modify your data."
)

mcp = MCPServer(name="terraproof", version=__version__, instructions=INSTRUCTIONS)


def _router() -> Any:
    """Import the router lazily: routing is optional for inspecting and checking."""
    try:
        from terraproof.router import find_guidance
    except Exception as exc:  # any import failure of the optional router package
        raise ToolError(
            "The Terraproof router is unavailable in this installation, so find_guidance cannot "
            f"rank skills ({exc}). Use `list_skills` and `load_section` instead."
        ) from exc
    return find_guidance


@mcp.tool()
def inspect_dataset(path: str) -> dict[str, Any]:
    """Inspect one local dataset and return its profile.

    Call this first on any vector, raster, or STAC Item file whose contents you have not
    seen: the result gives the CRS, units, extent, schema or bands, nodata, dtype,
    resolution, feature or pixel counts, and scale/offset that every later decision
    depends on. It reads local files only; it does not fetch URLs.
    """
    try:
        return jsonable(_inspect_dataset(path))
    except Exception as exc:  # tool boundary: a bad path is a message for the agent, not a crash
        raise ToolError(f"cannot inspect {path!r}: {exc}") from exc


@mcp.tool()
def run_checks(
    paths: list[str],
    operation: str | None = None,
    compare_to: str | None = None,
    resampling: str | None = None,
    categorical: bool = False,
    expect: str | None = None,
    lang: str = "en",
) -> dict[str, Any]:
    """Run Terraproof's deterministic evidence checks and return the grade and report.

    Call this before you claim a geospatial result is correct: the grade says whether the
    data path was verified (decision-grade), needs review, or is advisory only. Pass the
    outputs you produced, plus the inputs they came from, so CRS, geometry, scope, raster,
    and remote-sensing checks can run. `operation` is the metric operation the data will be
    used for (buffer, distance, area, length); `compare_to` is an input to compare record
    counts with; `resampling` is the method declared for the rasters and `categorical` says
    they hold class codes; `expect` is the value range the bands should hold (reflectance or
    index). `lang` selects the Markdown language (en or ar). Results match
    `python -m terraproof check`.
    """
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
        raise ToolError("paths must be a non-empty list of file paths")
    if lang not in LANGUAGES:
        raise ToolError(f"unsupported language: {lang!r}; use one of {', '.join(LANGUAGES)}")
    try:
        inspections = [_inspect_dataset(path) for path in paths]
        compare = _inspect_dataset(compare_to) if compare_to else None
        inputs = [input_record(path, "input", dataset["kind"]) for path, dataset in zip(paths, inspections)]
        if compare is not None:
            inputs.append(input_record(compare_to, "compare-to", compare["kind"]))
        results = _run_checks(
            inspections,
            compare_to=compare,
            operation=operation,
            resampling=resampling,
            categorical=categorical,
            expect=expect,
        )
    except Exception as exc:  # tool boundary: unreadable inputs are a message for the agent
        raise ToolError(f"cannot check {paths!r}: {exc}") from exc

    parameters = {
        "operation": operation,
        "compare_to": compare_to,
        "resampling": resampling,
        "categorical": categorical,
        "expect": expect,
    }
    report = build_report(inputs=inputs, results=results, parameters=parameters)
    return {
        "grade": report["grade"],
        "exit_code": EXIT_CODES[report["grade"]],
        "report": json.loads(to_json(report)),
        "markdown": render_markdown(report, lang=lang),
    }


@mcp.tool()
def list_skills() -> list[dict]:
    """List the Terraproof skills you can load, with their sections and checks.

    Call this when you need to know which guidance exists before choosing one, or when
    the router is unavailable. Each entry gives the skill name, its layer, a one-sentence
    explanation, the id and title of every section, and the check ids the skill bears on.
    Follow up with `load_section` to read a section.
    """
    try:
        return _list_skills()
    except Exception as exc:
        raise ToolError(f"cannot read the skill registry: {exc}") from exc


@mcp.tool()
def load_section(skill: str, section_id: str) -> dict[str, Any]:
    """Load one skill section's Markdown text.

    Call this after `find_guidance` or `list_skills` names a section you need, instead of
    reading a whole SKILL.md. Unknown skills and sections are rejected, and a section may
    only resolve to a file inside its own skill directory.
    """
    try:
        return _load_section(skill, section_id)
    except SectionError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        raise ToolError(f"cannot load {skill!r}/{section_id!r}: {exc}") from exc


@mcp.tool()
def find_guidance(task: str, data_paths: list[str] | None = None, top_k: int = 5) -> dict[str, Any]:
    """Rank the skill sections that fit a mapping or remote-sensing task.

    Call this at the start of a task, with the datasets you will work on, to get the few
    sections worth reading instead of the whole catalogue. `data_paths` are local datasets
    that are inspected to steer retrieval; `top_k` caps the number of ranked skills. The
    result also names the process skills (planning, verification) that apply. This is the
    same retrieval `python -m terraproof route` performs.
    """
    find_guidance_fn = _router()
    try:
        return jsonable(find_guidance_fn(task, data_paths=list(data_paths or []), top_k=top_k))
    except Exception as exc:  # tool boundary: an empty task or unreadable dataset
        raise ToolError(f"cannot route {task!r}: {exc}") from exc
