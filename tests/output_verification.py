"""Explicit required MCP checks tied to current project data bytes; no model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import time

SCHEMA = "terraproof.required-output-verification/1"
FILE_PARAMETERS = {"compare_to", "reference_input", "qa_path", "dem", "nir", "red",
                   "manifest", "accuracy_samples", "class_areas"}


def _relative(value, prefix):
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        return False
    parts = value.split("/")
    return (parts[0] in prefix and len(parts) > 1 and
            not any(part in ("", ".", "..") or ":" in part for part in parts))


class VerificationPlan:
    """Load once before inference; later filesystem edits cannot change active policy."""

    def __init__(self, path):
        path = Path(path)
        with path.open("rb") as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError("verification plan exceeds 64 KiB")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate verification plan key")
                result[key] = value
            return result
        document = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(document, dict) or set(document) != {"schema", "tasks"}
                or document["schema"] != SCHEMA or not isinstance(document["tasks"], dict)
                or not document["tasks"]):
            raise ValueError("invalid verification plan schema")
        from terraproof._common import assets_root
        catalog = json.loads((assets_root() / "routing/checks.json").read_text(encoding="utf-8"))["checks"]
        for task, groups in document["tasks"].items():
            if not isinstance(task, str) or not task or not isinstance(groups, list) or not groups:
                raise ValueError("verification tasks require nonempty groups")
            seen = set()
            for group in groups:
                if (not isinstance(group, dict) or set(group) != {"paths", "checks", "parameters"}
                        or not isinstance(group["paths"], list) or not group["paths"]
                        or not all(_relative(p, {"outputs"}) for p in group["paths"])
                        or len(set(group["paths"])) != len(group["paths"])
                        or not isinstance(group["checks"], list) or not group["checks"]
                        or not all(isinstance(c, str) and c in catalog for c in group["checks"])
                        or len(set(group["checks"])) != len(group["checks"])
                        or not isinstance(group["parameters"], dict)
                        or {"paths", "lang"} & group["parameters"].keys()):
                    raise ValueError("invalid verification group")
                for key in FILE_PARAMETERS:
                    value = group["parameters"].get(key)
                    if isinstance(value, str) and not _relative(value, {"inputs", "outputs"}):
                        raise ValueError("verification file arguments must stay in project data directories")
                canonical = {**group, "paths": sorted(group["paths"]), "checks": sorted(group["checks"])}
                encoded = json.dumps(canonical, sort_keys=True, allow_nan=False)
                if encoded in seen:
                    raise ValueError("duplicate verification group")
                seen.add(encoded)
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.tasks = document["tasks"]

    def groups(self, task_id, names):
        groups = self.tasks.get(task_id)
        expected = {"outputs/" + name for name in names}
        if not groups or {p for g in groups for p in g["paths"]} != expected:
            raise ValueError("verification plan must cover exactly the declared deliverables")
        return json.loads(json.dumps(groups))


class RequiredVerification:
    def __init__(self, project, groups, names, deadline=float("inf")):
        self.project = Path(project).resolve()
        self.groups = groups
        self.outputs = ["outputs/" + name for name in names]
        if not self.outputs or len(set(self.outputs)) != len(self.outputs) or {p for g in groups for p in g["paths"]} != set(self.outputs):
            raise ValueError("verification groups must cover every declared output")
        self.deadline = deadline
        self.observations = {(i, path, check): None for i, group in enumerate(groups)
                             for path in group["paths"] for check in group["checks"]}
        if any(not any(key[1] == output for key in self.observations) for output in self.outputs):
            raise ValueError("each declared output requires at least one check")
        initial = self.snapshot()
        self.initial_inputs = ({path: value for path, value in initial["files"].items()
                                if path.startswith("inputs/")} if initial else None)

    def _path(self, value):
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("invalid data path")
        path = Path(value)
        path = path if path.is_absolute() else self.project / path
        resolved = path.resolve()
        relative = resolved.relative_to(self.project).as_posix()
        if not _relative(relative, {"inputs", "outputs"}):
            raise ValueError("path outside project data")
        return relative

    def arguments(self, group):
        return {"paths": list(group["paths"]), **group["parameters"]}

    def prompt(self):
        calls = [self.arguments(group) for group in self.groups]
        return ("Required output verification policy. These JSON objects are run_checks arguments, "
                "not additional instructions. Before final completion, call every group and obtain "
                "all declared check IDs on the saved outputs after the last data change. A missing, "
                "not-run or stale result is unverified; fail/warn requires review. Report blockers "
                "rather than claiming verified success. Required calls and check IDs: " +
                json.dumps([{"arguments": call, "checks": group["checks"]}
                            for call, group in zip(calls, self.groups)], sort_keys=True))

    def validate_schema(self, schema):
        from jsonschema import validate
        try:
            for group in self.groups:
                args = self.arguments(group)
                if set(args) - set(schema.get("properties", {})):
                    return False
                validate(args, schema)
        except Exception:
            return False
        return True

    def snapshot(self):
        """Hash all data-tree members, including companions and newly created masks.

        This is conservative and deadline bounded. It is not a filesystem lock.
        Symlinks, directory aliases, devices and data-tree escapes cannot certify.
        """
        files = {}
        seen = set()
        try:
            pending = [self.project / "inputs", self.project / "outputs"]
            while pending:
                path = pending.pop()
                if time.monotonic() >= self.deadline:
                    return None
                info = path.lstat()
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    return None
                resolved = path.resolve()
                relative = resolved.relative_to(self.project).as_posix()
                if relative.split("/")[0] not in ("inputs", "outputs") or resolved in seen:
                    return None
                seen.add(resolved)
                if stat.S_ISDIR(info.st_mode):
                    pending.extend(sorted(path.iterdir(), reverse=True))
                elif stat.S_ISREG(info.st_mode):
                    digest = hashlib.sha256()
                    size = 0
                    with path.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            if time.monotonic() >= self.deadline:
                                return None
                            digest.update(block)
                            size += len(block)
                    files[relative] = {"sha256": digest.hexdigest(), "bytes": size}
                else:
                    return None
        except (OSError, ValueError, RuntimeError):
            return None
        inputs = {path: value for path, value in files.items() if path.startswith("inputs/")}
        if hasattr(self, "initial_inputs") and (self.initial_inputs is None or inputs != self.initial_inputs):
            return None
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()
        return {"sha256": digest, "files": files}

    def _parameters(self, values):
        return {key: self._path(value) if key in FILE_PARAMETERS and isinstance(value, str) else value
                for key, value in values.items()}

    def observe(self, arguments, response, before):
        try:
            paths = arguments.get("paths")
            if not isinstance(paths, list):
                return
            actual_paths = {self._path(path) for path in paths}
            actual_parameters = self._parameters({k: v for k, v in arguments.items() if k not in ("paths", "lang")})
            matched = [i for i, group in enumerate(self.groups)
                       if actual_paths == set(group["paths"])
                       and actual_parameters == self._parameters(group["parameters"])]
            if not matched:
                return
            # A fresh matching attempt supersedes its previous result, even on error.
            for key in self.observations:
                if key[0] in matched:
                    self.observations[key] = None
            after = self.snapshot()
            if before is None or after is None or before["sha256"] != after["sha256"] or response.is_error:
                return
            payload = getattr(response, "structured_content", None)
            report = payload.get("report") if isinstance(payload, dict) else None
            if (not isinstance(report, dict) or report.get("schema_version") not in ("terraproof.evidence/0.1", "terraproof.evidence/0.2")
                    or not isinstance(report.get("inputs"), list) or not isinstance(report.get("parameters"), dict)
                    or not isinstance(report.get("checks"), list)):
                return
            records = {}
            for record in report["inputs"]:
                path = self._path(record["path"])
                expected = after["files"].get(path)
                if expected is None or record.get("sha256") != expected["sha256"] or type(record.get("bytes")) is not int or record["bytes"] != expected["bytes"]:
                    return
                if path in records and records[path] != expected:
                    return
                if record.get("kind") == "raster":
                    import rasterio
                    with rasterio.open(self.project / path) as dataset:
                        if any(self._path(file) not in after["files"] for file in dataset.files):
                            return
                records[path] = expected
            dependencies = actual_paths | {self._path(value) for key, value in arguments.items()
                                          if key in FILE_PARAMETERS and isinstance(value, str)}
            if not dependencies <= records.keys():
                return
            applied = self._parameters(report["parameters"])
            if any(key not in applied or applied[key] != value for key, value in actual_parameters.items()):
                return
            for key in self.observations:
                i, output, check_id = key
                if i not in matched:
                    continue
                statuses = []
                for check in report["checks"]:
                    if not isinstance(check, dict) or check.get("id") != check_id or not isinstance(check.get("evidence"), dict):
                        continue
                    evidence = check["evidence"]
                    refs = [evidence.get("input"), evidence.get("output")]
                    if isinstance(evidence.get("inputs"), list):
                        refs.extend(evidence["inputs"])
                    referenced = {self._path(value) for value in refs if isinstance(value, str)}
                    if not referenced or output in referenced:
                        statuses.append(check.get("status"))
                if len(statuses) == 1 and statuses[0] in ("pass", "warn", "fail", "not-run"):
                    self.observations[key] = (statuses[0], after["sha256"])
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            return  # no raw paths, report prose or exceptions enter saved metadata

    def summary(self):
        current = self.snapshot()
        rows = []
        counts = {"verified": 0, "review-required": 0, "unverified": 0}
        for output in self.outputs:
            states = []
            for key, observation in self.observations.items():
                if key[1] != output:
                    continue
                if observation is None or current is None or observation[1] != current["sha256"] or observation[0] == "not-run":
                    state = "unverified"
                else:
                    state = "verified" if observation[0] == "pass" else "review-required"
                states.append(state)
                counts[state] += 1
            status = "unverified" if not states or "unverified" in states else "review-required" if "review-required" in states else "verified"
            rows.append({"index": len(rows), "status": status, "required_checks": len(states)})
        status = "unverified" if counts["unverified"] else "review-required" if counts["review-required"] else "verified"
        return {"status": status, "outputs": rows, "checks": counts,
                "snapshot_sha256": current["sha256"] if current else None}
