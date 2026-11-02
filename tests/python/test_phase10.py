"""Phase 10 S1-S3: QA no-data in declared masks, slopes on another grid, and multi-value reports."""
from __future__ import annotations

import json

import numpy as np
import pytest

from terraproof.checks import run_checks
from terraproof.cli import main
from terraproof.evidence import build_report, input_record, render_markdown
from terraproof.evidence.propose import command_flags
from terraproof.inspect import inspect_dataset

SHAPE = (24, 24)
CONTRACT = "terraproof.verification-contract/1"


def _only(results, check_id):
    found = [r for r in results if r.id == check_id]
    assert len(found) == 1, [r.id for r in results]
    return found[0]


def _run(output, **kwargs):
    return run_checks([inspect_dataset(output)], **kwargs)


# S1: a declared mask may not call a cell valid where the QA records no observation


@pytest.fixture
def swath_edge_scl():
    codes = np.random.default_rng(10).choice(np.array([4, 5, 6, 3, 8, 9], dtype="uint8"), size=SHAPE)
    codes[:3] = 0  # the swath edge: SCL class 0, no data
    return codes


def _mask(make_raster, name, keep):
    return make_raster(name, keep.astype("uint8"), nodata=None)


@pytest.mark.parametrize("qa_nodata", [0, None])  # SCL 0 counts as no observation whether or not it is nodata
def test_a_mask_that_keeps_the_swath_edge_fails(make_raster, swath_edge_scl, qa_nodata):
    codes = swath_edge_scl
    qa = make_raster("scl.tif", codes, nodata=qa_nodata)
    args = dict(output_form="validity-mask", qa_path=qa, qa_kind="s2-scl")
    right = _only(_run(_mask(make_raster, "right.tif", np.isin(codes, [4, 5, 6])), **args), "rs.cloud_mask_applied")
    assert right.status == "pass" and right.evidence["valid_without_qa_observation"] == 0
    kept = _mask(make_raster, "edge.tif", np.isin(codes, [4, 5, 6]) | (codes == 0))
    wrong = _only(_run(kept, **args), "rs.cloud_mask_applied")
    assert wrong.status == "fail" and wrong.evidence["valid_without_qa_observation"] == 3 * SHAPE[1]


def test_a_mask_that_keeps_landsat_fill_fails(make_raster):
    qa_pixel = np.full(SHAPE, 21824, dtype="uint16")  # clear land
    qa_pixel[5:8] = 22280  # cloud (bit 3) with dilated cloud (bit 1)
    qa_pixel[-2:] = 1      # fill (bit 0)
    qa = make_raster("qa_pixel.tif", qa_pixel, nodata=None)
    args = dict(output_form="validity-mask", qa_path=qa, qa_kind="landsat-qa-pixel")
    clear = qa_pixel == 21824
    assert _only(_run(_mask(make_raster, "right.tif", clear), **args), "rs.cloud_mask_applied").status == "pass"
    wrong = _only(_run(_mask(make_raster, "fill.tif", clear | (qa_pixel == 1)), **args), "rs.cloud_mask_applied")
    assert wrong.status == "fail" and wrong.evidence["valid_without_qa_observation"] == 2 * SHAPE[1]


def test_data_outputs_and_keep_code_rules_keep_missing_qa_unverifiable(make_raster, swath_edge_scl):
    codes = swath_edge_scl
    qa = make_raster("scl.tif", codes, nodata=0)
    reflectance = np.where(np.isin(codes, [3, 8, 9]), np.nan, 0.2).astype("float32")  # values over the edge too
    data = _only(_run(make_raster("refl.tif", reflectance), qa_path=qa, qa_kind="s2-scl", processing_full_scan=True),
                 "rs.cloud_mask_applied")
    assert data.status == "not-run" and data.evidence["valid_without_qa_observation"] is None
    kept = _mask(make_raster, "edge.tif", np.isin(codes, [4, 5, 6]) | (codes == 0))
    rule = _only(_run(kept, output_form="validity-mask", qa_path=qa, qa_kind="keep-codes", qa_keep_codes=[4, 5, 6]),
                 "rs.cloud_mask_applied")
    assert rule.status == "not-run"  # a declared keep-codes rule says nothing about cells with no QA


# S2: slopes delivered on another grid


def _units(path, unit):
    import rasterio
    with rasterio.open(path, "r+") as dataset:
        dataset.units = (unit,)
    return path


