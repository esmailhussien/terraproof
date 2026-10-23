"""Executable benchmark harness for the `evals/tasks/*.json` specifications.

Run it with `python -m terraproof.evals run`. It builds generated fixtures, runs the real
checks and provenance APIs, compares the results with each spec's `expected_checks`, and
reports false passes, checker blind spots and the acceptance that remains human or external.
"""

from __future__ import annotations

from terraproof.evals.harness import LIMITATIONS, run_benchmark, to_json
from terraproof.evals.specs import SpecError, TaskSpec, load_specs

__all__ = ["LIMITATIONS", "SpecError", "TaskSpec", "load_specs", "run_benchmark", "to_json"]
