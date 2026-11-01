"""Phase 9 Q1-Q4: validity masks, slope units, declared summaries and the next step."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
import rasterio

from terraproof.checks import run_checks
from terraproof.cli import main
from terraproof.evidence import build_report, input_record, render_markdown
from terraproof.inspect import inspect_dataset

SHAPE = (24, 24)


def _only(results, check_id):
    found = [r for r in results if r.id == check_id]
    assert len(found) == 1, [r.id for r in results]
    return found[0]


def _run(output, **kwargs):
    return run_checks([inspect_dataset(output)], **kwargs)


# Q1: validity masks


@pytest.fixture
def scl(make_raster):
    codes = np.random.default_rng(5).choice(np.array([4, 5, 6, 8, 9, 3], dtype="uint8"), size=SHAPE)
    return codes, make_raster("scl.tif", codes, nodata=0)


def _mask(make_raster, name, keep):
    return make_raster(name, keep.astype("uint8"), nodata=None)


def test_a_declared_validity_mask_passes_the_qa_rule_it_follows(make_raster, scl):
    codes, qa = scl
    mask = _mask(make_raster, "mask.tif", np.isin(codes, [4, 5, 6]))
    qa_args = dict(qa_path=qa, qa_kind="keep-codes", qa_keep_codes=[4, 5, 6])
    declared = _only(_run(mask, output_form="validity-mask", **qa_args), "rs.cloud_mask_applied")
    assert declared.status == "pass" and declared.evidence["output_valid_value"] == 1.0
    undeclared = _only(_run(mask, processing_full_scan=True, **qa_args), "rs.cloud_mask_applied")
    assert undeclared.status == "fail"  # a 1/0 raster without the binding is still read as data


def test_a_mask_that_keeps_a_rejected_class_fails(make_raster, scl):
    codes, qa = scl
    mask = _mask(make_raster, "mask.tif", np.isin(codes, [4, 5, 6, 9]))
    check = _only(_run(mask, output_form="validity-mask", qa_path=qa, qa_kind="keep-codes",
                       qa_keep_codes=[4, 5, 6]), "rs.cloud_mask_applied")
    assert check.status == "fail" and check.evidence["unmasked_flagged_pixels"] == int((codes == 9).sum())


def test_a_mask_with_another_valid_value_and_the_support_rule(make_raster):
    heights = np.random.default_rng(6).uniform(-5, 50, SHAPE).astype("float32")
    heights[:3] = -9999.0
    heights[5, 5] = 0.0  # a real zero
    source = make_raster("dem.tif", heights, nodata=-9999.0)
    right = make_raster("right.tif", np.where(heights != -9999.0, 255, 0).astype("uint8"), nodata=None)
    zeros_evicted = make_raster("wrong.tif", np.where((heights != -9999.0) & (heights != 0), 255, 0).astype("uint8"),
                                nodata=None)
    support = dict(support_sources=[inspect_dataset(source)], support_rule="all", output_form="validity-mask",
                   output_valid_value=255)
    assert _only(_run(right, **support), "raster.nodata_support").status == "pass"
    wrong = _only(_run(zeros_evicted, **support), "raster.nodata_support")
    assert wrong.status == "fail" and wrong.evidence["valid_treated_as_fill_cells"] == 1


def test_an_unknown_output_form_is_refused(make_raster, scl):
    with pytest.raises(ValueError, match="output_form"):
        _run(scl[1], output_form="probability")


# Q2: slope units


@pytest.fixture
def plane(make_raster):
    x = np.arange(SHAPE[1], dtype="float64") * 10.0
    dem = make_raster("plane.tif", np.tile(0.1 * x, (SHAPE[0], 1)).astype("float32"), nodata=-9999.0)
    with rasterio.open(dem, "r+") as dataset:
        dataset.units = ("m",)
    return dem, math.degrees(math.atan(0.1))


def _slope(make_raster, name, value):
    values = np.full(SHAPE, value, dtype="float32")
    values[0, :] = values[-1, :] = values[:, 0] = values[:, -1] = -9999.0
    return make_raster(name, values, nodata=-9999.0)


def test_a_percent_slope_passes_when_its_unit_is_declared(make_raster, plane):
    dem, degrees = plane
    percent = _slope(make_raster, "percent.tif", 10.0)
    declared = _only(_run(percent, dem=inspect_dataset(dem), slope_unit="percent"), "terrain.slope_consistent")
    assert declared.status == "pass" and declared.evidence["slope_unit"] == "percent"
    assert _only(_run(percent, dem=inspect_dataset(dem)), "terrain.slope_consistent").status != "pass"
    in_degrees = _slope(make_raster, "degrees.tif", degrees)
    assert _only(_run(in_degrees, dem=inspect_dataset(dem), slope_unit="percent"),
                 "terrain.slope_consistent").status != "pass"
    formula = _only(_run(percent, dem=inspect_dataset(dem), slope_method="central-difference", slope_unit="percent"),
                    "terrain.slope_formula")
    assert formula.status == "pass"


# Q3: declared summaries


def _report(tmp_path, name, document):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_plain_json_is_a_report_and_geojson_stays_vector(tmp_path):
    report = inspect_dataset(_report(tmp_path, "summary.json", {"stats": {"mean": 1.0}}))
    assert report["kind"] == "report" and report["keys"] == ["stats"]
    collection = _report(tmp_path, "layer.json", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [30.0, 30.0]}}]})
    assert inspect_dataset(collection)["kind"] == "vector"


def test_raster_summaries_honour_nodata_and_a_mask(tmp_path, make_raster):
    values = np.arange(SHAPE[0] * SHAPE[1], dtype="float32").reshape(SHAPE)
    values[0] = -9999.0
    source = make_raster("heights.tif", values, nodata=-9999.0)
    valid = values[values != -9999.0]
    right = _report(tmp_path, "right.json", {"elevation": {"mean_m": round(float(valid.mean()), 6)}})
    fill_in = _report(tmp_path, "wrong.json", {"elevation": {"mean_m": float(values.mean())}})
    base = dict(summary_key="elevation.mean_m", summary_statistic="mean", summary_source=inspect_dataset(source))
    assert _only(_run(right, **base), "report.summary_value").status == "pass"
    wrong = _only(_run(fill_in, **base), "report.summary_value")
    assert wrong.status == "fail" and wrong.evidence["expected"] == pytest.approx(float(valid.mean()))
    keep = (values >= 300).astype("uint8")
    mask = make_raster("keep.tif", keep, nodata=None)
    counted = _report(tmp_path, "count.json", {"n": int(keep.sum())})
    check = _only(_run(counted, summary_key="n", summary_statistic="count", summary_source=inspect_dataset(source),
                       summary_mask=inspect_dataset(mask)), "report.summary_value")
    assert check.status == "pass"


def test_vector_summaries_are_geodesic_and_filtered(tmp_path, make_geojson):
    ring = [[-20.0, 64.0], [-14.0, 64.0], [-14.0, 66.0], [-20.0, 66.0], [-20.0, 64.0]]
    other = [[10.0, 45.0], [11.0, 45.0], [11.0, 46.0], [10.0, 46.0], [10.0, 45.0]]
    layer = make_geojson("countries.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"NAME": "Iceland"}, "geometry": {"type": "Polygon", "coordinates": [ring]}},
        {"type": "Feature", "properties": {"NAME": "Other"}, "geometry": {"type": "Polygon", "coordinates": [other]}}]})
    from pyproj import Geod
    truth = abs(Geod(ellps="WGS84").polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])[0]) / 1e6
    base = dict(summary_key="area_km2", summary_statistic="area", summary_source=inspect_dataset(layer),
                summary_feature="NAME=Iceland")
    right = _report(tmp_path, "right.json", {"area_km2": truth})
    degrees = _report(tmp_path, "wrong.json", {"area_km2": 12.0})  # square degrees labelled km2
    assert _only(_run(right, summary_unit="square_kilometre", **base), "report.summary_value").status == "pass"
    assert _only(_run(degrees, summary_unit="square_kilometre", **base), "report.summary_value").status == "fail"
    missing = _only(_run(right, **base), "report.summary_value")
    assert missing.status == "not-run" and missing.evidence["missing_bindings"] == ["summary_unit"]


def test_a_summary_check_needs_a_report_output(make_raster, tmp_path):
    raster = make_raster("r.tif", np.ones(SHAPE, dtype="float32"))
    check = _only(_run(raster, summary_key="x", summary_statistic="mean", summary_source=inspect_dataset(raster)),
                  "report.summary_value")
    assert check.status == "not-run"


# Q4: the next step


def test_checks_run_from_arguments_suggest_declaring_their_goal(make_raster, plane):
    dem, degrees = plane
    output = _slope(make_raster, "slope.tif", degrees)
    parameters = {"dem": dem, "dem_vertical_unit": None}
    results = _run(output, dem=inspect_dataset(dem))
    report = build_report(inputs=[input_record(output, "input", "raster")], results=results, parameters=parameters)
    step = report["next_step"]
    assert step["profiles"] == ["slope-from-dem"] and report["grade"] != "decision-grade"
    assert step["propose_contract"]["arguments"] == {"dem": dem}
    assert step["command"][:4] == ["python", "-m", "terraproof", "propose"] and "--dem" in step["command"]
    assert "propose" in render_markdown(report) and "propose" in render_markdown(report, lang="ar")
    contract = {"schema": "terraproof.verification-contract/1",
                "requirements": [{"paths": [output], "profiles": ["slope-from-dem"], "parameters": {"dem": dem}}]}
    declared = build_report(inputs=[input_record(output, "input", "raster")], results=results,
                            parameters={"dem": dem}, contract=contract)
    assert "next_step" not in declared


def test_summary_cli_mcp_parity(make_raster, tmp_path, capsys):
    pytest.importorskip("mcp", reason="the mcp extra is not installed")
    from test_mcp import call

    values = np.full(SHAPE, 2.0, dtype="float32")
    source = make_raster("s.tif", values, nodata=-9999.0)
    report = _report(tmp_path, "sum.json", {"total": float(values.sum())})
    args = ["--summary-key", "total", "--summary-statistic", "sum", "--summary-source", source]
    assert main(["check", report, *args]) == 0
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [report], "summary_key": "total", "summary_statistic": "sum",
                                  "summary_source": source}).structured_content
    a = next(c for c in cli["checks"] if c["id"] == "report.summary_value")
    b = next(c for c in payload["report"]["checks"] if c["id"] == "report.summary_value")
    assert a == b and a["status"] == "pass"
    assert cli["next_step"]["profiles"] == ["summary-value"]


# After Q5.1: fixes for the two weaknesses it found


def test_a_declared_mask_needs_no_full_scan_flag_to_be_verified(make_raster, scl):
    codes, qa = scl
    mask = _mask(make_raster, "mask.tif", np.isin(codes, [4, 5, 6]))
    args = dict(qa_path=qa, qa_kind="keep-codes", qa_keep_codes=[4, 5, 6], output_form="validity-mask")
    contract = {"schema": "terraproof.verification-contract/1",
                "requirements": [{"paths": [mask], "profiles": ["qa-masked"], "parameters": args}]}
    results = _run(mask, **args)
    report = build_report(inputs=[input_record(mask, "input", "raster")], results=results, parameters=args,
                          contract=contract)
    row = report["verification"]["requirements"][0]
    assert row["status"] == "pass" and row["missing_bindings"] == [] and row["scope"] == "full-grid"


def _geographic_dem(make_raster, lat=78.0, step=0.001):
    """A DEM rising 0.2 m per ground metre eastward and 0.1 northward, on WGS84 degrees."""
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    rows, cols = 30, 30
    lats = lat + 0.5 * step - (np.arange(rows) + 0.5) * step
    east = np.array([geod.inv(16.0, la, 16.0 + step, la)[2] for la in lats])
    north = geod.inv(16.0, lat, 16.0, lat + step)[2]
    z = 0.2 * np.arange(cols)[None, :] * east[:, None] - 0.1 * np.arange(rows)[:, None] * north + 500.0
    dem = make_raster("geo_dem.tif", z.astype("float64"), crs="EPSG:4326", origin=(16.0, lat + 0.5 * step),
                      resolution=step, nodata=-9999.0)
    return dem, z, lats, step


def _spherical_slope(z, lats, step, scale_longitude=True):
    metres = 111320.0 * step
    dx = metres * (np.cos(np.radians(lats)) if scale_longitude else np.ones_like(lats))
    gx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx[1:-1, None])
    gy = (z[2:, 1:-1] - z[:-2, 1:-1]) / (2 * metres)
    out = np.full(z.shape, -9999.0)
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(gx, gy)))
    return out.astype("float32")


def test_a_spherical_spacing_model_passes_and_ignoring_latitude_fails(make_raster):
    dem, z, lats, step = _geographic_dem(make_raster)
    args = dict(dem=inspect_dataset(dem), dem_vertical_unit="metre")
    sphere = make_raster("sphere.tif", _spherical_slope(z, lats, step), crs="EPSG:4326",
                         origin=(16.0, lats[0] + 0.5 * step), resolution=step, nodata=-9999.0)
    passed = _only(_run(sphere, **args), "terrain.slope_consistent")
    assert passed.status == "pass" and passed.evidence["tolerance"]["rtol"] == 0.01
    ignored = make_raster("ignored.tif", _spherical_slope(z, lats, step, scale_longitude=False), crs="EPSG:4326",
                          origin=(16.0, lats[0] + 0.5 * step), resolution=step, nodata=-9999.0)
    assert _only(_run(ignored, **args), "terrain.slope_consistent").status == "fail"


def test_a_mask_without_anything_to_verify_it_names_what_is_missing(make_raster, scl):
    codes, _qa = scl
    mask = _mask(make_raster, "mask.tif", np.isin(codes, [4, 5, 6]))
    parameters = {"output_form": "validity-mask"}
    report = build_report(inputs=[input_record(mask, "input", "raster")], results=_run(mask, output_form="validity-mask"),
                          parameters=parameters)
    step = report["next_step"]
    assert step["profiles"] == [] and step["missing"]["qa-masked"] == ["qa_path", "qa_kind"]
    assert "qa_path" in render_markdown(report) and "qa_path" in render_markdown(report, lang="ar")
    with_qa = build_report(inputs=[input_record(mask, "input", "raster")],
                           results=_run(mask, output_form="validity-mask", qa_path=_qa, qa_kind="keep-codes",
                                        qa_keep_codes=[4, 5, 6]),
                           parameters=dict(parameters, qa_path=_qa))
    assert "missing" not in with_qa.get("next_step", {})
