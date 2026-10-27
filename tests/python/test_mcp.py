"""MCP server tests: tool surface, inspections, checks, sections, and the router fallback."""

from __future__ import annotations

import json
import sys

import numpy as np
import pytest
from shapely.geometry import Polygon

pytest.importorskip("anyio", reason="the mcp extra is not installed")
pytest.importorskip("mcp", reason="the mcp extra is not installed")

import anyio  # noqa: E402
from mcp import Client  # noqa: E402

from terraproof.cli import main  # noqa: E402
from terraproof.mcp.server import mcp  # noqa: E402

TOOL_NAMES = ["find_guidance", "inspect_dataset", "list_skills", "load_section", "preflight", "run_checks"]


def test_full_processing_cli_mcp_parity_for_an_off_stride_error(make_raster, capsys):
    raw = np.full((129, 131), 2500, dtype="uint16")
    values = raw.astype("float32")*.0001-.1
    values[1, 1] += .125
    source = make_raster("full_source.tif", raw, nodata=65535)
    output = make_raster("full_output.tif", values, nodata=-9999.)
    assert main(["check", output, "--reference-input", source, "--encoding", "s2-l2a",
                 "--processing-full-scan"]) == 3
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [output], "reference_input": source,
        "encoding": "s2-l2a", "processing_full_scan": True}).structured_content
    a = next(c for c in cli["checks"] if c["id"] == "rs.scale_applied_once")
    b = next(c for c in payload["report"]["checks"] if c["id"] == "rs.scale_applied_once")
    assert a == b and a["status"] == "fail" and a["evidence"]["mismatched_pixels"] == 1


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def call(name: str, arguments: dict | None = None):
    """Call one tool through the SDK's in-memory client."""

    async def _call():
        async with Client(mcp, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(_call)


@pytest.mark.parametrize("defect", ["double", "offset", "nodata"])
def test_optical_blindspot_cli_mcp_parity(make_raster, capsys, defect):
    raw = np.full((16, 16), 2500, dtype="uint16")
    raw[0, 1] = 0
    decoded = raw.astype("float32") * 0.0001 - 0.1
    if defect == "double":
        decoded = decoded * 0.0001 - 0.1
    elif defect == "offset":
        decoded = raw.astype("float32") * 0.0001
    if defect != "nodata":
        decoded[0, 1] = -9999.0
    dn = make_raster("parity_dn.tif", raw, nodata=0)
    out = make_raster("parity_out.tif", decoded, nodata=-9999.0)
    assert main(["check", out, "--reference-input", dn, "--encoding", "s2-l2a"]) == 3
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [out], "reference_input": dn, "encoding": "s2-l2a"}).structured_content
    cli_check = next(c for c in cli["checks"] if c["id"] == "rs.scale_applied_once")
    mcp_check = next(c for c in payload["report"]["checks"] if c["id"] == "rs.scale_applied_once")
    assert cli_check == mcp_check
    assert cli_check["status"] == "fail"


@pytest.mark.parametrize("defect", ["created", "credentials", "structure"])
def test_manifest_blindspot_cli_mcp_parity(make_raster, tmp_path, capsys, defect):
    from terraproof.provenance._core import _hash_core

    path = make_raster("manifest_parity.tif", np.full((16, 16), 0.2, dtype="float32"), nodata=-9999.0)
    manifest_path = tmp_path / "parity.manifest.json"
    _write_manifest(manifest_path, [path], [path])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if defect == "created":
        manifest["core"]["created"] = "2024-01-01"
    elif defect == "credentials":
        manifest["core"]["parameters"]["nested"] = [{"href": "https://example.invalid/a?sig=PRIVATE"}]
    else:
        manifest["core"]["files"] = [None]
    manifest["core_sha256"] = _hash_core(manifest["core"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert main(["check", path, "--manifest", str(manifest_path)]) == 3
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [path], "manifest": str(manifest_path)}).structured_content
    cli_check = next(c for c in cli["checks"] if c["id"] == "provenance.reproducible")
    mcp_check = next(c for c in payload["report"]["checks"] if c["id"] == "provenance.reproducible")
    assert cli_check == mcp_check
    assert cli_check["status"] == "fail"
    assert "PRIVATE" not in json.dumps(cli_check)


def test_tool_list_names_and_guidance():
    async def _list():
        async with Client(mcp, raise_exceptions=True) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in anyio.run(_list).tools}

    assert sorted(tools) == TOOL_NAMES
    assert all(tool.description for tool in tools.values())
    assert "before you claim" in tools["run_checks"].description
    assert "before you claim" in tools["list_skills"].description or "before choosing" in tools["list_skills"].description
    assert "start of a task" in tools["find_guidance"].description


