"""Provenance run manifest: write and verify deterministic run records."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from terraproof import __version__ as terraproof_version
from terraproof._common import InputError, sha256_and_size
from terraproof.checks.base import FAIL, PASS, WARN, CheckResult, result

SCHEMA_VERSION = "terraproof.manifest/0.1"
CHECK_ID = "provenance.reproducible"


def tool_versions() -> dict:
    """Versions of the tools recorded in a manifest."""
    import numpy
    import pyogrio
    import pyproj
    import rasterio
    import shapely

    return {
        "terraproof": terraproof_version,
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pyproj": pyproj.__version__,
        "shapely": shapely.__version__,
        "pyogrio": pyogrio.__version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
    }


def _relative_within_root(path: str | os.PathLike, root: Path, workspace: Path) -> str:
    """Return *path* relative to *root*, using forward slashes.

    The path must be inside *workspace* (or equal to it). For manifest-parent
    roots the workspace is one level above *root*, which lets sibling folders
    be referenced with ``..``. For explicit roots the workspace is *root*.
    """
    root_resolved = root.resolve()
    if not root_resolved.exists():
        raise InputError(f"root does not exist: {root}")
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise InputError(f"path does not exist: {path}")
    if not _is_within_root(resolved, workspace):
        raise ValueError(f"path outside root/workspace: {path}")
    rel = Path(os.path.relpath(resolved, root_resolved))
    return rel.as_posix()


def _is_within_root(path: Path, root: Path) -> bool:
    """Return True if *path* is inside *root* (or equals it), after resolving both."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _workspace_for(root_path: Path, root_rule: str) -> Path:
    """Return the directory a recorded path must stay inside during verify.

    When the manifest was written with its parent as the root, the intended
    workspace is the directory containing that root (e.g. the project folder
    that holds both ``data/`` and ``runs/``). For an explicit or cwd root the
    boundary is the root itself.
    """
    if root_rule == "manifest-parent":
        return root_path.resolve().parent
    return root_path.resolve()


def _read_stac_item(path: str | os.PathLike) -> dict:
    """Read a local STAC Item and return the provenance fields we keep."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("type") != "Feature" or "stac_version" not in data:
        raise InputError(f"not a STAC Item: {path}")

    properties = data.get("properties") or {}
    assets = data.get("assets") or {}
    asset_hrefs = {
        key: asset.get("href")
        for key, asset in sorted(assets.items())
        if asset.get("href") is not None
    }

    return {
        "id": data.get("id"),
        "collection": data.get("collection"),
        "datetime": properties.get("datetime"),
        "href": data.get("href"),
        "asset_hrefs": asset_hrefs,
    }


def _canonical_json(value: Any) -> bytes:
    """Deterministic UTF-8 JSON suitable for hashing."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash_core(core: dict) -> str:
    """SHA-256 of the canonical JSON of *core*."""
    return hashlib.sha256(_canonical_json(core)).hexdigest()


def _file_records(
    paths: list[str | os.PathLike],
    role: str,
    root: Path,
    workspace: Path,
) -> list[dict]:
    """Build deterministic file records for one role."""
    records = []
    for path in paths:
        rel = _relative_within_root(path, root, workspace)
        digest, size = sha256_and_size(path)
        records.append({
            "role": role,
            "path": rel,
            "sha256": digest,
            "size": size,
        })
    return sorted(records, key=lambda r: (r["role"], r["path"]))


