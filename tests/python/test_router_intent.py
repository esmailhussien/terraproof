"""Public dev-only paired intent regressions; no held-out corpora are consulted."""

import json
from pathlib import Path

import pytest

from terraproof.router import find_guidance
from terraproof.router.index import PROCESS_SKILLS, get_index
from terraproof.router.intent import intent_text

# These authored cases are recorded in dev.jsonl and pythonScenarios to exercise
# each rule through the public scenario path.
CASES = [
    ('Rename the button label to "Compute NDVI with GDAL".', 'en', [], '*'),
    ('Compute NDVI with GDAL from the local satellite bands.', 'en', ['spectral-indices', 'gdal'], ['geospatial-data-discovery']),
    ('Draft an email about STAC and Sentinel-1 calibration.', 'en', [], '*'),
    ('Calibrate Sentinel-1 backscatter and compare relative orbits.', 'en', ['sar-basics'], ['satellite-preprocessing']),
    ('Translate "PostGIS spatial index" into Arabic.', 'en', [], '*'),
    ('Design a PostGIS spatial index without Python.', 'en', ['design-postgis-tables'], ['spectral-indices']),
    ('Do not compute NDVI or mask clouds; draw a publication figure in Matplotlib instead.', 'en', ['scientific-visualization'], ['spectral-indices', 'satellite-preprocessing']),
    ('Compute NDVI and mask clouds using SCL; do not draw a publication figure.', 'en', ['spectral-indices', 'satellite-preprocessing'], ['scientific-visualization']),
    ('I have offline Landsat imagery; calculate NDVI without downloading scenes.', 'en', ['spectral-indices'], ['geospatial-data-discovery']),
    ('Download Landsat imagery, then calculate NDVI.', 'en', ['geospatial-data-discovery', 'spectral-indices'], []),
    ('Change the account password in the CRUD REST API.', 'en', [], ['time-series-and-change', 'stac-and-cloud-access', 'geospatial-frontend']),
    ('Read cloud raster assets with HTTP range requests.', 'en', ['stac-and-cloud-access'], ['geospatial-frontend']),
    ('Check numerical accuracy of floating point arithmetic.', 'en', [], ['accuracy-assessment']),
    ('Assess land cover map accuracy with a confusion matrix.', 'en', ['accuracy-assessment'], ['satellite-preprocessing']),
    ('Pick a random sample of names for an email invitation.', 'en', [], ['accuracy-assessment']),
    ('Design stratified sampling for map accuracy with reference samples.', 'en', ['accuracy-assessment'], []),
    ('No Python: build an interactive web map with Leaflet.', 'en', ['geospatial-frontend'], []),
    ('Do not build a web map; fix the service startup exception.', 'en', [], ['geospatial-frontend']),
    ('غيّر نص الزر إلى «احسب NDVI باستخدام GDAL».', 'ar', [], '*'),
    ('احسب NDVI باستخدام GDAL من المرئيات المحلية', 'ar', ['spectral-indices', 'gdal'], ['geospatial-data-discovery']),
    ('اكتب رسالة عن STAC ومعايرة سنتينل 1', 'ar', [], '*'),
    ('احسب التشتت الخلفي للاستشعار الراداري وقارن المدار النسبي', 'ar', ['sar-basics'], ['satellite-preprocessing']),
    ('ترجم «فهرس مكاني PostGIS» إلى الإنجليزية', 'ar', [], '*'),
    ('صمم قاعدة بيانات مكانية PostGIS بدون بايثون', 'ar', ['design-postgis-tables'], ['spectral-indices']),
    ('لا تحسب NDVI؛ ارسم شكلا للنشر باستخدام Matplotlib', 'ar', ['scientific-visualization'], ['spectral-indices']),
    ('احسب مؤشر المياه من الصور الفضائية؛ لا ترسم خريطة ويب', 'ar', ['spectral-indices'], ['geospatial-frontend']),
    ('عندي مرئيات لاندسات محلية؛ احسب مؤشر النبات بدون تحميل بيانات', 'ar', ['spectral-indices'], ['geospatial-data-discovery']),
    ('نزل مرئيات لاندسات ثم احسب مؤشر النبات', 'ar', ['geospatial-data-discovery', 'spectral-indices'], []),
    ('غير كلمة المرور في تطبيق CRUD و REST API', 'ar', [], ['time-series-and-change', 'stac-and-cloud-access', 'geospatial-frontend']),
    ('اقرأ المرئيات عبر قراءة النوافذ وروابط موقعة', 'ar', ['stac-and-cloud-access'], ['scientific-visualization']),
    ('راجع دقة النص في صور البريد على شبكة المكتب', 'ar', [], '*'),
    ('تقييم الدقة للتصنيف مع عينات طبقية ودقة المنتج ودقة المستخدم والدقة الكلية', 'ar', ['accuracy-assessment'], ['satellite-preprocessing']),
    ('احسب متوسط القدرة الخطية للتبعثر الخلفي للرادار', 'ar', ['sar-basics'], ['satellite-preprocessing', 'spectral-indices']),
    ('حلل السلسلة الزمنية للغطاء الأرضي وكشف التغيرات', 'ar', ['time-series-and-change'], ['accuracy-assessment']),
    ('بدون بايثون: ابني خريطة تفاعلية باستخدام Leaflet', 'ar', ['geospatial-frontend'], []),
    ('لا اريد تحليل GIS؛ اصلح خطأ تشغيل الخدمة', 'ar', [], ['geospatial-frontend', 'geopandas', 'gdal']),
    ('Write a document about the phrase "NDVI; STAC. GDAL".', 'en', [], '*'),
    ('اكتب مستندا عن العبارة «NDVI؛ STAC. GDAL»', 'ar', [], '*'),
    ('Rename the button to "NDVI; then STAC"; compute NetworkX centrality instead.', 'en', ['networkx'], ['spectral-indices', 'stac-and-cloud-access']),
    ('غير نص الزر إلى «NDVI؛ ثم STAC»؛ احسب مركزية شبكة الطرق', 'ar', ['networkx'], ['spectral-indices', 'stac-and-cloud-access']),
]


