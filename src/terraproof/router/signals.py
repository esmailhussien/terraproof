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
    r"|\b(?:public|open|free) (?:data )?sources?\b|\bsources? of\b|\b(?:which|what) (?:open|public|free)\b"
    r"|(?:ما هي|ايه|اي) .{0,40}(?:مفتوح|متاح|مجاني)"
    r"|(?:ابحث|دور(?: لي| لنا)? علي|لاقي|نزل|تحميل|هات|جيب|احمل|منين|مصدر|فين.{0,30}(?:بيانات|داتا|صور)|هل (?:توجد|هناك))")
_SOURCING_OBJECT = re.compile(
    r"\b(?:catalog|catalogue|stac|openstreetmap|osm|overture|shapefiles?|geojson|geopackage|dem|"
    r"scenes?|imagery|images?|photos?|photographs?|satellite|landsat|sentinel|data|datasets?|footprints|"
    r"rivers?|boundar\w*|centre ?lines?|center ?lines?|coastlines?|buildings?|land cover)\b"
    r"|(?:انهار|حدود|مباني|غطاء ارضي|كتالوج|مصادر|مشاهد|مرئيه|مرئيات|صور|داتا|بيانات|ارتفاعات|بصمات المباني)")
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
    r"\b(?:scene classification|qa_?pixel|boa_add_offset|surface reflectance|scale and offset|scale factors?)\b"
    r"|(?<![\u0621-\u064a])(?:[وفبلك]{0,2}(?:ال)?)(?:قناع|سحب|غيوم|ظل|ظلال|فك|انعكاس)(?:يه|ي|ه|ها|ات)?(?![\u0621-\u064a])"
    r"|(?:معامل القياس|معامل.{0,25}ازاحه|ازاحه.{0,25}معامل)")
_PREPROCESS_ACTION = re.compile(
    r"\b(?:decod\w*|mask\w*|harmoni[sz]\w*|calibrat(?:e|ion|ing)|composit(?:e|ing)|scl|qa_?pixel|boa_add_offset)\b"
    r"|(?<![\u0621-\u064a])(?:[وفبلك]{0,2}(?:ال)?)(?:قناع|فك|ازاله|شيل)(?![\u0621-\u064a])")
_CLASSIFICATION_WORDS = frozenset(tokenize("classify classifier classification"))
_ANALYSIS_WORDS = _CLASSIFICATION_WORDS | frozenset(tokenize(
    "statistics statistic statistical plot chart figure visualization"))
_NAMED_INDEX_WORDS = frozenset(tokenize("ndvi ndwi mndwi nbr dnbr evi savi ndbi ndmi ndsi gndvi msavi ndre bsi nbr2"))
_INDEX_WORDS = _NAMED_INDEX_WORDS | frozenset(tokenize("index indices"))
_INDEX_TEXT = re.compile(r"مؤشر|\b(?:burn severity|spectral indices|vegetation index|water index)\b")
# Named index phrases identify a spectral index without needing an acronym.
_NAMED_INDEX_TEXT = re.compile(
    r"\b(?:(?:normali[sz]ed )?burn ratio|normali[sz]ed difference \w+ index|vegetation index|water index)\b"
    r"|نسبه الاحتراق|مؤشر (?:ال)?(?:غطاء )?(?:ال)?نبات|مؤشر (?:ال)?(?:مياه|ماء)")
# Inference wording: a comparison that asks whether a difference is real.
_STATISTICAL_TEXT = re.compile(
    r"\btest(?:ing)? whether\b|\bdiffers?\b(?: \w+){0,2} between\b|\bsignifican\w*|\bstatistically\b"
    r"|\bcompare (?:the )?(?:mean|average)s?\b|\bappropriate (?:statistical )?test\b"
    r"|دال[هة]? احصائي|(?:بي|ي)ختلف بين|باختبار|اختبار (?:احصائي|مناسب|فرضي)|قارن (?:بين )?متوسط|"
    r"ارتباط معنوي|معنوي")