def test_inspect_dataset_returns_the_profile(make_vector):
    path = make_vector("parcels.gpkg", [square(500000, 5000000)])

    result = call("inspect_dataset", {"path": path})

    assert not result.is_error
    assert result.structured_content["kind"] == "vector"
    assert result.structured_content["crs"]["epsg"] == 32636
    assert result.structured_content["feature_count"] == 1


def test_inspect_dataset_missing_file_is_a_tool_error(tmp_path):
    result = call("inspect_dataset", {"path": str(tmp_path / "missing.gpkg")})

    assert result.is_error
    assert "file not found" in result.content[0].text


def test_run_checks_matches_the_cli_grade_and_report(make_vector, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    assert main(["check", path, "--operation", "area"]) == 0
    cli_report = json.loads(capsys.readouterr().out)

    payload = call("run_checks", {"paths": [path], "operation": "area"}).structured_content

    assert payload["report"] == cli_report
    assert payload["report"]["parameters"]["categorical"] is False
    assert payload["grade"] == cli_report["grade"] == "decision-grade"
    assert payload["exit_code"] == 0
    assert payload["markdown"].startswith("# Terraproof evidence report")


def test_run_checks_exit_code_follows_the_cli_contract(make_vector, capsys):
    empty = make_vector("empty.gpkg", [square(500000, 5000000), Polygon()])

    assert main(["check", empty]) == 2
    capsys.readouterr()

    payload = call("run_checks", {"paths": [empty]}).structured_content

    assert payload["grade"] == "review-required"
    assert payload["exit_code"] == 2


def test_run_checks_markdown_language(make_vector):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    payload = call("run_checks", {"paths": [path], "lang": "ar"}).structured_content
    assert payload["markdown"].startswith("# تقرير أدلة Terraproof")

    assert call("run_checks", {"paths": [path], "lang": "fr"}).is_error
    assert call("run_checks", {"paths": []}).is_error


def test_list_skills_describes_the_registry():
    skills = {skill["name"]: skill for skill in call("list_skills").structured_content["result"]}

    assert "gdal" in skills and "crs-and-units" in skills
    gdal = skills["gdal"]
    assert gdal["layer"] == "domain"
    assert gdal["explanation"]
    assert {"id": "quick-reference", "title": "Quick Reference"} in gdal["sections"]
    assert "raster.cog_layout" in gdal["checks"]


def test_load_section_reads_a_heading_and_a_reference():
    heading = call("load_section", {"skill": "gdal", "section_id": "quick-reference"}).structured_content
    reference = call("load_section", {"skill": "gdal", "section_id": "gdal-recipes"}).structured_content

    assert heading["title"] == "Quick Reference"
    assert heading["source"] == "SKILL.md#quick-reference"
    assert "gdalinfo" in heading["text"]
    assert reference["source"] == "references/gdal-recipes.md"
    assert len(reference["text"]) > 0


@pytest.mark.parametrize(
    "skill, section_id",
    [
        ("gdal", "../routing/registry.json"),
        ("gdal", "../../AGENTS.md"),
        ("gdal", "/etc/passwd"),
        ("gdal", ".."),
        ("../gdal", "quick-reference"),
        ("nope", "quick-reference"),
        ("gdal", "no-such-section"),
    ],
)
def test_load_section_rejects_traversal_and_unknown_ids(skill, section_id):
    result = call("load_section", {"skill": skill, "section_id": section_id})

    assert result.is_error
    assert "Error executing tool load_section" in result.content[0].text
    assert "Traceback" not in result.content[0].text


def test_find_guidance_reports_a_missing_router(monkeypatch):
    monkeypatch.setitem(sys.modules, "terraproof.router", None)

    result = call("find_guidance", {"task": "compute NDVI over the AOI"})

    assert result.is_error
    assert "router is unavailable" in result.content[0].text


def test_find_guidance_candidates_mode_includes_explanations():
    payload = call("find_guidance", {"task": "compute NDVI", "mode": "candidates"}).structured_content

    assert any("explanation" in skill for skill in payload["skills"])


def test_find_guidance_accepts_semantic_flag():
    payload = call("find_guidance", {"task": "compute NDVI", "semantic": True}).structured_content

    assert isinstance(payload["skills"], list)


# --- Preflight tool ---


def test_preflight_matches_cli_report(make_raster, tmp_path, capsys):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"operation": "area"}), encoding="utf-8")
    raster = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)

    assert main(["preflight", str(raster), "--plan", str(plan_path)]) == 0
    cli_report = json.loads(capsys.readouterr().out)

    payload = call("preflight", {"paths": [str(raster)], "plan": str(plan_path)}).structured_content

    assert payload["grade"] == cli_report["grade"]
    assert payload["report"] == cli_report


