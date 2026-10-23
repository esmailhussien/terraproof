"""Benchmark specification loading and validation for `python -m terraproof.evals`.

The specs under `evals/tasks/*.json` are the contract: this module validates them against
the check catalog in `routing/checks.json` and never invents ids. A spec that cannot be
used raises SpecError instead of being skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TASK_KEYS = frozenset({"id", "prompt", "inputs", "acceptance", "expected_checks", "pitfall"})
SPEC_KEYS = frozenset({"skill", "tasks"})
EXPECTED_CHECK_STATUSES = frozenset({"pass", "warn", "fail"})
TASKS_PER_SPEC = 3


class SpecError(ValueError):
    """A benchmark spec, a check catalog, or the recipe registry is inconsistent."""


@dataclass(frozen=True)
class TaskSpec:
    """One validated task spec, with the file it came from."""

    skill: str
    id: str
    prompt: str
    inputs: str
    acceptance: tuple[str, ...]
    expected_checks: dict[str, str]
    pitfall: str
    path: Path

    @property
    def spec_file(self) -> str:
        return self.path.name


def repo_root() -> Path:
    """The checkout root that holds `evals/` and `routing/` (src/terraproof/evals/specs.py -> 4 up)."""
    return Path(__file__).resolve().parents[3]


def default_spec_dir() -> Path:
    return repo_root() / "evals" / "tasks"


def catalog_path() -> Path:
    path = repo_root() / "routing" / "checks.json"
    if not path.is_file():
        raise SpecError(f"check catalog not found: {path}")
    return path


def catalog_check_ids() -> set[str]:
    """The check ids the repository catalog registers. The harness accepts no other ids."""
    data = json.loads(catalog_path().read_text(encoding="utf-8"))
    checks = data.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise SpecError(f"{catalog_path()} has no non-empty 'checks' mapping")
    return set(checks)


def _text(value: object, field: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"{where}: '{field}' must be a non-empty string")
    return value


def _load_spec(path: Path, allowed: set[str]) -> list[TaskSpec]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SpecError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(document, dict) or set(document) != SPEC_KEYS:
        raise SpecError(f"{path}: top-level keys must be exactly {sorted(SPEC_KEYS)}")
    skill = _text(document["skill"], "skill", str(path))
    if skill != path.stem:
        raise SpecError(f"{path}: skill '{skill}' must equal the file stem '{path.stem}'")
    tasks = document["tasks"]
    if not isinstance(tasks, list) or len(tasks) != TASKS_PER_SPEC:
        raise SpecError(f"{path}: expected exactly {TASKS_PER_SPEC} tasks")
    specs = []
    for index, task in enumerate(tasks):
        where = f"{path}: tasks[{index}]"
        if not isinstance(task, dict) or set(task) != TASK_KEYS:
            raise SpecError(f"{where}: keys must be exactly {sorted(TASK_KEYS)}")
        task_id = _text(task["id"], "id", where)
        acceptance = task["acceptance"]
        if not isinstance(acceptance, list) or not acceptance:
            raise SpecError(f"{where}: 'acceptance' must be a non-empty list")
        for criterion in acceptance:
            _text(criterion, "acceptance[]", where)
        expected = task["expected_checks"]
        if not isinstance(expected, dict) or not expected:
            raise SpecError(f"{where}: 'expected_checks' must be a non-empty mapping")
        clean_expected = {}
        for check_id, status in expected.items():
            if check_id not in allowed:
                raise SpecError(f"{where}: check id '{check_id}' is not registered in {catalog_path()}")
            if status not in EXPECTED_CHECK_STATUSES:
                raise SpecError(f"{where}: status '{status}' for '{check_id}' is not one of {sorted(EXPECTED_CHECK_STATUSES)}")
            clean_expected[check_id] = status
        specs.append(
            TaskSpec(
                skill=skill,
                id=task_id,
                prompt=_text(task["prompt"], "prompt", where),
                inputs=_text(task["inputs"], "inputs", where),
                acceptance=tuple(acceptance),
                expected_checks=clean_expected,
                pitfall=_text(task["pitfall"], "pitfall", where),
                path=path,
            )
        )
    return specs


def load_specs(spec_dir: Path | str | None = None) -> list[TaskSpec]:
    """Load and validate every spec file. Duplicate task ids or a missing id fail loudly."""
    directory = Path(spec_dir) if spec_dir is not None else default_spec_dir()
    if not directory.is_dir():
        raise SpecError(f"spec directory not found: {directory}")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise SpecError(f"no spec files under {directory}")
    allowed = catalog_check_ids()
    specs: list[TaskSpec] = []
    seen: dict[str, Path] = {}
    for path in files:
        for spec in _load_spec(path, allowed):
            if spec.id in seen:
                raise SpecError(f"duplicate task id '{spec.id}' in {seen[spec.id]} and {path}")
            seen[spec.id] = path
            specs.append(spec)
    return specs
