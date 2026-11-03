"""Source selection/acquisition contracts with bounded fake public responses, no live network."""
from copy import deepcopy
import io
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError

import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from rasterio.transform import from_origin

from terraproof._common import InputError
from terraproof.cli import main
from terraproof.workflows import sources, approve, execute
from terraproof.workflows.intent import digest, load, write

ITEM = 'LC08_L2SP_175042_20250615_02_T1'
PRODUCT = 'LC08_L2SP_175042_20250615_20250620_02_T1'


@pytest.fixture
def scene(tmp_path):
    native = tmp_path/'native'; native.mkdir()
    filenames = {'mtl.txt':PRODUCT+'_MTL.txt','lwir11':PRODUCT+'_ST_B10.TIF',
                 'qa_pixel':PRODUCT+'_QA_PIXEL.TIF','qa':PRODUCT+'_ST_QA.TIF'}
    for role,value,dtype,nodata in [('lwir11',40000,'uint16',0),('qa_pixel',0,'uint16',1),('qa',200,'int16',-9999)]:
        with rasterio.open(native/filenames[role],'w',driver='GTiff',width=4,height=4,count=1,
            crs=32632,transform=from_origin(500000,1000000,30,30),dtype=dtype,nodata=nodata) as ds:
            ds.write(np.full((4,4),value,dtype=dtype),1)
    metadata = f'''GROUP = LANDSAT_METADATA_FILE
GROUP = PRODUCT_CONTENTS
LANDSAT_PRODUCT_ID = "{PRODUCT}"
PROCESSING_LEVEL = "L2SP"
COLLECTION_NUMBER = "02"
FILE_NAME_BAND_ST_B10 = "{filenames['lwir11']}"
FILE_NAME_QUALITY_L1_PIXEL = "{filenames['qa_pixel']}"
FILE_NAME_QUALITY_L2_SURFACE_TEMPERATURE = "{filenames['qa']}"
END_GROUP = PRODUCT_CONTENTS
GROUP = IMAGE_ATTRIBUTES
SPACECRAFT_ID = "LANDSAT_8"
DATE_ACQUIRED = "2025-06-15"
SCENE_CENTER_TIME = "10:15:00Z"
END_GROUP = IMAGE_ATTRIBUTES
GROUP = LEVEL2_SURFACE_TEMPERATURE_PARAMETERS
TEMPERATURE_MULT_BAND_ST_B10 = 0.00341802
TEMPERATURE_ADD_BAND_ST_B10 = 149.0
END_GROUP = LEVEL2_SURFACE_TEMPERATURE_PARAMETERS
END_GROUP = LANDSAT_METADATA_FILE
END
'''
    (native/filenames['mtl.txt']).write_text(metadata,encoding='utf-8')
    aoi = tmp_path/'aoi.geojson'
    write(aoi,{'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:32632'}},
        'features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[
        [[500030,999970],[500090,999970],[500090,999910],[500030,999910],[500030,999970]]]}}]})
    request = tmp_path/'request.json'
    write(request,{'schema':sources.REQUEST,'id':'source <review>','intent':{
        'quantity':'land-surface-temperature','unit':'degree_Celsius','aoi':str(aoi),
        'acquired_between':['2025-06-01','2025-06-30'],'reject_qa_bits':[0,1,2,3,4,5,7],
        'min_valid_fraction':0.6},'search':{'max_scene_cloud':100}})
    transform = Transformer.from_crs(32632,4326,always_xy=True)
    x,y = transform.transform(500060,999940)
    ring = [[x-.01,y-.01],[x+.01,y-.01],[x+.01,y+.01],[x-.01,y+.01],[x-.01,y-.01]]
    base = 'https://'+sources.BLOB+'/landsat-c2/level-2/standard/oli-tirs/2025/175/042/'+PRODUCT+'/'
    item = {'type':'Feature','collection':'landsat-c2-l2','id':ITEM,
        'properties':{'platform':'landsat-8','landsat:correction':'L2SP','datetime':'2025-06-15T10:15:00Z','eo:cloud_cover':1},
        'geometry':{'type':'Polygon','coordinates':[ring]},'assets':{role:{'href':base+filename} for role,filename in filenames.items()}}
    return request,item,native,filenames


