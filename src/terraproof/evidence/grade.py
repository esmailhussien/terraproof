"""Evidence grade: maps check results, and declared coverage when there is one, to a grade."""

from __future__ import annotations

from terraproof.checks.base import FAIL, NOT_RUN, WARN, CheckResult

DECISION = "decision-grade"
CHECKS_PASSED = "checks-passed"
REVIEW = "review-required"
ADVISORY = "advisory-only"

# Process exit status for each grade (usage errors and unreadable inputs use 1).
EXIT_CODES = {DECISION: 0, CHECKS_PASSED: 0, REVIEW: 2, ADVISORY: 3}


def grade_for(results: list[CheckResult]) -> str:
    """The grade the checks that ran support on their own.

    Checks passed: every check passed. It never means decision-grade: that needs declared coverage
    that was fully verified (a verification contract). Review required: warnings only. Advisory
    only: any failure or any check that could not run. A run with no checks is Advisory only,
    because nothing was verified."""
    statuses = {result.status for result in results}
    if not results or statuses & {FAIL, NOT_RUN}:
        return ADVISORY
    if WARN in statuses:
        return REVIEW
    return CHECKS_PASSED
