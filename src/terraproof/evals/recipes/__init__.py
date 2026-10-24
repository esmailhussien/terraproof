"""Recipe registry: every task id in `evals/tasks` must map to exactly one fixture recipe."""

from __future__ import annotations

from terraproof.evals.recipes import accuracy, crs, indices, raster, sar, satellite, stac, timeseries, vector, harder
from terraproof.evals.specs import SpecError

_MODULES = (accuracy, crs, indices, raster, sar, satellite, stac, timeseries, vector, harder)


def build_registry() -> dict:
    registry: dict = {}
    for module in _MODULES:
        for task_id, function in module.RECIPES.items():
            if task_id in registry:
                raise SpecError(f"duplicate recipe for task id '{task_id}'")
            registry[task_id] = function
    return registry


REGISTRY = build_registry()


def validate_registry(spec_ids) -> None:
    """Reject recipes that no spec names; a spec without a recipe is reported as unrunnable."""
    orphans = sorted(set(REGISTRY) - set(spec_ids))
    if orphans:
        raise SpecError(f"recipes registered for tasks that are not in the specs: {orphans}")
