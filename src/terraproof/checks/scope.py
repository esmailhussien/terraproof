"""Scope checks: scope.record_count compares output and input feature counts."""

from __future__ import annotations

from terraproof.checks.base import NOT_RUN, PASS, WARN, result


def check_record_count(vectors: list[dict], compare_to: dict) -> list:
    if not vectors:
        return [
            result(
                "scope.record_count",
                NOT_RUN,
                f"No vector output to count against --compare-to {compare_to['path']}.",
                compare_to=compare_to["path"],
            )
        ]
    if compare_to["kind"] != "vector":
        return [
            result(
                "scope.record_count",
                NOT_RUN,
                f"--compare-to {compare_to['path']} is not a vector dataset; record counts cannot be compared.",
                compare_to=compare_to["path"],
            )
        ]

    results = []
    compare_count = compare_to["feature_count"]
    for dataset in vectors:
        output_count = dataset["feature_count"]
        difference = output_count - compare_count
        evidence = {
            "output": dataset["path"],
            "compare_to": compare_to["path"],
            "output_count": output_count,
            "compare_count": compare_count,
            "difference": difference,
        }
        if difference == 0:
            status = PASS
            message = f"{dataset['path']} keeps all {compare_count} records of {compare_to['path']}."
        elif difference < 0:
            status = WARN
            message = (
                f"{dataset['path']} has {output_count} records, {-difference} fewer than "
                f"{compare_to['path']} ({compare_count})."
            )
        else:
            status = WARN
            message = (
                f"{dataset['path']} has {output_count} records, {difference} more than "
                f"{compare_to['path']} ({compare_count})."
            )
        results.append(result("scope.record_count", status, message, **evidence))
    return results
