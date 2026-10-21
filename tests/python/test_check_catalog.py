"""The check catalog in routing/checks.json must match the check ids the Python package can emit.

The emitted ids are read from the source: every literal id passed to result(...) in src/terraproof/checks/*.py.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_DIR = REPO_ROOT / "src" / "terraproof" / "checks"
CATALOG_PATH = REPO_ROOT / "routing" / "checks.json"
ID_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")


def emitted_check_ids() -> tuple[set[str], list[str]]:
    """Return the literal ids passed to result(...), and the call sites whose id is not a literal."""
    ids: set[str] = set()
    dynamic: list[str] = []
    for path in sorted(CHECKS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "result":
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    ids.add(first.value)
                else:
                    dynamic.append(f"{path.name}:{node.lineno}")
    return ids, dynamic


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["checks"]


def test_catalog_lists_exactly_the_emitted_check_ids():
    emitted, _ = emitted_check_ids()
    catalog = set(load_catalog())
    assert emitted, "no result(...) calls with literal check ids were found under src/terraproof/checks"
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