# Counting or summarising one vector layer by the polygons of another.
_VECTOR_PER_POLYGON = re.compile(
    r"\b(?:count\w*|density|densities|totals?|sums?) (?:\w+ ){0,3}(?:per|in each|within each|inside each)\b"
    r"|\bpoints? in polygons?\b|(?:عدد|كثاف[هت]|مجموع|اجمالي) .{0,25}(?:في )?لكل|عدد .{0,25}(?:في )?كل")
_GDAL_CONTEXT = re.compile(
    r"\b(?:gdal\w*|ogr\w*|rasterio|rasters?|geotiffs?|tiff?|cogs?|cloud optimi[sz]ed|vrt|overviews?|warp\w*|"
    r"command line|cli|ecw|jp2|jpeg2000|mrsid|hdf\d?|netcdf|grib|nodata|compression|dem|dsm|dtm|elevation|"
    r"tiles?|mosaic\w*|imagery|bands?|pixels?|resampl\w*|format conversions?|convert\w*|translat\w*|"
    r"file ?gdb|virtual)\b"
    r"|راستر|تيف|سطر الاوامر|بلاطات|ارتفاعات|مرئي|صور|نطاقات|بكسل|جي ?دال|تحويل|صيغ")
_RASTER_CLI = re.compile(r"\b(?:geotiff|raster|dem|cog)\b.{0,60}\b(?:command line|cli|gdal\w*|cutline)\b"
                         r"|\b(?:command line|cli|gdal\w*|cutline)\b.{0,60}\b(?:geotiff|raster|dem|cog)\b"
                         r"|geotiff.{0,60}سطر الاوامر|سطر الاوامر.{0,60}geotiff")
# Vector-quality symptoms and CRS-mismatch symptoms phrased without skill keywords.
_VECTOR_DEFECT_TEXT = re.compile(
    r"\b(?:zero[- ]length|degenerate|stored backwards|reversed (?:lines?|direction)|self[- ]intersect\w*|"
    r"slivers?|dangles?|duplicate (?:features|geometr\w*|lines|points|polygons)|empty geometr\w*|"
    r"clean (?:up )?(?:the )?(?:layer|geometr\w*))\b"
    r"|طولها صفر|بالعكس|(?:نضف|تنظيف) (?:ال)?طبق|شظايا|مضلعات? (?:\w+ ){0,3}(?:مكرر|فاضي|فارغ)")
_CRS_SYMPTOM_TEXT = re.compile(
    r"\b(?:do(?:es)?n ?t|do(?:es)? not|never) (?:line up|overlap|align|match up|coincide)\b|\bmisaligned layers?\b"
    r"|طبق.{0,30}(?:مش|مو|ليست|لا) (?:فوق بعض|متطابق|راكب)")
# Statistical-figure wording that does not depend on the generic 'plot' trigger.
_VIZ_TEXT = re.compile(
    r"\b(?:box ?plots?|violin(?: plots?)?|scatter ?plots?|for the (?:paper|journal|manuscript)|readable fonts?|"
    r"axis labels?)\b|مخطط صندوقي|للورق[هة] البحثي|للمجل[هة]|للنشر")
# Phrases whose spatial-sounding words belong to another field.
_HOMONYM_VETO = re.compile(
    r"\b(?:vector graphics|raster graphics|graphic design|logo design|designing a logo|buffer overflow|"
    r"spatial (?:reasoning|awareness)|aptitude tests?|levenshtein|edit distance|string distance|css grid|"
    r"grid layout|satellite (?:tv|dish)|tv package)\b"
    r"|\bin psychology\b|رسومات (?:ال)?(?:راستر|فيكتور)|تصميم (?:ال)?شعار|تفكير مكاني|اختبار قدرات|باقه دش|علم النفس")
