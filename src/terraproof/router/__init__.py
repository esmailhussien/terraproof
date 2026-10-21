"""Offline, deterministic section retrieval informed by inspected dataset profiles."""

from __future__ import annotations

import re
from collections import defaultdict

from .index import PROCESS_SKILLS, get_index
from .signals import data_signals, dataset_summary, process_skills
from .text import expand_query, normalize, tokenize

__all__ = ["find_guidance"]
MIN_SCORE = 5.0


def _profiles(datasets: list[dict] | None, data_paths: list[str] | None) -> list[dict]:
    if datasets is not None and not isinstance(datasets, list):
        raise ValueError("datasets must be a list of inspection profiles")
    profiles = list(datasets or [])
    if data_paths is not None:
        if not isinstance(data_paths, list) or any(not isinstance(path, str) for path in data_paths):
            raise ValueError("data_paths must be a list of paths")
        # Keep geospatial/native dependencies out of text-only retrieval imports.
        if data_paths:
            from terraproof.inspect import inspect_dataset
            profiles.extend(inspect_dataset(path) for path in data_paths)
    for ds in profiles:
        if not isinstance(ds, dict) or ds.get("kind") not in {"vector", "raster", "stac"}:
            raise ValueError("each dataset needs kind vector, raster, or stac")
        if ds.get("crs") is not None and not isinstance(ds["crs"], dict):
            raise ValueError("dataset crs must be an inspection dictionary or null")
        if ds.get("bands") is not None and (not isinstance(ds["bands"], list)
                                            or any(not isinstance(band, dict) for band in ds["bands"])):
            raise ValueError("dataset bands must be a list of band dictionaries")
        if ds.get("geometry_types") is not None and (not isinstance(ds["geometry_types"], list)
                                                     or any(not isinstance(value, str) for value in ds["geometry_types"])):
            raise ValueError("geometry_types must be a list of names")
    return profiles


def _excerpt(text: str, terms: list[str], limit: int = 480) -> str:
    """Return a compact, real-text window near a matching query term."""
    compact = re.sub(r"\s+", " ", text).strip()
    term_set = set(terms)
    start = 0
    for match in re.finditer(r"\w+", compact):
        if term_set.intersection(tokenize(match.group())):
            start = max(0, match.start() - 80)
            break
    end = start + limit
    return ("…" if start else "") + compact[start:end] + ("…" if len(compact) > end else "")


def find_guidance(
    task: str,
    datasets: list[dict] | None = None,
    data_paths: list[str] | None = None,
    top_k: int = 5,
    sections_per_skill: int = 2,
) -> dict:
    """Rank non-process skills using BM25 sections, exact triggers and data/wording rules.

    Score = best section BM25 + .25 * second section BM25 + trigger boosts +
    one-time dataset and wording boosts/penalties. Scores below MIN_SCORE are omitted;
    incidental body-only matches without metadata/data support need at least 12.
    The scoring top-two is independent of sections_per_skill (a display limit).
    Input profiles are never mutated. Paths are inspected locally, on demand.
    """
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    for name, value in (("top_k", top_k), ("sections_per_skill", sections_per_skill)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    profiles = _profiles(datasets, data_paths)
    query, terms, expansion_reasons = expand_query(task)
    index = get_index()
    grouped: dict[str, list] = defaultdict(list)
    for section in index.sections:
        if section.skill not in PROCESS_SKILLS:
            score, reasons = index.score(section, terms)
            grouped[section.skill].append((score, section, reasons))
    signals = data_signals(profiles, terms, query["normalized"])
    matching_text = " " + normalize(query["normalized"] + " " + " ".join(query["expanded_terms"])) + " "
    skills = []
    for name, candidates in sorted(grouped.items()):
        candidates.sort(key=lambda item: (-item[0], item[1].id))
        score = 0.0
        reasons = []
        for position, (section_score, section, contributions) in enumerate(candidates[:2]):
            weight = 1.0 if position == 0 else 0.25
            score += section_score * weight
            if contributions:
                breakdown = ", ".join(f"{term}={amount * weight:.6f}" for term, amount in contributions)
                reasons.append(f"BM25 {section.id} (section weight {weight:g}; {breakdown}) +{section_score * weight:.6f}")
        for trigger in index.skills[name]["triggers"]:
            phrase = normalize(trigger)
            if " " + phrase + " " in matching_text:
                boost = 4.0 if " " in phrase else 2.0
                # A bare 'map' is deliberately not a strong web-frontend signal.
                if phrase == "map":
                    boost = 0.5
                score += boost
                reasons.append(f"Exact trigger '{trigger}' +{boost:.6f}")
        for value, reason in signals.get(name, []):
            score += value
            reasons.append(reason)
        metadata = index.skills[name]
        metadata_terms = set(tokenize(" ".join([name, metadata["explanation"],
                                                *metadata["triggers"], *metadata["capabilities"]])))
        # Incidental prose/code words need stronger evidence than skill metadata.
        # This avoids promoting graph/map examples for an ordinary line chart.
        cutoff = MIN_SCORE if metadata_terms.intersection(terms) or any(value > 0 for value, _ in signals.get(name, [])) else 12.0
        if score < cutoff:
            continue
        sections = [{"id": section.id, "title": section.title, "source": section.source,
                     "score": round(section_score, 6), "excerpt": _excerpt(section.text, terms)}
                    for section_score, section, _ in candidates[:sections_per_skill]]
        skills.append({"name": name, "score": round(score, 6),
                       "reasons": expansion_reasons + reasons, "sections": sections})
    skills.sort(key=lambda skill: (-skill["score"], skill["name"]))
    return {"query": query, "skills": skills[:top_k], "process": process_skills(task),
            "datasets": [dataset_summary(ds) for ds in profiles]}


def render_markdown(result: dict) -> str:
    """Small CLI view; JSON remains the stable machine-readable API."""
    lines = ["# Terraproof guidance", "", f"Task: {result['query']['text']}", "",
             f"Language: {result['query']['language']}", "",
             "Process: " + ", ".join(result["process"]), ""]
    for ds in result["datasets"]:
        lines.append(f"Dataset: {ds['path'] or '(profile)'} — {ds['summary']}")
    if not result["skills"]:
        lines.extend(["No skills met the minimum relevance score.", ""])
    for skill in result["skills"]:
        lines.extend([f"## {skill['name']} ({skill['score']:.3f})", "", "Reasons:"])
        lines.extend(f"- {reason}" for reason in skill["reasons"])
        lines.extend(["", "Top sections:"])
        for section in skill["sections"]:
            lines.extend([f"- {section['title']} — `{section['source']}` ({section['score']:.3f})",
                          f"  {section['excerpt']}"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
