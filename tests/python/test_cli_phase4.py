"""Phase 4 CLI wiring: preflight, processing-level checks, manifests, and provenance."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Polygon

from terraproof.cli import main
from terraproof._run_helpers import load_accuracy_samples, verify_manifest_coverage


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI as a subprocess to exercise the module entry point."""
    result = subprocess.run(
        [sys.executable, "-m", "terraproof", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# --- Preflight command ---


def test_preflight_command_exits_with_advisory_for_failing_plan(make_raster, tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"operation": "area"}), encoding="utf-8")
    raster = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0, crs="EPSG:4326")

    code, stdout, _ = _run(["preflight", str(raster), "--plan", str(plan_path)])

    report = json.loads(stdout)
    assert code == 3
    assert report["grade"] == "advisory-only"
    assert any(check["id"] == "preflight.metric_crs" and check["status"] == "fail" for check in report["checks"])


def test_preflight_command_exits_zero_for_passing_plan(make_raster, tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"operation": "area"}), encoding="utf-8")
    raster = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)

    code, stdout, _ = _run(["preflight", str(raster), "--plan", str(plan_path)])

    report = json.loads(stdout)
    assert code == 0
    assert report["grade"] == "checks-passed"


def test_preflight_rejects_invalid_plan(make_raster, tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"operation": "volume"}), encoding="utf-8")
    raster = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)

    code, _, stderr = _run(["preflight", str(raster), "--plan", str(plan_path)])

    assert code == 1
    assert "operation" in stderr


# --- Phase 4 run_checks wiring on the CLI ---


def test_check_with_reference_input_and_encoding(make_raster, tmp_path, capsys):
    dn = make_raster("dn.tif", np.full((64, 64), 1500, dtype="uint16"), nodata=65535)
    out = make_raster("out.tif", np.full((64, 64), 0.05, dtype="float32"), nodata=-9999.0)

    assert main(["check", str(out), "--reference-input", str(dn), "--encoding", "s2-l2a"]) == 0

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("rs.scale_applied_once") == "pass"
    assert report["parameters"]["encoding"] == "s2-l2a"
    assert report["parameters"]["reference_input"] == str(dn)


