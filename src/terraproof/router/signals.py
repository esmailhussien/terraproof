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

# Sourcing requires both an acquisition intent and a data object. A question about
# availability is an acquisition intent too; "find shortest path" is not one.
_SOURCING_VERB = re.compile(
    r"\b(?:find\w*|search\w*|look for|browse\w*|quer\w*|acquir\w*|fetch\w*|download\w*|sourc\w*|pull)\b"
    r"|\bwhere\b.{0,60}\b(?:get|obtain|access)\b"
    r"|\b(?:is|are) there\b.{0,60}\b(?:open|public|available|datasets?)\b"
    r"|(?:ابحث|دور علي|لاقي|نزل|تحميل|هات|جيب|احمل|منين|فين.{0,30}(?:بيانات|داتا|صور)|هل (?:توجد|هناك))")
_SOURCING_OBJECT = re.compile(
    r"\b(?:catalog|catalogue|stac|openstreetmap|osm|overture|shapefiles?|geojson|geopackage|dem|"
    r"scenes?|imagery|images?|photos?|satellite|landsat|sentinel|data|datasets?|footprints)\b"
    r"|(?:كتالوج|مصادر|مشاهد|مرئيه|مرئيات|صور|داتا|بيانات)")
_PROCESSING_WORDS = frozenset(tokenize(
    "mask decode reflectance cloud shadow scl harmonize composite calibrate process compute "
    "calculate statistics zonal index indices ndvi ndwi mndwi nbr dnbr evi savi classify "
    "classifier classification reproject resample clip join overlay centrality shortest path plot figure"))
_PROCESSING_TEXT = re.compile(r"قناع|سحب|فك|احسب|حساب|معالج|مؤشر|تصنيف|قص|ارسم|حلل")
_VECTOR_OPERATIONS = frozenset(tokenize("join overlay buffer dissolve intersection reproject clip"))
_IN_HAND = re.compile(
    r"\b(?:already|provided|given|local|loaded|in hand|on disk|(?:i|we) have)\b"
    r"|(?:عندي|عندنا|معايا|معاي|الموجود|بياناتي|داتتي)")

# Separate preprocessing evidence from index evidence: a calibrated raster or a
# statistic is not by itself an index request, nor is a sensor a decoding request.
_PREPROCESS_WORDS = frozenset(tokenize(
    "decode decoding mask masking cloud clouds shadow shadows scl reflectance harmonize "
    "harmonization composite compositing calibration calibrated"))
_PREPROCESS_TEXT = re.compile(
    r"\b(?:scene classification|qa_?pixel|boa_add_offset|surface reflectance|scale and offset)\b"
    r"|(?:قناع|سحب|غيوم|ظل|ظلال|فك|انعكاس|معامل القياس)")
_PREPROCESS_ACTION = re.compile(
    r"\b(?:decod\w*|mask\w*|harmoni[sz]\w*|calibrat(?:e|ion|ing)|composit(?:e|ing)|scl|qa_?pixel|boa_add_offset)\b"
    r"|قناع|فك|ازاله|شيل")
_CLASSIFICATION_WORDS = frozenset(tokenize("classify classifier classification"))
_ANALYSIS_WORDS = _CLASSIFICATION_WORDS | frozenset(tokenize(
    "statistics statistic statistical plot chart figure visualization"))
_NAMED_INDEX_WORDS = frozenset(tokenize("ndvi ndwi mndwi nbr dnbr evi savi"))
_INDEX_WORDS = _NAMED_INDEX_WORDS | frozenset(tokenize("index indices"))
_INDEX_TEXT = re.compile(r"مؤشر|\b(?:burn severity|spectral indices|vegetation index|water index)\b")
_SATELLITE_WORDS = frozenset(tokenize("satellite imagery sentinel landsat reflectance spectral"))
_NON_SPECTRAL_INDEX = re.compile(r"\b(?:spatial|database|pandas|dataframe|gist) index\b|فهرس مكاني")

# Separate affirmative intent wording for the four Phase 4 skills. Each is
# guarded off unless its own domain wording appears; incidental body matches
# (e.g. "random forest" inside an accuracy section) must not select them.
_SAR_WORDS = frozenset(tokenize(
    "sar backscatter sigma0 gamma0 beta0 speckle decibel radar grd slc polarization"))