# Explicit vector analysis keeps GeoPandas despite a GDAL/OGR command in the same request.
_VECTOR_ANALYSIS = re.compile(r"\b(?:geopandas|geodataframe|sjoin|spatial join|dissolve|attribute joins?)\b"
                              r"|جيوبانداز|ربط مكاني")
_VECTOR_LAYER = re.compile(r"\b(?:layers?|polygons?|districts?|boundar\w*|shapefiles?|geopackage)\b"
                           r"|طبق|مضلع|حدود|(?<![ء-ي])(?:ال)?(?:حي|احياء|محافظ\w*)(?![ء-ي])")
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
    r"|\b(?:between|from) (?:19|20)\d\d (?:and|to|until|through) (?:19|20)\d\d\b"
    r"|\bbefore and after\b|\bpre (?:and|vs) post\b|\b(?:image|scene|landsat|sentinel|time) stacks?\b"
    r"|\b(?:year|date) (?:each|every) (?:pixel|cell|field)\b|\bloss year\b"
    r"|(?:سلاسل زمنيه|سلسله (?:زمنيه|شهريه|سنويه)|خط زمني|رصد التغير|كشف التغير|تغيرات|فترات زمنيه|اتجاه عام|"
    r"قبل وبعد|مكدس|سنه فقدان|"
    r"مركب(?:ات)? (?:\w+ ){0,2}(?:ال)?(?:شهري|سنوي|موسمي)|عبر السنين|علي مدار (?:ال)?سن|موسمي|ازاله الغابات|التغير في|بين (?:19|20)\d\d و ?(?:19|20)\d\d|"
    r"من (?:19|20)\d\d (?:لحد|حتي|الي|ل) ?(?:19|20)\d\d|سنه (?:ال)?تغير)")
_ACCURACY_WORDS = frozenset(tokenize("accuracy stratified confusion matrix"))
_ACCURACY_TEXT = re.compile(
    r"\b(?:accuracy assessments?|confusion matrix|error matrix|stratified\s+(?:random\s+)?"
    r"sampling|area[ -]adjusted|reference samples?|sample design|map accuracy|"
    r"(?:user|producer|overall)'\s?s accuracy|validation (?:samples?|points?|sites?)|"
    r"(?:assess\w*|evaluat\w*) (?:\w+ ){0,4}(?:map|classification))\b"
    r"|(?:مصفوفه.{0,12}التباس|دقه الخريط[هه]|معايره طبقيه|عينات مرجعيه|دقه التصنيف|"
    r"عين(?:ه|ات) طبقي|عين[هة] تحقق|تحقق مستقل|نقا?ط[هه]? تحقق|تقييم (?:ال)?دقه|للتحقق من (?:ال)?خريط)")
_CLOUD_ACCESS_TEXT = re.compile(
    r"\b(?:stac|pystac|vsicurl|planetary computer|requester[\s_-]*pays|windowed "
    r"reads?|signed (?:asset )?urls?|http range requests?|s3|gcs|azure blob)\b"
    r"|(?:جزء|نافذه) .{0,25}cog|cog .{0,25}(?:جزء|نافذه)"
    r"|(?:رابط موقع|روابط موقعه|قراءه (?:نافذ|النوافذ)|استعلام كتالوج|حاسوب الكوكب)")

# Web technologies or map-specific interaction, not a bare map/chart/dashboard.
_WEB_TECH = re.compile(r"\b(?:maplibre|mapbox|leaflet|openlayers|cesium|kepler gl|deck gl|deckgl|spatial ui)\b"
                       r"|\bmaps?\b.{0,40}\b(?:clicks?|hover\w*|popups?|tooltips?|highlight\w*)\b"
                       r"|خريط.{0,40}(?:يضغط|ضغط|كليك|تتظلل|تلميح|منبثق)")
