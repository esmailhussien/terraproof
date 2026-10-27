"""The Phase 6 headroom cohort: 36 candidate tasks, kept apart from the frozen benchmark.

Specs live in `evals/headroom/tasks.json`, not `evals/tasks`, so `python -m terraproof.evals run`
still reports the historical 33 tasks. The pool, its trap families and the seeded
development/confirmation split were fixed first (`pool.json`, `split.json`); this module only
reads them. The lift harness builds its `LiftTask`s from `LIFT_TASK_FIELDS`.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from terraproof.evals.specs import EXPECTED_CHECK_STATUSES, SpecError, TaskSpec, catalog_check_ids, repo_root

COHORT = "headroom"
SPEC_KEYS = frozenset({"id", "family", "skill", "prompt", "inputs", "acceptance", "expected_checks", "pitfall", "lift"})


def spec_dir() -> Path:
    return repo_root() / "evals" / "headroom"


def _document(name: str) -> dict:
    return json.loads((spec_dir() / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def tasks() -> tuple[dict, ...]:
    """The validated task records, in pool order."""
    path = spec_dir() / "tasks.json"
    records = _document("tasks.json")["tasks"]
    pool = [(t["id"], t["family"]) for t in _document("pool.json")["tasks"]]
    if [(t.get("id"), t.get("family")) for t in records] != pool:
        raise SpecError(f"{path}: task ids and families must match pool.json exactly, in order")
    allowed = catalog_check_ids()
    for record in records:
        if set(record) != SPEC_KEYS:
            raise SpecError(f"{path}: {record.get('id')}: keys must be exactly {sorted(SPEC_KEYS)}")
        for check_id, status in record["expected_checks"].items():
            if check_id not in allowed or status not in EXPECTED_CHECK_STATUSES:
                raise SpecError(f"{path}: {record['id']}: bad expected check {check_id}={status}")
        lift = record["lift"]
        names = {name for name, _ in lift["deliverables"]}
        if not lift["seeded"] or any(target not in names for target, _ in lift["seeded"]):
            raise SpecError(f"{path}: {record['id']}: every seeded output must replace a declared deliverable")
    return tuple(records)


def specs() -> dict[str, TaskSpec]:
    path = spec_dir() / "tasks.json"
    return {t["id"]: TaskSpec(skill=t["skill"], id=t["id"], prompt=t["prompt"], inputs=t["inputs"],
                              acceptance=tuple(t["acceptance"]), expected_checks=dict(t["expected_checks"]),
                              pitfall=t["pitfall"], path=path) for t in tasks()}


def frozen_split() -> dict:
    return _document("split.json")


def lift_task_fields(task_ids: list[str]) -> tuple[tuple, ...]:
    """(task_id, inputs, deliverables, seeded) for LiftTask, in the order given."""
    by_id = {t["id"]: t["lift"] for t in tasks()}
    return tuple((task_id, tuple(by_id[task_id]["inputs"]),
                  tuple(tuple(item) for item in by_id[task_id]["deliverables"]),
                  tuple(tuple(item) for item in by_id[task_id]["seeded"])) for task_id in task_ids)


def recipe_registry() -> dict:
    from terraproof.evals.headroom.recipes import RECIPES

    return RECIPES
