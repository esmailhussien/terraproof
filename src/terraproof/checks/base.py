"""The result type shared by every check family."""

from __future__ import annotations

from dataclasses import dataclass, field

PASS = "pass"
WARN = "warn"
FAIL = "fail"
NOT_RUN = "not-run"
STATUSES = (PASS, WARN, FAIL, NOT_RUN)


@dataclass(frozen=True)
class CheckResult:
    """One check outcome. The family is the id prefix before the first dot."""

    id: str
    family: str
    status: str
    message: str
    evidence: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status: {self.status!r}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "family": self.family,
            "status": self.status,
            "message": self.message,
            "evidence": self.evidence,
        }


def result(check_id: str, status: str, message: str, **evidence) -> CheckResult:
    """Build a CheckResult; the family is derived from the check id."""
    return CheckResult(check_id, check_id.split(".", 1)[0], status, message, dict(evidence))
