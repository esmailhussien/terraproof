"""MCP server tests: tool surface, inspections, checks, sections, and the router fallback."""

from __future__ import annotations

import json
import sys

import pytest
from shapely.geometry import Polygon

pytest.importorskip("anyio", reason="the mcp extra is not installed")
pytest.importorskip("mcp", reason="the mcp extra is not installed")

import anyio  # noqa: E402
from mcp import Client  # noqa: E402

from terraproof.cli import main  # noqa: E402
from terraproof.mcp.server import mcp  # noqa: E402

TOOL_NAMES = ["find_guidance", "inspect_dataset", "list_skills", "load_section", "run_checks"]


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def call(name: str, arguments: dict | None = None):
    """Call one tool through the SDK's in-memory client."""

    async def _call():
        async with Client(mcp, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(_call)


def test_tool_list_names_and_guidance():
    async def _list():
        async with Client(mcp, raise_exceptions=True) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in anyio.run(_list).tools}

    assert sorted(tools) == TOOL_NAMES
    assert all(tool.description for tool in tools.values())
    assert "before you claim" in tools["run_checks"].description
    assert "before you claim" in tools["list_skills"].description or "before choosing" in tools["list_skills"].description
    assert "start of a task" in tools["find_guidance"].description


def test_inspect_dataset_returns_the_profile(make_vector):
    path = make_vector("parcels.gpkg", [square(500000, 5000000)])

    result = call("inspect_dataset", {"path": path})

    assert not result.is_error
    assert result.structured_content["kind"] == "vector"
    assert result.structured_content["crs"]["epsg"] == 32636
    assert result.structured_content["feature_count"] == 1


def test_inspect_dataset_missing_file_is_a_tool_error(tmp_path):
    result = call("inspect_dataset", {"path": str(tmp_path / "missing.gpkg")})

    assert result.is_error
    assert "file not found" in result.content[0].text


def test_run_checks_matches_the_cli_grade_and_report(make_vector, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    assert main(["check", path, "--operation", "area"]) == 0
    cli_report = json.loads(capsys.readouterr().out)

    payload = call("run_checks", {"paths": [path], "operation": "area"}).structured_content

    assert payload["report"] == cli_report
    assert payload["report"]["parameters"]["categorical"] is False
    assert payload["grade"] == cli_report["grade"] == "decision-grade"
    assert payload["exit_code"] == 0
    assert payload["markdown"].startswith("# Terraproof evidence report")


def test_run_checks_exit_code_follows_the_cli_contract(make_vector, capsys):
    empty = make_vector("empty.gpkg", [square(500000, 5000000), Polygon()])

    assert main(["check", empty]) == 2
    capsys.readouterr()

    payload = call("run_checks", {"paths": [empty]}).structured_content

    assert payload["grade"] == "review-required"
    assert payload["exit_code"] == 2


def test_run_checks_markdown_language(make_vector):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    payload = call("run_checks", {"paths": [path], "lang": "ar"}).structured_content
    assert payload["markdown"].startswith("# تقرير أدلة Terraproof")

    assert call("run_checks", {"paths": [path], "lang": "fr"}).is_error
    assert call("run_checks", {"paths": []}).is_error


def test_list_skills_describes_the_registry():
    skills = {skill["name"]: skill for skill in call("list_skills").structured_content["result"]}

    assert "gdal" in skills and "crs-and-units" in skills
    gdal = skills["gdal"]
    assert gdal["layer"] == "domain"
    assert gdal["explanation"]
    assert {"id": "quick-reference", "title": "Quick Reference"} in gdal["sections"]
    assert "raster.cog_layout" in gdal["checks"]


def test_load_section_reads_a_heading_and_a_reference():
    heading = call("load_section", {"skill": "gdal", "section_id": "quick-reference"}).structured_content
    reference = call("load_section", {"skill": "gdal", "section_id": "gdal-recipes"}).structured_content

    assert heading["title"] == "Quick Reference"
    assert heading["source"] == "SKILL.md#quick-reference"
    assert "gdalinfo" in heading["text"]
    assert reference["source"] == "references/gdal-recipes.md"
    assert len(reference["text"]) > 0


@pytest.mark.parametrize(
    "skill, section_id",
    [
        ("gdal", "../routing/registry.json"),
        ("gdal", "../../AGENTS.md"),
        ("gdal", "/etc/passwd"),
        ("gdal", ".."),
        ("../gdal", "quick-reference"),
        ("nope", "quick-reference"),
        ("gdal", "no-such-section"),
    ],
)
def test_load_section_rejects_traversal_and_unknown_ids(skill, section_id):
    result = call("load_section", {"skill": skill, "section_id": section_id})

    assert result.is_error
    assert "Error executing tool load_section" in result.content[0].text
    assert "Traceback" not in result.content[0].text


def test_find_guidance_reports_a_missing_router(monkeypatch):
    monkeypatch.setitem(sys.modules, "terraproof.router", None)

    result = call("find_guidance", {"task": "compute NDVI over the AOI"})

    assert result.is_error
    assert "router is unavailable" in result.content[0].text