_WEB_MAP = re.compile(
    r"\b(?:(?:web|interactive|slippy|browser) (?:\w+ ){0,2}maps?|map dashboard|cartography web|dashboard.{0,30}\bmap\b|"
    r"maps? in the browser|basemap (?:switcher|toggle)|toggle (?:\w+ ){0,5}basemaps?)\b"
    r"|خريط.{0,20}(?:علي )?(?:ال)?متصفح"
    r"|(?:خريط[هه].{0,30}(?:تفاعلي|ويب)|خرائط.{0,30}(?:تفاعلي|ويب)|dashboard.{0,30}خريط[هه])")

# A graph/chart homonym is not enough: require network, algorithm, or topology wording.
_GRAPH_WORDS = frozenset(tokenize(
    "network networkx centrality nodes edges topology route routing betweenness closeness connectivity"))
_GRAPH_TEXT = re.compile(r"\b(?:shortest paths?|community detection|graph analysis|network graph)\b")
# Connectivity failure of a road or utility network: which links isolate which places.
_CONNECTIVITY_TEXT = re.compile(
    r"\b(?:roads?|links?|bridges?|streets?|pipes?|lines?|edges?)\b.{0,60}\b(?:cut off|isolat\w*|unreachable|disconnect\w*)\b"
    r"|\b(?:cut off|isolat\w*|unreachable|disconnect\w*)\b.{0,60}\b(?:roads?|links?|bridges?|streets?|network)\b"
    r"|\b(?:upstream|downstream)\b.{0,40}\b(?:segments?|reaches|nodes?|links?|stations?)\b"
    r"|شبكه .{0,20}(?:النهر|الانهار|مقاطع|المجاري)"
    r"|(?:طرق|طريق|شبكه|كوبري|جسر|وصلات).{0,60}(?:تعزل|معزول|انقطع|مقطوع|منفصل)"
    r"|(?:تعزل|معزول|انقطع|مقطوع|منفصل).{0,60}(?:طرق|طريق|شبكه|كوبري|جسر)")
_NEGATED_INTENT = re.compile(r"\b(?:no|not|without|never|مش|بدون|ليس|لا)(?:\s+(?:a|an|any|the))?\s*$")

# Homonyms in ordinary software/copy requests must not gain domain intent from
# BM25 prose. Explicit domain tools/objects still win for mixed requests.
_NON_DOMAIN_CONTEXT = re.compile(
    r"\b(?:api|rest|express|fastapi|postgresql|javascript|react|css|dockerfile|"
    r"login|password|shopping|invoice|birthday|recipe|detective|fictional|logo|"
    r"library loans|unit tests|array map|network request|chat application|tcp|dns|tls|websocket)\b|"
    r"(?:كلمه السر|تسجيل الدخول|كلمه المرور|سله المشتريات|شعار|فاتوره|وصفه|قصه|مكتبه)")
_DOMAIN_ANCHORS = frozenset(tokenize(
    "geospatial spatial gis postgis gdal gdalinfo gdalwarp gdal_translate gdalbuildvrt gdaladdo "
    "geopandas geodataframe geoparquet geozarr zarr raster rasterio geotiff cog vector polygon "
    "geometry shapefile geojson geopackage crs epsg projection terrain elevation dem lidar "
    "watershed hydrology satellite landsat sentinel sar radar backscatter stac ndvi ndwi "
    "mndwi nbr dnbr spectral reflectance maplibre mapbox leaflet deckgl networkx centrality "
    "betweenness anova regression hypothesis statistical matplotlib seaborn cartography"))


def non_domain_request(text: str, terms: list[str]) -> bool:
    """Reject a known non-domain task, unless it also names a domain capability."""
    return bool(_NON_DOMAIN_CONTEXT.search(text) and not (_DOMAIN_ANCHORS & set(terms)))


