"""Native project-level formats for each supported agent.

Every format below was checked against the agent's own documentation before it was
implemented; the source URL is cited next to the writer that produces it.

Shared rules: nothing is written outside the target project, an existing JSON or TOML
config is merged rather than replaced, and a Markdown section lives between
`<!-- terraproof:begin -->` and `<!-- terraproof:end -->` so a rerun replaces exactly that
block and leaves the rest of the file alone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

BEGIN = "<!-- terraproof:begin -->"
END = "<!-- terraproof:end -->"
SERVER_NAME = "terraproof"
SKIP_NAMES = frozenset({"UPSTREAM.md", "skill.json"})
SKIP_PARTS = frozenset({"__pycache__", ".git"})


class InstallError(ValueError):
    """A target, skill, or existing config file the installer cannot handle."""


@dataclass(frozen=True)
class Skill:
    """A registered skill, as the writers need it."""

    name: str
    directory: Path
    layer: str
    explanation: str
    description: str
    body: str
    sections: tuple[dict, ...]
    checks: tuple[str, ...]


@dataclass(frozen=True)
class Write:
    """One planned file: its final bytes and the reason it is written."""

    path: Path
    content: bytes
    note: str


# --- shared content ---------------------------------------------------------------

def _yaml_scalar(value: str) -> str:
    """A single-quoted YAML scalar; quotes are doubled, as YAML requires."""
    return "'" + " ".join(value.split()).replace("'", "''") + "'"


def _toml_scalar(value: str) -> str:
    """A TOML literal string, which does not process backslashes in Windows paths."""
    return "'" + value.replace("'", "''") + "'"


def _json_servers(path: Path, key: str, name: str, entry: dict, *, schema: str | None = None) -> Write:
    """Merge one server entry into a JSON config, keeping every other key and server."""
    document: dict = {}
    if path.is_file():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstallError(f"cannot merge into {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise InstallError(f"cannot merge into {path}: the file does not hold a JSON object")
    if schema is not None:
        document.setdefault("$schema", schema)
    servers = document.setdefault(key, {})
    if not isinstance(servers, dict):
        raise InstallError(f"cannot merge into {path}: {key!r} is not an object")
    servers[name] = entry
    return Write(path, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), f"{key}.{name}")


def _toml_servers(path: Path, name: str, command: str, args: list[str]) -> Write:
    """Merge `[mcp_servers.<name>]` into a TOML config, keeping every other table.

    A line-based rewrite is enough here: the block is a table header plus simple keys, so
    the existing file is kept byte for byte apart from that one table, and a rerun with the
    same command produces identical bytes.
    """
    header = re.compile(rf"^\s*\[\s*mcp_servers\s*\.\s*[\"']?{re.escape(name)}[\"']?\s*\]\s*$")
    any_header = re.compile(r"^\s*\[")
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    start = next((index for index, line in enumerate(lines) if header.match(line)), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and not any_header.match(lines[end]):
            end += 1
        lines = lines[:start] + lines[end:]
    while lines and not lines[-1].strip():
        lines.pop()
    block = [f"[mcp_servers.{name}]", f"command = {_toml_scalar(command)}",
             "args = [" + ", ".join(_toml_scalar(argument) for argument in args) + "]"]
    if lines:
        lines.append("")
    body = "\n".join([*lines, *block]) + "\n"
    return Write(path, body.encode("utf-8"), f"mcp_servers.{name}")


def _markdown_section(path: Path, body: str) -> Write:
    """Write a Markdown file's Terraproof block, replacing the previous one on a rerun."""
    block = f"{BEGIN}\n{body.rstrip()}\n{END}\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL)
    if pattern.search(existing):
        content = pattern.sub(lambda _match: block, existing, count=1)
    else:
        base = existing.rstrip("\n")
        content = f"{base}\n\n{block}" if base else block
    return Write(path, content.encode("utf-8"), "terraproof block")


def _skill_copies(skill: Skill, destination: Path) -> list[Write]:
    """Every file of the skill that belongs to the agent's own skill format."""
    writes = []
    for path in sorted(skill.directory.rglob("*")):
        relative = path.relative_to(skill.directory)
        if not path.is_file() or path.name in SKIP_NAMES or SKIP_PARTS.intersection(relative.parts):
            continue
        writes.append(Write(destination / relative, path.read_bytes(), f"from skills/{skill.name}/{relative.as_posix()}"))
    return writes


