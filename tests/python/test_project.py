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


def test_before_the_file_exists_the_plan_is_the_guide_to_writing_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    guide = project.plan()
    assert guide["mode"] == "guide" and guide["exit_code"] == 3 and guide["deliverables"] == []
    assert set(guide["goals"]) == set(project.profiles()) and set(guide["bindings"]) == project.BINDINGS
    assert guide["goals"]["slope-from-dem"]["required_bindings"] == ["dem"]
    for goal in guide["goals"].values():  # every binding a goal requires is described
        assert set(goal["required_bindings"]) <= set(guide["bindings"])
    assert guide["bindings"]["qa_keep_codes"]["value"] == "list of integers"
    assert "qa_kind keep-codes" in guide["bindings"]["qa_keep_codes"]["meaning"]  # flags named as bindings
    assert guide["bindings"]["expect"]["choices"] == ["reflectance", "index"]
    assert project.plan(tmp_path / "later" / "terraproof.json") == guide  # a path not yet written
    pytest.importorskip("mcp")
    from terraproof.mcp.server import verify_project
    assert verify_project(plan=True) == json.loads(json.dumps(guide))
    assert main(["verify", "--plan"]) == 3 and "slope-from-dem" in capsys.readouterr().out


@needs_toml
def test_the_guide_template_is_a_complete_declaration(tmp_path):
    path = tmp_path / "terraproof.toml"
    path.write_text(project.guide()["template"], encoding="utf-8")
    summary = project.plan(path)
    assert summary["mode"] == "plan" and summary["exit_code"] == 0 and len(summary["deliverables"]) == 2


def _declared(root, task_id, wrong, **binding):
    """A headroom task's inputs and one of its outputs, declared with the given bindings."""
    from terraproof.evals import lift

    task = lift.lift_task(task_id)
    lift._generate(task, root)
    if wrong:
        (root / "result.tif").write_bytes((root / wrong).read_bytes())
    path = root / "terraproof.json"
    path.write_text(json.dumps({"schema": project.SCHEMA, "deliverables": [
        dict(name="result", outputs=["result.tif"], **binding)]}), encoding="utf-8")
    return path


MIXED = {"goals": ["vertical-units"], "vertical_operation": "difference",
         "vertical_sources": ["dem_2023.tif", "dem_2015.tif"], "vertical_unit": "metre"}


def test_a_declaration_its_source_file_contradicts_fails_before_and_after_outputs(tmp_path):
    # the 2015 survey's band unit is ft; declaring it metre repeats the units-ignored mistake
    path = _declared(tmp_path, "hr-elevation-change-mixed-units", "units-ignored.tif",
                     vertical_source_units=["metre", "metre"], **MIXED)
    planned = project.plan(path)["deliverables"][0]
    assert not planned["ready"] and planned["missing_bindings"] == []
    assert planned["conflicts"] == ["vertical_source_units for dem_2015.tif is declared metre, "
                                    "but its metadata states dem_2015.tif band 1 unit = ft"]
    row = project.verify(path)["deliverables"][0]
    assert row["status"] == "failed" and row["grade"] == "advisory-only" and row["exit_code"] == 3
    assert row["findings"][0]["check"] == project.DECLARATION
    assert "CONFLICT" in project.render(project.plan(path))
    right = _declared(tmp_path / "right", "hr-elevation-change-mixed-units", None,
                      vertical_source_units=["metre", "foot"], **MIXED)
    assert project.plan(right)["deliverables"][0]["conflicts"] == []
    assert project.verify(right)["deliverables"][0]["status"] == "verified"