def search(monkeypatch,scene,items=None,folder='search'):
    request,item,_,_ = scene
    monkeypatch.setattr(sources,'_json',lambda url:{'features':items if items is not None else [item],'links':[]})
    output = request.parent/folder
    report = sources.discover(request,output)
    return output,report


class Response(io.BytesIO):
    def __init__(self,data,length=True):
        super().__init__(data); self.headers = {'Content-Length':str(len(data))} if length else {}


def native_transport(monkeypatch,scene,mutate=None):
    _,_,native,_ = scene
    monkeypatch.setattr(sources,'_json',lambda url:{'token':'TEST-TRANSIENT-TOKEN'})
    def opened(url):
        assert '?TEST-TRANSIENT-TOKEN' in url
        data = (native/Path(urlsplit(url).path).name).read_bytes()
        return Response(mutate(url,data) if mutate else data)
    monkeypatch.setattr(sources,'_open',opened)


def test_metadata_only_discovery_is_deterministic_and_not_approval(scene,monkeypatch):
    _,item,_,_ = scene
    later = deepcopy(item); later['id'] = 'later'; later['properties']['datetime'] = '2025-06-16T10:15:00Z'
    cloudy = deepcopy(item); cloudy['id'] = 'cloudier'; cloudy['properties']['eo:cloud_cover'] = 30
    folder,report = search(monkeypatch,scene,[cloudy,item,later])
    _,reversed_report = search(monkeypatch,scene,[later,item,cloudy],folder='reversed')
    assert [c['id'] for c in report['candidates']] == ['later',ITEM,'cloudier']
    assert [c['id'] for c in reversed_report['candidates']] == ['later',ITEM,'cloudier']
    assert report['status'] == 'ready-for-selection' and report['eligible_count'] == 3
    assert not list(folder.glob('*.TIF')) and not (folder/'approval.json').exists()
    html = (folder/'report.html').read_text(encoding='utf-8')
    assert 'source &lt;review&gt;' in html and 'No pixel quality verified' in html


def test_polygon_footprint_not_bbox_and_partial_requires_explicit_choice(scene,monkeypatch):
    request,item,_,_ = scene
    smaller = deepcopy(item)
    geometry = sources._request(request)[3]
    x0,y0,x1,y1 = geometry.bounds
    smaller['geometry'] = {'type':'Polygon','coordinates':[[[x0-.01,y0-.01],[(x0+x1)/2,y0-.01],
        [(x0+x1)/2,y1+.01],[x0-.01,y1+.01],[x0-.01,y0-.01]]]}
    smaller['bbox'] = item['geometry']['coordinates'][0][0]+item['geometry']['coordinates'][0][2]
    _,report = search(monkeypatch,scene,[smaller])
    assert report['status'] == 'unresolved' and not report['candidates'][0]['eligible']
    doc = load(request); doc['intent']['scene_coverage'] = 'allow-partial'; write(request,doc)
    _,report = search(monkeypatch,scene,[smaller],folder='partial')
    assert report['status'] == 'ready-for-selection' and not report['candidates'][0]['catalog_full_aoi']


@pytest.mark.parametrize('change',['date','platform','level','cloud','nan-cloud','roles','signed','geometry'])
def test_unsupported_or_malformed_catalog_items_are_explained(scene,monkeypatch,change):
    _,item,_,_ = scene; item = deepcopy(item)
    if change == 'date': item['properties']['datetime'] = '2025-07-01T00:00:00Z'
    if change == 'platform': item['properties']['platform'] = 'landsat-7'
    if change == 'level': item['properties']['landsat:correction'] = 'L2SR'
    if change == 'cloud': item['properties']['eo:cloud_cover'] = None
    if change == 'nan-cloud': item['properties']['eo:cloud_cover'] = float('nan')
    if change == 'roles': del item['assets']['qa']
    if change == 'signed': item['assets']['qa']['href'] += '?signature=not-persisted-token'
    if change == 'geometry': item['geometry'] = None
    # Nonfinite raw JSON is refused before this filter in the live transport.
    if change == 'nan-cloud':
        request,_,_,_ = scene; _,doc,_,geometry,start,end,coverage,_ = sources._request(request)
        result = sources._candidate(item,geometry,start,end,coverage,100)
        assert result['eligible'] is False
    else:
        folder,report = search(monkeypatch,scene,[item])
        assert report['eligible_count'] == 0 and report['candidates'][0]['reasons']
        if change == 'signed':
            assert 'not-persisted-token' not in ''.join(p.read_text() for p in folder.glob('*.json'))