def test_preflight_accepts_plan_dict(make_raster):
    raster = make_raster("x.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)

    payload = call("preflight", {"paths": [str(raster)], "plan": {"operation": "area"}}).structured_content

    assert payload["exit_code"] == 0
    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids["preflight.metric_crs"] == "pass"


# --- Phase 4 run_checks options ---


def test_run_checks_with_reference_input_and_encoding(make_raster):
    dn = make_raster("dn.tif", np.full((64, 64), 1500, dtype="uint16"), nodata=65535)
    out = make_raster("out.tif", np.full((64, 64), 0.05, dtype="float32"), nodata=-9999.0)

    payload = call("run_checks", {
        "paths": [str(out)],
        "reference_input": str(dn),
        "encoding": "s2-l2a",
    }).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("rs.scale_applied_once") == "pass"


def test_run_checks_with_dem_flags_a_slope_that_ignores_vertical_units(tmp_path):
    from rasterio.transform import from_origin
    from terraproof.evals.fixtures import write_raster_grid

    r, c = np.indices((8, 8))
    z = (0.5 * c * c + 0.3 * r * r).astype("float32")
    grid = from_origin(500000, 5000000, 30, 30)
    dem = write_raster_grid(tmp_path / "dem.tif", z, transform=grid, unit="ft")
    slope = np.full(z.shape, -9999.0, dtype="float32")
    gx = (z[1:-1, 2:] - z[1:-1, :-2]) / 60
    gy = (z[2:, 1:-1] - z[:-2, 1:-1]) / 60
    slope[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(gx, gy)))  # feet read as metres
    out = write_raster_grid(tmp_path / "slope.tif", slope, transform=grid)

    payload = call("run_checks", {"paths": [out], "dem": dem}).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("terrain.slope_consistent") == "fail"


def test_run_checks_with_sar_expect(make_raster):
    path = make_raster("sar.tif", np.full((64, 64), -8.0, dtype="float32"), nodata=-9999.0)

    payload = call("run_checks", {"paths": [str(path)], "sar_expect": "sigma0-db"}).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("sar.value_domain") == "pass"
    assert ids.get("sar.geocoded") == "pass"


def test_run_checks_with_qa_and_time_range_matches_cli(make_raster, make_stac_item, tmp_path, capsys):
    import rasterio
    out = make_raster("out.tif", np.full((64, 64), 0.25, dtype="float32"), nodata=-9999.0)
    qa = tmp_path / "scl.tif"
    with rasterio.open(
        qa, "w", driver="GTiff", width=64, height=64, count=1, dtype="uint8", crs="EPSG:32636",
        transform=rasterio.transform.from_origin(500000.0, 5000000.0, 10.0, 10.0), nodata=None,
    ) as dst:
        dst.write(np.full((64, 64), 9, dtype="uint8"), 1)
    item = make_stac_item("item.json", {"datetime": "2025-06-15T00:00:00Z"})

    assert main(["check", str(out), str(item), "--qa", str(qa), "--qa-kind", "s2-scl",
                 "--time-range", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]) == 3
    cli_report = json.loads(capsys.readouterr().out)

    payload = call("run_checks", {
        "paths": [str(out), str(item)],
        "qa_path": str(qa),
        "qa_kind": "s2-scl",
        "time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"],
    }).structured_content

    assert payload["grade"] == cli_report["grade"]
    assert payload["report"] == cli_report


def test_run_checks_with_accuracy_samples_and_class_areas_matches_cli(make_vector, tmp_path, capsys):
    path = make_vector("dummy.gpkg", [square(500000, 5000000)])
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps([
        {"map_class": "forest", "ref_class": "forest"},
        {"map_class": "water", "ref_class": "water"},
    ] * 30), encoding="utf-8")
    areas = tmp_path / "areas.json"
    areas.write_text(json.dumps({"forest": 1000.0, "water": 500.0}), encoding="utf-8")

    main(["check", str(path), "--accuracy-samples", str(samples), "--class-areas", str(areas),
          "--estimates-requested", "--min-per-class", "10"])
    cli_report = json.loads(capsys.readouterr().out)

    payload = call("run_checks", {
        "paths": [str(path)],
        "accuracy_samples": str(samples),
        "class_areas": str(areas),
        "estimates_requested": True,
        "min_per_class": 10,
    }).structured_content

    assert payload["report"] == cli_report


