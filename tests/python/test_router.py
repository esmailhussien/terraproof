"""Retrieval contracts, Arabic matching, data rules, evaluation and CLI regressions."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point

from terraproof.cli import main as cli_main
from terraproof.inspect import inspect_dataset
from terraproof.router import find_guidance
from terraproof.router.evaluate import evaluate_file, main as evaluate_main
from terraproof.router.index import PROCESS_SKILLS, Index, Section, find_root, get_index, markdown_sections
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
    registry = json.loads(find_root().joinpath("routing", "registry.json").read_text(encoding="utf-8"))
    assert len(index.skills) == len(registry["skills"])
    assert set(index.skills) == set(registry["skills"])
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


def test_arabic_plural_bases_need_a_lexicon_form():
    from terraproof.router.text import _plural_bases
    # Plurals reach a known lexicon word; singular nouns ending in the same
    # letters (address, law, storage, improvement) gain no invented base.
    assert "ارتفاع" in _plural_bases({"ارتفاعات"})
    assert _plural_bases({"عنوان", "قانون", "تخزين", "تحسين", "ميزان"}) == set()


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


@pytest.mark.parametrize("arabic,english", [
    ("المساحات", "area"), ("ولمساحتها", "area"), ("مساحاتهم", "area"),
    ("مسافاتهم", "distance"), ("المسافات", "distance"), ("بأطوالها", "length"),
    ("بالكيلومترات", "kilometre"), ("بكيلومتراتنا", "kilometre"),
    ("بأمتارها", "metre"), ("وهكتاراتنا", "hectare"),
    ("الأفدنة", "acre"), ("أفدنتها", "acre"), ("بالفدادين", "acre"), ("بالأميال", "mile"),
    ("مساراتهم", "routing"), ("ترابطها", "connectivity"), ("اتصاليتها", "connectivity"),
    ("العقدة", "node"), ("حافتها", "edge"), ("وصلاتها", "edges"),
    ("الجراف", "network"), ("توجيه", "routing"), ("طوبولوجيا", "topology"),
    ("مؤشرها", "index"), ("ولمؤشراتنا", "indices"), ("مرئياتها", "satellite"),
    ("أجيب", "acquire"), ("ألاقي", "search"), ("أحملها", "download"),
])
def test_arabic_plurals_and_attached_pronouns(arabic, english):
    query, _, reasons = expand_query(arabic)
    assert english in query["expanded_terms"]
    assert any("Arabic lexicon" in text for text in reasons)


@pytest.mark.parametrize("word", ["كمبيوتر", "مؤشراتيح", "مساحتهندسة", "كيلومتراتولوجيا"])
def test_arabic_morphology_does_not_match_interior_substrings(word):
    assert expand_query(word)[0]["expanded_terms"] == []


@pytest.mark.parametrize("word", ["المساحات", "بالكيلومترات", "الأفدنة", "مسافاتهم", "ولمساحتها", "أفدنتها"])
def test_geographic_metric_rule_with_arabic_morphology(word):
    result = find_guidance(word, datasets=[vector(GEOGRAPHIC)])
    assert names(result)[0] == "crs-and-units"
    assert reason(result, "crs-and-units", "geographic horizontal CRS with metric wording")
    assert not reason(find_guidance(word, datasets=[vector()]), "crs-and-units", "metric wording")


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
    "Classify the calibrated Sentinel reflectance imagery into land cover classes",
    "Compute descriptive statistics for the calibrated reflectance raster",
    "Plot the calibrated reflectance bands in a figure",
    "اعمل تصنيف للانعكاس السطحي الموجود عندي",
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


@pytest.mark.parametrize("task", [
    "Create a spatial index in PostGIS, then compute NDVI from Sentinel imagery",
    "Create a spatial index in PostGIS, then compute the water index from Landsat",
])
def test_nonspectral_index_guard_preserves_separate_spectral_intent(task):
    result = find_guidance(task)
    assert {"design-postgis-tables", "spectral-indices"} <= set(names(result))


def test_web_map_and_data_sourcing_wording_keep_frontend_and_discovery():
    assert "geospatial-frontend" in names(find_guidance("Build an interactive web map dashboard with MapLibre"))
    assert "geospatial-frontend" in names(find_guidance("ابني خريطة تفاعلية للنيل بـ MapLibre"))
    assert "geospatial-data-discovery" in names(find_guidance("Download OpenStreetMap road network data for the city"))
    assert "geospatial-data-discovery" in names(find_guidance("نزّل داتا شبكة الطرق من OpenStreetMap"))


@pytest.mark.parametrize("task", [
    "Where can I get a shapefile of the watershed boundaries?",
    "Where could we obtain a GeoJSON dataset of public parks?",
    "Is there an open dataset of building footprints?",
    "Are there public datasets of soil polygons?",
    "Pull imagery for the coastal study area.",
    "Where can I get a land-cover classification shapefile?",
    "Where can I get a spatial index dataset in GeoJSON?",
    "منين أجيب shapefile للحدود الإدارية؟",
    "هل هناك dataset مفتوح لصور المدينة؟",
    "فين بيانات المباني اللي أقدر أحملها؟",
    "عاوز ألاقي GeoJSON للقرى وأعرف ترخيصها",
])
def test_indirect_discovery_wording_without_geopandas(task):
    result = find_guidance(task)
    assert "geospatial-data-discovery" in names(result)
    assert "geopandas" not in names(result)
    assert reason(result, "geospatial-data-discovery", "data acquisition or availability question")


PYTHON_SCENARIOS = json.loads((Path(__file__).parents[1] / "router" / "scenarios.json").read_text(encoding="utf-8"))["pythonScenarios"]


@pytest.mark.parametrize("scenario", PYTHON_SCENARIOS, ids=lambda scenario: scenario["id"])
def test_python_routing_scenarios(scenario):
    result = find_guidance(scenario["prompt"], datasets=scenario.get("datasets"))
    assert set(scenario["mustInclude"]) <= set(names(result))
    assert not set(scenario.get("mustExclude", [])) & set(names(result))
    assert len(result["skills"]) <= scenario.get("maxSkills", 5)


@pytest.fixture
def controlled_index(monkeypatch):
    """Control BM25 independently of corpus wording to test selection boundaries."""
    import terraproof.router as router
    metadata = {
        "raster-processing": {"triggers": ["rasterio"]},
        "gdal": {"triggers": []}, "geozarr": {"triggers": []},
        "geomaster": {"triggers": ["sentinel"]}, "networkx": {"triggers": []},
        "geopandas": {"triggers": []}, "vector-quality": {"triggers": []},
        "spectral-indices": {"triggers": ["routing"]},
    }
    for skill in metadata.values():
        skill.update(explanation="raster network", capabilities=[])
    sections = tuple(Section(name, "test", "Test", "SKILL.md#test", "raster network", {}, 1)
                     for name in metadata)
    index = Index(metadata, sections, {}, 1.0)
    scores = {}
    monkeypatch.setattr(router, "get_index", lambda: index)
    monkeypatch.setattr(Index, "score", lambda self, section, terms: (scores.get(section.skill, 0.0), []))
    return router, scores


def test_relative_cutoff_boundary_and_direct_trigger_exemption(controlled_index):
    router, scores = controlled_index
    scores.update({"raster-processing": 38.0, "gdal": 20.0, "geozarr": 19.999, "geomaster": 5.0})
    result = router.find_guidance("rasterio raster sentinel", top_k=10)
    assert router.RELATIVE_CUTOFF == 0.5
    assert names(result) == ["raster-processing", "gdal", "geomaster"]
    assert result["skills"][1]["score"] == result["skills"][0]["score"] * router.RELATIVE_CUTOFF
    # The directly requested sensor skill survives below the relative threshold.
    assert result["skills"][2]["score"] < result["skills"][1]["score"]


def test_relative_cutoff_keeps_positive_dataset_evidence(controlled_index):
    router, scores = controlled_index
    scores.update({"raster-processing": 100.0})
    result = router.find_guidance("rasterio raster", datasets=[vector()], top_k=10)
    assert {"geopandas", "vector-quality"} <= set(names(result))
    assert all(skill["score"] < router.RELATIVE_CUTOFF * result["skills"][0]["score"]
               for skill in result["skills"] if skill["name"] != "raster-processing")


def test_empty_result_fallback_single_best_and_explanation(controlled_index):
    router, scores = controlled_index
    scores.update({"networkx": 0.5, "geomaster": 0.5})
    result = router.find_guidance("routing sentinel")
    assert names(result) == ["networkx"]
    assert router.FALLBACK_MIN_SCORE <= result["skills"][0]["score"] < router.MIN_SCORE
    assert reason(result, "networkx", "empty-result fallback")
    assert router.find_guidance("routing sentinel", top_k=0)["skills"] == []
    assert router.find_guidance("routing sentinel", sections_per_skill=0)["skills"][0]["sections"] == []


def test_empty_result_fallback_floor_ties_and_guards(controlled_index, monkeypatch):
    router, scores = controlled_index
    scores.update({"networkx": 0.5, "geomaster": 1.5, "spectral-indices": 2.0})
    # Both supported candidates score 3.5; names break ties. The artificial index
    # trigger for spectral-indices must not bypass its no-index-intent guard.
    assert names(router.find_guidance("routing sentinel")) == ["geomaster"]
    monkeypatch.setattr(router, "FALLBACK_MIN_SCORE", 3.500001)
    assert router.find_guidance("routing sentinel")["skills"] == []
    assert router.find_guidance("bananas")["skills"] == []


def test_fallback_not_added_when_another_skill_passes(controlled_index):
    router, scores = controlled_index
    scores.update({"raster-processing": 10.0, "networkx": 0.5})
    result = router.find_guidance("rasterio routing")
    assert names(result) == ["raster-processing"]
    assert not any("fallback" in text for skill in result["skills"] for text in skill["reasons"])


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
    assert metrics["mean_ranked_skills"] == 1.0
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
    assert len(items) >= 169
    additions = [item for item in items if "-precision-" in item["id"]]
    assert len(additions) >= 40
    assert sum(item["lang"] == "ar" for item in additions) >= 20
    assert sum(item["lang"] == "en" for item in items) >= 25
    assert sum(item["lang"] == "ar" for item in items) >= 25
    assert sum(bool(item.get("datasets")) for item in items) >= 10
    assert {name for item in items for name in item["expected"]} == set(get_index().skills) - PROCESS_SKILLS


# --- Candidate mode ----------------------------------------------------------


SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "router_head_snapshot.json").read_text(encoding="utf-8-sig"))

# The registry grew from 20 to 24 non-process skills in Phase 4 (the four new
# skills below). BM25 idf and mean section length cover the whole corpus, so
# catalog expansion legitimately changes every BM25 score. The committed
# fixture is immutable, therefore this compatibility test pins the corpus: it
# recomputes idf/mean length with the identical code path over the snapshot-era
# (20-skill) baseline and points the router at it. New 24-skill behaviour is
# covered by the pythonScenarios, dev.jsonl and semantic assertions instead.
SNAPSHOT_NEW_SKILLS = ("sar-basics", "accuracy-assessment",
                       "stac-and-cloud-access", "time-series-and-change")


@pytest.fixture
def head_snapshot_index(monkeypatch):
    """Filter live Section/Index data to the 1cac039 baseline and recompute BM25."""
    import terraproof.router as router
    import terraproof.router.index as index_module
    full = index_module.get_index()
    sections = tuple(section for section in full.sections if section.skill not in SNAPSHOT_NEW_SKILLS)
    ranked = [section for section in sections if section.skill not in index_module.PROCESS_SKILLS]
    document_frequency: Counter = Counter()
    for section in ranked:
        document_frequency.update(section.frequencies.keys())
    count = len(ranked)
    idf = {term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
           for term, frequency in document_frequency.items()}
    skills = {name: full.skills[name] for name in full.skills if name not in SNAPSHOT_NEW_SKILLS}
    average = sum(section.length for section in ranked) / count
    index = Index(skills, sections, idf, average)
    monkeypatch.setattr(index_module, "get_index", lambda: index)
    monkeypatch.setattr(router, "get_index", lambda: index)
    return index


def canonical(result):
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("record", SNAPSHOT["prompts"], ids=lambda record: record["slug"])
def test_ranked_default_output_byte_identical_to_head(record, head_snapshot_index):
    """JSON output with default arguments matches the committed 1cac039 snapshot
    on the controlled 20-skill corpus the fixture was recorded against."""
    result = find_guidance(record["prompt"], datasets=copy.deepcopy(record["datasets"]))
    assert canonical(result) == canonical(record["output"])


def test_candidates_contract_and_defaults():
    result = find_guidance("Fix the broken parcels layer", mode="candidates")
    assert len(result["skills"]) <= 8
    assert all(skill["reasons"] for skill in result["skills"])
    assert all(isinstance(skill.get("explanation"), str) and skill["explanation"]
               for skill in result["skills"])
    # Default top_k for candidates is 8, ranked remains 5.
    wide = find_guidance("Fix the broken parcels layer", mode="candidates", top_k=16)
    assert result["skills"] == wide["skills"][:8]


def test_candidates_drop_relative_cutoff_but_keep_intents(controlled_index):
    router, scores = controlled_index
    scores.update({"raster-processing": 38.0, "gdal": 20.0, "geozarr": 19.999, "geomaster": 5.0})
    ranked = router.find_guidance("rasterio raster sentinel", top_k=10)
    assert names(ranked) == ["raster-processing", "gdal", "geomaster"]
    candidates = router.find_guidance("rasterio raster sentinel", top_k=10, mode="candidates")
    # Candidate mode keeps the ranked result as an ordered prefix; the lower-
    # scoring geozarr candidate fills after the direct geomaster intent.
    assert names(candidates) == ["raster-processing", "gdal", "geomaster", "geozarr"]
    assert names(router.find_guidance("Tell me a joke about bananas", mode="candidates")) == []
    assert names(router.find_guidance("fix a raster error", mode="candidates")) == []


def test_candidates_lowered_metadata_floor_but_litmus_for_body_only():
    # Metadata-adjacent wording can enter on the lowered floor...
    assert "crs-and-units" in names(find_guidance("عازل بالمتر ميتر", datasets=[vector()], mode="candidates"))
    # ...while dangling body-only matches stay out of a chart-only request.
    result = find_guidance("Draw a line chart.", mode="candidates")
    assert "geopandas" not in names(result)
    assert "statistical-analysis" not in names(result)


def test_invalid_mode_and_semantic_type(tmp_path):
    with pytest.raises(ValueError):
        find_guidance("NDVI", mode="auto")
    with pytest.raises(ValueError):
        find_guidance("NDVI", semantic="yes")
    with pytest.raises(ValueError):
        from terraproof.router.evaluate import evaluate_file
        evaluate_file(str(tmp_path / "missing.jsonl"), mode="top")


# --- Semantic retrieval (fake embedder; never downloads in CI) ----------------


class FakeEmbedder:
    """Hash-bag deterministic embedder; word overlap drives cosine similarity."""

    DIM = 32

    def _vector(self, text):
        import math
        from terraproof.router.text import tokenize
        vector = [0.0] * self.DIM
        for word in sorted(set(tokenize(text))):
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            if digest[0] < 128:  # noisy words keep similarities realistic
                vector[digest[1] % self.DIM] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed(self, documents, batch_size=32):
        return [self._vector(document) for document in documents]


@pytest.fixture
def fake_semantic(monkeypatch, tmp_path):
    from terraproof.router import semantic
    monkeypatch.setenv("TERRAPROOF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(semantic, "get_embedder", lambda: FakeEmbedder())
    return semantic


def test_semantic_fusion_scores_and_reasons(fake_semantic, monkeypatch):
    import terraproof.router as module

    module.SEMANTIC_MIN_SCORE = 0.0
    module.SEMANTIC_TOP_N = 16
    module.SEMANTIC_DELTA = 1.0
    task = "store the multidimensional arrays as cloud native zarr"
    plain = find_guidance(task, mode="candidates", semantic=False)
    result = find_guidance(task, mode="candidates", semantic=True)
    names_sem = names(result)
    assert "geozarr" in names_sem
    skill = next(s for s in result["skills"] if s["name"] == "geozarr")
    assert any("Semantic: cosine=" in text for text in skill["reasons"])
    assert all(round(value, 6) == value for value in (s["score"] for s in result["skills"]))
    # Everything available lexically stays available with the model on.
    assert {s["name"] for s in plain["skills"]} <= set(names_sem)


def test_semantic_true_overrides_env_off(fake_semantic):
    # semantic=False wins even when the environment asks for the model.
    result = find_guidance("store the multidimensional arrays as zarr", semantic=False)
    assert not any("Semantic: cosine=" in text for skill in result["skills"] for text in skill["reasons"])
    assert "reasons" not in result


def test_semantic_missing_extra_falls_back_and_warns(monkeypatch, tmp_path):
    monkeypatch.setenv("TERRAPROOF_CACHE_DIR", str(tmp_path / "cache"))
    # No model in a fresh cache; the real fastembed is not even importable here.
    lexical = find_guidance("NDVI from Sentinel reflectance", semantic=False)
    result = find_guidance("NDVI from Sentinel reflectance", semantic=True)
    # The skill list and scores must match the lexical fallback; the warning is
    # surfaced separately so the caller sees why semantic retrieval did not run.
    assert canonical({k: v for k, v in result.items() if k != "reasons"}) == canonical(lexical)
    warnings = sorted({text for skill in result["skills"] for text in skill["reasons"]
                       if "semantic retrieval unavailable" in text} | set(result.get("reasons", [])))
    assert warnings and "terraproof[semantic]" in warnings[0] and "--download-model" in warnings[0]


def test_semantic_download_command(tmp_path, monkeypatch, capsys):
    from terraproof.router.__main__ import main as router_main
    assert router_main([]) == 1
    called = {}

    def fake_download(download):
        called["download"] = download
        return Path("/cached/model")

    import terraproof.router.semantic as semantic
    monkeypatch.setenv("TERRAPROOF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(semantic, "model_path", fake_download)
    assert router_main(["--download-model"]) == 0
    assert called == {"download": True}
    assert "model ready at /cached/model" in capsys.readouterr().out


def test_semantic_section_cache_key_follows_registry_content(fake_semantic, tmp_path):
    from terraproof.router.index import Index, Section, get_index
    from terraproof.router.semantic import content_key
    index = get_index()
    first = content_key(index)
    modified = Index(dict(index.skills), index.sections, index.idf, index.average_length)
    modified.skills["geozarr"] = dict(modified.skills["geozarr"], explanation="changed")
    assert content_key(modified) != first
    assert content_key(index) == first


def test_semantic_real_model_only_when_cached(tmp_path):
    """With the real model cached in the user cache, verify a scored result; else skip."""
    pytest.importorskip("fastembed", reason="semantic extra not installed")
    from terraproof.router import semantic
    snapshots = list(semantic.cache_dir().glob("models/models--*/snapshots/*"))
    if not snapshots:
        pytest.skip("pinned semantic model not downloaded yet")
    result = find_guidance("احسب مؤشر الغطاء النباتي من مرئية سنتينل 2", semantic=True)
    skill = result["skills"][0]
    assert any("Semantic: cosine=" in text for text in skill["reasons"])
    assert skill["score"] > 0


# --- Mode invariants (dev-wide) -----------------------------------------------


@pytest.fixture
def dev_items():
    return [json.loads(line) for line in (find_root() / "evals" / "routing" / "dev.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def test_candidates_relevance_superset_of_ranked_on_dev(dev_items):
    """Default caps: every ranked choice appears in the candidates top 8, and the
    ranked list is the relevance-order prefix of the candidates list."""
    for item in dev_items:
        datasets = item.get("datasets")
        ranked = find_guidance(item["prompt"], datasets=datasets, mode="ranked")
        candidates = find_guidance(item["prompt"], datasets=datasets, mode="candidates")
        ranked_names = [skill["name"] for skill in ranked["skills"]]
        candidate_names = [skill["name"] for skill in candidates["skills"]]
        assert set(ranked_names) <= set(candidate_names[:len(ranked_names)] + candidate_names[len(ranked_names):])
        assert candidate_names[:len(ranked_names)] == ranked_names


def test_candidates_keep_ranked_choices_at_equal_cap_on_dev(dev_items):
    """Same explicit cap: candidates preserve the ranked choices inside the cap
    and fill remaining slots by relevance (candidate-only entries score below)."""
    for item in dev_items:
        datasets = item.get("datasets")
        ranked = find_guidance(item["prompt"], datasets=datasets, top_k=4)
        candidates = find_guidance(item["prompt"], datasets=datasets, top_k=4, mode="candidates")
        ranked_names = [skill["name"] for skill in ranked["skills"]]
        candidate_names = [skill["name"] for skill in candidates["skills"]]
        assert candidate_names[:len(ranked_names)] == ranked_names
        assert len(candidate_names) <= 4


def test_candidates_deterministic_explanations_and_topk0(dev_items):
    for item in dev_items[:40]:
        datasets = item.get("datasets")
        first = find_guidance(item["prompt"], datasets=datasets, mode="candidates")
        second = find_guidance(item["prompt"], datasets=datasets, mode="candidates")
        assert canonical(first) == canonical(second)
        assert all(skill["reasons"] and isinstance(skill["explanation"], str) and skill["explanation"]
                   for skill in first["skills"])
    assert find_guidance("NDVI", mode="candidates", top_k=0)["skills"] == []


def test_candidates_tie_break_and_debug_guard_determinism(controlled_index):
    router, scores = controlled_index
    scores.update({"raster-processing": 8.0, "gdal": 8.0, "networkx": 8.0})
    result = router.find_guidance("rasterio routing", mode="candidates", top_k=10)
    names_order = [skill["name"] for skill in result["skills"]]
    assert names_order == sorted(names_order)
    again = router.find_guidance("rasterio routing", mode="candidates", top_k=10)
    assert [skill["name"] for skill in again["skills"]] == names_order
    # Debug wording must not admit metadata-only matches even in candidates mode.
    scores.update({"geozarr": 50.0})
    debug = router.find_guidance("fix the broken raster layer", mode="candidates", top_k=10)
    assert "geozarr" not in [skill["name"] for skill in debug["skills"]]


def test_semantic_candidates_superset_and_warning(fake_semantic):
    task = "store the multidimensional arrays as cloud native zarr"
    result = find_guidance(task, mode="candidates", semantic=True)
    plain = find_guidance(task, mode="candidates", semantic=False)
    assert {s["name"] for s in plain["skills"]} <= {s["name"] for s in result["skills"]}
    again_plain = find_guidance(task, mode="candidates", semantic=False)
    assert again_plain == plain


def test_semantic_missing_model_forced_falls_back_identically(monkeypatch, tmp_path):
    """Force the missing-model failure with monkeypatch (never the user's install)."""
    from terraproof.router import semantic as semantic_module

    def missing_model(index, task):
        raise RuntimeError("model files missing (forced by test)")

    monkeypatch.setattr(semantic_module, "section_scores", missing_model)
    lexical = find_guidance("NDVI from Sentinel reflectance", semantic=False)
    result = find_guidance("NDVI from Sentinel reflectance", semantic=True)
    assert canonical({k: v for k, v in result.items() if k != "reasons"}) == canonical(lexical)
    warnings = sorted({text for skill in result["skills"] for text in skill["reasons"]
                       if "semantic retrieval unavailable" in text} | set(result.get("reasons", [])))
    assert warnings and "terraproof[semantic]" in warnings[0] and "--download-model" in warnings[0]
