"""Offline, deterministic section retrieval informed by inspected dataset profiles."""

from __future__ import annotations

import os
import re
from collections import defaultdict

from .index import PROCESS_SKILLS, get_index
from .signals import data_signals, dataset_summary, process_skills
from .text import expand_query, normalize, tokenize

__all__ = ["find_guidance"]
MIN_SCORE = 5.0
RELATIVE_CUTOFF = 0.5
FALLBACK_MIN_SCORE = 2.5

# Semantic fusion settings. These are module-level so tests can monkeypatch them.
SEMANTIC_WEIGHT = 0.4
SEMANTIC_SCALE = 100.0
SEMANTIC_MIN_SCORE = 0.55
SEMANTIC_TOP_N = 4
SEMANTIC_DELTA = 0.05

# Candidate-mode settings.
CANDIDATE_DEFAULT_TOP_K = 8
CANDIDATE_FLOOR = 2.5


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


def _semantic_enabled(semantic: bool | None) -> bool:
    """Resolve the semantic switch: explicit value wins over TERRAPROOF_SEMANTIC."""
    if semantic is None:
        return os.environ.get("TERRAPROOF_SEMANTIC", "").strip().lower() in {"1", "true", "yes"}
    if not isinstance(semantic, bool):
        raise ValueError("semantic must be a boolean")
    return semantic


def _semantic_scores(index, task: str) -> tuple[dict[tuple[str, str], float], str | None]:
    """Return per-section cosine scores, or fall back with a human-readable warning."""
    try:
        from . import semantic as semantic_module
        return semantic_module.section_scores(index, task), None
    except Exception as exc:  # noqa: BLE001
        return {}, (
            f"semantic retrieval unavailable ({exc}); install terraproof[semantic] "
            f"and run `python -m terraproof.router --download-model`"
        )


def _skill_sections(candidates: list, terms: list[str], sections_per_skill: int) -> list[dict]:
    """Build the display section list for a skill (lexical order)."""
    return [{"id": section.id, "title": section.title, "source": section.source,
             "score": round(section_score, 6), "excerpt": _excerpt(section.text, terms)}
            for section_score, section, _ in candidates[:sections_per_skill]]


def _metadata_terms(name: str, metadata: dict) -> set[str]:
    return set(tokenize(" ".join([name, metadata["explanation"],
                                  *metadata["triggers"], *metadata["capabilities"]])))


def _skill_cutoff(name: str, metadata: dict, terms: set[str], signals: dict, mode: str) -> float:
    """Minimum fused score a skill must reach to be eligible for the result list."""
    supported = bool(_metadata_terms(name, metadata).intersection(terms)) or any(
        value > 0 for value, _ in signals.get(name, [])
    )
    if mode == "candidates":
        return CANDIDATE_FLOOR if supported else 12.0
    return MIN_SCORE if supported else 12.0


def _fuse_semantic(
    name: str,
    lexical_score: float,
    reasons: list[str],
    sem_scores: dict[tuple[str, str], float],
    semantic_pool: set[str],
) -> tuple[float, list[str]]:
    """Optionally blend the best section cosine into the lexical score."""
    if name not in semantic_pool:
        return lexical_score, reasons
    best = max(sem_scores[key] for key in sem_scores if key[0] == name)
    semantic_boost = round(best * SEMANTIC_SCALE, 6)
    fused = round((1 - SEMANTIC_WEIGHT) * lexical_score + SEMANTIC_WEIGHT * semantic_boost, 6)
    reasons = reasons + [
        f"Semantic: cosine={best:.6f} (weight {SEMANTIC_WEIGHT}; scale {SEMANTIC_SCALE:g}) "
        f"+{SEMANTIC_WEIGHT * semantic_boost:.6f}"
    ]
    return fused, reasons


