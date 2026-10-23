"""Shared helpers used by both the CLI and the MCP server for run inputs.

This keeps sample/area loading and manifest-coverage logic identical across the
two entry points.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from terraproof._common import InputError
from terraproof.checks.accuracy import read_samples as _read_csv_samples
from terraproof.checks.base import result
from terraproof.provenance import verify_manifest as _verify_manifest
from terraproof.provenance._core import _is_within_root, _resolve_recorded_path, _workspace_for


def _normalise_sample_record(raw: Any) -> dict:
    """Return a {map_class, ref_class, stratum_weight} dict, rejecting malformed records."""
    if isinstance(raw, dict):
        map_value = raw.get("map_class")
        ref_value = raw.get("ref_class")
        map_class = "" if map_value is None else str(map_value).strip()
        ref_class = "" if ref_value is None else str(ref_value).strip()
        weight = raw.get("stratum_weight")
    elif isinstance(raw, (list, tuple)):
        if len(raw) < 2:
            raise InputError(f"sample record must have at least map_class and ref_class: {raw!r}")
        map_class = str(raw[0]).strip()
        ref_class = str(raw[1]).strip()
        weight = raw[2] if len(raw) > 2 else None
    else:
        raise InputError(f"sample record must be a dict or sequence: {raw!r}")

    if not map_class or not ref_class:
        raise InputError(f"sample record missing map_class or ref_class: {raw!r}")

    if weight is not None:
        try:
            weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise InputError(f"stratum_weight must be a number: {weight!r}") from exc

    return {"map_class": map_class, "ref_class": ref_class, "stratum_weight": weight}


def load_accuracy_samples(value: Any) -> dict:
    """Load reference samples from a CSV/JSON file, a list, or a records dict.

    The returned dict matches ``terraproof.checks.accuracy.read_samples``:
    ``{"path", "records": [{map_class, ref_class, stratum_weight}, ...], "has_weights"}``.
    """
    if isinstance(value, dict):
        if "records" not in value:
            raise InputError("accuracy_samples dict must contain a 'records' list")
        records = [_normalise_sample_record(r) for r in value["records"]]
        has_weights = bool(
            value.get("has_weights", any(r["stratum_weight"] is not None for r in records))
        )
        return {"path": value.get("path", "(supplied dict)"), "records": records, "has_weights": has_weights}

    if isinstance(value, list):
        records = [_normalise_sample_record(r) for r in value]
        return {
            "path": "(supplied list)",
            "records": records,
            "has_weights": any(r["stratum_weight"] is not None for r in records),
        }

    if isinstance(value, str):
        path = Path(value)
        if not path.is_file():
            raise InputError(f"accuracy samples file not found: {value}")
        if path.suffix.lower() == ".csv":
            return _read_csv_samples(path)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and "records" in data:
            records = [_normalise_sample_record(r) for r in data["records"]]
            has_weights = bool(
                data.get("has_weights", any(r["stratum_weight"] is not None for r in records))
            )
            return {"path": str(path), "records": records, "has_weights": has_weights}
        if isinstance(data, list):
            records = [_normalise_sample_record(r) for r in data]
            return {
                "path": str(path),
                "records": records,
                "has_weights": any(r["stratum_weight"] is not None for r in records),
            }
        raise InputError(f"accuracy samples JSON must be a list or {{records: [...]}}: {value}")

    raise InputError("accuracy_samples must be a file path, dict, or list")


def load_class_areas(value: Any) -> dict:
    """Load a class-name-to-area mapping from a dict or a JSON file."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        path = Path(value)
        if not path.is_file():
            raise InputError(f"class areas file not found: {value}")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise InputError(f"class areas JSON must be an object: {value}")
        return data
    raise InputError("class_areas must be a dict or file path")


def verify_manifest_coverage(
    manifest_path: str | os.PathLike,
    checked_paths: list[str],
    root: str | os.PathLike | None = None,
) -> Any:
    """Verify a manifest and confirm it covers every path in ``checked_paths``.

    ``checked_paths`` should include all files that contribute to the check run
    (primary inputs, compare-to, reference-input, QA, accuracy samples, class
    areas). The manifest's own ``root_rule`` is respected when resolving recorded
    paths. A malformed manifest returns a ``provenance.reproducible`` failure
    rather than raising.
    """
    manifest_path_obj = Path(manifest_path).resolve()
    try:
        with open(manifest_path_obj, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return result(
            "provenance.reproducible",
            "fail",
            f"cannot read manifest: {exc}",
            manifest=str(manifest_path_obj),
        )

    if not isinstance(manifest, dict):
        return result(
            "provenance.reproducible",
            "fail",
            "manifest must be a JSON object",
            manifest=str(manifest_path_obj),
        )

    schema = manifest.get("schema")
    if schema != "terraproof.manifest/0.1":
        return result(
            "provenance.reproducible",
            "fail",
            f"unsupported manifest schema: {schema!r}",
            manifest=str(manifest_path_obj),
            schema=schema,
        )

    core = manifest.get("core", {})

    # Let the provenance verifier handle hash, missing/changed files, and version drift.
    # Its schema/structure errors are part of the provenance result, not an API crash.
    try:
        provenance_result = _verify_manifest(manifest_path_obj, root=root)
    except Exception as exc:  # malformed schema/structure must preserve CLI/MCP parity
        return result(
            "provenance.reproducible",
            "fail",
            f"invalid manifest structure: {exc}",
            manifest=str(manifest_path_obj),
        )
    if provenance_result.status == "fail":
        return provenance_result

    root_path = Path(root).resolve() if root else manifest_path_obj.parent
    root_rule = core.get("root_rule", "manifest-parent" if root is None else "explicit")
    workspace = _workspace_for(root_path, root_rule)

    recorded: set[str] = set()
    for record in core.get("files", []):
        try:
            resolved = _resolve_recorded_path(record["path"], root_path)
        except Exception as exc:
            return result(
                "provenance.reproducible",
                "fail",
                f"invalid recorded path {record.get('path')!r}: {exc}",
                manifest=str(manifest_path_obj),
            )
        if not _is_within_root(resolved, workspace):
            return result(
                "provenance.reproducible",
                "fail",
                f"recorded path escapes workspace: {record.get('path')}",
                manifest=str(manifest_path_obj),
                workspace=str(workspace),
            )
        recorded.add(str(resolved))

    missing: list[str] = []
    for path in checked_paths:
        if path is None or not isinstance(path, (str, os.PathLike)) or not str(path):
            continue
        resolved = str(Path(path).resolve())
        if resolved not in recorded:
            missing.append(str(path))

    if missing:
        return result(
            "provenance.reproducible",
            "fail",
            f"manifest does not cover the checked path(s): {', '.join(missing)}",
            manifest=str(manifest_path_obj),
            uncovered_paths=missing,
        )

    return provenance_result