def test_intent_cases_registered_in_public_scenarios_and_dev_set():
    root = Path(__file__).resolve().parents[2]
    scenarios = json.loads((root / 'tests/router/scenarios.json').read_text(encoding='utf-8'))['pythonScenarios']
    dev = [json.loads(line) for line in (root / 'evals/routing/dev.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    registered = {item['id']: item for item in scenarios if item['id'].startswith('intent-')}
    authored = {item['id']: item for item in dev if item['id'].startswith('intent-')}
    assert len(registered) == len(authored) == len(CASES)
    assert registered.keys() == authored.keys()
    for ordinal, (prompt, lang, expected, forbidden) in enumerate(CASES, 1):
        identifier = f'intent-{lang}-{ordinal:02d}'
        scenario, item = registered[identifier], authored[identifier]
        excluded = sorted(set(get_index().skills) - PROCESS_SKILLS) if forbidden == '*' else forbidden
        assert scenario['prompt'] == item['prompt'] == prompt
        assert scenario['mustInclude'] == item['expected'] == expected
        assert set(scenario['mustExclude']) == set(item['must_not']) == set(excluded)


@pytest.mark.parametrize('prompt,lang,expected,forbidden', CASES)
@pytest.mark.parametrize('mode', ['ranked', 'candidates'])
def test_requested_intent_pairs(prompt, lang, expected, forbidden, mode):
    result = find_guidance(prompt, mode=mode, semantic=False)
    selected = {skill['name'] for skill in result['skills']}
    assert set(expected) <= selected
    excluded = set(get_index().skills) - PROCESS_SKILLS if forbidden == '*' else set(forbidden)
    assert not selected & excluded
    assert result['query']['text'] == prompt
    assert result['query']['language'] == lang


def test_quotes_as_operands_and_negative_descriptions_are_not_deleted():
    assert not intent_text('Do not use GDAL or GeoPandas')
    assert not intent_text("Don't run STAC searches")
    assert not intent_text('لا تستخدم GDAL ولا GeoPandas')
    assert 'NDVI' in intent_text('Compute "NDVI" from the bands')
    assert 'reflectance' in intent_text('The raw values are not reflectance')
    assert 'GeoTIFF' in intent_text('Without Python, convert GeoTIFF to COG with GDAL')


def test_editorial_and_negative_scopes_cannot_be_resurrected_by_semantics(monkeypatch):
    import terraproof.router as router
    monkeypatch.setattr(router, '_semantic_scores', lambda index, task: (
        {(section.skill, section.id): 0.99 for section in index.sections}, None))
    for prompt in ['Draft an email about NDVI and SAR.', 'Do not compute NDVI.']:
        assert find_guidance(prompt, semantic=True)['skills'] == []