def test_page_cap_and_network_failure_never_offer_selectable_partial_search(scene,monkeypatch):
    request,item,_,_ = scene
    monkeypatch.setattr(sources,'PAGE_CAP',1)
    monkeypatch.setattr(sources,'_json',lambda url:{'features':[item],'links':[{'rel':'next','href':sources.API+'/search?page=2'}]})
    output = request.parent/'capped'; report = sources.discover(request,output)
    assert report['status'] == 'incomplete' and report['eligible_count'] == 1
    with pytest.raises(InputError,match='incomplete'):
        sources.acquire(output/'report.json',ITEM,request.parent/'never',expected_digest=report['report_digest'])
    def fail(url): raise InputError('public metadata unavailable')
    monkeypatch.setattr(sources,'_json',fail)
    failed = sources.discover(request,request.parent/'network-failure')
    assert failed['status'] == 'incomplete' and not failed['catalog_search_complete']


def test_conflicting_duplicate_ids_are_not_silently_ranked(scene,monkeypatch):
    _,item,_,_ = scene; changed = deepcopy(item); changed['properties']['eo:cloud_cover'] = 20
    _,report = search(monkeypatch,scene,[item,changed])
    assert report['status'] == 'incomplete' and 'conflicting' in report['issues'][0]


def test_acquire_creates_unapproved_native_workflow_then_existing_core_runs(scene,monkeypatch):
    request,_,_,_ = scene; folder,report = search(monkeypatch,scene)
    native_transport(monkeypatch,scene)
    output = request.parent/'package'
    package = sources.acquire(folder/'report.json',ITEM,output,expected_digest=report['report_digest'])
    assert package['status'] == 'ready-for-review' and package['approved'] is package['processed'] is False
    assert not (output/'approval.json').exists() and not (output/'temperature_celsius.tif').exists()
    assert 'TEST-TRANSIENT-TOKEN' not in ''.join(p.read_text() for p in output.glob('*.json'))
    review = load(output/'plan.json')
    approve(output/'workflow.json',output/'approval.json',reviewer='synthetic-test',expected_digest=review['spec_digest'])
    assert execute(output/'approval.json',output/'run')['status'] == 'verified'
    assert load(output/'workflow.json')['intent'] == {**load(request)['intent'],'aoi':str(request.parent/'aoi.geojson')}
    with pytest.raises(FileExistsError):
        sources.acquire(folder/'report.json',ITEM,output,expected_digest=report['report_digest'])


@pytest.mark.parametrize('changed',['digest','report','request','aoi','page','selection'])
def test_changed_review_inputs_refuse_before_download(scene,monkeypatch,changed):
    request,_,_,_ = scene; folder,report = search(monkeypatch,scene)
    expected = report['report_digest']; item = ITEM
    if changed == 'digest': expected = 'not-the-reviewed-digest'
    if changed == 'report':
        report['candidates'][0]['scene_cloud_percent'] = 99; write(folder/'report.json',report)
    if changed == 'request':
        doc = load(request); doc['intent']['min_valid_fraction'] = 0.1; write(request,doc)
    if changed == 'aoi':
        with (request.parent/'aoi.geojson').open('a') as out: out.write('\n')
    if changed == 'page': (folder/'catalog-page-1.json').write_text('{}')
    if changed == 'selection': item = 'unlisted-item'
    def forbidden(url): raise AssertionError('no download or signing before review consistency')
    monkeypatch.setattr(sources,'_open',forbidden)
    output = request.parent/'never'
    with pytest.raises(InputError):
        sources.acquire(folder/'report.json',item,output,expected_digest=expected)
    assert not output.exists()


