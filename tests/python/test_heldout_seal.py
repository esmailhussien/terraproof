"""Phase 7 V0 and V0b: the held-out verification cases are sealed by hash and must not be edited for product tuning."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[2] / "evals"
SEALED = {
    "verification-heldout/cases.json": "83cb9e0ff78f603d4e4a0e6202f8a7d4d8a87ac480602c35bbe6cf30d6bcfd19",
    "verification-heldout/generate.py": "a6b7e4ed93b921698a79414c3d277fee821b15308e5d55d19c6c3f2e98ce5f96",
    "verification-heldout/oracle.py": "1247b8c78b833ededf6b9707e71599935fe18c29e3f090a175518035dba92b1e",
    "verification-heldout/README.md": "70ba34d4cba080f7c2d6351cc77b2026920926d6e87ea954bd50b23438ce5883",
    "verification-heldout-v0b/cases.json": "5f0c32ef821a809fe3c5957bdda963679a67a382ba016e5413562399d642e860",
    "verification-heldout-v0b/generate.py": "604f38538fe24136c9c0cf3be9daffe033885af83cc7cd2da626ef0e6a5351be",
    "verification-heldout-v0b/oracle.py": "3674990f278a31624a1874cf611504cb99ab71306a33589774147a7e5c53407b",
    "verification-heldout-v0b/README.md": "aa8cbc85875aac102c4e996bf028840370a526f71f4324b29dd234b7c3d934a6",
}


@pytest.mark.parametrize("name", sorted(SEALED))
def test_sealed_file_is_unchanged(name):
    data = (EVALS / name).read_bytes().replace(b"\r\n", b"\n")  # any checkout's line endings
    assert hashlib.sha256(data).hexdigest() == SEALED[name], f"{name} changed after its seal"
