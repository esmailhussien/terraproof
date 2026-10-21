"""Installer tests: per-agent native formats, merges, idempotency, and dry runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from terraproof.install import main

SKILLS = "gdal,crs-and-units"

NATIVE_FILES = {
    "claude": [
        ".claude/skills/gdal/SKILL.md",
        ".claude/skills/gdal/references/gdal-recipes.md",
        ".claude/skills/crs-and-units/SKILL.md",
    ],
    "cursor": [".cursor/rules/terraproof-gdal.mdc", ".cursor/rules/terraproof-crs-and-units.mdc"],
    "codex": ["AGENTS.md", ".agents/skills/gdal/SKILL.md", ".agents/skills/gdal/references/gdal-recipes.md"],
    "gemini": ["GEMINI.md"],
    "copilot": [".github/instructions/terraproof-gdal.instructions.md"],
    "opencode": ["AGENTS.md"],
}

MCP_FILES = {
    "claude": (".mcp.json", "mcpServers"),
    "cursor": (".cursor/mcp.json", "mcpServers"),
    "gemini": (".gemini/settings.json", "mcpServers"),
    "copilot": (".vscode/mcp.json", "servers"),
    "opencode": ("opencode.json", "mcp"),
}


def install(target: Path, *extra: str) -> int:
    return main(["--agent", extra[0], "--skills", SKILLS, "--target", str(target), *extra[1:]])


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def mcp_entry(target: Path, agent: str) -> dict:
    relative, key = MCP_FILES[agent]
    return json.loads((target / relative).read_text(encoding="utf-8"))[key]["terraproof"]


@pytest.mark.parametrize("agent", sorted(NATIVE_FILES))
def test_agent_writes_its_native_files(agent, tmp_path):
    assert install(tmp_path, agent, "--with-mcp") == 0

    for relative in NATIVE_FILES[agent]:
        assert (tmp_path / relative).is_file(), relative

    assert not (tmp_path / ".claude/skills/gdal/UPSTREAM.md").exists()
    assert not (tmp_path / ".claude/skills/gdal/skill.json").exists()
    assert not (tmp_path / ".agents/skills/gdal/skill.json").exists()


def test_claude_skill_keeps_its_frontmatter(tmp_path):
    assert install(tmp_path, "claude") == 0

    text = (tmp_path / ".claude/skills/gdal/SKILL.md").read_text(encoding="utf-8")

    assert text.startswith("---\nname: gdal\ndescription: ")
    assert "## Quick Reference" in text


def test_cursor_rule_has_mdc_frontmatter(tmp_path):
    assert install(tmp_path, "cursor") == 0

    lines = (tmp_path / ".cursor/rules/terraproof-gdal.mdc").read_text(encoding="utf-8").splitlines()

    assert lines[0] == "---"
    assert lines[1].startswith("description: 'This skill should be used")
    assert lines[2] == "alwaysApply: false"
    assert lines[3] == "---"


def test_copilot_instruction_has_apply_to_frontmatter(tmp_path):
    assert install(tmp_path, "copilot") == 0

    lines = (tmp_path / ".github/instructions/terraproof-gdal.instructions.md").read_text(encoding="utf-8").splitlines()

    assert lines[0] == "---"
    assert lines[1].startswith("description: ")
    assert lines[2] == "applyTo: '**'"
    assert lines[3] == "---"


def test_agents_md_uses_the_terraproof_markers(tmp_path):
    for agent in ("codex", "gemini", "opencode"):
        assert install(tmp_path, agent) == 0
        text = (tmp_path / ("AGENTS.md" if agent != "gemini" else "GEMINI.md")).read_text(encoding="utf-8")
        assert text.count(f"<!-- terraproof:{agent}:begin -->") == 1
        assert text.count(f"<!-- terraproof:{agent}:end -->") == 1
        assert text.count("<!-- terraproof:begin -->") == 0
        assert text.count("<!-- terraproof:end -->") == 0
        assert "gdal" in text


@pytest.mark.parametrize("agent", sorted(MCP_FILES))
def test_mcp_server_entry_uses_the_running_interpreter(agent, tmp_path):
    assert install(tmp_path, agent, "--with-mcp") == 0

    entry = mcp_entry(tmp_path, agent)

    if agent == "opencode":
        assert entry["type"] == "local"
        assert entry["enabled"] is True
        assert entry["command"] == [sys.executable, "-m", "terraproof.mcp"]
    else:
        assert Path(entry["command"]) == Path(sys.executable)
        assert entry["args"] == ["-m", "terraproof.mcp"]


def test_codex_writes_a_project_toml_table(tmp_path):
    assert install(tmp_path, "codex", "--with-mcp") == 0

    text = (tmp_path / ".codex/config.toml").read_text(encoding="utf-8")

    assert "[mcp_servers.terraproof]" in text
    assert "args = ['-m', 'terraproof.mcp']" in text


def test_skill_option_does_not_change_an_existing_config(tmp_path):
    existing = {"mcpServers": {"other": {"command": "keepme"}}, "custom": 1}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    assert install(tmp_path, "claude", "--with-mcp") == 0

    document = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))

    assert document["custom"] == 1
    assert document["mcpServers"]["other"] == {"command": "keepme"}
    assert document["mcpServers"]["terraproof"]["args"] == ["-m", "terraproof.mcp"]


def test_existing_toml_tables_survive(tmp_path):
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text(
        'model = "gpt-6.1"\n\n[mcp_servers.other]\ncommand = "keepme"\n\n[other_table]\na = 1\n',
        encoding="utf-8",
    )

    assert install(tmp_path, "codex", "--with-mcp") == 0
    text = (tmp_path / ".codex/config.toml").read_text(encoding="utf-8")

    assert 'model = "gpt-6.1"' in text
    assert '[mcp_servers.other]\ncommand = "keepme"' in text
    assert "[other_table]\na = 1" in text
    assert "[mcp_servers.terraproof]" in text


def test_markdown_outside_the_markers_is_preserved(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Project\n\nKeep this paragraph.\n", encoding="utf-8")

    assert install(tmp_path, "codex") == 0
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert text.startswith("# Project\n\nKeep this paragraph.\n")
    assert text.count("<!-- terraproof:codex:begin -->") == 1
    assert text.count("<!-- terraproof:codex:end -->") == 1


def test_rerun_is_byte_identical(tmp_path):
    for agent in sorted(NATIVE_FILES):
        directory = tmp_path / agent
        directory.mkdir()
        assert install(directory, agent, "--with-mcp") == 0
        first = snapshot(directory)
        assert install(directory, agent, "--with-mcp") == 0
        assert snapshot(directory) == first, agent


def test_dry_run_writes_nothing(tmp_path):
    assert install(tmp_path, "claude", "--with-mcp", "--dry-run") == 0

    assert snapshot(tmp_path) == {}


def test_unknown_skill_exits_1(tmp_path, capsys):
    assert main(["--agent", "claude", "--skills", "gdal,no-such-skill", "--target", str(tmp_path)]) == 1

    assert "unknown skill(s): no-such-skill" in capsys.readouterr().err
    assert snapshot(tmp_path) == {}


def test_requires_skills_or_task(tmp_path, capsys):
    assert main(["--agent", "claude", "--target", str(tmp_path)]) == 1
    assert "--skills" in capsys.readouterr().err

    assert main(["--agent", "claude", "--skills", "gdal", "--task", "NDVI", "--target", str(tmp_path)]) == 1
    assert "not both" in capsys.readouterr().err


def test_missing_target_exits_1(tmp_path, capsys):
    assert main(["--agent", "claude", "--skills", "gdal", "--target", str(tmp_path / "missing")]) == 1

    assert "not a directory" in capsys.readouterr().err


def test_task_routes_skills(tmp_path):
    pytest.importorskip("terraproof.router")

    assert main(["--agent", "codex", "--task", "clip a GDAL raster and build a COG", "--target", str(tmp_path)]) == 0

    assert list((tmp_path / ".agents/skills").iterdir())


def test_codex_and_opencode_blocks_coexist_in_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Project\n\nKeep this paragraph.\n", encoding="utf-8")

    assert install(tmp_path, "codex") == 0
    assert install(tmp_path, "opencode") == 0

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert text.startswith("# Project\n\nKeep this paragraph.\n")
    assert text.count("<!-- terraproof:codex:begin -->") == 1
    assert text.count("<!-- terraproof:codex:end -->") == 1
    assert text.count("<!-- terraproof:opencode:begin -->") == 1
    assert text.count("<!-- terraproof:opencode:end -->") == 1
    assert text.count("<!-- terraproof:begin -->") == 0
    assert text.count("<!-- terraproof:end -->") == 0
    assert "gdal" in text


def test_codex_and_opencode_reruns_are_idempotent(tmp_path):
    assert install(tmp_path, "codex") == 0
    assert install(tmp_path, "opencode") == 0
    first = snapshot(tmp_path)

    assert install(tmp_path, "codex") == 0
    assert install(tmp_path, "opencode") == 0
    assert snapshot(tmp_path) == first


def test_legacy_terraproof_block_is_migrated(tmp_path, capsys):
    legacy_block = (
        "<!-- terraproof:begin -->\n"
        "## Old Terraproof skills\n\nold content\n"
        "<!-- terraproof:end -->\n"
    )
    (tmp_path / "AGENTS.md").write_text("# Project\n\nKeep this paragraph.\n\n" + legacy_block, encoding="utf-8")

    assert install(tmp_path, "codex") == 0

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("<!-- terraproof:begin -->") == 0
    assert text.count("<!-- terraproof:end -->") == 0
    assert text.count("<!-- terraproof:codex:begin -->") == 1
    assert text.count("<!-- terraproof:codex:end -->") == 1
    assert "Keep this paragraph." in text
    assert "migrated legacy terraproof block to terraproof:codex scope" in capsys.readouterr().out
