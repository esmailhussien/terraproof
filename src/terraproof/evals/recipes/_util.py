"""Shared helpers for the benchmark recipes."""

from __future__ import annotations

from pathlib import Path

from terraproof.checks import run_checks
from terraproof.checks.base import CheckResult
from terraproof.evals.fixtures import write_csv
from terraproof.evals.harness import Control, Step, TaskRecipe, CORRECT, WRONG
from terraproof.evals.oracles import Oracle
from terraproof.inspect import inspect_dataset
from terraproof.provenance import verify_manifest, write_manifest

import json


def check_step(command: str, inputs: list[str], *, compare_to: str | None = None, **params) -> Step:
    """Model one invocation of the public `run_checks` dispatcher."""
    inspections = [inspect_dataset(path) for path in inputs]
    compare = inspect_dataset(compare_to) if compare_to is not None else None
    results = run_checks(inspections, compare_to=compare, **params)
    return Step(command=command, results=results)


def write_manifest_file(
    manifest_path: Path,
    *,
    inputs: list[str],
    outputs: list[str],
    parameters: dict | None = None,
    stac_items: list[str] | None = None,
    command_line: list[str] | None = None,
) -> dict:
    """Build a manifest with the public API and persist it, as the provenance CLI does."""
    manifest = write_manifest(
        inputs,
        outputs,
        parameters=parameters or {},
        stac_items=stac_items,
        manifest_path=manifest_path,
        command_line=command_line or ["python", "-m", "terraproof.evals", "run"],
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def manifest_step(
    command: str,
    root: Path,
    *,
    inputs: list[str],
    outputs: list[str],
    parameters: dict | None = None,
    stac_items: list[str] | None = None,
    manifest_name: str = "run.manifest.json",
) -> Step:
    """Write a provenance manifest with the public API and verify it in the same step."""
    manifest_path = root / manifest_name
    write_manifest_file(manifest_path, inputs=inputs, outputs=outputs, parameters=parameters, stac_items=stac_items)
    verify_result: CheckResult = verify_manifest(manifest_path)
    return Step(command=command, results=[verify_result])


def stream(text: str) -> str:
    return " ".join(text.split())


def results_for(steps: list[Step], check_id: str) -> list[CheckResult]:
    """Every result with this id, in step order (multi-input checks emit one result per input)."""
    return [result for step in steps for result in step.results if result.id == check_id]


def correct(name: str, description: str, steps: list[Step], oracle: Oracle, notes: str = "") -> Control:
    return Control(name=name, kind=CORRECT, description=stream(description), steps=steps, oracle=oracle, notes=stream(notes))


def wrong(name: str, description: str, steps: list[Step], oracle: Oracle, notes: str = "") -> Control:
    return Control(name=name, kind=WRONG, description=stream(description), steps=steps, oracle=oracle, notes=stream(notes))


def recipe(
    task_id: str,
    correct_control: Control,
    wrong_controls: list[Control],
    *,
    automated_scope: list[str],
    remaining: list[str],
    notes: list[str] | None = None,
) -> TaskRecipe:
    return TaskRecipe(
        task_id=task_id,
        correct=correct_control,
        wrong=wrong_controls,
        automated_scope=[stream(item) for item in automated_scope],
        remaining_requirements=[stream(item) for item in remaining],
        notes=[stream(item) for item in (notes or [])],
    )


def sample_csv(path: Path, matrix: dict[str, dict[str, int]], reference_classes: list[str]) -> str:
    """Write a reference-sample CSV from an explicit map-by-reference count matrix."""
    rows = []
    for map_class in sorted(matrix):
        for reference_class in reference_classes:
            for _ in range(matrix[map_class].get(reference_class, 0)):
                rows.append([map_class, reference_class])
    return write_csv(path, ["map_class", "ref_class"], rows)


def weighted_sample_csv(
    path: Path,
    matrix: dict[str, dict[str, int]],
    reference_classes: list[str],
    stratum_weights: dict[str, float],
) -> str:
    """Write a reference-sample CSV that also records each stratum's mapped-area weight."""
    rows = []
    for map_class in sorted(matrix):
        for reference_class in reference_classes:
            for _ in range(matrix[map_class].get(reference_class, 0)):
                rows.append([map_class, reference_class, f"{stratum_weights[map_class]:.6f}"])
    return write_csv(path, ["map_class", "ref_class", "stratum_weight"], rows)
