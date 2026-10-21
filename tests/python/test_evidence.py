"""Evidence report tests: bilingual Markdown labels and deterministic JSON."""

from __future__ import annotations

import json

from shapely.geometry import Polygon

from terraproof.evidence import (
    ADVISORY,
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
        (_report(evaluate, clean, operation="area"), DECISION, "Decision-grade", "جاهز للقرار"),
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
    assert document["schema_version"] == "terraproof.evidence/0.1"
    assert document["grade"] == DECISION
    assert document["limitation"] == LIMITATION_EN
    assert set(document["tool_versions"]) >= {"terraproof", "pyproj", "shapely", "numpy", "pyogrio",
                                              "rasterio", "gdal"}
    assert document["inputs"][0]["sha256"]
    assert document["inputs"][0]["bytes"] > 0
    assert "generated" not in first and "timestamp" not in first
