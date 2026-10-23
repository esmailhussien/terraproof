"""Provenance run manifest: write and verify deterministic run records."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from terraproof import __version__ as terraproof_version
from terraproof._common import InputError, sha256_and_size
from terraproof.checks.base import FAIL, PASS, WARN, CheckResult, result

SCHEMA_VERSION = "terraproof.manifest/0.1"
CHECK_ID = "provenance.reproducible"


def _has_credentials(value: Any) -> bool:
    """Find credential-bearing URLs, including URLs embedded in command arguments."""
    if isinstance(value, dict):
        return any(_has_credentials(k) or _has_credentials(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_credentials(v) for v in value)
    if not isinstance(value, str):
        return False
    for url in re.findall(r"(?:https?|s3)://[^\s\"'<>]+", value, flags=re.IGNORECASE):
        try:
            parts = urlsplit(url)
            keys = {key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)}
            if parts.username is not None or parts.password is not None or any(
                key in {"sig", "signature", "token", "access_token", "api_key", "apikey", "credential", "awsaccesskeyid"}
                or key.startswith(("x-amz-", "x-goog-")) for key in keys
            ):
                return True
        except ValueError:
            # A malformed URL cannot safely be persisted as a stable identity.
            return True
    return False


def _valid_structure(manifest: Any) -> bool:
    """Validate schema 0.1 before hashing or dereferencing untrusted records."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA_VERSION:
        return False
    core = manifest.get("core")
    if not isinstance(core, dict) or set(core) != {"files", "stac_items", "tool_versions", "parameters", "root_rule"}:
        return False
    if core["root_rule"] not in ("explicit", "cwd", "manifest-parent"):
        return False
    if not isinstance(core["parameters"], dict) or not isinstance(core["tool_versions"], dict):
        return False
    if not all(isinstance(v, str) for v in core["tool_versions"].values()):
        return False
    if not isinstance(manifest.get("context"), dict) or not isinstance(manifest.get("core_sha256"), str):
        return False
    context = manifest["context"]
    if not isinstance(context.get("created"), str) or not isinstance(context.get("command_line"), list):
        return False
    if not all(isinstance(argument, str) for argument in context["command_line"]):
        return False
    files = core["files"]
    if not isinstance(files, list) or not files:
        return False
    for record in files:
        if not isinstance(record, dict) or set(record) != {"role", "path", "sha256", "size"}:
            return False
        if record["role"] not in ("input", "output") or not isinstance(record["path"], str) or not record["path"]:
            return False
        if not isinstance(record["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None:
            return False
        if type(record["size"]) is not int or record["size"] < 0:
            return False
    if {r["role"] for r in files} != {"input", "output"}:
        return False
    if not isinstance(core["stac_items"], list):
        return False
    for item in core["stac_items"]:
        if not isinstance(item, dict) or set(item) != {"id", "collection", "datetime", "href", "asset_hrefs"}:
            return False
        if not all(v is None or isinstance(v, str) for k, v in item.items() if k != "asset_hrefs"):
            return False
        if not isinstance(item["asset_hrefs"], dict) or not all(isinstance(v, str) for v in item["asset_hrefs"].values()):
            return False
    return True


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

    properties = data.get("properties", {})
    assets = data.get("assets", {})
    if not isinstance(properties, dict) or not isinstance(assets, dict):
        raise ValueError("STAC properties and assets must be objects")
    if not all(isinstance(asset, dict) for asset in assets.values()):
        raise ValueError("STAC asset records must be objects")
    if not all(value is None or isinstance(value, str) for value in (
        data.get("id"), data.get("collection"), data.get("href"), properties.get("datetime"),
    )):
        raise ValueError("recorded STAC identity and time fields must be strings or null")
    if not all(asset.get("href") is None or isinstance(asset["href"], str) for asset in assets.values()):
        raise ValueError("STAC asset hrefs must be strings or null")
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
    command_line: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Build a run manifest.

    Credential-bearing URLs in STAC metadata, nested parameters or command arguments
    are rejected before a manifest is returned; use stable unsigned identities instead.
    Non-secret query parameters and acquisition time ranges are preserved verbatim.
    Parameters must be a JSON-compatible object; nested tuples normalize to JSON arrays
    without changing the canonical hash. Command arguments accept a list or tuple of
    strings, normalized to a list. Unsupported shapes are rejected without echoing values.
    File paths are resolved relative to *root*
    if given, otherwise relative to the directory that will hold the manifest
    (*manifest_path* parent), and finally relative to the current working
    directory. They are stored with forward slashes.
    """
    if not inputs:
        raise ValueError("at least one input is required")
    if not outputs:
        raise ValueError("at least one output is required")

    # Screen URLs before filesystem errors can echo supplied path arguments.
    supplied_paths = [os.fspath(p) for p in [*inputs, *outputs, *(stac_items or [])]]
    supplied_paths += [os.fspath(p) for p in (root, manifest_path) if p is not None]
    try:
        credential_url = _has_credentials([parameters, command_line if command_line is not None else sys.argv, supplied_paths])
    except RecursionError:
        raise ValueError("manifest inputs must be acyclic JSON-compatible values") from None
    if credential_url:
        raise ValueError("credential-bearing URL prohibited; record a stable unsigned identity")

    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError("parameters must be a JSON-compatible object")
    command_line = command_line if command_line is not None else sys.argv
    if not isinstance(command_line, (list, tuple)) or not all(isinstance(arg, str) for arg in command_line):
        raise ValueError("command_line must be a list or tuple of strings")
    command_line = list(command_line)
    try:
        parameters = json.loads(_canonical_json(parameters if parameters is not None else {}))
    except (TypeError, ValueError, RecursionError):
        raise ValueError("parameters must be a finite canonical JSON-compatible object") from None

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

    if _has_credentials(core) or _has_credentials(context):
        raise ValueError("credential-bearing URL prohibited; record a stable unsigned identity")

    try:
        core_hash = _hash_core(core)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("manifest inputs must be finite canonical UTF-8 JSON-compatible values") from None
    manifest = {
        "schema": SCHEMA_VERSION,
        "core": core,
        "core_sha256": core_hash,
        "context": context,
    }
    if not _valid_structure(manifest):
        raise ValueError("manifest inputs do not satisfy schema 0.1")
    return manifest


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
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return result(CHECK_ID, FAIL, "manifest is unreadable or invalid JSON")

    if not _valid_structure(manifest):
        return result(CHECK_ID, FAIL, "unsupported manifest schema or malformed structure")
    if _has_credentials(manifest):
        return result(CHECK_ID, FAIL, "credential-bearing URL prohibited in manifest")

    core = manifest["core"]
    stored_core_hash = manifest["core_sha256"]
    try:
        computed_core_hash = _hash_core(core)
    except (TypeError, ValueError):
        return result(CHECK_ID, FAIL, "manifest core is not canonical JSON")
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
        try:
            resolved = _resolve_recorded_path(record["path"], root_path)
        except (OSError, ValueError):
            return result(CHECK_ID, FAIL, "invalid recorded file path")
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
        try:
            digest, size = sha256_and_size(resolved)
            # Run records and STAC metadata are local JSON, never remote hrefs.
            if resolved.suffix.lower() == ".json":
                with open(resolved, encoding="utf-8") as handle:
                    recorded_json = json.load(handle)
                if _has_credentials(recorded_json):
                    return result(CHECK_ID, FAIL, "credential-bearing URL prohibited in recorded JSON")
        except (OSError, ValueError, UnicodeError):
            return result(CHECK_ID, FAIL, "recorded file is unreadable or invalid JSON")
        if digest != record["sha256"] or size != record["size"]:
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