def test_check_with_qa_and_qa_kind(make_raster, tmp_path, capsys):
    out = make_raster("out.tif", np.full((64, 64), 0.25, dtype="float32"), nodata=-9999.0)
    qa = tmp_path / "scl.tif"
    import rasterio
    with rasterio.open(
        qa, "w", driver="GTiff", width=64, height=64, count=1, dtype="uint8", crs="EPSG:32636",
        transform=rasterio.transform.from_origin(500000.0, 5000000.0, 10.0, 10.0), nodata=None,
    ) as dst:
        dst.write(np.full((64, 64), 9, dtype="uint8"), 1)

    assert main(["check", str(out), "--qa", str(qa), "--qa-kind", "s2-scl"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("rs.cloud_mask_applied") == "fail"


def test_check_with_time_range(make_stac_item, capsys):
    item = make_stac_item("item.json", {"datetime": "2025-06-15T00:00:00Z"})

    assert main(["check", str(item), "--time-range", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("rs.temporal_scope") == "fail"


def test_check_with_sar_expect(make_raster, capsys):
    path = make_raster("sar.tif", np.full((64, 64), -8.0, dtype="float32"), nodata=-9999.0)

    assert main(["check", str(path), "--sar-expect", "sigma0-db"]) == 0

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("sar.value_domain") == "pass"
    assert ids.get("sar.geocoded") == "pass"


def test_check_with_accuracy_samples_and_class_areas(make_vector, tmp_path, capsys):
    path = make_vector("dummy.gpkg", [square(500000, 5000000)])
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps([
        {"map_class": "forest", "ref_class": "forest"},
        {"map_class": "water", "ref_class": "water"},
    ] * 30), encoding="utf-8")
    areas = tmp_path / "areas.json"
    areas.write_text(json.dumps({"forest": 1000.0, "water": 500.0}), encoding="utf-8")

    assert main(["check", str(path), "--accuracy-samples", str(samples), "--class-areas", str(areas), "--estimates-requested", "--min-per-class", "10"]) == 0

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("accuracy.sample_design") == "pass"
    assert ids.get("accuracy.estimates") == "pass"


# --- Manifest / provenance wiring ---


def test_manifest_write_and_verify_round_trip_via_cli(tmp_path):
    in_path = tmp_path / "in.txt"
    out_path = tmp_path / "out.txt"
    in_path.write_text("input", encoding="utf-8")
    out_path.write_text("output", encoding="utf-8")
    manifest_path = tmp_path / "run.manifest.json"

    code, _, _ = _run([
        "manifest", "write",
        "--inputs", str(in_path),
        "--outputs", str(out_path),
        "--out", str(manifest_path),
    ])
    assert code == 0

    code, stdout, _ = _run(["manifest", "verify", str(manifest_path)])
    assert code == 0
    assert "PASS" in stdout


def test_check_with_verified_manifest_passes(make_vector, tmp_path, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    manifest_path = tmp_path / "run.manifest.json"
    _run([
        "manifest", "write",
        "--inputs", str(path),
        "--outputs", str(path),
        "--out", str(manifest_path),
    ])

    assert main(["check", str(path), "--manifest", str(manifest_path), "--operation", "area"]) == 0

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "pass"


def test_check_with_unrelated_manifest_fails(make_vector, tmp_path, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    other = tmp_path / "other.txt"
    other.write_text("other", encoding="utf-8")
    manifest_path = tmp_path / "run.manifest.json"
    _run([
        "manifest", "write",
        "--inputs", str(other),
        "--outputs", str(other),
        "--out", str(manifest_path),
    ])

    assert main(["check", str(path), "--manifest", str(manifest_path), "--operation", "area"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "fail"
    assert "does not cover" in json.dumps(report).lower()


def test_check_with_tampered_manifest_fails(make_vector, tmp_path, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    manifest_path = tmp_path / "run.manifest.json"
    _run([
        "manifest", "write",
        "--inputs", str(path),
        "--outputs", str(path),
        "--out", str(manifest_path),
    ])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["core"]["parameters"]["tamper"] = True
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    assert main(["check", str(path), "--manifest", str(manifest_path), "--operation", "area"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "fail"


def test_check_require_provenance_without_manifest_is_advisory(make_vector, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    assert main(["check", str(path), "--operation", "area", "--require-provenance"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "fail"
    assert report["grade"] == "advisory-only"


def test_check_with_partially_covered_manifest_fails(make_vector, make_raster, tmp_path, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    ref = make_raster("ref.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)
    manifest_path = tmp_path / "run.manifest.json"
    _run([
        "manifest", "write",
        "--inputs", str(path),
        "--outputs", str(path),
        "--out", str(manifest_path),
    ])

    assert main(["check", str(path), "--reference-input", str(ref), "--manifest", str(manifest_path)]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "fail"
    assert "does not cover" in json.dumps(report).lower()


def test_check_with_missing_manifest_file_fails(make_vector, tmp_path, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    missing_manifest = tmp_path / "missing.manifest.json"

    assert main(["check", str(path), "--manifest", str(missing_manifest), "--operation", "area"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "fail"


def test_check_with_malformed_manifest_fails(make_vector, tmp_path, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    manifest_path = tmp_path / "bad.manifest.json"
    manifest_path.write_text("not json", encoding="utf-8")

    assert main(["check", str(path), "--manifest", str(manifest_path), "--operation", "area"]) == 3

    report = json.loads(capsys.readouterr().out)
    ids = {check["id"]: check["status"] for check in report["checks"]}
    assert ids.get("provenance.reproducible") == "fail"


# --- Weighted sample input forms ---


def test_accuracy_samples_json_and_csv_produce_same_results(make_vector, tmp_path, capsys):
    path = make_vector("dummy.gpkg", [square(500000, 5000000)])
    rows = [
        ("forest", "forest", 2.0),
        ("water", "water", 1.0),
    ] * 20
    json_path = tmp_path / "samples.json"
    json_path.write_text(
        json.dumps([{"map_class": r[0], "ref_class": r[1], "stratum_weight": r[2]} for r in rows]),
        encoding="utf-8",
    )
    csv_path = tmp_path / "samples.csv"
    csv_path.write_text("map_class,ref_class,stratum_weight\n" + "\n".join(f"{r[0]},{r[1]},{r[2]}" for r in rows) + "\n", encoding="utf-8")
    areas = tmp_path / "areas.json"
    areas.write_text(json.dumps({"forest": 1000.0, "water": 500.0}), encoding="utf-8")

    main(["check", str(path), "--accuracy-samples", str(json_path), "--class-areas", str(areas), "--estimates-requested", "--min-per-class", "10"])
    json_report = json.loads(capsys.readouterr().out)
    main(["check", str(path), "--accuracy-samples", str(csv_path), "--class-areas", str(areas), "--estimates-requested", "--min-per-class", "10"])
    csv_report = json.loads(capsys.readouterr().out)

    json_checks = {c["id"]: c["status"] for c in json_report["checks"]}
    csv_checks = {c["id"]: c["status"] for c in csv_report["checks"]}
    assert json_checks.get("accuracy.sample_design") == csv_checks.get("accuracy.sample_design")
    assert json_checks.get("accuracy.estimates") == csv_checks.get("accuracy.estimates")


def test_accuracy_sample_numeric_zero_class_is_preserved():
    loaded = load_accuracy_samples([{"map_class": 0, "ref_class": 0}])
    assert loaded["records"] == [{"map_class": "0", "ref_class": "0", "stratum_weight": None}]


def test_manifest_structural_error_is_provenance_failure(tmp_path):
    manifest_path = tmp_path / "malformed.manifest.json"
    manifest_path.write_text(json.dumps({"schema": "terraproof.manifest/0.1", "core": []}), encoding="utf-8")
    result = verify_manifest_coverage(manifest_path, [])
    assert result.id == "provenance.reproducible"
    assert result.status == "fail"


# --- Router mode and semantic flag ---


def test_route_candidates_mode_returns_explanations():
    code, stdout, _ = _run(["route", "compute NDVI", "--mode", "candidates"])

    assert code == 0
    result = json.loads(stdout)
    assert any("explanation" in skill for skill in result["skills"])


def test_route_semantic_flag_is_accepted():
    code, stdout, _ = _run(["route", "compute NDVI", "--semantic"])

    assert code == 0
    result = json.loads(stdout)
    assert isinstance(result["skills"], list)


# --- Old CLI behaviour is preserved ---


def test_check_without_phase4_options_still_works(make_vector, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    assert main(["check", str(path), "--operation", "area"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["grade"] == "checks-passed"
    assert report["parameters"]["categorical"] is False