def test_run_checks_weighted_samples_dict_and_file_match(make_vector, tmp_path, capsys):
    path = make_vector("dummy.gpkg", [square(500000, 5000000)])
    rows = [
        {"map_class": "forest", "ref_class": "forest", "stratum_weight": 2.0},
        {"map_class": "water", "ref_class": "water", "stratum_weight": 1.0},
    ] * 30
    samples_file = tmp_path / "samples.json"
    samples_file.write_text(json.dumps(rows), encoding="utf-8")
    areas = tmp_path / "areas.json"
    areas.write_text(json.dumps({"forest": 1000.0, "water": 500.0}), encoding="utf-8")

    payload_dict = call("run_checks", {
        "paths": [str(path)],
        "accuracy_samples": {"records": rows},
        "class_areas": str(areas),
        "estimates_requested": True,
        "min_per_class": 10,
    }).structured_content
    payload_file = call("run_checks", {
        "paths": [str(path)],
        "accuracy_samples": str(samples_file),
        "class_areas": str(areas),
        "estimates_requested": True,
        "min_per_class": 10,
    }).structured_content

    assert payload_dict["grade"] == payload_file["grade"]
    dict_checks = {c["id"]: c["status"] for c in payload_dict["report"]["checks"]}
    file_checks = {c["id"]: c["status"] for c in payload_file["report"]["checks"]}
    assert dict_checks.get("accuracy.sample_design") == file_checks.get("accuracy.sample_design")
    assert dict_checks.get("accuracy.estimates") == file_checks.get("accuracy.estimates")


# --- Manifest coverage in MCP ---


def _write_manifest(manifest_path: Path, inputs: list[Path], outputs: list[Path]):
    from terraproof.provenance import write_manifest
    manifest = write_manifest(
        inputs=[str(p) for p in inputs],
        outputs=[str(p) for p in outputs],
        parameters={},
        stac_items=[],
        root=None,
        manifest_path=manifest_path,
        command_line=["test"],
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")


def test_mcp_run_checks_with_good_manifest_passes(make_vector, tmp_path):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    manifest_path = tmp_path / "run.manifest.json"
    _write_manifest(manifest_path, [path], [path])

    payload = call("run_checks", {"paths": [str(path)], "manifest": str(manifest_path), "operation": "area"}).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("provenance.reproducible") == "pass"


def test_mcp_run_checks_with_unrelated_manifest_fails(make_vector, tmp_path):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    other = tmp_path / "other.txt"
    other.write_text("other", encoding="utf-8")
    manifest_path = tmp_path / "run.manifest.json"
    _write_manifest(manifest_path, [other], [other])

    payload = call("run_checks", {"paths": [str(path)], "manifest": str(manifest_path), "operation": "area"}).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("provenance.reproducible") == "fail"
    assert "does not cover" in json.dumps(payload["report"]).lower()


def test_mcp_run_checks_with_partially_covered_manifest_fails(make_vector, make_raster, tmp_path):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    ref = make_raster("ref.tif", np.full((8, 8), 1.0, dtype="float32"), nodata=-9999.0)
    manifest_path = tmp_path / "run.manifest.json"
    _write_manifest(manifest_path, [path], [path])

    payload = call("run_checks", {
        "paths": [str(path)],
        "reference_input": str(ref),
        "manifest": str(manifest_path),
    }).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("provenance.reproducible") == "fail"
    assert "does not cover" in json.dumps(payload["report"]).lower()


def test_mcp_run_checks_with_missing_manifest_fails(make_vector, tmp_path):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    missing = tmp_path / "missing.manifest.json"

    payload = call("run_checks", {"paths": [str(path)], "manifest": str(missing), "operation": "area"}).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("provenance.reproducible") == "fail"


def test_mcp_run_checks_with_tampered_manifest_fails(make_vector, tmp_path):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    manifest_path = tmp_path / "run.manifest.json"
    _write_manifest(manifest_path, [path], [path])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["core"]["parameters"]["tamper"] = True
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")

    payload = call("run_checks", {"paths": [str(path)], "manifest": str(manifest_path), "operation": "area"}).structured_content

    ids = {check["id"]: check["status"] for check in payload["report"]["checks"]}
    assert ids.get("provenance.reproducible") == "fail"


def test_lossy_jpeg_cog_cli_mcp_parity(tmp_path, capsys):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin

    rows, cols = np.indices((256, 256))
    path = str(tmp_path / "lossy_parity.tif")
    with rasterio.open(path, "w", driver="GTiff", width=256, height=256, count=1, dtype="uint8", crs="EPSG:32636",
                       transform=from_origin(500000, 5000000, 10, 10), nodata=0, tiled=True, blockxsize=128,
                       blockysize=128, compress="JPEG") as dst:
        dst.write((40 + (rows // 8 + cols // 8) % 90).astype("uint8"), 1)
        dst.build_overviews([2, 4], Resampling.average)
    assert main(["check", path]) == 2
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [path]}).structured_content
    cli_check = next(c for c in cli["checks"] if c["id"] == "raster.cog_layout")
    mcp_check = next(c for c in payload["report"]["checks"] if c["id"] == "raster.cog_layout")
    assert cli_check == mcp_check
    assert cli_check["status"] == "warn"
    assert "lossy JPEG compression" in cli_check["message"]


def test_clockwise_geojson_winding_cli_mcp_parity(tmp_path, capsys):
    exterior = [[30.0, 30.0], [30.0, 30.1], [30.1, 30.1], [30.1, 30.0], [30.0, 30.0]]
    document = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"pid": "P1"}, "geometry": {"type": "Polygon", "coordinates": [exterior]}},
    ]}
    path = tmp_path / "clockwise_parity.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["check", str(path)]) == 3
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [str(path)]}).structured_content
    cli_check = next(c for c in cli["checks"] if c["id"] == "geometry.winding")
    mcp_check = next(c for c in payload["report"]["checks"] if c["id"] == "geometry.winding")
    assert cli_check == mcp_check
    assert cli_check["status"] == "fail"


