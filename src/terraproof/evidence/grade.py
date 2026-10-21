"""Evidence grade: maps check results to one of three grades."""

from __future__ import annotations

from terraproof.checks.base import FAIL, NOT_RUN, WARN, CheckResult

DECISION = "decision-grade"
REVIEW = "review-required"
ADVISORY = "advisory-only"

# Process exit status for each grade (usage errors and unreadable inputs use 1).
EXIT_CODES = {DECISION: 0, REVIEW: 2, ADVISORY: 3}


def grade_for(results: list[CheckResult]) -> str:
    """Decision-grade: every check passed. Review required: warnings only.
    Advisory only: any failure or any check that could not run. A run with no checks is Advisory only,
    because nothing was verified."""
    statuses = {result.status for result in results}
    if not results or statuses & {FAIL, NOT_RUN}:
        return ADVISORY
    if WARN in statuses:
        return REVIEW
    return DECISION
