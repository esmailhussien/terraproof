"""Read-only access to the registered skills: the catalogue and one section's text.

Nothing here imports the MCP SDK, so the installer can reuse the same registry lookups.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from terraproof._common import assets_root

# Section ids and skill names come from the registry, never from a filesystem lookup,
# but they still must not be able to name a path.
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SectionError(ValueError):
    """An unknown skill or section, or a section source that escapes the skill directory."""


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    """The skill metadata from `routing/registry.json`, keyed by skill name."""
    path = assets_root() / "routing" / "registry.json"
    return json.loads(path.read_text(encoding="utf-8"))["skills"]


def skill_directory(name: str) -> Path:
    """The directory of a registered skill."""
    return assets_root() / registry()[name]["path"]


def markdown_sections(text: str) -> dict[str, str]:
    """The body of every `##` heading, keyed by its GitHub-style anchor.

    This mirrors the anchor convention the registry is generated with
    (`routing/SKILL_MANIFEST.md`): lowercase, punctuation removed, spaces become
    hyphens, and repeats get `-1`, `-2`. Headings inside fenced code are not sections.
    """
    bodies: dict[str, str] = {}
    seen: Counter[str] = Counter()
    current = None
    lines: list[str] = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
        heading = re.match(r"^##\s+(.+?)\s*#*\s*$", line) if fence is None else None
        if heading:
            if current is not None:
                bodies[current] = "\n".join(lines).strip()
            anchor = re.sub(r"[^\w\s-]", "", heading.group(1).lower()).replace(" ", "-")
            count = seen[anchor]
            seen[anchor] += 1
            current = f"{anchor}-{count}" if count else anchor
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        bodies[current] = "\n".join(lines).strip()
    return bodies


def list_skills() -> list[dict]:
    """Every registered skill with its layer, explanation, sections, and checks."""
    skills = registry()
    return [
        {
            "name": name,
            "layer": skills[name]["layer"],
            "explanation": skills[name]["explanation"],
            "sections": [{"id": section["id"], "title": section["title"]}
                         for section in skills[name]["sections"]],
            "checks": list(skills[name]["checks"]),
        }
        for name in sorted(skills)
    ]


def load_section(skill: str, section_id: str) -> dict:
    """Return one section's Markdown text.

    Raises SectionError for an unknown skill or section, or for a source that would
    resolve outside `skills/<skill>/`.
    """
    for label, value in (("skill", skill), ("section", section_id)):
        if not isinstance(value, str) or not IDENTIFIER.match(value):
            raise SectionError(f"invalid {label} name: {value!r}")
    skills = registry()
    if skill not in skills:
        raise SectionError(f"unknown skill: {skill!r}")
    metadata = skills[skill]
    section = next((item for item in metadata["sections"] if item["id"] == section_id), None)
    if section is None:
        known = ", ".join(item["id"] for item in metadata["sections"]) or "none"
        raise SectionError(f"unknown section {section_id!r} for skill {skill!r}; known sections: {known}")

    directory = (assets_root() / metadata["path"]).resolve()
    source = section["source"]
    if source.startswith("SKILL.md#"):
        anchor = source.split("#", 1)[1]
        text = markdown_sections((directory / "SKILL.md").read_text(encoding="utf-8")).get(anchor)
        if text is None:
            raise SectionError(f"section {section_id!r} has no '## {section['title']}' heading in {skill}/SKILL.md")
    else:
        path = (directory / source).resolve()
        if directory not in path.parents:
            raise SectionError(f"section {section_id!r} of {skill!r} resolves outside its skill directory")
        if not path.is_file():
            raise SectionError(f"section {section_id!r} of {skill!r} has no source file: {source}")
        text = path.read_text(encoding="utf-8")

    return {
        "skill": skill,
        "section_id": section_id,
        "title": section["title"],
        "source": source,
        "text": text,
    }