def _footer(with_mcp: bool, command: list[str]) -> str:
    check = "`python -m terraproof check <outputs>`"
    if with_mcp:
        check += f" or the `run_checks` tool of the `{SERVER_NAME}` MCP server (`{' '.join(command)}`)"
    return (
        "### Verify before you claim a result\n\n"
        "Run the Terraproof checks on your geospatial outputs and report the grade they give: "
        f"{check}. A passing grade covers the data path and the checks that ran; it is not a "
        "certification of survey, engineering, legal, or safety fitness."
    )


def _index_block(skills: list[Skill], *, agent: str, skills_dir: str, with_mcp: bool,
                 command: list[str]) -> str:
    lines = [
        "## Terraproof skills",
        "",
        f"Generated by `python -m terraproof.install --agent {agent}`. Re-run the installer to "
        "replace this block; everything outside the `terraproof` markers is left untouched.",
        "",
        f"The skill folders are under `{skills_dir}` and each holds the full `SKILL.md`.",
        "",
    ]
    for skill in skills:
        sections = "; ".join(f"`{section['id']}` ({section['title']})" for section in skill.sections)
        lines += [
            f"### {skill.name}",
            "",
            skill.explanation,
            "",
            f"- Folder: `{skills_dir}/{skill.name}/SKILL.md`",
            f"- Sections: {sections}",
        ]
        if skill.checks:
            lines.append("- Checks: " + ", ".join(f"`{check}`" for check in skill.checks))
        lines.append("")
    lines += [_footer(with_mcp, command), ""]
    return "\n".join(lines)


def _inline_block(skills: list[Skill], *, agent: str, with_mcp: bool, command: list[str]) -> str:
    lines = [
        "## Terraproof skills",
        "",
        f"Generated by `python -m terraproof.install --agent {agent}` from the Terraproof registry. "
        "Re-run the installer to replace this block; everything outside the `terraproof` markers "
        "is left untouched.",
        "",
    ]
    for skill in skills:
        lines += [f"### {skill.name}", "", skill.explanation, "", _demote_headings(skill.body.strip()), ""]
    lines += [_footer(with_mcp, command), ""]
    return "\n".join(lines)


def _demote_headings(body: str, levels: int = 2) -> str:
    """Nest a whole SKILL.md body under a `###` heading without touching fenced code."""
    lines = []
    fence = None
    for line in body.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
        heading = re.match(r"^(#{1,6})\s+\S", line) if fence is None else None
        if heading:
            line = "#" * min(6, len(heading.group(1)) + levels) + line[len(heading.group(1)):]
        lines.append(line)
    return "\n".join(lines)


# --- agents -----------------------------------------------------------------------

def plan_claude(target: Path, skills: list[Skill], *, with_mcp: bool, command: list[str]) -> list[Write]:
    """Claude Code project skills and project MCP servers.

    Skills: https://code.claude.com/docs/en/skills (`<project>/.claude/skills/<name>/SKILL.md`,
    supporting files alongside).
    MCP: https://code.claude.com/docs/en/mcp (`<project>/.mcp.json`, `mcpServers` entry with
    `type`, `command`, `args`).
    """
    writes: list[Write] = []
    for skill in skills:
        writes += _skill_copies(skill, target / ".claude" / "skills" / skill.name)
    if with_mcp:
        entry = {"type": "stdio", "command": command[0], "args": command[1:]}
        writes.append(_json_servers(target / ".mcp.json", "mcpServers", SERVER_NAME, entry))
    return writes


def plan_cursor(target: Path, skills: list[Skill], *, with_mcp: bool, command: list[str]) -> list[Write]:
    """Cursor project rules and project MCP servers.

    Rules: https://cursor.com/docs/rules (`.cursor/rules/<name>.mdc`, frontmatter
    `description`/`globs`/`alwaysApply`; `alwaysApply: false` with a `description` lets the
    agent pull the rule in when it is relevant).
    MCP: https://cursor.com/docs/mcp (`.cursor/mcp.json`, `mcpServers` entry; stdio fields are
    `type`, `command`, `args`).
    """
    writes: list[Write] = []
    for skill in skills:
        text = "\n".join([
            "---",
            f"description: {_yaml_scalar(skill.description or skill.explanation)}",
            "alwaysApply: false",
            "---",
            "",
            f"<!-- Generated by `python -m terraproof.install` from skills/{skill.name}/SKILL.md. -->",
            "",
            skill.body.strip(),
            "",
        ])
        writes.append(Write(target / ".cursor" / "rules" / f"terraproof-{skill.name}.mdc",
                            text.encode("utf-8"), f"rule for {skill.name}"))
    if with_mcp:
        entry = {"type": "stdio", "command": command[0], "args": command[1:]}
        writes.append(_json_servers(target / ".cursor" / "mcp.json", "mcpServers", SERVER_NAME, entry))
    return writes