@pytest.fixture
def hills(make_raster):
    """A smooth 30 m DEM in metres, and a way to warp a slope made from it onto a 45 m grid."""
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    from terraproof.checks import terrain

    y, x = np.mgrid[0:48, 0:48].astype("float64")
    z = 300 + 40 * np.sin(x / 6) * np.cos(y / 8) + 2.0 * x
    dem = _units(make_raster("dem.tif", z.astype("float32"), resolution=30.0, nodata=-9999.0), "m")

    def delivered(name, values, factor=1.0, unit="degrees", method=Resampling.bilinear):
        degrees = terrain._slope(values, np.isfinite(values), (factor, 30.0, 30.0), "central")
        written = np.tan(np.radians(degrees)) * 100 if unit == "percent" else degrees
        out = np.full((30, 30), np.nan)
        reproject(written, out, src_transform=from_origin(500000, 5000000, 30, 30), src_crs="EPSG:32636",
                  dst_transform=from_origin(500000, 5000000, 45, 45), dst_crs="EPSG:32636", resampling=method,
                  src_nodata=np.nan, dst_nodata=np.nan)
        return make_raster(name, np.where(np.isfinite(out), out, -9999.0).astype("float32"), resolution=45.0,
                           nodata=-9999.0)

    return dem, z, delivered


def test_a_slope_warped_onto_another_grid_passes_by_reproduction(hills):
    from rasterio.warp import Resampling
    dem, z, delivered = hills
    for method in (Resampling.bilinear, Resampling.average):
        check = _only(_run(delivered(f"slope_{method.name}.tif", z, method=method), dem=inspect_dataset(dem)),
                      "terrain.slope_consistent")
        assert check.status == "pass" and check.evidence["comparison"] == "resampled"
        assert check.evidence["declared_fit"]["match_way"].startswith(f"slope then warp, {method.name}")
    percent = _only(_run(delivered("percent.tif", z, unit="percent"), dem=inspect_dataset(dem), slope_unit="percent"),
                    "terrain.slope_consistent")
    assert percent.status == "pass"


def test_mistakes_on_another_grid_fail_and_an_unrelated_slope_warns(make_raster, hills):
    from terraproof.checks.terrain import CONFUSED
    dem, z, delivered = hills
    feet = _units(make_raster("dem_ft.tif", (z / 0.3048).astype("float32"), resolution=30.0, nodata=-9999.0), "ft")
    ignored = _only(_run(delivered("ignored.tif", z / 0.3048), dem=inspect_dataset(feet)), "terrain.slope_consistent")
    assert ignored.status == "fail" and "vertical units ignored" in ignored.message
    confused = _only(_run(delivered("confused.tif", z, unit="percent"), dem=inspect_dataset(dem)),
                     "terrain.slope_consistent")
    assert confused.status == "fail" and CONFUSED in confused.message
    noise = np.random.default_rng(3).uniform(5, 25, (30, 30)).astype("float32")
    unrelated = _only(_run(make_raster("noise.tif", noise, resolution=45.0, nodata=-9999.0), dem=inspect_dataset(dem)),
                      "terrain.slope_consistent")
    assert unrelated.status == "warn"


# S3: multi-value reports