def test_download_budget_retains_failure_without_secrets(scene,monkeypatch):
    request,_,_,_ = scene; doc = load(request); doc['search']['max_download_bytes'] = 1; write(request,doc)
    folder,report = search(monkeypatch,scene); native_transport(monkeypatch,scene)
    output = request.parent/'too-large'
    with pytest.raises(InputError,match='cap'):
        sources.acquire(folder/'report.json',ITEM,output,expected_digest=report['report_digest'])
    assert load(output/'failure.json')['processed'] is False
    assert 'TEST-TRANSIENT-TOKEN' not in (output/'failure.json').read_text()
    assert list(output.glob('*.partial')) and not (output/'workflow.json').exists()


def test_download_transport_failure_redacts_temporary_url(scene,monkeypatch):
    request,_,_,_ = scene; folder,report = search(monkeypatch,scene)
    monkeypatch.setattr(sources,'_json',lambda url:{'token':'TEST-TRANSIENT-TOKEN'})
    def fail(url): raise HTTPError(url,403,'no access',{},None)
    monkeypatch.setattr(sources,'_open',fail)
    output = request.parent/'unavailable'
    with pytest.raises(InputError,match='HTTP 403'):
        sources.acquire(folder/'report.json',ITEM,output,expected_digest=report['report_digest'])
    assert 'TEST-TRANSIENT-TOKEN' not in (output/'failure.json').read_text()


def test_downloaded_metadata_cannot_change_selected_product_identity(scene,monkeypatch):
    request,_,_,_ = scene; folder,report = search(monkeypatch,scene)
    def alter(url,data):
        return data.replace(PRODUCT.encode(),PRODUCT.replace('20250615','20250616').encode()) if '_MTL.txt' in url else data
    native_transport(monkeypatch,scene,alter)
    output = request.parent/'wrong-identity'
    with pytest.raises(InputError,match='identity'):
        sources.acquire(folder/'report.json',ITEM,output,expected_digest=report['report_digest'])
    assert not (output/'workflow.json').exists() and load(output/'failure.json')['approved'] is False


def test_native_coverage_is_rechecked_after_metadata_proposal(scene,monkeypatch):
    request,_,_,_ = scene
    document = load(request.parent/'aoi.geojson')
    document['features'][0]['geometry']['coordinates'][0][1][0] = 500150
    document['features'][0]['geometry']['coordinates'][0][2][0] = 500150
    write(request.parent/'aoi.geojson',document)
    folder,report = search(monkeypatch,scene); native_transport(monkeypatch,scene)
    package = sources.acquire(folder/'report.json',ITEM,request.parent/'native-partial',expected_digest=report['report_digest'])
    assert package['status'] == 'unresolved' and package['approved'] is False
    assert load(request.parent/'native-partial/plan.json')['facts']['scene_coverage_satisfied'] is False


def test_source_cli_init_and_discover_use_same_intent_contract(scene,monkeypatch,capsys):
    request,item,_,_ = scene; draft = request.parent/'cli-source.json'
    assert main(['workflow','source-init',str(draft),'--aoi',str(request.parent/'aoi.geojson'),
        '--start','2025-06-01','--end','2025-06-30','--reject-qa-bits','0','3','7',
        '--min-valid-fraction','0.6','--max-scene-cloud','50']) == 0
    capsys.readouterr()
    assert load(draft)['schema'] == sources.REQUEST and load(draft)['intent']['scene_coverage'] == 'full-aoi'
    monkeypatch.setattr(sources,'_json',lambda url:{'features':[item],'links':[]})
    assert main(['workflow','discover',str(draft),'--out',str(request.parent/'cli-search')]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'ready-for-selection'


def test_public_json_blocks_redirects_untrusted_hosts_and_oversize(monkeypatch):
    with pytest.raises(InputError,match='endpoint'): sources._json('https://example.org/catalog')
    monkeypatch.setattr(sources,'_open',lambda url:Response(b' '*(sources.PAGE_BYTES+1)))
    with pytest.raises(InputError,match='cap'): sources._json(sources.API+'/search')
    assert sources._NoRedirect().redirect_request(None,None,302,'',{},'https://example.org') is None
