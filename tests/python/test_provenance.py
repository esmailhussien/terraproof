"""Tests for provenance run manifests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from terraproof.provenance import verify_manifest, write_manifest


def _write_manifest(
    tmp_path: Path,
    inputs: list[Path],
    outputs: list[Path],
    *,
    params: dict | None = None,
    stac_items: list[Path] | None = None,
    root: Path | None = None,
) -> Path:
    manifest_path = tmp_path / "run.manifest.json"
    manifest = write_manifest(
        inputs=inputs,
        outputs=outputs,
        parameters=params,
        stac_items=stac_items,
        root=root,
        manifest_path=manifest_path,
        command_line=["test"],
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_round_trip_pass(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])
    check = verify_manifest(manifest_path)

    assert check.status == "pass"
    assert check.id == "provenance.reproducible"


def test_changed_output_byte_fails(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])
    output_path.write_bytes(output_path.read_bytes() + b"!")
    check = verify_manifest(manifest_path)

    assert check.status == "fail"
    assert "out.txt" in check.evidence["changed"]


def test_deleted_file_fails(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])
    output_path.unlink()
    check = verify_manifest(manifest_path)

    assert check.status == "fail"
    assert "out.txt" in check.evidence["missing"]


def test_tampered_core_fails(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["core"]["parameters"]["tamper"] = True
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    check = verify_manifest(manifest_path)
    assert check.status == "fail"
    assert "does not match its recorded hash" in check.message


def test_version_drift_warns(tmp_path, monkeypatch):
    from terraproof.provenance._core import tool_versions as real_tool_versions

    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])

    original_versions = real_tool_versions()

    def _drifted_versions():
        versions = dict(original_versions)
        versions["numpy"] = "0.0.0-drift"
        return versions

    monkeypatch.setattr("terraproof.provenance._core.tool_versions", _drifted_versions)
    check = verify_manifest(manifest_path)

    assert check.status == "warn"
    assert "numpy" in check.evidence["drifted"]


def test_path_outside_root_rejected(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    other_root = tmp_path / "other"
    other_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="outside root"):
        write_manifest(
            inputs=[input_path],
            outputs=[output_path],
            root=other_root,
        )


def test_stac_item_recorded(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    stac_path = tmp_path / "item.json"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    stac_path.write_text(
        json.dumps({
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "S2A_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2024-01-01T00:00:00Z"},
            "assets": {
                "red": {"href": "./red.tif"},
                "nir": {"href": "./nir.tif"},
            },
        }),
        encoding="utf-8",
    )

    manifest = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        stac_items=[stac_path],
        root=tmp_path,
    )

    stac_items = manifest["core"]["stac_items"]
    assert len(stac_items) == 1
    assert stac_items[0]["id"] == "S2A_TEST"
    assert stac_items[0]["collection"] == "sentinel-2-l2a"
    assert stac_items[0]["datetime"] == "2024-01-01T00:00:00Z"
    assert stac_items[0]["asset_hrefs"] == {"nir": "./nir.tif", "red": "./red.tif"}


def test_deterministic_core(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest_a = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        root=tmp_path,
        command_line=["test"],
    )
    manifest_b = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        root=tmp_path,
        command_line=["test"],
    )

    assert manifest_a["core"] == manifest_b["core"]
    assert manifest_a["core_sha256"] == manifest_b["core_sha256"]


def test_paths_stored_with_forward_slashes(tmp_path):
    input_path = tmp_path / "sub" / "in.txt"
    output_path = tmp_path / "sub" / "out.txt"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")

    manifest = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        root=tmp_path,
    )

    paths = {f["path"] for f in manifest["core"]["files"]}
    assert all("/" in p and "\\" not in p for p in paths)


def test_default_root_is_manifest_parent(tmp_path):
    """write stores paths relative to the manifest's parent by default."""
    data_dir = tmp_path / "data"
    runs_dir = tmp_path / "runs"
    data_dir.mkdir()
    runs_dir.mkdir()
    input_path = data_dir / "in.txt"
    output_path = data_dir / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    manifest_path = runs_dir / "run.manifest.json"

    manifest = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        manifest_path=manifest_path,
    )

    assert manifest["core"]["root_rule"] == "manifest-parent"
    paths = {f["path"] for f in manifest["core"]["files"]}
    assert paths == {"../data/in.txt", "../data/out.txt"}

    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")
    check = verify_manifest(manifest_path)
    assert check.status == "pass"