def test_a_stac_item_beside_the_source_is_metadata_too(tmp_path):
    # the Item's asset href points at B04.tif and states offset -0.1; declaring 0 repeats the no-offset mistake
    scl = {"goals": ["qa-masked", "scaled-reflectance"], "qa_path": "SCL.tif", "qa_kind": "keep-codes",
           "qa_keep_codes": [4, 5, 6], "reference_input": "B04.tif", "decode_scale": 0.0001, "expect": "reflectance",
           "processing_full_scan": True}
    row = project.verify(_declared(tmp_path, "hr-s2-scl-red", "no-offset.tif", decode_offset=0.0, **scl))
    finding = row["deliverables"][0]["findings"][0]
    assert finding["check"] == project.DECLARATION and "item.json assets.red.raster:bands[0].offset = -0.1" \
        in finding["message"]
    # a fill only the Item's classification states must be declared: the files' own masks miss it
    fill = {"goals": ["nodata-support"], "support_sources": ["landcover_2019.tif", "landcover_2023.tif"],
            "support_rule": "all"}
    missed = project.plan(_declared(tmp_path / "lc", "hr-landcover-change-fill", None, **fill))
    assert len(missed["deliverables"][0]["conflicts"]) == 2
    assert "classification:classes = 0" in missed["deliverables"][0]["conflicts"][0]
    declared = _declared(tmp_path / "lc2", "hr-landcover-change-fill", None, support_source_nodata=[0, 0], **fill)
    assert project.verify(declared)["deliverables"][0]["status"] == "verified"


def test_metadata_that_disagrees_with_itself_is_not_held_against_the_declaration(tmp_path):
    from terraproof.evidence.propose import declaration_conflicts, local_stac_links

    _declared(tmp_path, "hr-s2-scl-red", None)
    item = json.loads((tmp_path / "item.json").read_text(encoding="utf-8"))
    item["properties"]["earthsearch:boa_offset_applied"] = True  # beside offset -0.1: ambiguous, so not compared
    (tmp_path / "item.json").write_text(json.dumps(item), encoding="utf-8")
    stac = local_stac_links([tmp_path])
    assert stac[(tmp_path / "B04.tif").resolve()][1] == "red"
    for offset in (0.0, -0.1):
        assert declaration_conflicts({"reference_input": str(tmp_path / "B04.tif"), "decode_offset": offset}, stac) == []


def test_the_plan_names_a_source_decode_no_declared_check_applies(tmp_path):
    # t2m.tif states scale 0.0018 and offset 285; declaring only its support leaves a kelvin output unverified
    support = {"goals": ["nodata-support"], "support_sources": ["t2m.tif"], "support_rule": "all"}
    hints = project.plan(_declared(tmp_path, "hr-reanalysis-air-temperature", None, **support))["deliverables"][0]
    assert hints["hints"] == ["t2m.tif states scale 0.0018 and offset 285.0; if the output holds its decoded "
                              "values, declare rs.scale_applied_once with it as reference_input"]
    assert hints["ready"]  # advisory: the declaration is still complete
    decoded = dict(support, checks=["rs.scale_applied_once"], reference_input="t2m.tif", decode_scale=0.0018,
                   decode_offset=285.0, unit_conversion="kelvin-to-celsius", processing_full_scan=True)
    row = project.verify(_declared(tmp_path / "decoded", "hr-reanalysis-air-temperature", None, **decoded))
    assert row["deliverables"][0]["hints"] == [] and row["deliverables"][0]["status"] == "verified"


def test_checks_with_no_source_say_the_derivation_was_not_checked(make_raster, tmp_path, capsys):
    elevation = np.arange(64 * 64, dtype="float32").reshape(64, 64)
    make_raster("dem.tif", elevation)
    make_raster("feet.tif", elevation / 0.3048)
    assert main(["check", str(tmp_path / "feet.tif"), "--format", "json"]) == 0
    step = json.loads(capsys.readouterr().out)["next_step"]
    assert step["derivation_checked"] is False and "project file" in step["why"]
    main(["check", str(tmp_path / "feet.tif"), "--vertical-operation", "convert", "--vertical-source",
          str(tmp_path / "dem.tif"), "--vertical-source-unit", "metre", "--vertical-unit", "foot", "--format", "json"])
    step = json.loads(capsys.readouterr().out)["next_step"]  # a source-enabled check ran: declare its goal
    assert "derivation_checked" not in step and step["profiles"] == ["vertical-units"]
