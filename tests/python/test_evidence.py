"""Evidence report tests: bilingual Markdown labels, deterministic JSON, and grade coverage."""

from __future__ import annotations

import json

import numpy as np
from shapely.geometry import Polygon

from terraproof.evidence import (
    ADVISORY,
    CHECKS_PASSED,
    DECISION,
    REVIEW,
    build_report,
    input_record,
    render_markdown,
    to_json,
)
from terraproof.evidence.report import LIMITATION_EN


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _report(evaluate, path, **params):
    results, _grade = evaluate([path], **params)
    return build_report(
        inputs=[input_record(path, "input", "vector")],
        results=results,
        parameters={"operation": params.get("operation"), "compare_to": None, "resampling": None,
                    "categorical": False, "expect": None},
    )


def test_markdown_renders_grade_labels_in_english_and_arabic(make_vector, evaluate):
    clean = make_vector("clean.gpkg", [square(500000, 5000000)])
    empty = make_vector("empty.gpkg", [square(500000, 5000000), Polygon()])
    geographic = make_vector("lonlat.gpkg", [square(30.0, 30.0, 0.01)], crs="EPSG:4326")

    cases = [
        (_report(evaluate, clean, operation="area"), CHECKS_PASSED, "Checks passed (coverage not assessed)",
         "الفحوصات نجحت (التغطية غير مُقيَّمة)"),
        (_report(evaluate, empty), REVIEW, "Review required", "يحتاج مراجعة"),
        (_report(evaluate, geographic, operation="buffer"), ADVISORY, "Advisory only", "استرشادي فقط"),
    ]
    for report, grade, english, arabic in cases:
        assert report["grade"] == grade
        text_en = render_markdown(report, lang="en")
        text_ar = render_markdown(report, lang="ar")

        assert english in text_en
        assert arabic in text_ar
        assert arabic not in text_en
        assert english not in text_ar
        assert "`geometry.valid`" in text_en
        assert "`geometry.valid`" in text_ar
        assert LIMITATION_EN in text_en


def test_markdown_renders_multi_input_checks(make_vector, evaluate):
    projected = make_vector("utm.gpkg", [square(500000, 5000000)], crs="EPSG:32636")
    geographic = make_vector("wgs84.gpkg", [square(30.0, 30.0, 0.01)], crs="EPSG:4326")
    results, _grade = evaluate([projected, geographic])
    report = build_report(
        inputs=[input_record(projected, "input", "vector"), input_record(geographic, "input", "vector")],
        results=results,
        parameters={"operation": None, "compare_to": None, "resampling": None, "categorical": False,
                    "expect": None},
    )

    text_en = render_markdown(report, lang="en")
    text_ar = render_markdown(report, lang="ar")

    assert "`crs.consistent`" in text_en and "`crs.consistent`" in text_ar
    assert "| fail |" in text_en
    assert "`" + projected + "`, `" + geographic + "`" in text_en


def test_arabic_report_uses_arabic_status_words(make_vector, evaluate):
    report = _report(evaluate, make_vector("empty.gpkg", [square(500000, 5000000), Polygon()]))

    text_ar = render_markdown(report, lang="ar")

    assert "تحذير" in text_ar
    assert "ناجح" in text_ar
    assert "warn" not in text_ar


def test_identical_inputs_give_byte_identical_json(make_vector, evaluate):
    path = make_vector("parcels.gpkg", [square(500000, 5000000), square(500100, 5000100)])

    first = to_json(_report(evaluate, path, operation="area"))
    second = to_json(_report(evaluate, path, operation="area"))

    assert first == second
    document = json.loads(first)
    assert document["schema_version"] == "terraproof.evidence/0.2"
    assert document["grade"] == CHECKS_PASSED
    assert document["limitation"] == LIMITATION_EN
    assert set(document["tool_versions"]) >= {"terraproof", "pyproj", "shapely", "numpy", "pyogrio",
                                              "rasterio", "gdal"}
    assert document["inputs"][0]["sha256"]
    assert document["inputs"][0]["bytes"] > 0
    assert "generated" not in first and "timestamp" not in first


def test_passing_checks_without_a_contract_are_never_decision_grade(make_raster, evaluate):
    from terraproof.evidence import EXIT_CODES
    path = make_raster("ndvi.tif", np.full((16, 16), 0.25, dtype="float32"))
    results, grade = evaluate([path])
    report = build_report(inputs=[input_record(path, "input", "raster")], results=results, parameters={})

    assert grade == report["grade"] == CHECKS_PASSED and EXIT_CODES[CHECKS_PASSED] == 0
    assert report["coverage"]["assessed"] is False
    not_checked = {item["check"]: item["enabled_by"] for item in report["coverage"]["not_checked"]}
    assert not_checked["rs.cloud_mask_applied"] == ["qa_path", "qa_kind"]
    assert not_checked["rs.scale_applied_once"] == ["reference_input", "encoding"]
    assert "scope.record_count" not in not_checked  # vector-only
    assert not set(not_checked) & {check["id"] for check in report["checks"]}
    text = render_markdown(report)
    assert "Not assessed" in text and "`rs.cloud_mask_applied`: `qa_path`, `qa_kind`" in text
    assert "غير مُقيَّمة" in render_markdown(report, lang="ar")


def test_a_check_that_ran_leaves_the_not_checked_list(make_raster, evaluate):
    path = make_raster("ndvi.tif", np.full((16, 16), 0.25, dtype="float32"))
    results, _grade = evaluate([path], expect="index")
    report = build_report(inputs=[input_record(path, "input", "raster")], results=results,
                          parameters={"expect": "index"})
    assert "rs.index_range" in {check["id"] for check in report["checks"]}
    assert "rs.index_range" not in {item["check"] for item in report["coverage"]["not_checked"]}


def test_preflight_reports_list_no_output_coverage(make_raster):
    path = make_raster("in.tif", np.ones((16, 16), dtype="uint16"))
    report = build_report(inputs=[input_record(path, "input", "raster")], results=[],
                          parameters={"plan": "plan.json", "plan_content": {}})
    assert report["coverage"] == {"assessed": False, "not_checked": []}