def test_verify_from_different_cwd(tmp_path):
    data_dir = tmp_path / "data"
    runs_dir = tmp_path / "runs"
    data_dir.mkdir()
    runs_dir.mkdir()
    input_path = data_dir / "in.txt"
    output_path = data_dir / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    manifest_path = runs_dir / "run.manifest.json"

    manifest = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        manifest_path=manifest_path,
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        check = verify_manifest(manifest_path)
        assert check.status == "pass"
    finally:
        os.chdir(original_cwd)


def test_verify_after_copying_whole_folder(tmp_path):
    data_dir = tmp_path / "data"
    runs_dir = tmp_path / "runs"
    data_dir.mkdir()
    runs_dir.mkdir()
    input_path = data_dir / "in.txt"
    output_path = data_dir / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    manifest_path = runs_dir / "run.manifest.json"

    manifest = write_manifest(
        inputs=[input_path],
        outputs=[output_path],
        manifest_path=manifest_path,
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    copy_dir = tmp_path / "copy"
    shutil.copytree(tmp_path, copy_dir)
    check = verify_manifest(copy_dir / "runs" / "run.manifest.json")
    assert check.status == "pass"


def _recompute_core_sha256(manifest: dict) -> None:
    from terraproof.provenance._core import _hash_core
    manifest["core_sha256"] = _hash_core(manifest["core"])


def test_recorded_path_with_dotdot_fails_verify(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Escapes even the workspace (parent of the manifest parent).
    manifest["core"]["files"][0]["path"] = "../../escape/in.txt"
    _recompute_core_sha256(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    check = verify_manifest(manifest_path)
    assert check.status == "fail"
    assert "escapes workspace" in check.message


def test_recorded_absolute_path_fails_verify(tmp_path):
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.txt"
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    manifest_path = _write_manifest(tmp_path, [input_path], [output_path])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["core"]["files"][0]["path"] = "/etc/passwd"
    _recompute_core_sha256(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    check = verify_manifest(manifest_path)
    assert check.status == "fail"
    assert "escapes workspace" in check.message


class TestCli:
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, "-m", "terraproof.provenance", *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode, result.stdout, result.stderr

    def test_write_and_verify_round_trip(self, tmp_path):
        input_path = tmp_path / "in.txt"
        output_path = tmp_path / "out.txt"
        input_path.write_text("input", encoding="utf-8")
        output_path.write_text("output", encoding="utf-8")
        manifest_path = tmp_path / "run.manifest.json"

        code, _, _ = self._run([
            "write",
            "--inputs", str(input_path),
            "--outputs", str(output_path),
            "--out", str(manifest_path),
        ])
        assert code == 0

        code, stdout, _ = self._run(["verify", str(manifest_path)])
        assert code == 0
        assert "PASS" in stdout

    def test_verify_changed_file_exits_3(self, tmp_path):
        input_path = tmp_path / "in.txt"
        output_path = tmp_path / "out.txt"
        input_path.write_text("input", encoding="utf-8")
        output_path.write_text("output", encoding="utf-8")
        manifest_path = tmp_path / "run.manifest.json"

        self._run([
            "write",
            "--inputs", str(input_path),
            "--outputs", str(output_path),
            "--root", str(tmp_path),
            "--out", str(manifest_path),
        ])
        output_path.write_bytes(output_path.read_bytes() + b"!")

        code, stdout, _ = self._run(["verify", str(manifest_path)])
        assert code == 3
        assert "FAIL" in stdout

    def test_verify_json_format(self, tmp_path):
        input_path = tmp_path / "in.txt"
        output_path = tmp_path / "out.txt"
        input_path.write_text("input", encoding="utf-8")
        output_path.write_text("output", encoding="utf-8")
        manifest_path = tmp_path / "run.manifest.json"

        self._run([
            "write",
            "--inputs", str(input_path),
            "--outputs", str(output_path),
            "--root", str(tmp_path),
            "--out", str(manifest_path),
        ])

        code, stdout, _ = self._run(["verify", "--format", "json", str(manifest_path)])
        assert code == 0
        parsed = json.loads(stdout)
        assert parsed["id"] == "provenance.reproducible"
        assert parsed["status"] == "pass"

    def test_usage_error_exits_1(self, tmp_path):
        code, _, _ = self._run(["write", "--inputs", "missing.txt", "--outputs", "out.txt", "--out", str(tmp_path / "m.json")])
        assert code == 1

    def test_path_outside_root_exits_1(self, tmp_path):
        input_path = tmp_path / "in.txt"
        output_path = tmp_path / "out.txt"
        input_path.write_text("input", encoding="utf-8")
        output_path.write_text("output", encoding="utf-8")
        other_root = tmp_path / "other"
        other_root.mkdir(parents=True, exist_ok=True)

        code, _, stderr = self._run([
            "write",
            "--inputs", str(input_path),
            "--outputs", str(output_path),
            "--root", str(other_root),
            "--out", str(tmp_path / "m.json"),
        ])
        assert code == 1
        assert "outside root" in stderr

    def test_default_manifest_parent_root_round_trip(self, tmp_path):
        """Exact scenario from review: data/ inputs and runs/ manifest, no --root."""
        data_dir = tmp_path / "data"
        runs_dir = tmp_path / "runs"
        data_dir.mkdir()
        runs_dir.mkdir()
        (data_dir / "in.txt").write_text("input", encoding="utf-8")
        (data_dir / "out.txt").write_text("output", encoding="utf-8")
        manifest_path = runs_dir / "run.manifest.json"

        code, _, _ = self._run([
            "write",
            "--inputs", str(data_dir / "in.txt"),
            "--outputs", str(data_dir / "out.txt"),
            "--out", str(manifest_path),
        ])
        assert code == 0

        code, stdout, _ = self._run(["verify", str(manifest_path)])
        assert code == 0
        assert "PASS" in stdout

    def test_verify_from_different_cwd_cli(self, tmp_path):
        data_dir = tmp_path / "data"
        runs_dir = tmp_path / "runs"
        data_dir.mkdir()
        runs_dir.mkdir()
        (data_dir / "in.txt").write_text("input", encoding="utf-8")
        (data_dir / "out.txt").write_text("output", encoding="utf-8")
        manifest_path = runs_dir / "run.manifest.json"

        self._run([
            "write",
            "--inputs", str(data_dir / "in.txt"),
            "--outputs", str(data_dir / "out.txt"),
            "--out", str(manifest_path),
        ])

        result = subprocess.run(
            [sys.executable, "-m", "terraproof.provenance", "verify", str(manifest_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_verify_copied_folder_cli(self, tmp_path):
        data_dir = tmp_path / "data"
        runs_dir = tmp_path / "runs"
        data_dir.mkdir()
        runs_dir.mkdir()
        (data_dir / "in.txt").write_text("input", encoding="utf-8")
        (data_dir / "out.txt").write_text("output", encoding="utf-8")
        manifest_path = runs_dir / "run.manifest.json"

        self._run([
            "write",
            "--inputs", str(data_dir / "in.txt"),
            "--outputs", str(data_dir / "out.txt"),
            "--out", str(manifest_path),
        ])

        copy_dir = tmp_path / "copy"
        shutil.copytree(tmp_path, copy_dir)

        code, stdout, _ = self._run(["verify", str(copy_dir / "runs" / "run.manifest.json")])
        assert code == 0
        assert "PASS" in stdout

    def test_recorded_dotdot_path_fails_verify_cli(self, tmp_path):
        input_path = tmp_path / "in.txt"
        output_path = tmp_path / "out.txt"
        input_path.write_text("input", encoding="utf-8")
        output_path.write_text("output", encoding="utf-8")
        manifest_path = tmp_path / "run.manifest.json"

        self._run([
            "write",
            "--inputs", str(input_path),
            "--outputs", str(output_path),
            "--out", str(manifest_path),
        ])

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["core"]["files"][0]["path"] = "../../escape/in.txt"
        _recompute_core_sha256(manifest)
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

        code, stdout, _ = self._run(["verify", str(manifest_path)])
        assert code == 3
        assert "escapes workspace" in stdout