# Positive domain gate. Text is normalized task text plus Arabic lexicon
# expansions, so Arabic domain nouns arrive here as English retrieval terms.
# Strong anchors are unambiguous geospatial, remote-sensing or scientific-analysis
# vocabulary; bare homonyms (network, map, projection, layer, satellite, index,
# resolution, buffer, vector) are not.
_STRONG_DOMAIN = re.compile(
    r"\b(?:geo(?:pandas|dataframe|series|parquet|zarr|json|tiffs?|package|cod\w*|referenc\w*|spatial\w*|"
    r"graphic(?:al)?|server|database|desic|ids?|hash\w*|fenc\w*)|gis|qgis|arcgis|postgis|st_\w+|srid|gist|gdal\w*|ogr\w*|rasterio|shapely|fiona|pyproj|"
    r"xarray|rioxarray|zarr|netcdf|hdf5?|grib|rasters?|cog|cogs|cloud optimi[sz]ed|shapefiles?|shp|"
    r"gpkg|kml|kmz|crs|epsg|wgs ?84|nad ?83|utm|datum|srs|reproject\w*|projected|equal area|"
    r"map projections?|coordinate (?:reference )?systems?|latitude|longitude|lat lon|lon lat|"
    r"basemaps?|choropleth|cartograph\w*|slippy|vector tiles?|tile server|maplibre|mapbox|leaflet|"
    r"openlayers|cesium|deck gl|deckgl|kepler gl|"
    r"satellites? (?:imagery|images?|scenes?|data|sensors?|missions?|products?|bands?|observations?)|"
    r"remote sensing|earth observation|imagery|multispectral|hyperspectral|reflectance|"
    r"spectral (?:index|indices|bands?|signatures?)|near infrared|nir|swir|red edge|(?:water|vegetation) index|ndvi|ndwi|mndwi|ndbi|nbr|dnbr|evi|savi|"
    r"sentinel ?[1-3]|landsat|modis|viirs|planetscope|worldview|copernicus|usgs|"
    r"earth ?engine|stac|pystac\w*|stackstac|odc|planetary computer|vsicurl|"
    r"sar|insar|backscatter\w*|sigma0|gamma0|speckle|polarimetr\w*|lidar|point clouds?|"
    r"dem|dsm|dtm|digital elevation|elevation models?|terrain (?:models?|analysis|correction)|hillshade|watersheds?|hydrolog\w*|flow accumulation|"
    r"land (?:cover|use)|lulc|nodata|resampl\w*|orthophoto\w*|orthomosaic\w*|aerial (?:imagery|photo\w*)|"
    r"polygons?|polylines?|multipolygons?|parcels?|cadastr\w*|census tracts?|zonal|spatially|spatial (?:join|index|analysis|data|database|quer|resolution|autocorrelation|"
    r"statistic|interpolat|extent|referenc|distribut|pattern|weight|unit|cluster|model|scale|filter|predicate|"
    r"operation|overlay|relationship)\w*|"
    r"geometr(?:y|ies) (?:column|validity|repair|types?)|invalid geometr\w*|make_valid|"
    r"openstreetmap|osm|overture|footprints?|road networks?|street networks?|river networks?|"
    r"isochrones?|catchments?|travel time|nearest facilit\w*|"
    r"networkx|centrality|betweenness|closeness|shortest paths?|dijkstra|community detection|"
    r"nodes? and edges|graph (?:analysis|algorithms?|theory)|"
    r"anova|t ?test|chi square|mann whitney|wilcoxon|kruskal|p values?|hypothesis tests?|"
    r"confidence intervals?|effect sizes?|statistical(?:ly)? (?:significan\w*|tests?|power|analysis|inference)|"
    r"statistical|kriging|variogram|interpolat\w*|moran\w*|autocorrelation|"
    r"matplotlib|seaborn|plotly|colou?rbars?|colou?r ?maps?|viridis|colou?rblind\w*|"
    r"publication (?:figures?|maps?)|journal figures?|multi ?panel|"
    r"confusion matrix|error matrix|accuracy assessments?|stratified\w*|reference samples?|"
    r"change detection|time series|burn severity|flood mapping|cloud mask\w*|cloud cover|"
    r"bands? (?:math|ratio|stack)|tiles? (?:mosaic|grid)|mosaic\w*|composites?|compositing|"
    r"vegetation (?:cover|health|index|indices|loss|change)|data ?cubes?|object storage|administrative boundar\w*|sample size|"
    r"power analysis|burn ratio|wildfires?|land surface temperature)\b")
