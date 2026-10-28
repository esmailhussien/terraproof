"""Phase 7 V0: the held-out verification cases are sealed by hash and must not be edited for product tuning."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

HELDOUT = Path(__file__).resolve().parents[2] / "evals" / "verification-heldout"
SEALED = {
    "cases.json": "83cb9e0ff78f603d4e4a0e6202f8a7d4d8a87ac480602c35bbe6cf30d6bcfd19",
    "generate.py": "a6b7e4ed93b921698a79414c3d277fee821b15308e5d55d19c6c3f2e98ce5f96",
    "oracle.py": "1247b8c78b833ededf6b9707e71599935fe18c29e3f090a175518035dba92b1e",
    "README.md": "70ba34d4cba080f7c2d6351cc77b2026920926d6e87ea954bd50b23438ce5883",
}


@pytest.mark.parametrize("name", sorted(SEALED))
def test_sealed_file_is_unchanged(name):
    data = (HELDOUT / name).read_bytes().replace(b"\r\n", b"\n")  # any checkout's line endings
    assert hashlib.sha256(data).hexdigest() == SEALED[name], f"{name} changed after the V0 seal"
