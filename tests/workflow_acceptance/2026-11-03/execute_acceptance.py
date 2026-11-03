"""External acceptance runner. Public frozen instructions only; no sealed criteria."""
from pathlib import Path
import copy, hashlib, json, sys, time, traceback
from datetime import datetime, timezone
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
PUBLIC_HASH = 'ae6a5051d5c56ad964cc254f10ea1094a10dbd2455a2d89c1ffc8319706b6621'
CAP = 536870912

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        while block := f.read(1024*1024): h.update(block)
    return h.hexdigest()

def write(p, value):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def now(): return datetime.now(timezone.utc).isoformat()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def preflight(spec):
    opener = build_opener(NoRedirect())
    from terraproof.workflows.sources import TOKEN
    # Anonymous public container token; kept in memory, never persisted/logged.
    with opener.open(TOKEN, timeout=60) as r:
        token = json.loads(r.read(1024*1024))['token']
    sizes = []; total = 0
    for case in spec['cases']:
        for role, url in case['fixed_native_assets'].items():
            parsed = urlsplit(url)
            assert parsed.scheme == 'https' and parsed.hostname == 'landsateuwest.blob.core.windows.net'
            assert not parsed.query and not parsed.fragment
            with opener.open(Request(url+'?'+token, method='HEAD'), timeout=60) as r:
                length = int(r.headers['Content-Length'])
                assert length > 0 and r.status == 200
                sizes.append({'case':case['id'], 'role':role, 'url':url, 'bytes':length,
                              'etag':r.headers.get('ETag')})
                total += length
    result = {'utc':now(), 'method':'anonymous signed HEAD, no native body bytes',
              'records':sizes, 'total_native_bytes':total, 'aggregate_cap':CAP,
              'within_budget':total <= CAP, 'retries_permitted':False}
    write(ROOT/'head-preflight.json', result)
    if total > CAP: raise RuntimeError('Fixed source set exceeds frozen aggregate budget; no substitution')
    return result

def corner_aoi(case_dir, workflow):
    """Headers only. Freeze geometry before reading ANY diagnostic corner pixels."""
    import numpy as np, rasterio, pyproj, shapely
    from terraproof.workflows.intent import product_metadata
    mtl = Path(workflow['source']['metadata'])
    content = product_metadata(mtl)['PRODUCT_CONTENTS']
    st = mtl.parent/content['FILE_NAME_BAND_ST_B10']
    with rasterio.open(st) as ds:
        transform, crs, shape = ds.transform, ds.crs, (ds.height, ds.width)
    header = {'crs':str(crs), 'affine':list(transform)[:6], 'shape':list(shape), 'file':str(st)}
    for key in ('FILE_NAME_QUALITY_L1_PIXEL', 'FILE_NAME_QUALITY_L2_SURFACE_TEMPERATURE'):
        with rasterio.open(mtl.parent/content[key]) as ds:
            assert ds.transform == transform and ds.crs == crs and (ds.height,ds.width) == shape
    project = pyproj.Transformer.from_crs(crs,4326,always_xy=True)
    points = []
    for (x0,y0),(x1,y1) in zip([(0,0),(10,0),(10,10),(0,10)],[(10,0),(10,10),(0,10),(0,0)]):
        for k in range(40):
            t = k/40; x,y = transform*(x0+(x1-x0)*t,y0+(y1-y0)*t)
            points.append(project.transform(x,y))
    points.append(points[0])
    geom = {'type':'Polygon','coordinates':[points]}
    aoi = case_dir/'corner-aoi.geojson'
    write(aoi,{'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':geom}]})
    rows,cols = np.mgrid[-2:13,-2:13]
    x = transform.c+(cols+.5)*transform.a+(rows+.5)*transform.b
    y = transform.f+(cols+.5)*transform.d+(rows+.5)*transform.e
    lon,lat = project.transform(x,y)
    inside = shapely.intersects_xy(shapely.geometry.shape(geom),lon,lat)
    chosen = sorted(zip(rows[inside].tolist(), cols[inside].tolist()))
    assert chosen == [(r,c) for r in range(10) for c in range(10)]
    write(case_dir/'corner-geometry-freeze.json',{'utc':now(), 'header':header,
          'aoi_sha256':sha(aoi),'selected_centres':len(chosen),'row_col_centres':chosen,
          'diagnostic_pixels_read_before_this_freeze':False,
          'search_aoi_automatic_acquire_preflight_allowed_by_public_clarification':True})
    return aoi

