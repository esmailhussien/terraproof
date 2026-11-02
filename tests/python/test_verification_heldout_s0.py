"""Phase 10 held-out verification cases from real data (evals/verification-heldout-s0).

Runs the bundle's fetch/derive/oracle when a cache or the network is available
and skips otherwise. On CI (`CI` set) it skips without a cache unless
`TERRAPROOF_HELDOUT_S0_FETCH=1`. Verifies that two derive runs are
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
BUNDLE = ROOT / "evals" / "verification-heldout-s0"
CACHE = Path(
    os.environ.get(
        "TERRAPROOF_HELDOUT_S0_CACHE", ROOT / ".terracache" / "s0"
    )
)


def _network_available() -> bool:
    for host in ("earth-search.aws.element84.com", "raw.githubusercontent.com",
                 "copernicus-dem-30m.s3.amazonaws.com", "prd-tnm.s3.amazonaws.com"):
        try:
            socket.getaddrinfo(host, 443)
        except OSError:
            return False
    return True


def _cache_filled() -> bool:
    return (CACHE / "manifest.json").is_file() and bool(list(CACHE.rglob("*.tif")))


def _run(script: str, *args: object):
    cmd = [sys.executable, str(BUNDLE / script), *(map(str, args))]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=5400)


@pytest.fixture(scope="module")
def heldout_cache() -> Path:
    if _cache_filled():
        return CACHE
    fetch_allowed = (
        os.environ.get("TERRAPROOF_HELDOUT_S0_FETCH") == "1"
        or (not os.environ.get("CI") and _network_available())
    )
    if not fetch_allowed:
        pytest.skip("verification-heldout-s0: no cache and fetching not allowed here")
    if not _network_available():
        pytest.skip("verification-heldout-s0: no cache and no network")
    result = _run("fetch.py", CACHE)
    if result.returncode != 0:
        pytest.skip(f"fetch failed (no usable cache): {result.stderr[-800:]}")
    return CACHE


def _hash_dir(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            hashes[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return hashes


def test_bundle_sources_never_import_terraproof() -> None:
    forbidden = (b"terraproof.checks", b"terraproof.evidence", b"terraproof.evals")
    for name in ("fetch.py", "derive.py", "oracle.py"):
        data = (BUNDLE / name).read_bytes()
        for token in (b"import terraproof", b"from terraproof"):
            assert token not in data, f"{name} imports terraproof"
        for token in forbidden:
            assert token not in data, f"{name} references {token}"


def test_cases_json_shape_counts_forms_and_chains() -> None:
    cases = json.loads((BUNDLE / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 40
    fams: dict[str, dict[str, int]] = {}
    forms: dict[str, int] = {}
    orders: dict[str, int] = {"slope_then_warp": 0, "warp_then_slope": 0}
    methods: dict[str, int] = {}
    list_reports = 0
    for case in cases:
        assert case["kind"] in ("wrong", "correct")
        assert case["deliverable_form"] in ("dataset", "validity-mask", "summary")
        assert case["scenario"] and case["goal"]
        assert case["sources"] and case["facts"]
        assert case["facts"].keys() == case["facts_in_metadata"].keys()
        assert case["oracle"].get("value") is not None
        fams.setdefault(case["family"], {"wrong": 0, "correct": 0})[case["kind"]] += 1
        forms[case["deliverable_form"]] = forms.get(case["deliverable_form"], 0) + 1
        facts = case["facts"]
        if case["family"] == "reprojected_slopes":
            orders[facts["computation_order"]] += 1
            methods[facts["resampling"]] = methods.get(facts["resampling"], 0) + 1
        if case["family"] == "multi_value_reports":
            assert "report_numbers" in facts
            if any(k.startswith("per_class[") for k in facts["report_numbers"]):
                list_reports += 1
    for family, (wrong, correct) in {
        "qa_validity_masks": (5, 5),
        "reprojected_slopes": (5, 5),
        "multi_value_reports": (5, 5),
        "same_grid_geographic_slopes": (2, 2),
    }.items():
        assert fams[family]["wrong"] >= wrong, family
        assert fams[family]["correct"] >= correct, family
    assert fams["plain"]["correct"] >= 4 and fams["plain"]["wrong"] == 0
    assert orders["slope_then_warp"] >= 1 and orders["warp_then_slope"] >= 1
    assert len(methods) >= 2
    assert list_reports >= 2
    for form in ("dataset", "validity-mask", "summary"):
        assert forms.get(form, 0) >= 1


def test_fetch_manifest_hashes(heldout_cache: Path) -> None:
    manifest = json.loads((heldout_cache / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"], "manifest is empty"
    for name, expected in manifest["sha256"].items():
        p = heldout_cache / name
        assert p.is_file(), f"missing fetched file {name}"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, name


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
    assert summary["total"] >= 40
    assert summary["agree"] == summary["total"]
    cases = json.loads((BUNDLE / "cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    for line in summary["cases"]:
        assert line["verdict"], line
        assert line["id"] in by_id
        assert line["kind"] == by_id[line["id"]]["kind"]