def find_guidance(
    task: str,
    datasets: list[dict] | None = None,
    data_paths: list[str] | None = None,
    top_k: int | None = None,
    sections_per_skill: int = 2,
    mode: str = "ranked",
    semantic: bool | None = None,
) -> dict:
    """Rank or recall non-process skills using BM25, exact triggers, data/wording rules
    and an optional local semantic retrieval pass.

    Score = best section BM25 + .25 * second section BM25 + trigger boosts +
    one-time dataset and wording boosts/penalties. Intent guards always apply.
    In ``ranked`` mode scores below MIN_SCORE are omitted; incidental body-only
    matches need 12. Neighbours below RELATIVE_CUTOFF * top score need a direct
    trigger (not bare 'map') or positive data/intent signal. If no skill passes,
    return only the best directly supported candidate above FALLBACK_MIN_SCORE.
    In ``candidates`` mode the relative cutoff is dropped and the metadata/signal
    floor is lowered to CANDIDATE_FLOOR so the host model can re-rank a broad set.

    The optional semantic pass is controlled by the ``semantic`` argument or the
    ``TERRAPROOF_SEMANTIC`` environment variable. A missing extra, missing model,
    or inference failure falls back to lexical retrieval with a warning reason.
    The scoring top-two is independent of sections_per_skill (a display limit).
    Input profiles are never mutated. Paths are inspected locally, on demand.
    """
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if mode not in {"ranked", "candidates"}:
        raise ValueError("mode must be 'ranked' or 'candidates'")
    for name, value in (("top_k", top_k), ("sections_per_skill", sections_per_skill)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"{name} must be a non-negative integer")
    if top_k is None:
        top_k = CANDIDATE_DEFAULT_TOP_K if mode == "candidates" else 5

    profiles = _profiles(datasets, data_paths)
    query, terms, expansion_reasons = expand_query(task)
    process = process_skills(task)
    index = get_index()
    grouped: dict[str, list] = defaultdict(list)
    for section in index.sections:
        if section.skill not in PROCESS_SKILLS:
            score, reasons = index.score(section, terms)
            grouped[section.skill].append((score, section, reasons))
    signals, guarded = data_signals(profiles, terms, query["normalized"])
    matching_text = " " + normalize(query["normalized"] + " " + " ".join(query["expanded_terms"])) + " "

    semantic_on = _semantic_enabled(semantic)
    sem_scores: dict[tuple[str, str], float] = {}
    semantic_warning: str | None = None
    if semantic_on:
        sem_scores, semantic_warning = _semantic_scores(index, task)

    # Build the semantic candidate pool once.
    semantic_pool: set[str] = set()
    if sem_scores:
        per_skill_sem: dict[str, float] = {}
        for (skill_name, _), value in sem_scores.items():
            per_skill_sem[skill_name] = max(per_skill_sem.get(skill_name, 0.0), value)
        if per_skill_sem:
            max_sem = max(per_skill_sem.values())
            eligible_sem = {
                skill_name: value
                for skill_name, value in per_skill_sem.items()
                if value >= SEMANTIC_MIN_SCORE and value >= max_sem - SEMANTIC_DELTA
            }
            semantic_pool = {
                skill_name
                for skill_name, _ in sorted(
                    eligible_sem.items(), key=lambda item: (-item[1], item[0])
                )[:SEMANTIC_TOP_N]
            }

    term_set = set(terms)
    entries = []
    supported = set()
    eligible = set()
    ranked_eligible = set()
    for name, candidates in sorted(grouped.items()):
        if name in guarded:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1].id))
        lexical_score = 0.0
        has_body = False
        reasons = list(expansion_reasons)
        for position, (section_score, section, contributions) in enumerate(candidates[:2]):
            weight = 1.0 if position == 0 else 0.25
            lexical_score += section_score * weight
            if contributions:
                has_body = True
                breakdown = ", ".join(f"{term}={amount * weight:.6f}" for term, amount in contributions)
                reasons.append(f"BM25 {section.id} (section weight {weight:g}; {breakdown}) +{section_score * weight:.6f}")
        metadata = index.skills[name]
        is_metadata_supported = bool(_metadata_terms(name, metadata).intersection(term_set))
        for trigger in metadata["triggers"]:
            phrase = normalize(trigger)
            if " " + phrase + " " in matching_text:
                boost = 4.0 if " " in phrase else 2.0
                # A bare 'map' is deliberately not a strong web-frontend signal.
                if phrase == "map":
                    boost = 0.5
                lexical_score += boost
                reasons.append(f"Exact trigger '{trigger}' +{boost:.6f}")
                if phrase != "map":
                    supported.add(name)
        for value, reason in signals.get(name, []):
            lexical_score += value
            reasons.append(reason)
            if value > 0:
                supported.add(name)

        if semantic_on:
            score, reasons = _fuse_semantic(name, lexical_score, reasons, sem_scores, semantic_pool)
        else:
            score = lexical_score

        trigger_or_signal_supported = name in supported
        is_supported = trigger_or_signal_supported or is_metadata_supported
        if mode == "candidates":
            # Candidate membership is lexical even when semantic fusion is on:
            # semantic retrieval may reorder/boost, but must not drop a lexical
            # candidate from the host's recall-oriented set.
            candidate_score = lexical_score
            # Guard domain skills that only match metadata/body text when the request
            # is clearly a debug/fix task; keep triggered/signalled skills available.
            debug_metadata_only = (
                "systematic-debugging" in process
                and not trigger_or_signal_supported
                and not has_body
            )
            if debug_metadata_only:
                cutoff = float("inf")
            else:
                cutoff = CANDIDATE_FLOOR if is_supported else 12.0
                if not is_supported and not has_body:
                    cutoff = float("inf")
            if candidate_score >= cutoff:
                eligible.add(name)
        # The ranked selection is computed for both modes: candidates keep the
        # ranked choices first (subset invariant) and fill remaining slots by
        # relevance under the same cap.
        ranked_score = lexical_score if mode == "candidates" else score
        ranked_cutoff = MIN_SCORE if is_supported else 12.0
        debug_metadata_guard = (
            mode == "candidates"
            and "systematic-debugging" in process
            and not trigger_or_signal_supported
            and not has_body
        )
        if ranked_score >= ranked_cutoff and (is_supported or has_body) and not debug_metadata_guard:
            ranked_eligible.add(name)
        sections = _skill_sections(candidates, terms, sections_per_skill)
        skill_entry = {
            "name": name,
            "lexical_score": lexical_score,
            "score": round(score, 6),
            "reasons": reasons,
            "sections": sections,
        }
        if mode == "candidates":
            skill_entry["explanation"] = metadata["explanation"]
        entries.append(skill_entry)

    # Candidate list construction: start with the ranked-kept selection (computed
    # above from ranked_eligible: cutoffs + relative cutoff + fallback) so every
    # ranked choice is preserved, then fill the remaining slots (down to the cap)
    # with candidate-eligible entries by relevance — a broad host re-ranking set,
    # never a precision ranker.
    entries.sort(key=lambda skill: (-skill["score"], skill["name"]))
    if mode == "ranked":
        skills = [skill for skill in entries if skill["name"] in ranked_eligible]
        if skills:
            relative_floor = RELATIVE_CUTOFF * skills[0]["score"]
            skills = [skill for skill in skills if skill["score"] >= relative_floor or skill["name"] in supported]
        else:
            # Never resurrect guarded skills or incidental prose matches. Stable score/
            # name ordering makes the single-candidate fallback deterministic too.
            skills = [skill for skill in entries if skill["name"] in supported
                      and skill["score"] >= FALLBACK_MIN_SCORE][:1]
            if skills:
                skills[0]["reasons"].append(
                    f"Selection: empty-result fallback; direct trigger or data/intent signal, "
                    f"score >= {FALLBACK_MIN_SCORE:g}; no skill met the normal cutoffs +0.000000"
                )
        skills = skills[:top_k]
    else:
        # Preserve the ranked choices as an ordered prefix, then fill the
        # larger recall-oriented candidate cap by deterministic relevance.
        lexical_entries = sorted(entries, key=lambda skill: (-skill["lexical_score"], skill["name"]))
        skills = [skill for skill in lexical_entries if skill["name"] in ranked_eligible]
        if skills:
            relative_floor = RELATIVE_CUTOFF * skills[0]["lexical_score"]
            skills = [skill for skill in skills
                      if skill["lexical_score"] >= relative_floor or skill["name"] in supported]
        else:
            skills = [skill for skill in lexical_entries if skill["name"] in supported
                      and skill["lexical_score"] >= FALLBACK_MIN_SCORE][:1]
        included = {skill["name"] for skill in skills}
        fill = [skill for skill in entries if skill["name"] in eligible and skill["name"] not in included]
        skills = skills + sorted(fill, key=lambda skill: (-skill["score"], skill["name"]))
        skills = skills[:top_k]

    # Remove the internal bookkeeping field before returning.
    for skill in skills:
        skill.pop("lexical_score", None)

    result: dict = {"query": query, "skills": skills, "process": process,
            "datasets": [dataset_summary(ds) for ds in profiles]}
    if semantic_warning:
        result["reasons"] = [semantic_warning]
    return result


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
