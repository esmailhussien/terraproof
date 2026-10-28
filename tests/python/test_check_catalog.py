"""The check catalog in routing/checks.json must match the check ids the Python package can emit.

The emitted ids are read from the source: every literal id passed to result(...) in
src/terraproof/checks/*.py, src/terraproof/provenance/_core.py and src/terraproof/preflight.py.
A module-level string constant is also accepted as the id when result() is called with it.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "src" / "terraproof"
CHECKS_DIR = PKG_DIR / "checks"
PROVENANCE_CORE = PKG_DIR / "provenance" / "_core.py"
PREFLIGHT = PKG_DIR / "preflight.py"
CATALOG_PATH = REPO_ROOT / "routing" / "checks.json"
ID_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")


def scanned_files() -> list[Path]:
    """Every source file whose result(...) calls name an emitted check id.

    preflight.py is globbed rather than required, so the suite does not fail on a
    checkout where that module has not been written yet; once it exists it is scanned
    like any other emitter.
    """
    files = sorted(CHECKS_DIR.glob("*.py"))
    for extra in sorted(PKG_DIR.glob("preflight*.py")) + [PROVENANCE_CORE]:
        if extra not in files:
            files.append(extra)
    return files


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants, e.g. CHECK_ID = "a.b" -> {"CHECK_ID": "a.b"}."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    return constants


def emitted_check_ids() -> tuple[set[str], list[str]]:
    """Return the ids passed to result(...), and the call sites whose id is neither a
    string literal nor a module-level string constant."""
    ids: set[str] = set()
    dynamic: list[str] = []
    for path in scanned_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "result":
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    ids.add(first.value)
                elif isinstance(first, ast.Name) and first.id in constants:
                    # Resolve a CHECK_ID-style constant to the value it is assigned.
                    ids.add(constants[first.id])
                else:
                    dynamic.append(f"{path.name}:{node.lineno}")
    return ids, dynamic


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["checks"]


def test_catalog_lists_exactly_the_emitted_check_ids():
    emitted, _ = emitted_check_ids()
    catalog = set(load_catalog())
    assert emitted, "no result(...) calls with check ids were found in the scanned emitters"
    assert catalog - emitted == set(), f"catalog lists ids the package never emits: {sorted(catalog - emitted)}"
    assert emitted - catalog == set(), f"package emits ids missing from routing/checks.json: {sorted(emitted - catalog)}"


def test_every_result_call_uses_a_literal_check_id():
    # A computed id would hide an emitted check from the catalog comparison above.
    _, dynamic = emitted_check_ids()
    assert dynamic == [], f"result(...) called with a non-literal check id at: {dynamic}"


def test_family_and_description_are_consistent():
    for check_id, entry in load_catalog().items():
        assert ID_PATTERN.match(check_id), f"malformed check id: {check_id}"
        assert entry["family"] == check_id.split(".", 1)[0], f"family mismatch for {check_id}"
        assert entry["description"].strip(), f"empty description for {check_id}"
        assert "\n" not in entry["description"], f"description must be one line: {check_id}"

def test_enabling_parameters_are_real_run_checks_arguments():
    """`coverage.not_checked` tells users which arguments enable a check; each must exist and apply to a real kind."""
    import inspect

    from terraproof.checks import run_checks

    arguments = set(inspect.signature(run_checks).parameters) | {"manifest"}  # manifest is a check/MCP option
    checks = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["checks"]
    enabled = {check_id: entry for check_id, entry in checks.items() if "enabled_by" in entry}
    assert {"rs.cloud_mask_applied", "rs.scale_applied_once", "crs.metric_operation"} <= set(enabled)
    for check_id, entry in enabled.items():
        assert entry["enabled_by"] and set(entry["enabled_by"]) <= arguments, check_id
        assert entry["applies_to"] and set(entry["applies_to"]) <= {"raster", "vector", "stac"}, check_id
