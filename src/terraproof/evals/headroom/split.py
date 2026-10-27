"""The seeded development/confirmation split of the headroom pool (Phase 6 E1).

The split is a function of the pool's ids and trap families and of SPLIT_SEED only. It was
made before any recipe, oracle or agent run existed for these tasks and is frozen in
`evals/headroom/split.json`; a test proves the file is this function's output.
"""

from __future__ import annotations

import json
import random

SPLIT_SEED = 20261027
DEVELOPMENT_FRACTION = 3  # one task in three per family goes to development


def make_split(pool: list[dict], seed: int = SPLIT_SEED) -> dict:
    """Stratified by family: shuffle each family's sorted ids with one seeded stream, take the first third."""
    families: dict[str, list[str]] = {}
    for task in pool:
        families.setdefault(task["family"], []).append(task["id"])
    rng = random.Random(seed)
    development, confirmation, counts = [], [], {}
    for family in sorted(families):
        ids = sorted(families[family])
        if len(ids) % DEVELOPMENT_FRACTION:
            raise ValueError(f"family {family!r} has {len(ids)} tasks; a stratified third needs a multiple of 3")
        rng.shuffle(ids)
        take = len(ids) // DEVELOPMENT_FRACTION
        development += ids[:take]
        confirmation += ids[take:]
        counts[family] = {"development": take, "confirmation": len(ids) - take}
    return {"seed": seed, "method": "per-family shuffle of sorted ids with random.Random(seed), first third to development",
            "development": sorted(development), "confirmation": sorted(confirmation), "family_counts": counts}


def to_json(split: dict) -> str:
    return json.dumps(split, indent=2, sort_keys=True) + "\n"