# Arabic forms not covered by lexicon expansions; attached clitics are allowed.
_STRONG_DOMAIN_AR = re.compile(
    r"(?<![ء-ي])(?:[وفبلك]{0,2}(?:ال)?)(?:خريط|خرائط|جغرافي|مكاني|احداثي|"
    r"اقمار صناعيه|قمر صناعي|فضائي|استشعار|تضاريس|ارتفاعات|طبوغراف|مستجمع|"
    r"غطاء (?:ال)?ارض|غطاء نباتي|استخدام(?:ات)? (?:ال)?اراضي|كنتور|شيب ?فايل|جيو)")
# Weak anchors are homonyms that count only when no everyday context is present.
_WEAK_DOMAIN = re.compile(
    r"\b(?:maps?|mapping|chart|charts|plot|plots|figures?|graphs?|histograms?|statistics|"
    r"correlation|network|routing|connectivity|layers?|grid|classif\w*|accuracy|"
    r"region|regions|area|distance|buffer|clip|overlay|join|points?|lines?|vector|projection|catalog\w*|"
    r"datasets?|boundar\w*|buildings?|overlaps?|gaps|cube|multi ?dimensional|observations?|seasons?|monthly|annual|"
    r"samples?|sampling|records|features|rivers?|lakes?|coastlines?|centre ?lines?|center ?lines?|"
    r"statistically|significan\w*|test whether|forests?|deforestation|roads?|streets?|villages?|"
    r"neighbou?rhoods?|districts?|crops?|yields?|farms?|fields?|wells?|scenes?|regression|pixels?|temporal|"
    r"sentinel|elevation|terrain|vegetation|nearest|stores?|addresses?)\b"
    r"|(?<![\u0621-\u064a])(?:[وفبلك]{0,2}(?:ال)?)(?:بيانات|داتا|صور|حدود|طبق[هات]|مؤشر|شبك|مباني|معالم|"
    r"طرق|شوارع|قري|احياء|محافظ|مناطق|مزارع|محاصيل|حقول|انتاجي)")
_EVERYDAY_CONTEXT = re.compile(
    r"\bmap out\b|\b(?:mind|site|hash|key|road) ?map\b|\b(?:email|letter|cover letter|resume|cv|essay|poem|story|"
    r"speech|wedding|birthday|recipe|cake|cook\w*|grocer\w*|gym|diet|workout|budget|spending|expenses?|"
    r"salary|mortgage|loan|tax|invoice|excel|spreadsheet|marketing|colleagues?|"
    r"conference|interview|career|itinerary|trips?|travel plan|vacation|holiday|deploy\w*|checkout|website|"
    r"homework|exam|lesson|kids?|child|calculus|derivatives?|algebra|equations?|neural|backpropagation|engineer|career|"
    r"linkedin|instagram|tweet|newsletter|meeting|agenda|team building|onboarding|"
    r"react|javascript|css|html|docker|kubernetes|node js|tcp|dns|tls|vpn|wifi|router|osi|novel|book|"
    r"movie|film|character|psycholog\w*|paragraphs?|apps?|class|methods?|functions?|strings?|overflow|"
    r"attackers?|exploit\w*|vulnerabilit\w*|puzzles?)\b"
    r"|(?:رساله|خطاب|مقال|قصيد|قصه|روايه|فرح|وصفه|كيك|طبخ|ميزاني|مصاريف|مصروف|راتب|مرتب|قرض|اكسل|"
    r"كلاس|داله|دوال|مخترق|اختراق|لغز|تسويق|زملاء|مهني|عصبي|تعلم عميق|فائده|توفير|خصم|جنيه|ريال|دولار|مقابله|اجازه|امتحان|مذاكر|علم النفس|نفسي|لينكد)")