def _report(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def heights(make_raster):
    values = np.arange(SHAPE[0] * SHAPE[1], dtype="float32").reshape(SHAPE) / 10.0
    values[0] = -9999.0
    source = make_raster("heights.tif", values, nodata=-9999.0)
    keep = (values >= 30).astype("uint8")
    mask = make_raster("keep.tif", keep, nodata=None)
    valid = values[values != -9999.0]
    return source, mask, valid, keep


def _summaries(source, mask):
    return [{"key": "stats.mean", "statistic": "mean", "source": source},
            {"key": "stats.max", "statistic": "max", "source": source},
            {"key": "bands.0.count", "statistic": "count", "source": source},
            {"key": "high_share_pct", "statistic": "fraction", "source": source, "mask": mask, "unit": "percent"}]


def _inspected(entries):
    return [dict(e, source=inspect_dataset(e["source"]), mask=inspect_dataset(e["mask"]) if e.get("mask") else None)
            for e in entries]


def _document(valid, keep, mean=None):
    share = 100.0 * float(keep[1:].sum()) / valid.size
    return json.dumps({"stats": {"mean": round(float(valid.mean()) if mean is None else mean, 1),
                                 "max": float(valid.max())},
                       "bands": [{"name": "B1", "count": int(valid.size)}],
                       "high_share_pct": round(share, 2), "runtime_s": 12.5})


def test_every_declared_number_is_checked_and_undeclared_ones_are_listed(tmp_path, heights):
    source, mask, valid, keep = heights
    report = _report(tmp_path, "report.json", _document(valid, keep))
    results = [r for r in _run(report, summaries=_inspected(_summaries(source, mask))) if r.id == "report.summary_value"]
    assert [r.status for r in results] == ["pass"] * 4
    assert results[0].evidence["written_rounding"] == pytest.approx(0.05)  # mean written with one decimal
    assert results[0].evidence["undeclared_numbers"] == ["runtime_s"]
    built = build_report(inputs=[input_record(report, "input", "report")], results=results,
                         parameters={"summaries": _summaries(source, mask)})
    assert built["coverage"]["unchecked_numbers"] == [{"path": report, "keys": ["runtime_s"]}]
    assert "runtime_s" in render_markdown(built) and "runtime_s" in render_markdown(built, lang="ar")


def test_one_wrong_number_among_right_ones_fails_only_its_summary(tmp_path, heights):
    source, mask, valid, keep = heights
    with_fill = float((valid.sum() - 9999.0 * SHAPE[1]) / (SHAPE[0] * SHAPE[1]))  # fill averaged in
    report = _report(tmp_path, "report.json", _document(valid, keep, mean=with_fill))
    results = [r for r in _run(report, summaries=_inspected(_summaries(source, mask))) if r.id == "report.summary_value"]
    assert [r.status for r in results] == ["fail", "pass", "pass", "pass"]


def test_a_share_over_all_cells_instead_of_valid_cells_fails(tmp_path, heights):
    source, _mask_path, valid, _keep = heights
    entry = {"key": "valid_fraction", "statistic": "fraction", "source": source, "unit": "fraction"}
    right = _report(tmp_path, "right.json", json.dumps({"valid_fraction": valid.size / (SHAPE[0] * SHAPE[1])}))
    assert _only(_run(right, summaries=_inspected([entry])), "report.summary_value").status == "pass"
    missing = _only(_run(right, summaries=_inspected([dict(entry, unit=None)])), "report.summary_value")
    assert missing.status == "not-run" and missing.evidence["missing_bindings"] == ["summary_unit"]
    _source, mask, _valid, keep = heights
    over_all = _report(tmp_path, "wrong.json", json.dumps({"share": float(keep.sum()) / keep.size}))
    wrong = _only(_run(over_all, summaries=_inspected([{"key": "share", "statistic": "fraction", "source": source,
                                                         "mask": mask, "unit": "fraction"}])), "report.summary_value")
    assert wrong.status == "fail"


def test_a_contract_requires_every_summary_and_names_missing_fields(tmp_path, heights):
    source, mask, valid, keep = heights
    report = _report(tmp_path, "report.json", _document(valid, keep))
    entries = _summaries(source, mask)
    results = _run(report, summaries=_inspected(entries))
    contract = {"schema": CONTRACT, "requirements": [{"paths": [report], "profiles": ["summary-value"],
                                                      "parameters": {"summaries": entries}}]}
    verified = build_report(inputs=[input_record(report, "input", "report")], results=results,
                            parameters={"summaries": entries}, contract=contract)
    assert verified["verification"]["status"] == "verified" and verified["grade"] == "decision-grade"
    partial = [dict(entries[3], unit=None)]
    contract["requirements"][0]["parameters"] = {"summaries": partial}
    incomplete = build_report(inputs=[input_record(report, "input", "report")],
                              results=_run(report, summaries=_inspected(partial)),
                              parameters={"summaries": partial}, contract=contract)
    assert incomplete["verification"]["requirements"][0]["missing_bindings"] == ["summaries[0].unit"]


def test_summaries_cli_mcp_parity_and_the_proposed_command(tmp_path, heights, capsys):
    pytest.importorskip("mcp", reason="the mcp extra is not installed")
    from test_mcp import call

    source, mask, valid, keep = heights
    report = _report(tmp_path, "report.json", _document(valid, keep))
    entries = _summaries(source, mask)
    flags = command_flags({"summaries": entries})
    assert flags.count("--summary") == 4 and f"key=stats.mean,statistic=mean,source={source}" in flags
    assert main(["check", report, *flags]) == 0
    cli = json.loads(capsys.readouterr().out)
    payload = call("run_checks", {"paths": [report], "summaries": entries}).structured_content
    a = [c for c in cli["checks"] if c["id"] == "report.summary_value"]
    b = [c for c in payload["report"]["checks"] if c["id"] == "report.summary_value"]
    assert a == b and [c["status"] for c in a] == ["pass"] * 4
    assert cli["coverage"]["unchecked_numbers"] == payload["report"]["coverage"]["unchecked_numbers"]
    with pytest.raises(SystemExit):
        main(["check", report, "--summary", "key=x,colour=red"])