def write_manifest(
    inputs: list[str | os.PathLike],
    outputs: list[str | os.PathLike],
    *,
    parameters: dict | None = None,
    stac_items: list[str | os.PathLike] | None = None,
    root: str | os.PathLike | None = None,
    manifest_path: str | os.PathLike | None = None,
    command_line: list[str] | None = None,
) -> dict:
    """Build a run manifest.

    Parameters are stored verbatim. File paths are resolved relative to *root*
    if given, otherwise relative to the directory that will hold the manifest
    (*manifest_path* parent), and finally relative to the current working
    directory. They are stored with forward slashes.
    """
    if not inputs:
        raise ValueError("at least one input is required")
    if not outputs:
        raise ValueError("at least one output is required")

    if root is not None:
        root_path = Path(root).resolve()
        root_rule = "explicit"
    elif manifest_path is not None:
        manifest_path_obj = Path(manifest_path)
        root_path = manifest_path_obj.parent.resolve()
        root_rule = "manifest-parent"
    else:
        root_path = Path.cwd()
        root_rule = "cwd"
    workspace = _workspace_for(root_path, root_rule)

    parameters = parameters if parameters is not None else {}
    stac_items = stac_items if stac_items is not None else []

    core = {
        "files": (
            _file_records(inputs, "input", root_path, workspace)
            + _file_records(outputs, "output", root_path, workspace)
        ),
        "stac_items": sorted(
            [_read_stac_item(path) for path in stac_items],
            key=lambda item: item.get("id") or "",
        ),
        "tool_versions": tool_versions(),
        "parameters": parameters,
        "root_rule": root_rule,
    }

    context = {
        "created": datetime.now(timezone.utc).isoformat(),
        "command_line": command_line if command_line is not None else sys.argv,
    }

    return {
        "schema": SCHEMA_VERSION,
        "core": core,
        "core_sha256": _hash_core(core),
        "context": context,
    }


def _resolve_recorded_path(recorded_path: str, root: Path) -> Path:
    """Resolve a manifest path against *root*."""
    return (root / recorded_path).resolve()


def verify_manifest(
    path: str | os.PathLike,
    root: str | os.PathLike | None = None,
) -> CheckResult:
    """Verify a run manifest.

    *root* defaults to the directory containing the manifest file.
    Returns a ``provenance.reproducible`` CheckResult.
    """
    manifest_path = Path(path).resolve()
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)

    if manifest.get("schema") != SCHEMA_VERSION:
        return result(
            CHECK_ID,
            FAIL,
            f"unsupported manifest schema: {manifest.get('schema')!r}",
            schema=manifest.get("schema"),
        )

    core = manifest.get("core", {})
    stored_core_hash = manifest.get("core_sha256")
    computed_core_hash = _hash_core(core)
    if stored_core_hash != computed_core_hash:
        return result(
            CHECK_ID,
            FAIL,
            "manifest core does not match its recorded hash (edited or corrupted)",
            expected_core_sha256=stored_core_hash,
            actual_core_sha256=computed_core_hash,
        )

    root_path = Path(root).resolve() if root else manifest_path.parent
    root_rule = core.get("root_rule", "manifest-parent" if root is None else "explicit")
    workspace = _workspace_for(root_path, root_rule)

    file_records = core.get("files", [])
    changed = []
    missing = []
    for record in file_records:
        resolved = _resolve_recorded_path(record["path"], root_path)
        if not _is_within_root(resolved, workspace):
            return result(
                CHECK_ID,
                FAIL,
                f"recorded path escapes workspace: {record['path']}",
                escaped_path=record["path"],
                workspace=str(workspace),
            )
        if not resolved.exists():
            missing.append(record["path"])
            continue
        digest, _size = sha256_and_size(resolved)
        if digest != record["sha256"]:
            changed.append(record["path"])

    if missing or changed:
        message_parts = []
        if missing:
            message_parts.append(f"{len(missing)} missing file(s)")
        if changed:
            message_parts.append(f"{len(changed)} changed file(s)")
        return result(
            CHECK_ID,
            FAIL,
            "; ".join(message_parts),
            missing=missing,
            changed=changed,
        )

    stored_versions = core.get("tool_versions", {})
    current_versions = tool_versions()
    drifted = {
        tool: {"stored": stored_versions.get(tool), "current": current_versions.get(tool)}
        for tool in sorted(set(stored_versions) | set(current_versions))
        if stored_versions.get(tool) != current_versions.get(tool)
    }

    if drifted:
        return result(
            CHECK_ID,
            WARN,
            "all files match, but tool versions differ",
            drifted=drifted,
        )

    return result(CHECK_ID, PASS, "manifest verified: files and tool versions match")