def raw_evidence(spec_path, destination):
    """External raw AOI histograms, not an acceptance verdict or product import oracle."""
    import numpy as np, rasterio, pyproj, shapely
    from rasterio.windows import Window
    from terraproof.workflows.intent import product_metadata
    spec = load(spec_path); intent = spec['intent']; mtl = Path(spec['source']['metadata'])
    pc = product_metadata(mtl)['PRODUCT_CONTENTS']
    geo = shapely.geometry.shape(load(intent['aoi'])['features'][0]['geometry'])
    with rasterio.open(mtl.parent/pc['FILE_NAME_BAND_ST_B10']) as ds:
        fwd = pyproj.Transformer.from_crs(4326, ds.crs, always_xy=True)
        back = pyproj.Transformer.from_crs(ds.crs,4326,always_xy=True)
        dense = shapely.segmentize(geo, max_segment_length=.0001)
        xy = shapely.get_coordinates(dense); xx,yy = fwd.transform(xy[:,0],xy[:,1])
        cc,rr = (~ds.transform)*(xx,yy)
        c0,r0 = int(np.floor(min(cc)))-2,int(np.floor(min(rr)))-2
        c1,r1 = int(np.ceil(max(cc)))+2,int(np.ceil(max(rr)))+2
        rows,cols = np.mgrid[r0:r1,c0:c1]
        x = ds.transform.c+(cols+.5)*ds.transform.a+(rows+.5)*ds.transform.b
        y = ds.transform.f+(cols+.5)*ds.transform.d+(rows+.5)*ds.transform.e
        lon,lat = back.transform(x,y)
        selected = shapely.intersects_xy(geo,lon,lat)
        assert selected.sum() < 1000000
        in_grid = (cols>=0)&(cols<ds.width)&(rows>=0)&(rows<ds.height)
        window = Window(c0,r0,c1-c0,r1-r0)
        st = ds.read(1,window=window,boundless=True,fill_value=0)
        header = {'crs':str(ds.crs),'shape':[ds.height,ds.width], 'affine':list(ds.transform)[:6]}
    with rasterio.open(mtl.parent/pc['FILE_NAME_QUALITY_L1_PIXEL']) as ds:
        qa = ds.read(1,window=window,boundless=True,fill_value=1)
    with rasterio.open(mtl.parent/pc['FILE_NAME_QUALITY_L2_SURFACE_TEMPERATURE']) as ds:
        uq = ds.read(1,window=window,boundless=True,fill_value=-9999)
    acquired = selected & in_grid & ((qa&1)==0)
    bitmask = sum(1<<b for b in intent['reject_qa_bits'])
    base = acquired & (st != 0) & ((qa & bitmask)==0)
    valid = base.copy()
    if 'max_uncertainty_kelvin' in intent:
        from decimal import Decimal, ROUND_FLOOR
        ceiling = int((Decimal(str(intent['max_uncertainty_kelvin']))*100).to_integral_value(rounding=ROUND_FLOOR))
        valid &= (uq>=0)&(uq<=ceiling)
    def hist(a,m):
        values,counts = np.unique(a[m],return_counts=True)
        return {str(int(v)):int(n) for v,n in zip(values,counts)}
    good = st[valid].astype('float64')*.00341802+149-273.15
    write(destination,{'utc':now(),'native_header':header,'aoi_sha256':sha(intent['aoi']),
          'requested_count':int(selected.sum()),'grid_count':int((selected&in_grid).sum()),
          'acquired_count':int(acquired.sum()),'base_valid_count':int(base.sum()),
          'retained_count':int(valid.sum()),'mean_celsius_float64':float(good.mean()) if good.size else None,
          'raw_st_dn_histogram_in_grid_aoi':hist(st,selected&in_grid),
          'raw_qa_pixel_histogram_in_grid_aoi':hist(qa,selected&in_grid),
          'raw_st_qa_histogram_base_valid':hist(uq,base),
          'note':'Implementer external evidence only; reviewer supplies acceptance assessment separately.'})