_SAR_TEXT = re.compile(
    r"\b(?:sentinel[\s_-]*1|terrain corrections?|single look complex|"
    r"radiometric calibration|sigma nought|gamma nought|db values?)\b"
    r"|(?:رادار|ضجيج|استقطاب|سنتينل 1|تصحيح هندسي|باكان? سكاتر)")
_TIME_SERIES_WORDS = frozenset(tokenize("change temporal multitemporal breakpoint trend landtrendr ccdc bfast"))
_TIME_SERIES_TEXT = re.compile(
    r"\b(?:time[- ]?series|timeseries|change detection|change map|trend analysis|"
    r"seasonal composite|median composite|per[- ]date|gap fill\w*|temporal alignment)\b"
    r"|(?:سلاسل زمنيه|خط زمني|رصد التغير|كشف التغير|تغيرات|فترات زمنيه|اتجاه عام)")
_ACCURACY_WORDS = frozenset(tokenize("accuracy stratified confusion matrix"))
_ACCURACY_TEXT = re.compile(
    r"\b(?:accuracy assessments?|confusion matrix|error matrix|stratified\s+(?:random\s+)?"
    r"sampling|area[ -]adjusted|reference samples?|sample design|map accuracy|"
    r"(?:user|producer|overall)'\s?s accuracy|validation samples?)\b"
    r"|(?:مصفوفه.{0,12}التباس|دقه الخريط[هه]|معايره طبقيه|عينات مرجعيه|دقه التصنيف)")
_CLOUD_ACCESS_TEXT = re.compile(
    r"\b(?:stac|pystac|vsicurl|planetary computer|requester[\s_-]*pays|windowed "
    r"reads?|signed (?:asset )?urls?|http range requests?|rest api)\b"
    r"|(?:رابط موقع|قراءة نافذ|استعلام كتالوج|حاسوب الكوكب)")

# Web technologies or map-specific interaction, not a bare map/chart/dashboard.
_WEB_TECH = re.compile(r"\b(?:maplibre|mapbox|leaflet|deck gl|deckgl|spatial ui)\b")
_WEB_MAP = re.compile(
    r"\b(?:(?:web|interactive|slippy) (?:\w+ ){0,2}maps?|map dashboard|cartography web|dashboard.{0,30}\bmap\b)\b"
    r"|(?:خريط[هه].{0,15}(?:تفاعلي|ويب)|خرائط.{0,15}(?:تفاعلي|ويب)|dashboard.{0,30}خريط[هه])")

# A graph/chart homonym is not enough: require network, algorithm, or topology wording.
_GRAPH_WORDS = frozenset(tokenize(
    "network networkx centrality nodes edges topology route routing betweenness closeness connectivity"))
_GRAPH_TEXT = re.compile(r"\b(?:shortest paths?|community detection|graph analysis|network graph)\b")
_NEGATED_INTENT = re.compile(r"\b(?:no|not|without|never|مش|بدون|ليس|لا)(?:\s+(?:a|an|any|the))?\s*$")

# Symptom-style wording that points to a skill even when exact triggers are absent.
_VECTOR_QUALITY_WORDS = frozenset(tokenize("validity valid invalid repair records rows duplicate geometry"))
_CRS_WORDS = frozenset(tokenize("epsg wgs84 projection coordinate system"))
_STATISTICAL_WORDS = frozenset(tokenize("confidence interval statistical analysis difference between"))
_NETWORK_WORDS = frozenset(tokenize("travel time nearest facility road network routing connectivity"))
_GEOZARR_WORDS = frozenset(tokenize("multidimensional cube object storage publish store zarr"))


def _affirmed(pattern: re.Pattern, text: str) -> bool:
    """Ignore immediately negated capability requests, not arbitrary clause content."""
    return any(not _NEGATED_INTENT.search(text[:match.start()]) for match in pattern.finditer(text))


