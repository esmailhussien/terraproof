"""Project verification: every deliverable declared once in a project file, checked in one run."""
from __future__ import annotations

import json
import sys

import numpy as np
import pytest

from terraproof import project
from terraproof.cli import main

needs_toml = pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is in the standard library from 3.11")


@pytest.fixture
def pipeline(make_raster, tmp_path):
    """A QA layer, an elevation source, and a correct and a wrong deliverable of each form."""
    codes = np.full((512, 512), 4, dtype="uint8")
    codes[:, :64] = 8   # medium-probability cloud
    codes[:32, :] = 6   # water
    make_raster("scl.tif", codes, nodata=0)
    make_raster("mask.tif", np.isin(codes, [4, 5, 6]).astype("uint8"), nodata=None)
    make_raster("mask_cloud_kept.tif", np.ones_like(codes), nodata=None)
    elevation = np.arange(512 * 512, dtype="float32").reshape(512, 512) / 10.0
    make_raster("dem.tif", elevation)
    mean, top = float(elevation.astype("float64").mean()), float(elevation.max())
    (tmp_path / "report.json").write_text(json.dumps({"stats": [{"mean_m": round(mean, 3)}], "max_m": top}))
    (tmp_path / "report_wrong.json").write_text(json.dumps({"stats": [{"mean_m": round(mean * 1.05, 3)}], "max_m": top}))
    return tmp_path


TOML = """schema = "terraproof.project/1"

[[deliverables]]
name = "usable-pixel mask"
outputs = ["{mask}"]
goals = ["qa-masked"]
qa_path = "scl.tif"
qa_kind = "keep-codes"
qa_keep_codes = [4, 5, 6]
output_form = "validity-mask"
output_valid_value = 1

[[deliverables]]
name = "elevation report"
outputs = ["{report}"]
goals = ["summary-value"]

[[deliverables.summaries]]
key = "stats.0.mean_m"
statistic = "mean"
source = "dem.tif"

[[deliverables.summaries]]
key = "max_m"
statistic = "max"
source = "dem.tif"
"""


def _write(folder, mask="mask.tif", report="report.json"):
    path = folder / "terraproof.toml"
    path.write_text(TOML.format(mask=mask, report=report), encoding="utf-8")
    return path


@needs_toml
def test_correct_deliverables_are_verified_in_one_run(pipeline, monkeypatch, capsys, tmp_path_factory):
    path = _write(pipeline)
    monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))  # paths resolve against the file, not the cwd
    summary = project.verify(path)
    assert summary["exit_code"] == 0
    assert [(r["name"], r["status"], r["grade"]) for r in summary["deliverables"]] == [
        ("usable-pixel mask", "verified", "decision-grade"), ("elevation report", "verified", "decision-grade")]
    assert main(["verify", str(path)]) == 0
    assert "PASS" in capsys.readouterr().out


@needs_toml
def test_a_wrong_deliverable_fails_the_run_and_names_its_finding(pipeline, monkeypatch, capsys):
    monkeypatch.chdir(pipeline)
    _write(pipeline, mask="mask_cloud_kept.tif", report="report_wrong.json")
    assert main(["verify"]) == 3  # the default file in the current folder
    out = capsys.readouterr().out
    assert out.count("FAIL") == 2 and "rs.cloud_mask_applied fail" in out and "stats.0.mean_m" in out
    summary = project.verify(only=["elevation report"])
    findings = summary["deliverables"][0]["findings"]
    assert [f["check"] for f in findings] == ["report.summary_value"] and findings[0]["status"] == "fail"


@needs_toml
def test_plan_runs_nothing_and_names_missing_bindings(pipeline, tmp_path):
    path = pipeline / "terraproof.toml"
    path.write_text('schema = "terraproof.project/1"\n\n[[deliverables]]\nname = "slope"\noutputs = ["slope.tif"]\n'
                    'goals = ["slope-from-dem"]\n\n[[deliverables]]\nname = "share"\noutputs = ["share.json"]\n'
                    'goals = ["summary-value"]\n\n[[deliverables.summaries]]\nkey = "water"\nstatistic = "fraction"\n'
                    'source = "scl.tif"\n', encoding="utf-8")
    summary = project.plan(path)
    assert summary["exit_code"] == 3
    rows = {r["name"]: r for r in summary["deliverables"]}
    assert rows["slope"]["missing_bindings"] == ["dem"] and rows["slope"]["outputs_present"] == [False]
    assert rows["share"]["missing_bindings"] == ["summaries[0].unit"]
    verified = project.verify(path)
    assert {r["status"] for r in verified["deliverables"]} == {"missing-output"} and verified["exit_code"] == 3


def test_json_project_and_mcp_tool_agree_with_the_cli(pipeline, capsys):
    path = pipeline / "terraproof.json"
    path.write_text(json.dumps({"schema": "terraproof.project/1", "deliverables": [{
        "name": "usable-pixel mask", "outputs": ["mask.tif"], "goals": ["qa-masked"], "qa_path": "scl.tif",
        "qa_kind": "keep-codes", "qa_keep_codes": [4, 5, 6], "output_form": "validity-mask",
        "output_valid_value": 1}]}), encoding="utf-8")
    assert main(["verify", str(path), "--format", "json"]) == 0
    cli = json.loads(capsys.readouterr().out)
    pytest.importorskip("mcp")
    from terraproof.mcp.server import verify_project
    assert verify_project(str(path)) == cli


def test_reports_are_written_per_deliverable(pipeline):
    path = pipeline / "terraproof.json"
    path.write_text(json.dumps({"schema": "terraproof.project/1", "deliverables": [{
        "name": "elevation report", "outputs": ["report.json"], "goals": ["summary-value"],
        "summaries": [{"key": "max_m", "statistic": "max", "source": "dem.tif"}]}]}), encoding="utf-8")
    summary = project.verify(path, reports_dir=pipeline / "reports")
    report = json.loads((pipeline / "reports" / "elevation-report.json").read_text(encoding="utf-8"))
    assert summary["deliverables"][0]["report"].endswith("elevation-report.json")
    assert report["verification"]["status"] == "review-required"
    # the other number is not declared, so the report needs review
    assert summary["deliverables"][0]["grade"] == "review-required" and summary["exit_code"] == 2


@pytest.mark.parametrize("entry, message", [
    ({"name": "a", "outputs": ["x.tif"], "goals": ["qa-masked"], "qa_pth": "scl.tif"}, "unknown binding qa_pth"),
    ({"name": "a", "outputs": ["x.tif"], "goals": ["masked"]}, "unknown goal masked"),
    ({"name": "a", "outputs": ["x.tif"]}, "declare goals"),
    ({"outputs": ["x.tif"], "goals": ["qa-masked"]}, "needs a name"),
])
def test_invalid_declarations_are_usage_errors(tmp_path, capsys, entry, message):
    path = tmp_path / "terraproof.json"
    path.write_text(json.dumps({"schema": "terraproof.project/1", "deliverables": [entry]}), encoding="utf-8")
    assert main(["verify", str(path)]) == 1
    assert message in capsys.readouterr().err


def test_no_project_file_is_a_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["verify"]) == 1
    assert "terraproof.toml" in capsys.readouterr().err
