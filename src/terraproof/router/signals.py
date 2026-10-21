"""Explicit profile- and wording-based boosts. Rules fire once per request, not once per band."""

from __future__ import annotations

import re
from collections import defaultdict

from .text import normalize, tokenize

RASTER_SKILLS = ("raster-processing", "gdal", "geozarr", "satellite-preprocessing", "spectral-indices", "geomaster")
VECTOR_SKILLS = ("geopandas", "vector-quality", "geoparquet-validation", "design-postgis-tables")

# Unit and proximity wording (English tokens plus Arabic lexicon expansions) that turns a
# geographic horizontal CRS into a degrees-are-not-metres trap.
_METRIC_WORDS = frozenset(tokenize(
    "area distance buffer length metre meter metric perimeter kilometre kilometres kilometer "
    "kilometers km hectare hectares acre acres mile miles m2 proximity"))
_METRIC_NEAR = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:m|km|م)\b")

# Intent wording for STAC item profiles: catalog search vs. processing an item in hand.
_SOURCING_VERB = re.compile(
    r"\b(?:find\w*|search\w*|look for|list\w*|browse\w*|quer\w*|acquir\w*|fetch\w*|download\w*|sourc\w*)\b"
    r"|(?:ابحث|دور|لاقي|نزل|تحميل|هات|جيب)")
_SOURCING_OBJECT = re.compile(
    r"\b(?:catalog|catalogue|stac|openstreetmap|osm|overture|shapefile|dem|scenes?|imagery|images?|"
    r"photos?|satellite|landsat|sentinel|data)\b"
    r"|(?:كتالوج|مصادر|مشاهد|مرئيه|مرئيات|صور|داتا|بيانات)")
_PROCESSING_TEXT = re.compile(
    r"\b(?:mask\w*|decod\w*|reflectance|cloud\w*|shadow\w*|scl|qa\w*|harmoni[sz]\w*|composit\w*|"
    r"calibrat\w*|process\w*|comput\w*|calculat\w*|statistic\w*|zonal|indices?|ndvi|ndwi|mndwi|nbr|"
    r"dnbr|evi|savi)\b"
    r"|(?:قناع|سحب|غيوم|ظل|ظلال|فك|انعكاس|معامل|احسب|حساب|معالج|مؤشر)")

# Satellite preprocessing and spectral indices need decoding, cloud/QA masking, reflectance
# or index wording, or scaled-integer/STAC data signals; a bare imagery/statistics/
# classification/raster mention is not evidence.
_SATELLITE_WEAK = frozenset(tokenize(
    "satellite imagery image images photograph photographs photo photos statistics statistic "
    "statistical classify classification classified classifying raster rasters remote sensing"))
_SATELLITE_STRONG = frozenset(tokenize(
    "decode decoding decoded mask masking masked cloud clouds cloudless shadow shadows scl "
    "reflectance harmonize harmonized harmonization composite composites compositing "
    "calibration calibrated ndvi ndwi mndwi nbr dnbr evi savi index indices"))
_SATELLITE_STRONG_TEXT = re.compile(
    r"\b(?:scene classification|qa_?pixel|boa_add_offset|l2a|level[\s_-]*2|collection[\s_-]*2|"
    r"surface reflectance|scale and offset)\b"
    r"|(?:قناع|سحب|غيوم|ظل|ظلال|فك|انعكاس|معامل القياس|مؤشر)")

# Index wording that, with satellite reflectance profiles, surfaces spectral-indices.
_INDEX_WORDS = frozenset(tokenize("index indices ndvi ndwi mndwi nbr dnbr evi savi"))
_INDEX_TEXT = re.compile(r"مؤشر")

# Static or print figure wording is not an interactive web-map interface.
_STATIC_FIGURE = frozenset(tokenize(
    "paper journal png pdf publication print printing static multi panel figure matplotlib "
    "seaborn colorblind palette"))
_WEB_FRONTEND = frozenset(tokenize("web maplibre interactive dashboard deckgl zoom popup basemap"))
_STATIC_FIGURE_TEXT = re.compile(r"مجله|ورقه بحثيه|للنشر|مطبوع")

# Graph/network analysis wording is not a data sourcing task.
_GRAPH_WORDS = frozenset(tokenize(
    "network graph centrality shortest path nodes edges community detection topology route "
    "routing betweenness closeness"))
_GRAPH_TEXT = re.compile(r"شبك[هة]|مسار|عقد|حواف|مركزيه|اقصر")
_GRAPH_SOURCING = re.compile(
    r"\b(?:download\w*|catalog|catalogue|stac|openstreetmap|osm|overture|shapefile|dem|scenes?|"
    r"source|sources|sourcing|acquir\w*|browse\w*|fetch\w*|data sources?|find data|find scenes|"
    r"find images|find imagery|find satellite|find gis)\b"
    r"|(?:كتالوج|مصادر|مشاهد|بيانات مفتوحه|صور فضائيه|نزل|تحميل)")