@pytest.mark.parametrize("mistake", [False, True])
def test_ndvi_cli_mcp_source_contract_parity(tmp_path, capsys, mistake):
    from test_index_formula import _case, GRID
    from terraproof.evals.fixtures import write_raster_grid
    out, nir, red, values = _case(tmp_path)
    if mistake:
        values[-1, -1] += .1
        write_raster_grid(out, values, transform=GRID)
    args=["check",out,"--index-formula","ndvi","--nir",nir,"--red",red,"--format","json"]
    assert main(args) == (3 if mistake else 0)
    cli=json.loads(capsys.readouterr().out)
    payload=call("run_checks", {"paths":[out],"index_formula":"ndvi","nir":nir,"red":red}).structured_content
    assert cli == payload["report"]
    check=next(c for c in cli["checks"] if c["id"]=="rs.index_formula")
    assert check["status"] == ("fail" if mistake else "pass")


@pytest.mark.parametrize('kind',['slope','identity'])
def test_strict_raster_cli_mcp_parity_and_source_provenance(tmp_path,capsys,kind):
    from test_strict_raster_contracts import slope_case, identity_case
    from terraproof.provenance import write_manifest
    if kind=='slope':
        source,output=slope_case(tmp_path)
        flags=['--dem',source,'--slope-method','central-difference']
        params={'dem':source,'slope_method':'central-difference'}
        check_id='terrain.slope_formula'; role='dem'
    else:
        source,output=identity_case(tmp_path)
        flags=['--compare-to',source,'--raster-identity']
        params={'compare_to':source,'raster_identity':True}
        check_id='raster.source_identity'; role='compare-to'
    assert main(['check',output,*flags]) in (0,2)
    cli=json.loads(capsys.readouterr().out)
    tool=call('run_checks',{'paths':[output],**params}).structured_content['report']
    assert next(c for c in cli['checks'] if c['id']==check_id)==next(c for c in tool['checks'] if c['id']==check_id)
    assert all(cli['parameters'][k]==v==tool['parameters'][k] for k,v in params.items())
    assert any(r['role']==role and r['path']==source for r in cli['inputs'])
    manifest=tmp_path/'manifest.json'
    unrelated=tmp_path/'unrelated.txt'; unrelated.write_text('not the source',encoding='utf-8')
    manifest.write_text(json.dumps(write_manifest(inputs=[unrelated],outputs=[output],root=tmp_path,manifest_path=manifest)),encoding='utf-8')
    assert main(['check',output,*flags,'--manifest',str(manifest)])==3
    denied=json.loads(capsys.readouterr().out)
    assert any(c['id']=='provenance.reproducible' and c['status']=='fail' for c in denied['checks'])
    manifest.write_text(json.dumps(write_manifest(inputs=[source],outputs=[output],root=tmp_path,manifest_path=manifest)),encoding='utf-8')
    assert main(['check',output,*flags,'--manifest',str(manifest)]) in (0,2)
    capsys.readouterr()
