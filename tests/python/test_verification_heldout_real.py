"""Phase 8 held-out verification cases from real data (evals/verification-heldout-real).

Runs the bundle's fetch/derive/oracle when the cache or the network is
available and skips otherwise; verifies that two derive runs are
byte-identical and that the oracle agrees with every case's kind. This test
never imports terraproof.checks, terraproof.evidence or terraproof.evals.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "evals" / "verification-heldout-real"
CACHE = Path(
    os.environ.get(
        "TERRAPROOF_HELDOUT_REAL_CACHE", ROOT / ".terracache" / "verification-heldout-real"
    )
)


def _network_available() -> bool:
    try:
        socket.getaddrinfo("earth-search.aws.element84.com", 443)
    except OSError:
        return False
    try:
        socket.getaddrinfo("raw.githubusercontent.com", 443)
    except OSError:
        return False
    return True


def _cache_filled() -> bool:
    return (CACHE / "manifest.json").is_file() and any(CACHE.rglob("*.tif"))


def _run(script: str, *args: object, capture: bool = True):
    cmd = [sys.executable, str(BUNDLE / script), *(map(str, args))]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    return cmd


@pytest.fixture(scope="module")
def heldout_cache() -> Path:
    if _cache_filled():
        return CACHE
    if os.environ.get("CI") and os.environ.get("TERRAPROOF_HELDOUT_REAL_FETCH") != "1":
        pytest.skip("verification-heldout-real: no cache; CI fetches only with TERRAPROOF_HELDOUT_REAL_FETCH=1")
    if _network_available():
        result = _run("fetch.py", CACHE)
        if result.returncode != 0:
            pytest.skip(f"fetch failed (no usable cache): {result.stderr[-800:]}")
        return CACHE
    pytest.skip("verification-heldout-real: no cache and no network")


def _hash_dir(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


def test_bundle_sources_never_import_terraproof() -> None:
    forbidden = (b"terraproof.checks", b"terraproof.evidence", b"terraproof.evals")
    for name in ("fetch.py", "derive.py", "oracle.py"):
        data = (BUNDLE / name).read_bytes()
        for token in (b"import terraproof", b"from terraproof"):
            assert token not in data, f"{name} imports terraproof"
        for token in forbidden:
            assert token not in data, f"{name} references {token}"


def test_cases_json_shape_and_counts() -> None:
    cases = json.loads((BUNDLE / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 32
    counts: dict[str, dict[str, int]] = {}
    for case in cases:
        assert case["kind"] in ("wrong", "correct")
        assert case["scenario"] and case["goal"]
        assert case["sources"] and case["facts"]
        assert case["facts"].keys() == case["facts_in_metadata"].keys()
        assert case["oracle"].get("value") is not None
        counts.setdefault(case["family"], {"wrong": 0, "correct": 0})[case["kind"]] += 1
    checks = {
        "qa_masking": (4, 4),
        "scale_offset_fill": (3, 3),
        "elevation_units_slope": (3, 3),
        "nodata": (2, 2),
        "delivered_metrics": (2, 2),
    }
    for family, (wrong, correct) in checks.items():
        assert counts[family]["wrong"] >= wrong, family
        assert counts[family]["correct"] >= correct, family
    assert counts["plain"]["correct"] >= 4
    assert counts["plain"]["wrong"] == 0


def test_fetch_manifest_hashes(heldout_cache: Path) -> None:
    manifest = json.loads((heldout_cache / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"], "manifest is empty"
    for name, expected in manifest["sha256"].items():
        p = heldout_cache / name
        assert p.is_file(), f"missing fetched file {name}"
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == expected, f"hash mismatch for {name}"


def test_derive_is_byte_identical_across_runs(tmp_path_factory, heldout_cache: Path) -> None:
    out1 = tmp_path_factory.mktemp("derive1")
    out2 = tmp_path_factory.mktemp("derive2")
    result1 = _run("derive.py", heldout_cache, out1)
    result2 = _run("derive.py", heldout_cache, out2)
    assert result1.returncode == 0, result1.stderr[-4000:]
    assert result2.returncode == 0, result2.stderr[-4000:]
    assert _hash_dir(out1) == _hash_dir(out2), "two derive runs differ"


def test_oracle_agrees_with_every_case(tmp_path_factory, heldout_cache: Path) -> None:
    out = tmp_path_factory.mktemp("oracle_out")
    result = _run("derive.py", heldout_cache, out)
    assert result.returncode == 0, result.stderr[-4000:]
    oracle = _run("oracle.py", heldout_cache, out)
    assert oracle.returncode == 0, oracle.stdout[-2000:] + oracle.stderr[-4000:]
    summary = json.loads(oracle.stdout)
    assert summary["total"] >= 32
    assert summary["agree"] == summary["total"]
    cases = json.loads((BUNDLE / "cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    for line in summary["cases"]:
        assert line["verdict"], line
        assert line["id"] in by_id
        assert line["kind"] == by_id[line["id"]]["kind"]
