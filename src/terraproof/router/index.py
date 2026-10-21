"""Read and cache the real skill sections, with a small standard-library BM25 index."""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .text import tokenize

PROCESS_SKILLS = frozenset({"brainstorming", "writing-plans", "systematic-debugging", "verification"})


def find_root() -> Path:
    """Locate source-checkout assets or installed package/share assets, not the cwd."""
    package = Path(__file__).resolve().parents[1]
    candidates = [package, package / "data", package / "_data", package / "resources",
                  Path(sys.prefix) / "share" / "terraproof", *package.parents]
    for candidate in candidates:
        if (candidate / "routing" / "registry.json").is_file() and (candidate / "skills").is_dir():
            return candidate
    raise FileNotFoundError("Terraproof routing/registry.json and skills assets not found beside the package or in share/terraproof")


def markdown_sections(text: str) -> dict[str, str]:
    """Extract ## bodies with GitHub anchors; ignore headings inside fenced code."""
    bodies: dict[str, str] = {}
    seen: Counter = Counter()
    current = None
    lines: list[str] = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
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


@dataclass(frozen=True)
class Section:
    skill: str
    id: str
    title: str
    source: str
    text: str
    frequencies: Counter
    length: int


@dataclass(frozen=True)
class Index:
    skills: dict
    sections: tuple[Section, ...]
    idf: dict[str, float]
    average_length: float

    def score(self, section: Section, terms: list[str]) -> tuple[float, list[tuple[str, float]]]:
        """BM25 k1=1.5, b=.75; binary query frequency prevents expansion repetition."""
        contributions = []
        for term in terms:
            frequency = section.frequencies.get(term, 0)
            if frequency:
                denominator = frequency + 1.5 * (0.25 + 0.75 * section.length / self.average_length)
                contributions.append((term, self.idf[term] * frequency * 2.5 / denominator))
        total = sum(value for _, value in contributions)
        return total, contributions


@lru_cache(maxsize=1)
def get_index() -> Index:
    root = find_root()
    skills = json.loads((root / "routing" / "registry.json").read_text(encoding="utf-8"))["skills"]
    sections = []
    for name, skill in sorted(skills.items()):
        directory = root / skill["path"]
        bodies = markdown_sections((directory / "SKILL.md").read_text(encoding="utf-8"))
        metadata = " ".join([name, skill["explanation"], *skill["triggers"], *skill["capabilities"]])
        for description in skill["sections"]:
            source = description["source"]
            if source.startswith("SKILL.md#"):
                anchor = source.split("#", 1)[1]
                if anchor not in bodies:
                    raise ValueError(f"Missing section {name}/{source}")
                text = bodies[anchor]
            else:
                # Registry is local trusted metadata, but never permit traversal.
                path = (directory / source).resolve()
                if directory.resolve() not in path.parents:
                    raise ValueError(f"Section escapes skill directory: {source}")
                text = path.read_text(encoding="utf-8")
            frequencies = Counter(tokenize(description["title"] + " " + text + " " + metadata))
            sections.append(Section(name, description["id"], description["title"], source, text,
                                    frequencies, sum(frequencies.values())))
    ranked = [section for section in sections if section.skill not in PROCESS_SKILLS]
    document_frequency: Counter = Counter()
    for section in ranked:
        document_frequency.update(section.frequencies.keys())
    count = len(ranked)
    idf = {term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
           for term, frequency in document_frequency.items()}
    return Index(skills, tuple(sections), idf, sum(section.length for section in ranked) / count)
