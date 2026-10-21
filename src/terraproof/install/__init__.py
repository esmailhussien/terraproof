"""Install Terraproof skills and the MCP server into an agent's own project format.

Usage:
    python -m terraproof.install --agent claude --skills gdal,crs-and-units --target DIR [--with-mcp] [--dry-run]
    python -m terraproof.install --agent cursor --task "NDVI change for 2020-2024" --target DIR

The formats, and the documentation each was verified against, are in `agents.py`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from terraproof._common import InputError, assets_root
from terraproof.install.agents import PLANNERS, InstallError, Skill, Write

EXIT_USAGE = 1
AGENTS = tuple(sorted(PLANNERS))


class _Parser(argparse.ArgumentParser):
    """Exit with status 1 on usage errors, as the other Terraproof entry points do."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m terraproof.install",
        description="Install Terraproof skills, and optionally the MCP server, into one agent's project format.",
    )
    parser.add_argument("--agent", required=True, choices=AGENTS, metavar="AGENT",
                        help=f"target agent: {', '.join(AGENTS)}")
    parser.add_argument("--skills", metavar="a,b,c", help="comma-separated skill names from routing/registry.json")
    parser.add_argument("--task", metavar="TEXT",
                        help="task description to route instead of naming skills")
    parser.add_argument("--target", required=True, metavar="PROJECT_DIR", help="project directory to install into")
    parser.add_argument("--with-mcp", action="store_true", help="also register the Terraproof MCP server")
    parser.add_argument("--dry-run", action="store_true", help="print the planned writes and change nothing")
    return parser


def _registry() -> dict[str, dict]:
    path = assets_root() / "routing" / "registry.json"
    return json.loads(path.read_text(encoding="utf-8"))["skills"]


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a `---` YAML block holding simple `key: value` fields from the Markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        fields: dict[str, str] = {}
        key = None
        for line in lines[1:index]:
            match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
            if match:
                key = match.group(1)
                fields[key] = match.group(2).strip()
            elif key and line.strip():
                fields[key] += " " + line.strip()
        return fields, "\n".join(lines[index + 1:]).lstrip("\n")
    return {}, text


def _load_skill(name: str, metadata: dict) -> Skill:
    directory = assets_root() / metadata["path"]
    frontmatter, body = _split_frontmatter((directory / "SKILL.md").read_text(encoding="utf-8"))
    return Skill(
        name=name,
        directory=directory,
        layer=metadata["layer"],
        explanation=metadata["explanation"],
        description=frontmatter.get("description", ""),
        body=body,
        sections=tuple({"id": section["id"], "title": section["title"]} for section in metadata["sections"]),
        checks=tuple(metadata["checks"]),
    )


def resolve_skill_names(skills: str | None, task: str | None) -> list[str]:
    """Skill names from `--skills`, or the ones the router finds for `--task`."""
    registry = _registry()
    if skills and task:
        raise InstallError("use --skills or --task, not both")
    if not skills and not task:
        raise InstallError('give --skills "a,b,c" or --task "<text>"')
    if task:
        try:
            from terraproof.router import find_guidance
        except Exception as exc:  # any import failure of the optional router package
            raise InstallError(f"--task needs the Terraproof router, which is unavailable here ({exc})") from exc
        try:
            guidance = find_guidance(task)
        except Exception as exc:
            raise InstallError(f"cannot route the task {task!r}: {exc}") from exc
        names = [skill["name"] for skill in guidance["skills"]]
        if not names:
            raise InstallError(f"the router ranked no skills for the task {task!r}; name skills with --skills")
    else:
        names = []
        for item in (skills or "").split(","):
            name = item.strip()
            if name and name not in names:
                names.append(name)
        if not names:
            raise InstallError("--skills held no skill names")

    unknown = [name for name in names if name not in registry]
    if unknown:
        raise InstallError(
            "unknown skill(s): " + ", ".join(unknown)
            + f"; the registry has {', '.join(sorted(registry))}"
        )
    return names


def _relative(path: Path, target: Path) -> str:
    resolved = path.resolve()
    if resolved != target and target not in resolved.parents:
        raise InstallError(f"refusing to write outside the target project: {resolved}")
    return resolved.relative_to(target).as_posix()


def apply(writes: list[Write], target: Path, *, dry_run: bool) -> int:
    """Write the planned files and return how many changed."""
    changed = 0
    for write in sorted(writes, key=lambda item: str(item.path)):
        relative = _relative(write.path, target)
        existing = write.path.read_bytes() if write.path.is_file() else None
        status = "unchanged" if existing == write.content else ("update" if existing is not None else "create")
        if status != "unchanged":
            changed += 1
            if not dry_run:
                write.path.parent.mkdir(parents=True, exist_ok=True)
                write.path.write_bytes(write.content)
        prefix = "would " if dry_run else ""
        print(f"{prefix}{status:<9} {relative}  ({write.note})")
    return changed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = Path(args.target)
    try:
        if not target.is_dir():
            raise InstallError(f"target is not a directory: {target}")
        target = target.resolve()
        names = resolve_skill_names(args.skills, args.task)
        registry = _registry()
        skills = [_load_skill(name, registry[name]) for name in names]
        command = [sys.executable or "python", "-m", "terraproof.mcp"]
        writes = PLANNERS[args.agent](target, skills, with_mcp=args.with_mcp, command=command)
        print(f"terraproof install: agent={args.agent} target={target.as_posix()} skills={', '.join(names)}")
        if args.with_mcp:
            print("terraproof install: MCP server command: " + " ".join(command))
        changed = apply(writes, target, dry_run=args.dry_run)
        suffix = " (dry run: nothing written)" if args.dry_run else ""
        print(f"terraproof install: {len(writes)} file(s) planned, {changed} changed{suffix}")
        return 0
    except (InstallError, InputError, OSError) as exc:
        print(f"terraproof install: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
