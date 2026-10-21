"""Retrieval contracts, Arabic matching, data rules, evaluation and CLI regressions."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point

from terraproof.cli import main as cli_main
from terraproof.inspect import inspect_dataset
from terraproof.router import find_guidance
from terraproof.router.evaluate import evaluate_file, main as evaluate_main
from terraproof.router.index import PROCESS_SKILLS, find_root, get_index, markdown_sections
from terraproof.router.lexicon import ARABIC_TERMS
from terraproof.router.text import expand_query, normalize_arabic, tokenize

PROJECTED = {"is_projected": True, "is_geographic": False, "horizontal_kind": "projected", "epsg": 32636}
GEOGRAPHIC = {"is_projected": False, "is_geographic": True, "horizontal_kind": "geographic", "epsg": 4326}


def vector(crs=PROJECTED):
    return {"kind": "vector", "crs": crs, "geometry_types": ["Polygon"], "feature_count": 20}


def raster(dtype="float32", scale=1, offset=0, crs=PROJECTED):
    return {"kind": "raster", "crs": crs, "band_count": 1,
            "bands": [{"dtype": dtype, "scale": scale, "offset": offset, "nodata": -9999}]}


def names(result):
    return [skill["name"] for skill in result["skills"]]


def reason(result, name, fragment):
    return any(fragment in text for skill in result["skills"] if skill["name"] == name for text in skill["reasons"])


def test_deterministic_json_and_inputs_not_mutated():
    datasets = [vector(GEOGRAPHIC), raster("uint16", 0.0001, -0.1)]
    original = copy.deepcopy(datasets)
    first = find_guidance("عايز احسب مساحة بالمتر وقناع السحب", datasets=datasets)
    second = find_guidance("عايز احسب مساحة بالمتر وقناع السحب", datasets=datasets)
    assert json.dumps(first, ensure_ascii=False).encode() == json.dumps(second, ensure_ascii=False).encode()
    assert datasets == original
    assert first["skills"] == sorted(first["skills"], key=lambda skill: (-skill["score"], skill["name"]))


def test_determinism_across_fresh_processes():
    command = [sys.executable, "-c", "import json; from terraproof.router import find_guidance; print(json.dumps(find_guidance('NDVI vegetation index'),sort_keys=True))"]
    first = subprocess.run(command, capture_output=True, check=True)
    second = subprocess.run(command, capture_output=True, check=True)
    assert first.stdout == second.stdout


def test_router_text_path_does_not_import_native_geospatial_libraries():
    command = [sys.executable, "-c", "import sys; from terraproof.router import find_guidance; find_guidance('NDVI'); assert not {'rasterio','pyproj','pyogrio','shapely'} & sys.modules.keys()"]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0


def test_index_loads_all_real_sections_and_is_cached(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    index = get_index()
    assert get_index() is index
    assert len(index.skills) == 20
    assert len(index.sections) == sum(len(skill["sections"]) for skill in index.skills.values())
    assert all(section.text.strip() for section in index.sections)
    assert find_root().joinpath("routing", "registry.json").is_file()
    reference = next(section for section in index.sections if section.skill == "gdal" and section.source.startswith("references/"))
    assert reference.text == (find_root() / "skills" / "gdal" / reference.source).read_text(encoding="utf-8")


def test_root_supports_installed_share_assets(monkeypatch, tmp_path):
    import terraproof.router.index as module
    package_file = tmp_path / "lib" / "terraproof" / "router" / "index.py"
    shared = tmp_path / "prefix" / "share" / "terraproof"
    (shared / "routing").mkdir(parents=True)
    (shared / "skills").mkdir()
    (shared / "routing" / "registry.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(package_file))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "prefix"))
    assert find_root() == shared


def test_markdown_heading_extraction_anchors_duplicates_and_fences():
    sections = markdown_sections("## A (test)!\nfirst\n```md\n## Not a section\n```\n### Nested\nbody\n## A (test)!\nsecond\n~~~\n## Also not\n~~~\n## Last\nlast")
    assert set(sections) == {"a-test", "a-test-1", "last"}
    assert "## Not a section" in sections["a-test"]
    assert "### Nested" in sections["a-test"]
    assert sections["last"] == "last"


def test_arabic_matching_forms_and_noise():
    assert normalize_arabic("إِسْقَاطــ آأٱ ى ة") == "اسقاط ااا ي ه"
    query, terms, reasons = expand_query("عَايِز إِسْقَاطــ وَمَسَاحَة بالمتر المربع")
    assert query["language"] == "ar"
    assert {"crs", "projection", "area", "metre"} <= set(query["expanded_terms"])
    assert "عايز" not in terms
    assert any("Arabic lexicon" in text for text in reasons)
    assert tokenize("buffers polygons resampling") == tokenize("buffer polygon resample")


@pytest.mark.parametrize("arabic,english", [
    ("نظام الإحداثيات", "crs"), ("عازل", "buffer"), ("بفر", "buffer"),
    ("قناع السحب", "mask"), ("انعكاس سطحي", "reflectance"),
    ("مؤشر الغطاء النباتي", "ndvi"), ("مضلع غير صالح", "invalid"),
    ("تقاطع ذاتي", "intersection"), ("صورة فضائية", "satellite"),
    ("مرئية", "imagery"), ("خريطة تفاعلية", "interactive"),
    ("تحويل الإحداثيات", "reprojection"), ("نقطة", "point"),
    ("خط", "line"), ("مضلع", "polygon"), ("راستر", "raster"),
    ("شبكة", "grid"), ("بيانات مفتوحة", "geospatial"), ("كتالوج STAC", "stac"),
    ("شكل", "figure"), ("مجلة", "journal"), ("ورقة بحثية", "paper"),
    ("لوحة متعددة", "multi"), ("ألوان لعمى الألوان", "colorblind"), ("ألوان مناسبة", "colorblind"),
    ("مسار", "path"), ("عقد", "nodes"), ("حواف", "edges"),
    ("ابحث", "search"), ("دور", "search"), ("لاقي", "find"), ("نزل", "download"),
    ("تحميل", "download"), ("مشاهد", "scenes"), ("منطقة", "region"),
    ("مؤشر", "index"), ("مؤشرات", "indices"),
    ("كم", "kilometre"), ("كيلومتر", "kilometre"), ("كيلو", "kilometre"),
    ("هكتار", "hectare"), ("فدان", "acre"), ("في نطاق", "within"),
    ("على بعد", "distance"), ("حوالين", "proximity"),
])
def test_lexicon_terms(arabic, english):
    assert english in expand_query("محتاج " + arabic)[0]["expanded_terms"]
    assert len(ARABIC_TERMS) >= 80


@pytest.mark.parametrize("task", ["Measure buffer distance in metres", "عايز احسب مساحة بالمتر", "احسب طول الخط"])
def test_geographic_metric_rule(task):
    result = find_guidance(task, datasets=[vector(GEOGRAPHIC)])
    assert names(result)[0] == "crs-and-units"
    assert reason(result, "crs-and-units", "geographic horizontal CRS with metric wording")


@pytest.mark.parametrize("task", [
    "List the schools within 5 km of the river",
    "Count the buildings 200 m of the coastline",
    "Sum the parcel areas in hectares",
    "Total farm area in acres and miles of fencing",
    "Mean patch size in square kilometres",
    "The map pixel size is 30 m; check the units",
    "احسب المساحة بالهكتار لكل قطعة",
    "مساحة كل مزرعة بالفدان",
    "المدارس على بعد 3 كم من النهر",
    "العيادات في نطاق 2 كم من المستشفى",
    "البيوت اللي حوالين خط المترو بمسافة 500 م",
    "طول الشوارع بالكيلومتر",
])
def test_geographic_unit_and_proximity_wording_rule(task):
    result = find_guidance(task, datasets=[vector(GEOGRAPHIC)])
    assert names(result)[0] == "crs-and-units"
    assert reason(result, "crs-and-units", "geographic horizontal CRS with metric wording")


def test_arabic_prefix_stripping_matches_new_lexicon_terms():
    # Covers ال/بال/لل/و/ب attachment: المساحة، بالكيلومتر، للمؤشر، وللفدان، ولمسافة.
    query, _, _ = expand_query("المساحة بالكيلومتر والهكتار للمؤشر وللفدان ولمسافة كيلو حوالين النهر")
    assert {"area", "kilometre", "hectare", "index", "acre", "distance", "proximity"} <= set(query["expanded_terms"])


def test_compound_horizontal_geographic_rule_and_projected_negative():
    compound = vector({"is_geographic": False, "horizontal_kind": "geographic"})
    assert reason(find_guidance("area", datasets=[compound]), "crs-and-units", "metric wording")
    assert not reason(find_guidance("area", datasets=[vector()]), "crs-and-units", "metric wording")


@pytest.mark.parametrize("profile", [vector(None), raster(crs=None), {"kind": "vector"}])
def test_missing_crs_rule(profile):
    result = find_guidance("Prepare this input", datasets=[profile])
    assert reason(result, "crs-and-units", "missing CRS")


def test_nullable_optional_band_metadata():
    result = find_guidance("Prepare input", datasets=[{"kind": "raster", "bands": None}])
    assert "raster-processing" in names(result)
    assert "unknown dtype" in result["datasets"][0]["summary"]


def test_stac_does_not_invent_missing_crs():
    result = find_guidance("Prepare this input", datasets=[{"kind": "stac", "collection": "local"}])
    assert not reason(result, "crs-and-units", "missing CRS")


@pytest.mark.parametrize("dtype,scale,offset", [("uint16", 0.0001, 0), ("int16", 1, -0.2), ("byte", 2, 3)])
def test_integer_scale_offset_rule(dtype, scale, offset):
    result = find_guidance("Prepare this input", datasets=[raster(dtype, scale, offset)])
    assert reason(result, "satellite-preprocessing", "integer raster has non-identity scale/offset")


@pytest.mark.parametrize("dtype,scale,offset", [("uint16", 1, 0), ("uint8", None, None), ("float32", 0.001, -0.2)])
def test_identity_or_float_does_not_trigger_integer_scaling(dtype, scale, offset):
    result = find_guidance("Prepare this input", datasets=[raster(dtype, scale, offset)])
    assert not reason(result, "satellite-preprocessing", "integer raster")


@pytest.mark.parametrize("collection", ["sentinel-2-l2a", "SENTINEL_2_L2A", "landsat-c2-l2"])
def test_sensor_collection_rule(collection):
    result = find_guidance("Prepare this input", datasets=[{"kind": "stac", "collection": collection}])
    assert names(result)[0] == "satellite-preprocessing"
    assert reason(result, "satellite-preprocessing", "Sentinel-2/Landsat STAC collection")
    assert reason(result, "geospatial-data-discovery", "STAC item")


def test_stac_intent_split_between_catalog_search_and_processing():
    stac = {"kind": "stac", "collection": "sentinel-2-l2a"}
    held = find_guidance("I have this Sentinel-2 STAC item; mask the clouds and decode the reflectance", datasets=[stac])
    assert names(held)[0] == "satellite-preprocessing"
    assert "geospatial-data-discovery" not in names(held)
    search = find_guidance("Find scenes in the STAC catalog over the delta", datasets=[stac])
    assert "geospatial-data-discovery" in names(search)
    assert reason(search, "geospatial-data-discovery", "STAC item with catalog search wording")
    assert "satellite-preprocessing" in names(search)
    dual = find_guidance("Download this Sentinel-2 STAC item, then mask the SCL clouds", datasets=[stac])
    assert {"geospatial-data-discovery", "satellite-preprocessing"} <= set(names(dual))
    index = find_guidance("Compute NDVI from this Landsat STAC item",
                          datasets=[{"kind": "stac", "collection": "landsat-c2-l2"}])
    assert {"satellite-preprocessing", "spectral-indices"} <= set(names(index))
    assert "geospatial-data-discovery" not in names(index)


@pytest.mark.parametrize("profile", [raster("uint16", 0.0001, -0.1), {"kind": "stac", "collection": "sentinel-2-l2a"}])
def test_reflectance_profiles_with_index_wording_surface_spectral_indices(profile):
    result = find_guidance("احسب المؤشر من الداتا دي", datasets=[profile])
    assert {"satellite-preprocessing", "spectral-indices"} <= set(names(result))
    assert reason(result, "spectral-indices", "index wording")


def test_raster_vector_preference_rules_and_mixed_inputs():
    raster_result = find_guidance("Prepare this input", datasets=[raster()])
    assert names(raster_result)[0] == "raster-processing"
    assert "geopandas" not in names(raster_result)
    vector_result = find_guidance("Prepare this input", datasets=[vector()])
    assert {"geopandas", "vector-quality"} <= set(names(vector_result))
    assert "raster-processing" not in names(vector_result)
    mixed = find_guidance("Prepare these inputs", datasets=[vector(), raster()])
    assert {"raster-processing", "geopandas"} <= set(names(mixed))
    assert not any("rather than" in text for skill in mixed["skills"] for text in skill["reasons"])


def test_negative_type_penalties_are_explained():
    result = find_guidance("GeoPandas spatial join buffer", datasets=[raster()])
    assert reason(result, "geopandas", "raster rather than vector input -4.000000")
    result = find_guidance("rasterio nodata resampling", datasets=[vector()])
    assert reason(result, "raster-processing", "vector rather than raster input -4.000000")


def test_multiple_rasters_and_repeated_profiles_do_not_multiply_rules():
    result = find_guidance("Prepare these inputs", datasets=[raster(), raster(), raster()])
    assert names(result)[0] == "raster-processing"
    assert reason(result, "raster-processing", "multiple rasters")
    contributions = next(skill for skill in result["skills"] if skill["name"] == "raster-processing")["reasons"]
    assert sum("multiple rasters" in text for text in contributions) == 1
    missing = find_guidance("Prepare these inputs", datasets=[vector(None), vector(None)])
    assert sum("missing CRS" in text for skill in missing["skills"] for text in skill["reasons"]) == 1


def test_full_inspection_profiles_and_data_paths(make_vector, make_raster, make_stac_item):
    paths = [make_vector("points.gpkg", [Point(500000, 5000000)], geometry_type="Point"),
             make_raster("scene.tif", np.ones((8, 8), dtype="uint16"), scale=0.0001),
             make_stac_item("item.json", {"datetime": "2024-01-01T00:00:00Z", "proj:epsg": 32636})]
    profiles = [inspect_dataset(path) for path in paths]
    direct = find_guidance("Prepare these inputs", datasets=profiles)
    inspected = find_guidance("Prepare these inputs", data_paths=paths)
    assert direct == inspected
    assert [ds["path"] for ds in inspected["datasets"]] == paths
    assert [ds["kind"] for ds in inspected["datasets"]] == ["vector", "raster", "stac"]
    assert all(ds["summary"] for ds in inspected["datasets"])
    assert find_guidance("Prepare inputs", datasets=[vector()])["datasets"][0]["path"] is None


@pytest.mark.parametrize("task,expected", [
    ("fix a raster error", ["systematic-debugging", "verification"]),
    ("اصلح مشكلة وخطأ في الملف", ["systematic-debugging", "verification"]),
    ("Build a map", ["brainstorming", "writing-plans", "verification"]),
    ("Create a dashboard", ["brainstorming", "writing-plans", "verification"]),
    ("صمم خريطة تفاعلية", ["brainstorming", "writing-plans", "verification"]),
    ("Design a fix for the error", ["brainstorming", "writing-plans", "systematic-debugging", "verification"]),
    ("plan NDVI analysis", ["writing-plans", "verification"]),
    ("NDVI", ["verification"]),
])
def test_process_layer(task, expected):
    result = find_guidance(task)
    assert result["process"] == expected
    assert not PROCESS_SKILLS.intersection(names(result))


def test_limits_and_section_content():
    result = find_guidance("Sentinel-2 SCL band NDVI", top_k=2, sections_per_skill=1)
    assert len(result["skills"]) == 2
    assert all(len(skill["sections"]) == 1 for skill in result["skills"])
    assert all(set(section) == {"id", "title", "source", "score", "excerpt"}
               for skill in result["skills"] for section in skill["sections"])
    assert all(section["excerpt"] for skill in result["skills"] for section in skill["sections"])
    assert find_guidance("NDVI", top_k=0)["skills"] == []
    assert find_guidance("NDVI", sections_per_skill=0)["skills"][0]["sections"] == []
    assert [(s["name"], s["score"]) for s in find_guidance("NDVI", sections_per_skill=0)["skills"]] == [(s["name"], s["score"]) for s in find_guidance("NDVI", sections_per_skill=3)["skills"]]


def test_scores_are_explained_and_multiword_triggers_have_boosts():
    result = find_guidance("surface reflectance SCL band", datasets=[raster("uint16", 0.0001)])
    assert reason(result, "satellite-preprocessing", "Exact trigger 'surface reflectance' +4.000000")
    for skill in result["skills"]:
        contributions = [float(text.rsplit(" ", 1)[1]) for text in skill["reasons"] if "Arabic lexicon" not in text]
        assert sum(contributions) == pytest.approx(skill["score"], abs=0.0001)


@pytest.mark.parametrize("task", ["Tell me a joke about bananas", "حكاية عن قطة نايمة"])
def test_irrelevant_task_score_cutoff(task):
    assert find_guidance(task)["skills"] == []


def test_line_chart_does_not_select_spatial_or_graph_tools():
    result = find_guidance("Draw a line chart")
    assert names(result) == ["scientific-visualization"]


@pytest.mark.parametrize("task", [
    "Classify the satellite imagery into land cover classes",
    "Compute summary statistics of the satellite imagery bands",
    "Reproject this raster with gdalwarp",
    "Compute zonal statistics of the raster",
    "احسب الإحصاءات الوصفية للمرئية",
    "اعمل تصنيف للمرئية ده للغطاء الأرضي",
])
def test_weak_imagery_wording_does_not_rank_satellite_skills(task):
    result = find_guidance(task)
    assert "satellite-preprocessing" not in names(result)
    assert "spectral-indices" not in names(result)


@pytest.mark.parametrize("task", [
    "Export the land cover map as a multi-panel PNG figure for the journal",
    "Save the map as a PDF figure for the print edition",
    "اطبع خريطة الغطاء الأرضي كشكل للنشر في مجلة",
])
def test_static_print_figure_wording_does_not_rank_geospatial_frontend(task):
    result = find_guidance(task)
    assert "scientific-visualization" in names(result)
    assert "geospatial-frontend" not in names(result)


@pytest.mark.parametrize("task", [
    "Analyze the city road network centrality and shortest paths",
    "Compute betweenness centrality for the road network nodes and edges",
    "Find the shortest path in the road network between the two nodes",
    "حلل شبكة الطرق ومركزية العقد",
])
def test_graph_analysis_wording_does_not_rank_data_discovery(task):
    result = find_guidance(task)
    assert names(result)[0] == "networkx"
    assert "geospatial-data-discovery" not in names(result)


def test_web_map_and_data_sourcing_wording_keep_frontend_and_discovery():
    assert "geospatial-frontend" in names(find_guidance("Build an interactive web map dashboard with MapLibre"))
    assert "geospatial-frontend" in names(find_guidance("ابني خريطة تفاعلية للنيل بـ MapLibre"))
    assert "geospatial-data-discovery" in names(find_guidance("Download OpenStreetMap road network data for the city"))
    assert "geospatial-data-discovery" in names(find_guidance("نزّل داتا شبكة الطرق من OpenStreetMap"))


@pytest.mark.parametrize("kwargs", [
    {"task": ""}, {"task": None}, {"task": "NDVI", "top_k": -1},
    {"task": "NDVI", "top_k": True}, {"task": "NDVI", "sections_per_skill": 1.5},
    {"task": "NDVI", "datasets": {}}, {"task": "NDVI", "datasets": [{"kind": "table"}]},
    {"task": "NDVI", "datasets": [{"kind": "raster", "crs": "EPSG:4326"}]},
    {"task": "NDVI", "datasets": [{"kind": "raster", "bands": [1]}]},
    {"task": "NDVI", "data_paths": "missing.tif"},
])
def test_api_input_errors(kwargs):
    with pytest.raises(ValueError):
        find_guidance(**kwargs)


def write_items(path, items):
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n", encoding="utf-8")
    return str(path)


def test_evaluator_metrics_and_recall_exit_codes(tmp_path, capsys):
    path = write_items(tmp_path / "tiny.jsonl", [
        {"id": "en", "prompt": "NetworkX centrality", "lang": "en", "expected": ["networkx", "spectral-indices"]},
        {"id": "ar", "prompt": "مؤشر الغطاء النباتي", "lang": "ar", "expected": ["spectral-indices"]},
    ])
    metrics = evaluate_file(path, top_k=1)
    assert metrics["mean_recall_at_k"] == 0.75
    assert metrics["per_language_recall"] == {"ar": 1.0, "en": 0.5}
    assert metrics["must_not_violations"] == 0
    assert metrics["failing_items"][0]["top_k"] == ["networkx"]
    assert evaluate_main([path, "--top-k", "1", "--min-recall", "0.75"]) == 0
    assert json.loads(capsys.readouterr().out) == metrics
    assert evaluate_main([path, "--top-k", "1", "--min-recall", "0.9"]) == 1
    capsys.readouterr()
    completed = subprocess.run([sys.executable, "-m", "terraproof.router.evaluate", path, "--top-k", "1", "--min-recall", "0.75"], capture_output=True, text=True)
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == metrics


def test_evaluator_must_not_exit_and_empty_expected(tmp_path, capsys):
    path = write_items(tmp_path / "tiny.jsonl", [
        {"id": "bad", "prompt": "NetworkX centrality", "lang": "en", "expected": [], "must_not": ["networkx"]},
    ])
    assert evaluate_main([path, "--min-recall", "0"]) == 1
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["mean_recall_at_k"] == 1.0
    assert metrics["must_not_violations"] == 1
    assert metrics["failing_items"][0]["must_not"] == ["networkx"]


@pytest.mark.parametrize("text", ["", "{invalid}", '{"id":"a","lang":"en","prompt":"x","expected":["verification"]}'])
def test_evaluator_invalid_file_exit(tmp_path, capsys, text):
    path = tmp_path / "invalid.jsonl"
    path.write_text(text, encoding="utf-8")
    assert evaluate_main([str(path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_evaluator_bad_threshold_and_missing_file(tmp_path, capsys):
    assert evaluate_main([str(tmp_path / "absent.jsonl")]) == 1
    assert "error:" in capsys.readouterr().err
    assert evaluate_main(["unused", "--min-recall", "nan"]) == 1
    assert "min-recall" in capsys.readouterr().err


def test_cli_route_json_and_markdown(capsys):
    assert cli_main(["route", "عايز مؤشر الغطاء النباتي", "--top-k", "1", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["query"]["language"] == "ar"
    assert names(result) == ["spectral-indices"]
    assert cli_main(["route", "Sentinel-2 SCL band NDVI", "--format", "md"]) == 0
    text = capsys.readouterr().out
    assert "## satellite-preprocessing" in text
    assert "Reasons:" in text and "Top sections:" in text and "SKILL.md#" in text


def test_cli_route_repeated_data_flags_and_multiple_paths(make_stac_item, capsys):
    path = make_stac_item("item.json", {"datetime": "2024-01-01T00:00:00Z", "proj:epsg": 32636})
    assert cli_main(["route", "Prepare inputs", "--data", path, path, "--data", path]) == 0
    assert len(json.loads(capsys.readouterr().out)["datasets"]) == 3


@pytest.mark.parametrize("args", [
    ["route"], ["route", "NDVI", "--format", "xml"], ["route", "NDVI", "--top-k", "x"],
    ["route", "NDVI", "--data"], ["route", "NDVI", "--unknown"],
])
def test_cli_route_usage_exit_codes(args):
    with pytest.raises(SystemExit) as exc:
        cli_main(args)
    assert exc.value.code == 1


@pytest.mark.parametrize("args", [["route", ""], ["route", "NDVI", "--top-k", "-1"], ["route", "NDVI", "--data", "absent.tif"]])
def test_cli_route_input_exit_codes(args, capsys):
    assert cli_main(args) == 1
    assert "error:" in capsys.readouterr().err


def test_dev_set_coverage_without_opening_any_other_evaluation_set():
    items = [json.loads(line) for line in (find_root() / "evals" / "routing" / "dev.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(items) >= 50
    assert sum(item["lang"] == "en" for item in items) >= 25
    assert sum(item["lang"] == "ar" for item in items) >= 25
    assert sum(bool(item.get("datasets")) for item in items) >= 10
    assert {name for item in items for name in item["expected"]} == set(get_index().skills) - PROCESS_SKILLS
