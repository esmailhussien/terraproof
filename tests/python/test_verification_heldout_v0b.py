"""Test suite for Phase 7 held-out verification cases (V0b).

Asserts:
1. Two independent generator runs produce 100% byte-identical files across all 48 cases.
2. The independent oracle reports every wrong case as wrong and every correct case as correct (48/48 agreement).
3. Neither this test, the generator, nor the oracle imports terraproof checks, evidence, or evals modules.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELDOUT_DIR = REPO_ROOT / "evals" / "verification-heldout-v0b"
GENERATE_SCRIPT = HELDOUT_DIR / "generate.py"
ORACLE_SCRIPT = HELDOUT_DIR / "oracle.py"
CASES_FILE = HELDOUT_DIR / "cases.json"


def test_no_forbidden_imports():
    """Verify that held-out scripts do not import checks, evidence, or evals modules."""
    scripts = [
        GENERATE_SCRIPT,
        ORACLE_SCRIPT,
        Path(__file__),
    ]
    forbidden_modules = ("terraproof.checks", "terraproof.evidence", "terraproof.evals")
    for script in scripts:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for pref in forbidden_modules:
                        assert not alias.name.startswith(pref), f"Forbidden import '{alias.name}' in {script}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for pref in forbidden_modules:
                    assert not mod.startswith(pref), f"Forbidden from-import '{mod}' in {script}"


def test_generator_determinism(tmp_path: Path):
    """Verify that two generator runs give byte-identical files across all 48 cases."""
    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"

    cmd1 = [sys.executable, str(GENERATE_SCRIPT), str(run1_dir)]
    res1 = subprocess.run(cmd1, capture_output=True, text=True)
    assert res1.returncode == 0, f"Generator run 1 failed:\n{res1.stderr}"

    cmd2 = [sys.executable, str(GENERATE_SCRIPT), str(run2_dir)]
    res2 = subprocess.run(cmd2, capture_output=True, text=True)
    assert res2.returncode == 0, f"Generator run 2 failed:\n{res2.stderr}"

    m1_path = run1_dir / "manifest.json"
    m2_path = run2_dir / "manifest.json"
    assert m1_path.is_file(), "Run 1 manifest.json missing"
    assert m2_path.is_file(), "Run 2 manifest.json missing"

    with open(m1_path, "r", encoding="utf-8") as f:
        m1 = json.load(f)
    with open(m2_path, "r", encoding="utf-8") as f:
        m2 = json.load(f)

    assert len(m1) >= 48, f"Expected at least 48 generated files, got {len(m1)}"
    assert m1.keys() == m2.keys(), "File sets differ between runs"

    diffs = {k: (m1[k], m2[k]) for k in m1 if m1[k] != m2[k]}
    assert not diffs, f"Hash mismatches between runs for: {diffs}"


def test_oracle_verifies_all_cases(tmp_path: Path):
    """Verify that oracle.py reports every wrong case as wrong and every correct case as correct."""
    out_dir = tmp_path / "cases"

    cmd_gen = [sys.executable, str(GENERATE_SCRIPT), str(out_dir)]
    res_gen = subprocess.run(cmd_gen, capture_output=True, text=True)
    assert res_gen.returncode == 0, f"Generator failed:\n{res_gen.stderr}"

    cmd_ora = [sys.executable, str(ORACLE_SCRIPT), str(out_dir), "--cases-json", str(CASES_FILE)]
    res_ora = subprocess.run(cmd_ora, capture_output=True, text=True)
    assert res_ora.returncode == 0, f"Oracle reported mismatches:\n{res_ora.stdout}\n{res_ora.stderr}"

    # Verify summary string
    assert "ALL 48 HELD-OUT CASES VERIFIED SUCCESSFULLY: 100% AGREEMENT." in res_ora.stdout