def execute(spec, heads):
    from terraproof.workflows.sources import discover, acquire
    from terraproof.workflows.intent import plan, approve
    from terraproof.workflows.lst import execute as run, verify
    outcomes = []; transferred = 0
    for case in spec['cases']:
        directory = ROOT/case['id']; directory.mkdir(exist_ok=False)
        public = case['source_search']; aoi = directory/'search-aoi.geojson'
        write(aoi, {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':public['intent']['aoi']}]})
        intent = copy.deepcopy(public['intent']); intent['aoi'] = str(aoi)
        # Omission is deliberate: test documented full-AOI default.
        intent.pop('scene_coverage',None)
        budget = sum(r['bytes'] for r in heads['records'] if r['case']==case['id'])
        assert transferred+budget <= CAP
        request = {'schema':'terraproof.source-request/2','id':case['id'], 'intent':intent,
                   'search':{'max_scene_cloud':public['max_cloud_percent'],'max_download_bytes':budget}}
        write(directory/'request.json',request)
        start = time.monotonic()
        try:
            report = discover(directory/'request.json', directory/'discovery')
            matches = [c for c in report['candidates'] if c['id']==case['selected_item_id'] and c['eligible']]
            assert len(matches)==1 and matches[0]['assets']==case['fixed_native_assets']
            write(directory/'selection.json', {'utc':now(),'item':case['selected_item_id'],
                 'report_digest':report['report_digest'],'public_cases_sha256':PUBLIC_HASH,
                 'asset_identities_match_frozen_spec':True,'no_substitution':True})
            package = acquire(directory/'discovery/report.json',case['selected_item_id'],directory/'package/inputs',
                              expected_digest=report['report_digest'])
            actual = sum(r['bytes'] for r in package['records']); assert actual==budget
            transferred += actual
            write(directory/'package/fetch-manifest.json',{'records':package['records'],'total_bytes':actual})
            workflow = load(package['workflow'])
            diagnostic = corner_aoi(directory,workflow) if case['id']=='R2' else aoi
            variants = []
            for variant in case['workflow_variants']:
                vd = directory/variant['id']; vd.mkdir()
                ws = copy.deepcopy(workflow); ws['id']=variant['id']; wi=ws['intent']
                wi['aoi']=str(diagnostic); wi['min_valid_fraction']=variant['min_valid_fraction']
                wi.pop('scene_coverage',None); wi.pop('max_uncertainty_kelvin',None)
                if isinstance(variant['max_uncertainty_kelvin'],(int,float)):
                    wi['max_uncertainty_kelvin']=variant['max_uncertainty_kelvin']
                write(vd/'workflow.json',ws)
                admission = plan(vd/'workflow.json'); write(vd/'plan.json',admission)
                result = {'variant':variant['id'],'admission':admission['status'], 'approved':False,'processed':False}
                if admission['status']=='ready-for-review':
                    approval = approve(vd/'workflow.json',vd/'approval.json',reviewer='Implementation agent; engineering execution under independent public protocol',
                                       expected_digest=admission['spec_digest'],review_kind='engineering-self-review')
                    result['approved']=True
                    rv=run(vd/'approval.json',vd/'outputs'); write(vd/'run-result.json',rv)
                    vv=verify(vd/'approval.json',vd/'outputs'); write(vd/'verify-result.json',vv)
                    result.update(processed=True,run_status=rv['status'],verification_status=vv['status'],grade=vv.get('grade'))
                write(vd/'outcome.json',result)
                raw_evidence(vd/'workflow.json',vd/'raw-evidence.json')
                variants.append(result)
                print(json.dumps(result),flush=True)
            outcomes.append({'case':case['id'],'status':'executed','native_bytes':actual,'variants':variants,
                             'duration_seconds':time.monotonic()-start})
        except Exception as e:
            # Exceptions never include signed access-service URLs from this runner.
            failure={'case':case['id'],'status':'execution-failed','error_type':type(e).__name__,
                     'error':str(e) if '?' not in str(e) else 'redacted URL-bearing error',
                     'duration_seconds':time.monotonic()-start}
            write(directory/'runner-failure.json',failure); outcomes.append(failure)
            print(json.dumps(failure),flush=True)
            # No retries/substitution. Preserve partial files and count actual transfers.
            break
        write(ROOT/'outcomes.partial.json',{'utc':now(),'outcomes':outcomes,'completed_native_bytes':transferred})
    files=[]
    for p in ROOT.glob('R*/package/inputs/*'):
        if p.is_file() and (p.name.endswith('.TIF') or p.name.endswith('_MTL.txt') or p.name.endswith('.partial')):
            files.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)})
    ledger={'new_native_bytes':sum(f['bytes'] for f in files),'aggregate_cap':CAP,'retries':0,'files':files}
    assert ledger['new_native_bytes']<=CAP
    write(ROOT/'transfer-ledger.json',ledger)
    write(ROOT/'outcomes.json',{'utc':now(),'source_commit':spec['selection_frozen_source_commit'],
          'public_cases_sha256':PUBLIC_HASH,'outcomes':outcomes,'transfer_ledger':ledger,
          'product_modified':False,'sealed_criteria_read':False})

def freeze():
    excluded=('reviewer/SEALED','installed/','wheel/','edge-')
    records=[]
    for p in sorted(ROOT.rglob('*')):
        rel=p.relative_to(ROOT).as_posix()
        if not p.is_file() or rel.startswith(excluded) or rel in ('OUTCOMES_FROZEN.json',): continue
        if rel.startswith('reviewer/') and p.name not in ('PUBLIC_CASES.json','PUBLIC_BRIEF.md','SHA256_MANIFEST.json'): continue
        records.append({'file':rel,'bytes':p.stat().st_size,'sha256':sha(p)})
    write(ROOT/'OUTCOMES_FROZEN.json',{'utc':now(),'criteria_read_before_this_freeze':False,
          'records':records,'source_commit':'77ce7aea9798f3622cec46d019a8267b52fb558a'})

if __name__=='__main__':
    assert sha(ROOT/'reviewer/PUBLIC_CASES.json')==PUBLIC_HASH
    spec=load(ROOT/'reviewer/PUBLIC_CASES.json')
    action=sys.argv[1]
    if action=='head':
        try:
            preflight(spec)
            print(json.dumps(load(ROOT/'head-preflight.json')),flush=True)
        except Exception as e:
            write(ROOT/'head-failure.json',{'error_type':type(e).__name__,'http_status':getattr(e,'code',None),
                                          'native_body_bytes':0,'utc':now()})
            print('HEAD preflight failed; sanitized details retained',flush=True); sys.exit(1)
    elif action=='execute': execute(spec,load(ROOT/'head-preflight.json'))
    elif action=='freeze': freeze()
    else: raise SystemExit('unknown action')