def plan_codex(target: Path, skills: list[Skill], *, with_mcp: bool, command: list[str]) -> list[Write]:
    """Codex project instructions, project skills, and project MCP servers.

    AGENTS.md: https://learn.chatgpt.com/docs/agent-configuration/agents-md (project root).
    Skills: https://learn.chatgpt.com/docs/build-skills (`<repo>/.agents/skills/<name>/`).
    MCP: https://learn.chatgpt.com/docs/extend/mcp (`.codex/config.toml`,
    `[mcp_servers.<name>]` with `command` and `args`; project config is read only when the
    project is trusted).
    """
    writes: list[Write] = []
    for skill in skills:
        writes += _skill_copies(skill, target / ".agents" / "skills" / skill.name)
    block = _index_block(skills, agent="codex", skills_dir=".agents/skills", with_mcp=with_mcp, command=command)
    writes.append(_markdown_section(target / "AGENTS.md", block))
    if with_mcp:
        writes.append(_toml_servers(target / ".codex" / "config.toml", SERVER_NAME, command[0], command[1:]))
    return writes


def plan_gemini(target: Path, skills: list[Skill], *, with_mcp: bool, command: list[str]) -> list[Write]:
    """Gemini CLI project context and project MCP servers.

    Context file: https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md
    (`GEMINI.md` at the project root; `context.fileName` defaults to it).
    MCP: the same page (project settings file `.gemini/settings.json`, `mcpServers` entry with
    `command` and `args`). Gemini CLI documents no project skills directory, so the guidance
    is written into the context file itself.
    """
    writes: list[Write] = []
    block = _inline_block(skills, agent="gemini", with_mcp=with_mcp, command=command)
    writes.append(_markdown_section(target / "GEMINI.md", block))
    if with_mcp:
        entry = {"command": command[0], "args": command[1:]}
        writes.append(_json_servers(target / ".gemini" / "settings.json", "mcpServers", SERVER_NAME, entry))
    return writes


def plan_copilot(target: Path, skills: list[Skill], *, with_mcp: bool, command: list[str]) -> list[Write]:
    """GitHub Copilot repository instructions and VS Code MCP servers.

    Instructions: https://code.visualstudio.com/docs/agent-customization/custom-instructions
    (`.github/instructions/*.instructions.md` with `description` and `applyTo` frontmatter).
    MCP: https://code.visualstudio.com/docs/agents/reference/mcp-configuration
    (`.vscode/mcp.json` with a top-level `servers` object; stdio entries take `type`,
    `command`, `args`).
    """
    writes: list[Write] = []
    for skill in skills:
        text = "\n".join([
            "---",
            f"description: {_yaml_scalar(skill.description or skill.explanation)}",
            f"applyTo: {_yaml_scalar('**')}",
            "---",
            "",
            f"<!-- Generated by `python -m terraproof.install` from skills/{skill.name}/SKILL.md. -->",
            "",
            skill.body.strip(),
            "",
        ])
        writes.append(Write(target / ".github" / "instructions" / f"terraproof-{skill.name}.instructions.md",
                            text.encode("utf-8"), f"instructions for {skill.name}"))
    if with_mcp:
        entry = {"type": "stdio", "command": command[0], "args": command[1:]}
        writes.append(_json_servers(target / ".vscode" / "mcp.json", "servers", SERVER_NAME, entry))
    return writes


def plan_opencode(target: Path, skills: list[Skill], *, with_mcp: bool, command: list[str]) -> list[Write]:
    """OpenCode project rules and project MCP servers.

    AGENTS.md: https://opencode.ai/docs/rules (project root).
    MCP: https://opencode.ai/docs/mcp-servers/ (`opencode.json`, `mcp` entry with
    `type: "local"`, `command` as an argument array, `enabled`).
    """
    writes: list[Write] = []
    block = _inline_block(skills, agent="opencode", with_mcp=with_mcp, command=command)
    writes.append(_markdown_section(target / "AGENTS.md", block))
    if with_mcp:
        entry = {"type": "local", "command": list(command), "enabled": True}
        writes.append(_json_servers(target / "opencode.json", "mcp", SERVER_NAME, entry,
                                    schema="https://opencode.ai/config.json"))
    return writes


PLANNERS = {
    "claude": plan_claude,
    "cursor": plan_cursor,
    "codex": plan_codex,
    "gemini": plan_gemini,
    "copilot": plan_copilot,
    "opencode": plan_opencode,
}