# Location-analysis combinations that stay domain work in a business or everyday
# setting: counts per district, nearest store per address, values by region on a map.
_SPATIAL_COMBO = re.compile(
    r"\bnearest (?:\w+ ){0,2}(?:stores?|shops?|branch\w*|facilit\w*|hospitals?|clinics?|schools?|stations?|"
    r"depots?|warehouses?)\b"
    r"|\b(?:on|in|as) a map\b.{0,60}\b(?:per|by|each) (?:district|region|neighbou?rhood|zone|province|county|"
    r"governorate|state|postcode|zip)"
    r"|\b(?:per|by|each) (?:district|region|neighbou?rhood|zone|province|county|governorate|state|postcode|zip)"
    r"\w*\b.{0,60}\b(?:on|in|as) a map\b"
    r"|اقرب (?:فرع|محل|مستشفي|مدرس|محط|مخزن|عياد)"
    r"|(?:لكل|حسب) (?:ال)?(?:حي|منطق|محافظ|مدين)\w*.{0,40}(?:علي|في) (?:ال)?خريط")


def geospatial_request(text: str) -> bool:
    """Accept only requests that name domain work; a homonym needs a domain-only context."""
    if _HOMONYM_VETO.search(text):
        return False
    if (_STRONG_DOMAIN.search(text) or _STRONG_DOMAIN_AR.search(text)
            or _CLOUD_ACCESS_TEXT.search(text) or _SAR_TEXT.search(text)):
        return True
    weak = _WEAK_DOMAIN.search(text) or _STATISTICAL_TEXT.search(text) or _CONNECTIVITY_TEXT.search(text)
    if weak and ((_VECTOR_PER_POLYGON.search(text) and _VECTOR_LAYER.search(text)) or _SPATIAL_COMBO.search(text)):
        return True
    return bool(weak and not _EVERYDAY_CONTEXT.search(text))

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
    spectral_context = bool((_SATELLITE_WORDS - {"spectral"}) & term_set
                            or re.search(r"spectral (?:index|indices)|مؤشرات? طيفي", text)
                            or any(ds["kind"] in {"raster", "stac"} for ds in profiles))
    index_wording = bool(_NAMED_INDEX_WORDS & term_set or (
        (_INDEX_WORDS & term_set or _INDEX_TEXT.search(text)) and spectral_context))
    if _NAMED_INDEX_TEXT.search(text):
        index_wording = True
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
    elif index_wording and (_SATELLITE_WORDS & term_set or rasters or _NAMED_INDEX_TEXT.search(text)) and not stac:
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
    elif _STATISTICAL_TEXT.search(text):
        wording("statistical-analysis", 6.0, "significance or group-difference test wording")
    if not rasters and re.search(r"\bnearest\b.{0,40}\b(?:for|to) (?:each|every)\b|(?:لكل|كل) .{0,30}اقرب", text):
        wording("geopandas", 5.0, "nearest feature for each record; a nearest-neighbour join")
    if not rasters and _VECTOR_PER_POLYGON.search(text) and _VECTOR_LAYER.search(text):
        wording("geopandas", 6.0, "count or summarise one vector layer per polygon of another")
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
    time_series_intent = bool((_TIME_SERIES_WORDS - {"chang"}) & term_set or _TIME_SERIES_TEXT.search(text)
        or (re.search(r"\b(?:monthly|annual|yearly|months|years|seasons)\b", text)
            and re.search(r"\b(?:composit\w*|ndvi|vegetation|imagery|observations?|landsat|sentinel|forest)\b", text)))
    accuracy_intent = bool(_ACCURACY_TEXT.search(text)
                           or {"confusion", "matrix"} <= term_set
                           or ("accuracy" in term_set and {"map", "classification", "classif", "referenc", "overall"} & term_set)
                           or (re.search(r"\b(?:probability|reference|stratified)\b.{0,30}\b(?:sampl\w*|validation)\b", text)
                               and re.search(r"\b(?:map|land cover|forest|class\w*)\b", text)))
    cloud_intent = bool(_CLOUD_ACCESS_TEXT.search(text) or "stac" in str(
        " ".join(str(ds.get("collection", "")) for ds in stac)).lower()
        or ({"cloud", "cog", "asset"} & term_set and {"range", "window"} & term_set))
    for affirmative, name in ((time_series_intent, "time-series-and-change"),
                              (accuracy_intent, "accuracy-assessment"),
                              (cloud_intent, "stac-and-cloud-access")):
        if affirmative:
            wording(name, 6.0, "explicit workflow capability intent")
    if not rasters and not stac and not _GDAL_CONTEXT.search(text):
        guard("gdal", "no GDAL command, raster format or raster data wording")
    if _RASTER_CLI.search(text) and not vectors and not _VECTOR_ANALYSIS.search(text):
        wording("geopandas", -6.0, "raster command-line task; a cutline polygon is not a vector analysis")
    if re.search(r"\b(?:gdalinfo|gdalwarp|gdal_translate|gdalbuildvrt|gdaladdo|gdaldem|gdal_calc\w*|"
                 r"gdal_merge\w*|gdal_rasterize|ogr2ogr|ogrinfo)\b", text):
        wording("gdal", 8.0, "named GDAL command")
    if re.search(r"\bzonal (?:statistics|stats|summar\w*)\b|احصا\w* .{0,30}داخل (?:ال)?مضلعات", text):
        wording("raster-processing", 6.0, "zonal statistics of a raster within polygons")
    if "raster-processing" not in guarded and {"dem", "elevation", "raster"} & term_set and {"gap", "hole", "nodata"} & term_set:
        wording("raster-processing", 4.0, "fill or preserve raster gaps and nodata")
    named_gdal = re.search(r"\b(?:gdal\w+|ogr2ogr|ogrinfo)\b", text)
    if named_gdal and not vectors and not _VECTOR_ANALYSIS.search(text):
        wording("geopandas", -6.0, "named GDAL/OGR command; a format conversion is not a GeoPandas analysis")
    if _affirmed(_WEB_MAP, text) and not _WEB_TECH.search(text):
        wording("geospatial-frontend", 5.0, "interactive or browser web-map wording")
    if re.search(r"\b(?:leaflet|mapbox|openlayers|cesium|kepler gl)\b", text):
        wording("geospatial-frontend", 6.0, "named web-map engine")
    if _VECTOR_DEFECT_TEXT.search(text):
        wording("vector-quality", 6.0, "geometry defect or cleaning wording")
    if _CRS_SYMPTOM_TEXT.search(text):
        wording("crs-and-units", 6.0, "layers that should coincide do not; CRS mismatch symptom")
    if _VIZ_TEXT.search(text):
        wording("scientific-visualization", 6.0, "statistical or publication figure wording")
    if _CONNECTIVITY_TEXT.search(text) and not sourcing:
        wording("networkx", 6.0, "network connectivity or link-failure wording")
    if "raster" in term_set and {"align", "alignment", "resampl", "grid", "resolution"} & term_set:
        wording("raster-processing", 4.0, "raster grid alignment or resampling intent")
    if stac and any(re.search(r"sentinel[\s_-]*1", str(ds.get("collection", "")), re.I) for ds in stac):
        sar_intent = True
        wording("sar-basics", 8.0, "Sentinel-1 STAC collection; SAR calibration and terrain correction wording")
    if sar_intent and not re.search(r"\b(?:landsat|sentinel[\s_-]*2|reflectance|optical|scl|qa_?pixel)\b|انعكاس|بصري", text):
        guard("satellite-preprocessing", "SAR preparation is not optical reflectance or cloud/QA preprocessing")
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