def data_signals(profiles: list[dict], terms: list[str], text: str = "") -> dict[str, list[tuple[float, str]]]:
    """One-shot boosts from dataset profiles and task wording; ``text`` is normalized task text."""
    signals: dict[str, list[tuple[float, str]]] = defaultdict(list)

    def boost(name: str, value: float, reason: str):
        signals[name].append((value, f"Dataset: {reason} {value:+.6f}"))

    def wording(name: str, value: float, reason: str):
        signals[name].append((value, f"Wording: {reason} {value:+.6f}"))

    rasters = [ds for ds in profiles if ds["kind"] == "raster"]
    vectors = [ds for ds in profiles if ds["kind"] == "vector"]
    stac = [ds for ds in profiles if ds["kind"] == "stac"]
    positional = rasters + vectors
    if any(not ds.get("crs") for ds in positional):
        boost("crs-and-units", 10.0, "missing CRS; establish the source coordinate reference system")
    metric = bool(_METRIC_WORDS & set(terms)) or bool(_METRIC_NEAR.search(text))
    if metric and any((ds.get("crs") or {}).get("is_geographic")
                      or (ds.get("crs") or {}).get("horizontal_kind") == "geographic" for ds in positional):
        boost("crs-and-units", 12.0, "geographic horizontal CRS with metric wording; do not measure in degrees")
    if rasters:
        boost("raster-processing", 6.0, "raster input; inspect masks, nodata, grid and dtype")
        boost("gdal", 2.0, "raster input supports GDAL raster operations")
        if not vectors:
            for name in VECTOR_SKILLS:
                boost(name, -4.0, "raster rather than vector input")
    if vectors:
        boost("geopandas", 6.0, "vector input; use vector geometry/attribute operations")
        boost("vector-quality", 5.0, "vector input; audit geometry validity and record preservation")
        if not rasters and not stac:
            for name in RASTER_SKILLS:
                boost(name, -4.0, "vector rather than raster input")
    if len(rasters) > 1:
        boost("raster-processing", 9.0, "multiple rasters; verify complete grid alignment before combining")
    scaled = any(re.fullmatch(r"u?int\d*|byte", str(band.get("dtype", "")).lower())
                 and (band.get("scale") not in (None, 1, 1.0) or band.get("offset") not in (None, 0, 0.0))
                 for ds in rasters for band in (ds.get("bands") or []))
    if scaled:
        boost("satellite-preprocessing", 11.0, "integer raster has non-identity scale/offset; review physical-value decoding (not proof of satellite origin)")
    index_wording = bool(_INDEX_WORDS & set(terms)) or bool(_INDEX_TEXT.search(text))
    if scaled and index_wording:
        boost("spectral-indices", 8.0, "scaled-integer reflectance raster with index wording; compute indices from decoded reflectance")
    if stac:
        boost("satellite-preprocessing", 5.0, "STAC item; verify product level and calibration metadata")
        if index_wording:
            boost("spectral-indices", 8.0, "STAC item with index wording; compute indices from decoded reflectance")
        if _SOURCING_VERB.search(text) and _SOURCING_OBJECT.search(text):
            boost("geospatial-data-discovery", 8.0, "STAC item with catalog search wording; retain catalog, asset and acquisition provenance")
        elif _PROCESSING_TEXT.search(text):
            wording("geospatial-data-discovery", -18.0, "STAC item already in hand for processing; no catalog search needed")
        else:
            boost("geospatial-data-discovery", 8.0, "STAC item; retain catalog, asset and acquisition provenance")
    if any(re.search(r"sentinel[\s_-]*2|landsat", str(ds.get("collection", "")), re.I) for ds in stac):
        boost("satellite-preprocessing", 10.0, "Sentinel-2/Landsat STAC collection; check reflectance encoding and QA masks")
    if (_SATELLITE_WEAK & set(terms)) and not (_SATELLITE_STRONG & set(terms) or _SATELLITE_STRONG_TEXT.search(text)) and not scaled and not stac:
        wording("satellite-preprocessing", -20.0,
                 "imagery/statistics/classification/raster mention without decoding, cloud/QA masking, reflectance or index evidence")
        wording("spectral-indices", -20.0,
                 "imagery/statistics/classification/raster mention without reflectance or index evidence")
    if (_STATIC_FIGURE & set(terms) or _STATIC_FIGURE_TEXT.search(text)) and not (_WEB_FRONTEND & set(terms)):
        wording("geospatial-frontend", -16.0, "static or print figure wording; not an interactive web map interface")
    if (_GRAPH_WORDS & set(terms) or _GRAPH_TEXT.search(text)) and not _GRAPH_SOURCING.search(text):
        wording("geospatial-data-discovery", -16.0, "graph/network analysis wording; not a data sourcing task")
    return signals


def dataset_summary(ds: dict) -> dict:
    crs = ds.get("crs") or {}
    label = f"EPSG:{crs['epsg']}" if crs.get("epsg") is not None else crs.get("horizontal_kind", "unknown CRS")
    if ds["kind"] == "vector":
        types = ", ".join(ds.get("geometry_types") or []) or "unspecified geometry"
        summary = f"{ds.get('feature_count', 'unknown')} features; {types}; {label}"
    elif ds["kind"] == "raster":
        dtypes = ", ".join(sorted({str(band.get('dtype', 'unknown')) for band in (ds.get('bands') or [])}))
        summary = f"{ds.get('band_count', 'unknown')} bands; {dtypes or 'unknown dtype'}; {label}"
    else:
        summary = f"STAC collection: {ds.get('collection') or 'unknown'}; item: {ds.get('id') or 'unknown'}"
    return {"path": ds.get("path"), "kind": ds["kind"], "summary": summary}


def process_skills(task: str) -> list[str]:
    text = normalize(task)
    result = []
    if re.search(r"\b(build\w*|creat\w*|design\w*|scaffold\w*|brainstorm\w*)\b|\b(ابني|انشئ|صمم|بناء|تصميم)\b", text):
        result.extend(["brainstorming", "writing-plans"])
    elif re.search(r"\b(plan\w*|roadmap)\b|\b(خطه|خطط)\b", text):
        result.append("writing-plans")
    if re.search(r"\b(fix\w*|debug\w*|error\w*|bug\w*|fail\w*|broken|crash\w*|exception\w*)\b|\b(اصلح|اصلاح|صلح|مشكله|خطا|غلط|بيبوظ|مشكله)\b", text):
        result.append("systematic-debugging")
    return result + ["verification"]