def data_signals(profiles: list[dict], terms: list[str], text: str = "") -> tuple[dict[str, list[tuple[float, str]]], set[str]]:
    """Return one-shot score evidence and intent guards (also respected by fallback).

    ``text`` is normalized task text. Guards cannot be outweighed by incidental
    BM25 matches; type-preference penalties remain soft for explicitly mixed work.
    """
    signals: dict[str, list[tuple[float, str]]] = defaultdict(list)
    guarded: set[str] = set()

    def boost(name: str, value: float, reason: str):
        signals[name].append((value, f"Dataset: {reason} {value:+.6f}"))

    def wording(name: str, value: float, reason: str):
        signals[name].append((value, f"Wording: {reason} {value:+.6f}"))

    def guard(name: str, reason: str):
        guarded.add(name)
        wording(name, -20.0, reason)

    term_set = set(terms)
    sourcing = bool(_affirmed(_SOURCING_VERB, text) and _SOURCING_OBJECT.search(text))
    processing = bool(_PROCESSING_WORDS & term_set or _PROCESSING_TEXT.search(text))
    graph = bool(_GRAPH_WORDS & term_set or _GRAPH_TEXT.search(text))
    preprocessing = bool(_PREPROCESS_WORDS & term_set or _PREPROCESS_TEXT.search(text))
    index_wording = bool(_INDEX_WORDS & term_set or _INDEX_TEXT.search(text))
    if _NON_SPECTRAL_INDEX.search(text) and not (_NAMED_INDEX_WORDS & term_set or _INDEX_TEXT.search(text)):
        index_wording = False
    if (sourcing or (_ANALYSIS_WORDS & term_set and not index_wording)) and not _PREPROCESS_ACTION.search(text):
        # Cloud-cover filters and calibrated input descriptions are not requests
        # to mask or decode scenes for a search, classification, statistic or plot.
        preprocessing = False
    rasters = [ds for ds in profiles if ds["kind"] == "raster"]
    vectors = [ds for ds in profiles if ds["kind"] == "vector"]
    stac = [ds for ds in profiles if ds["kind"] == "stac"]
    positional = rasters + vectors
    if not sourcing and (_CLASSIFICATION_WORDS & term_set) and (_SATELLITE_WORDS & term_set or rasters or stac):
        wording("geomaster", 3.0, "classification of satellite/raster data; remote-sensing analysis intent")
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
    if scaled and index_wording:
        boost("spectral-indices", 8.0, "scaled-integer reflectance raster with index wording; compute indices from decoded reflectance")
    elif index_wording and (_SATELLITE_WORDS & term_set or rasters) and not stac:
        wording("spectral-indices", 8.0, "satellite/raster data with index wording; choose spectral roles before computing")
    if stac:
        boost("satellite-preprocessing", 5.0, "STAC item; verify product level and calibration metadata")
        if index_wording:
            boost("spectral-indices", 8.0, "STAC item with index wording; compute indices from decoded reflectance")
        if sourcing:
            boost("geospatial-data-discovery", 8.0, "STAC item with catalog search wording; retain catalog, asset and acquisition provenance")
        elif not processing and not _IN_HAND.search(text):
            boost("geospatial-data-discovery", 8.0, "STAC item; retain catalog, asset and acquisition provenance")
    if any(re.search(r"sentinel[\s_-]*2|landsat", str(ds.get("collection", "")), re.I) for ds in stac):
        boost("satellite-preprocessing", 10.0, "Sentinel-2/Landsat STAC collection; check reflectance encoding and QA masks")
    if preprocessing:
        wording("satellite-preprocessing", 3.0, "decoding, masking or reflectance preparation intent")
    if not preprocessing and not scaled and (not stac or (processing and not index_wording)):
        guard("satellite-preprocessing", "no decoding, cloud/QA masking, reflectance or calibration need")
    if not index_wording:
        guard("spectral-indices", "no spectral-index computation or interpretation intent")
    if not (_affirmed(_WEB_TECH, text) or _affirmed(_WEB_MAP, text)):
        guard("geospatial-frontend", "no interactive web-map interface intent")
    if sourcing:
        wording("geospatial-data-discovery", 10.0, "data acquisition or availability question with a data object")
        # Formats identify the desired download, not a vector operation. Preserve
        # explicit processing and profiles for genuine search-then-analyze tasks.
        if not (_VECTOR_OPERATIONS & term_set) and not vectors and not re.search(r"\b(?:geopandas|geodataframe)\b", text):
            guard("geopandas", "data search without vector processing or a vector input")
    elif processing or graph or _IN_HAND.search(text):
        guard("geospatial-data-discovery", "data already in hand for processing or analysis; no catalog search needed")
    if graph and (not sourcing or processing):
        wording("networkx", 3.0, "network/routing analysis intent; use graph algorithms")
    if "routing" in term_set and not sourcing:
        wording("networkx", 4.0, "routing intent")

    # Symptom-style indirect signals (dev-only tuning, kept narrow to avoid over-selection).
    if _VECTOR_QUALITY_WORDS & term_set and ("join" in term_set or "shapefil" in term_set
                                              or "record" in term_set or "row" in term_set
                                              or (("valid" in term_set or "validity" in term_set or "repair" in term_set)
                                                  and ("polygon" in term_set or "geometry" in term_set))):
        wording("vector-quality", 4.0, "geometry or record-quality concern")
    if not rasters and (_CRS_WORDS & term_set) and "reproject" not in term_set:
        wording("crs-and-units", 5.0, "CRS or projection wording without a raster input")
    if rasters and ("reproject" in term_set or "reprojection" in term_set) and (_CRS_WORDS & term_set):
        wording("crs-and-units", 6.0, "raster reprojection to a named CRS")
    if rasters and "geotiff" in term_set and ("crs" in term_set or "alignment" in term_set):
        wording("crs-and-units", 5.0, "GeoTIFF CRS/alignment validation wording")
    if _STATISTICAL_WORDS & term_set and ("confidence" in term_set or "interval" in term_set
                                          or "statistical" in term_set or "difference" in term_set):
        wording("statistical-analysis", 6.0, "statistical inference wording")
    if (not graph and not sourcing and _NETWORK_WORDS & term_set
            and ("travel" in term_set or "nearest" in term_set
                 or "road" in term_set or "network" in term_set)):
        wording("networkx", 4.0, "network routing or accessibility wording")
    if (_GEOZARR_WORDS & term_set and ("multidimensional" in term_set or "cube" in term_set)
            and "geozarr" not in term_set and "zarr" not in term_set):
        wording("geozarr", 8.0, "multidimensional array or cloud storage wording")

    # Affirmative intent guards for the four Phase 4 skills: only their own
    # domain wording (English tokens, Arabic expansions or regex phrases) can
    # keep them selectable. Data evidence may affirm SAR intent specifically.
    sar_intent = bool(_SAR_WORDS & term_set or _SAR_TEXT.search(text))
    time_series_intent = bool(_TIME_SERIES_WORDS & term_set or _TIME_SERIES_TEXT.search(text))
    accuracy_intent = bool(_ACCURACY_WORDS & term_set or _ACCURACY_TEXT.search(text))
    cloud_intent = bool(_CLOUD_ACCESS_TEXT.search(text) or "stac" in str(
        " ".join(str(ds.get("collection", "")) for ds in stac)).lower())
    if stac and any(re.search(r"sentinel[\s_-]*1", str(ds.get("collection", "")), re.I) for ds in stac):
        sar_intent = True
        wording("sar-basics", 8.0, "Sentinel-1 STAC collection; SAR calibration and terrain correction wording")
    if not sar_intent:
        guard("sar-basics", "no SAR, backscatter, speckle or Sentinel-1 wording")
    if not accuracy_intent:
        guard("accuracy-assessment", "no accuracy, sampling design or confusion-matrix wording")
    if not time_series_intent:
        guard("time-series-and-change", "no time-series, temporal or change-detection wording")
    if not cloud_intent:
        guard("stac-and-cloud-access", "no STAC search or cloud-access wording")

    # "Sum the parcel areas in hectares" is a CRS/units question, not a
    # geometry-quality concern; incidental body wording like "parcel area" in a
    # topology section must not out-rank the CRS rule either. Narrow aggregate
    # wording ("sum") only; count/total/area tasks keep the quality audit.
    _quality_concern = bool((_VECTOR_QUALITY_WORDS & term_set)
                            - {"polygon", "polygon vector"} - {"geometry", "geometri"})
    if (metric and any((ds.get("crs") or {}).get("is_geographic")
                       or (ds.get("crs") or {}).get("horizontal_kind") == "geographic"
                       for ds in positional)
            and not _quality_concern and not _PREPROCESS_ACTION.search(text)
            and "sum" in term_set):
        wording("vector-quality", -6.0, "aggregate sum wording; the parcel-area quality body match is incidental here")
    return signals, guarded


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
