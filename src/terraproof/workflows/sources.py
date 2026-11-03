"""One bounded public Landsat catalog route: discover, explicitly select, acquire, review.

Catalog quality is a proposal, never a pixel-quality verdict. No model, credentials,
automatic approval, date mixing, source fallback or analytical processing lives here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import hashlib
from html import escape
import json
import math
from pathlib import Path
import re
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import shapely
from shapely.geometry import shape

from terraproof._common import InputError
from .intent import SCHEMA, aoi_geometry, digest, keys, load, local, plan, product_metadata, records, validate_intent, write

REQUEST = 'terraproof.source-request/1'
REPORT = 'terraproof.source-search/1'
API = 'https://planetarycomputer.microsoft.com/api/stac/v1'
TOKEN = 'https://planetarycomputer.microsoft.com/api/sas/v1/token/landsateuwest/landsat-c2'
BLOB = 'landsateuwest.blob.core.windows.net'
ROLES = {'mtl.txt': None, 'lwir11': 'FILE_NAME_BAND_ST_B10',
         'qa_pixel': 'FILE_NAME_QUALITY_L1_PIXEL', 'qa': 'FILE_NAME_QUALITY_L2_SURFACE_TEMPERATURE'}
BYTE_CAP = 512*1024*1024
PAGE_BYTES = 8*1024*1024
PAGE_CAP = 5


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(url):
    return build_opener(_NoRedirect).open(Request(url, headers={'User-Agent': 'Terraproof-native-ST-source/1'}), timeout=60)


def _json(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'planetarycomputer.microsoft.com' or not (
            parsed.path.startswith('/api/stac/v1/') or url == TOKEN):
        raise InputError('unsupported public metadata endpoint')
    try:
        with _open(url) as response:
            data = response.read(PAGE_BYTES+1)
        if len(data) > PAGE_BYTES:
            raise InputError('public JSON exceeds 8 MiB cap')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise InputError('duplicate public JSON field')
                result[key] = value
            return result
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(InputError('nonfinite public JSON')))
    except InputError:
        raise
    except Exception as error:
        # A signed download URL must never reach an error log or retained report.
        raise InputError(f'public metadata unavailable ({type(error).__name__}, HTTP {getattr(error,"code",None)})') from None


def _request(path):
    path = Path(path).resolve()
    document = load(path)
    keys(document, ('schema', 'id', 'intent', 'search'))
    if document['schema'] != REQUEST or not isinstance(document['id'], str) or not document['id'].strip():
        raise InputError('expected a named terraproof.source-request/1')
    start, end, coverage = validate_intent(document['intent'])
    search = document['search']; keys(search, ('max_scene_cloud',), ('max_download_bytes',))
    cloud = search['max_scene_cloud']
    budget = search.get('max_download_bytes', BYTE_CAP)
    if type(cloud) not in (int,float) or not math.isfinite(cloud) or not 0 <= cloud <= 100:
        raise InputError('max_scene_cloud must explicitly be 0..100; it is not AOI quality')
    if type(budget) is not int or not 1 <= budget <= BYTE_CAP:
        raise InputError('max_download_bytes must be an integer from 1 to 512 MiB')
    aoi = local(document['intent']['aoi'], path.parent)
    geometry = aoi_geometry(aoi, 4326)
    bounds = geometry.bounds
    if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
        raise InputError('AOI is outside longitude/latitude bounds')
    return path, document, aoi, geometry, start, end, coverage, budget


def _asset(href):
    if not isinstance(href, str):
        raise InputError('missing unsigned native asset URL')
    parsed = urlsplit(href)
    name = parsed.path.rsplit('/',1)[-1]
    if (parsed.scheme != 'https' or parsed.netloc != BLOB or parsed.query or parsed.fragment
            or not parsed.path.startswith('/landsat-c2/level-2/standard/oli-tirs/')
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', name)):
        raise InputError('asset must be an unsigned native Landsat HTTPS URL on the supported public store')
    return name


def _candidate(item, geometry, start, end, coverage, cloud_limit):
    identifier = item.get('id')
    if not isinstance(identifier,str) or not identifier:
        return {'id': '(missing)', 'eligible': False, 'reasons': ['missing item ID']}
    reasons = []
    result = {'id': identifier, 'eligible': False, 'reasons': reasons}
    try:
        if item.get('type') != 'Feature' or item.get('collection') != 'landsat-c2-l2':
            raise InputError('not an item from the supported collection')
        properties = item['properties']
        platform = properties.get('platform')
        if platform not in ('landsat-8','landsat-9') or properties.get('landsat:correction') != 'L2SP':
            reasons.append('requires Landsat 8/9 L2SP')
        acquired = datetime.fromisoformat(properties['datetime'].replace('Z','+00:00'))
        if acquired.utcoffset() is None:
            raise InputError('acquisition timestamp must declare its timezone')
        acquired = acquired.astimezone(timezone.utc)
        if not start <= acquired.date() <= end:
            reasons.append('outside the requested acquisition interval')
        cloud = properties.get('eo:cloud_cover')
        if type(cloud) not in (int,float) or not math.isfinite(cloud) or not 0 <= cloud <= 100:
            raise InputError('scene cloud metadata is unavailable or invalid; cannot rank')
        if cloud > cloud_limit:
            reasons.append('scene cloud exceeds the explicit search limit')
        footprint = shape(item['geometry'])
        if footprint.geom_type not in ('Polygon','MultiPolygon') or footprint.is_empty or not footprint.is_valid:
            raise InputError('invalid catalog polygon footprint')
        bounds = footprint.bounds
        if bounds[2]-bounds[0] > 180 or bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
            raise InputError('unsupported catalog footprint coordinates/antimeridian')
        fraction = max(0.0,min(1.0,geometry.intersection(footprint).area/geometry.area))
        full = bool(footprint.covers(geometry))
        if not fraction:
            reasons.append('catalog footprint does not overlap the AOI')
        elif coverage == 'full-aoi' and not full:
            reasons.append('catalog footprint does not cover the full requested AOI')
        if not isinstance(item.get('assets'),dict) or any(role not in item['assets'] for role in ROLES):
            raise InputError('missing native MTL/ST_B10/QA_PIXEL/ST_QA asset roles')
        assets = {role: item['assets'][role]['href'] for role in ROLES}
        names = [_asset(href) for href in assets.values()]
        if len(set(n.lower() for n in names)) != len(ROLES):
            raise InputError('native asset filenames conflict')
        result.update({'platform': platform, 'acquired': acquired.isoformat(), 'scene_cloud_percent': cloud,
                       'catalog_aoi_fraction_lonlat_plane': fraction, 'catalog_full_aoi': full, 'assets': assets})
        if not reasons:
            result['eligible'] = True
            reasons.extend(['native L2SP roles present', 'within requested dates and scene-cloud limit',
                            'catalog full-AOI coverage' if full else 'partial catalog footprint explicitly allowed'])
    except (InputError,ValueError,TypeError,KeyError,AttributeError,shapely.errors.GEOSException) as error:
        # Do not echo untrusted asset strings or arbitrary catalog fields.
        reasons.append(str(error) if isinstance(error,InputError) else 'malformed or missing catalog metadata')
    return result


def _rank(candidates):
    def order(candidate):
        return (not candidate['eligible'], candidate.get('scene_cloud_percent',math.inf),
                -datetime.fromisoformat(candidate['acquired']).timestamp() if candidate.get('acquired') else math.inf,
                candidate['id'])
    ordered = sorted(candidates, key=order)
    rank = 0
    for candidate in ordered:
        if candidate['eligible']:
            rank += 1; candidate['rank'] = rank
        else:
            candidate['rank'] = None
    return ordered


def _public_page(page):
    """Catalog asset URLs must be unsigned too; never retain a supplied SAS URL."""
    page = deepcopy(page)
    for item in page['features']:
        if not isinstance(item,dict) or not isinstance(item.get('assets'),dict):
            continue
        for asset in item['assets'].values():
            if not isinstance(asset,dict) or not isinstance(asset.get('href'),str):
                continue
            try:
                url = urlsplit(asset['href'])
                redact = bool(url.query or url.fragment or url.username or url.password)
            except ValueError:
                redact = True
            if redact:
                asset['href'] = '[redacted: signed or credential-bearing asset URL is not supported]'
    return page


def _html(report):
    rows = ''.join('<tr>'+''.join(f'<td>{escape(str(c.get(k,"unknown")))}</td>' for k in
        ('rank','id','eligible','acquired','scene_cloud_percent','catalog_aoi_fraction_lonlat_plane'))+
        '<td>'+escape('; '.join(c['reasons']))+'</td></tr>' for c in report['candidates'])
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Terraproof source alternatives</title>
<style>body{{font:16px system-ui;margin:30px}}td,th{{padding:9px;border:1px solid #bbb;text-align:left;overflow-wrap:anywhere;vertical-align:top}}table{{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px}}section{{padding:16px;background:#fff4ce}}</style>
<h1>Source alternatives: {escape(report['request']['id'])}</h1>
<section><h2>{escape(report['status'])}</h2><p>Metadata proposals only. No pixel quality verified, no scene approved, no analysis performed.</p>
<p>Coverage policy: {escape(report['scene_coverage'])}. Scene cloud is not AOI usable coverage.</p>
<p>Quantity: acquisition-time land surface temperature in degrees Celsius.
Acquisition interval: {escape(' through '.join(report['request']['intent']['acquired_between']))}.</p>
<p>Reject QA_PIXEL bits: {escape(str(report['request']['intent']['reject_qa_bits']))}.
Minimum usable within-scene fraction: {report['request']['intent']['min_valid_fraction']:.2%}.
Native download cap: {report['max_download_bytes']/1024/1024:.2f} MiB.</p>
<p>Order: eligible coverage, lowest reported scene cloud, latest acquisition, item ID.</p>
<p>{escape('; '.join(report['issues']))}</p></section>
<p>Choose an eligible item and pass this exact digest to acquire: <code>{report['report_digest']}</code>.</p>
<p>Acquisition writes an unapproved workflow for native-data review. It cannot change the requested dates, quality policy or quantity.</p>
<table><colgroup><col style="width:5%"><col style="width:19%"><col style="width:7%"><col style="width:15%"><col style="width:8%"><col style="width:11%"><col style="width:35%"></colgroup><tr><th>Rank</th><th>Item</th><th>Eligible</th><th>UTC acquisition</th><th>Scene cloud %</th><th>Catalog AOI fraction (lon/lat plane)</th><th>Reasons</th></tr>{rows}</table>
<p><a href="report.json">Machine report and frozen catalog-page hashes</a>. Unsigned consistency evidence, not authenticated approval.</p></html>'''


def discover(request_path, output):
    """Bounded metadata-only search; preserve all alternatives and rejection reasons."""
    path, document, aoi, geometry, start, end, coverage, budget = _request(request_path)
    inputs = records([path,aoi])
    output = Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    url = API+'/search?'+urlencode({'collections':'landsat-c2-l2','bbox':','.join(map(str,geometry.bounds)),
        'datetime':f'{start}T00:00:00Z/{end}T23:59:59.999999Z','limit':100})
    seen = {}; pages = []; issues = []; complete = False
    try:
        for index in range(PAGE_CAP):
            page = _json(url)
            if not isinstance(page,dict) or not isinstance(page.get('features'),list) or len(page['features']) > 100:
                raise InputError('unsupported catalog page; expected up to 100 features')
            page = _public_page(page)
            name = f'catalog-page-{index+1}.json'; write(output/name,page)
            pages.append({'file':name,'sha256':hashlib.sha256((output/name).read_bytes()).hexdigest()})
            for item in page['features']:
                if not isinstance(item,dict):
                    raise InputError('catalog feature must be an object')
                identifier = item.get('id')
                if not isinstance(identifier,str) or not identifier:
                    raise InputError('catalog item lacks a stable ID')
                if identifier in seen and digest(seen[identifier]) != digest(item):
                    raise InputError('conflicting repeated catalog ID; start a new search snapshot')
                seen[identifier] = item
            following = [v for v in page.get('links',[]) if v.get('rel') == 'next']
            if not following:
                complete = True; break
            if len(following) != 1 or following[0].get('method','GET') != 'GET':
                raise InputError('unsupported catalog pagination; no partial search can be selected')
            url = urljoin(url,following[0]['href'])
        if not complete:
            issues.append('five-page metadata cap reached; narrow the request and run a new search')
    except (InputError,ValueError,TypeError,KeyError,AttributeError) as error:
        issues.append(str(error) if isinstance(error,InputError) else 'malformed catalog pagination')
    if records([path,aoi]) != inputs:
        raise InputError('source request or AOI changed during discovery; retained snapshot is not selectable')
    candidates = _rank([_candidate(v,geometry,start,end,coverage,document['search']['max_scene_cloud']) for v in seen.values()])
    eligible = sum(c['eligible'] for c in candidates)
    status = 'incomplete' if not complete else ('ready-for-selection' if eligible else 'unresolved')
    if complete and not eligible:
        issues.append('No eligible single scene under the requested dates, coverage and search limit; no dates, QA or coverage were changed.')
    report = {'schema':REPORT,'status':status,'request_path':str(path),'request':document,'request_digest':digest(document),
        'inputs':inputs,'scene_coverage':coverage,'catalog':'planetary-computer/landsat-c2-l2',
        'catalog_search_complete':complete,'catalog_pages':pages,'candidates':candidates,'eligible_count':eligible,
        'max_download_bytes':budget,'issues':issues,
        'limitations':['Catalog footprints/cloud are proposals, not native-grid or usable-pixel verification.',
                       'One scene only; no date mixing, mosaics, inferred QA or automatic approval.']}
    report['report_digest'] = digest(report)
    write(output/'report.json',report)
    (output/'report.html').write_text(_html(report),encoding='utf-8')
    return report


def _download(href, target, remaining, token):
    _asset(href)
    checksum = hashlib.sha256(); size = 0
    try:
        with _open(href+'?'+token) as response, target.with_suffix(target.suffix+'.partial').open('xb') as out:
            declared = response.headers.get('Content-Length')
            if declared is not None and int(declared) > remaining:
                raise InputError('native download would exceed the reviewed byte cap')
            while block := response.read(min(1024*1024,remaining-size+1)):
                size += len(block)
                if size > remaining:
                    raise InputError('native download exceeded the reviewed byte cap; partial retained')
                checksum.update(block); out.write(block)
            if declared is not None and size != int(declared):
                raise InputError('native response ended before its declared length; partial retained')
            if not size:
                raise InputError('empty native asset; partial retained')
        target.with_suffix(target.suffix+'.partial').rename(target)
    except InputError:
        raise
    except Exception as error:
        raise InputError(f'native download unavailable ({type(error).__name__}, HTTP {getattr(error,"code",None)}); partial retained') from None
    return {'file':target.name,'url':href,'bytes':size,'sha256':checksum.hexdigest()}


def acquire(report_path, item_id, output, *, expected_digest):
    """Fetch exactly the selected proposal, then create an unapproved local workflow."""
    report_path = Path(report_path).resolve(); report = load(report_path)
    recorded = report.get('report_digest')
    if report.get('schema') != REPORT or not recorded or recorded != expected_digest or digest(
            {k:v for k,v in report.items() if k != 'report_digest'}) != recorded:
        raise InputError('source report changed or digest not reviewed')
    if report['status'] != 'ready-for-selection' or not report['catalog_search_complete']:
        raise InputError('cannot acquire from an unresolved or incomplete catalog search')
    path, document, aoi, _, _, _, _, budget = _request(report['request_path'])
    if digest(document) != report['request_digest'] or records([path,aoi]) != report['inputs']:
        raise InputError('request, AOI or known sidecars changed; discover and review again')
    for page in report['catalog_pages']:
        if Path(page['file']).name != page['file'] or hashlib.sha256((report_path.parent/page['file']).read_bytes()).hexdigest() != page['sha256']:
            raise InputError('catalog snapshot changed; discover and review again')
    matches = [c for c in report['candidates'] if c['id'] == item_id and c['eligible']]
    if len(matches) != 1:
        raise InputError('explicit selection must name exactly one eligible item')
    candidate = matches[0]
    assets = candidate['assets']; filenames = {role:_asset(assets[role]) for role in ROLES}
    if len(set(v.lower() for v in filenames.values())) != len(ROLES):
        raise InputError('selected asset filenames conflict')
    output = Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    downloaded = []
    try:
        token = _json(TOKEN).get('token')
        if not isinstance(token,str) or not token:
            raise InputError('public access service returned no temporary token')
        for role in ROLES:
            record = _download(assets[role],output/filenames[role],budget-sum(r['bytes'] for r in downloaded),token)
            record['role'] = role; downloaded.append(record)
            write(output/'download-progress.json',{'item':item_id,'records':downloaded})
        metadata_path = output/filenames['mtl.txt']
        metadata = product_metadata(metadata_path)
        product = metadata['PRODUCT_CONTENTS']; product_id = product['LANDSAT_PRODUCT_ID']
        match = re.fullmatch(r'(LC0[89]_L2SP_\d{6}_\d{8})_\d{8}_(02_T[12])',product_id)
        if not match or match[1]+'_'+match[2] != item_id or filenames['mtl.txt'] != product_id+'_MTL.txt':
            raise InputError('downloaded product identity contradicts the selected catalog item')
        if any(product[field] != filenames[role] for role,field in ROLES.items() if field):
            raise InputError('native MTL asset associations contradict the selected package')
        workflow = {'schema':SCHEMA,'id':document['id'],'intent':{**document['intent'],'aoi':str(aoi)},
                    'source':{'metadata':str(metadata_path),'representation':'usgs-native-dn'}}
        write(output/'workflow.json',workflow)
        review = plan(output/'workflow.json')
        if review['status'] == 'ready-for-review' and (
                review['facts']['date'] != candidate['acquired'][:10]
                or review['facts']['sensor'] != candidate['platform'].upper().replace('-','_')):
            raise InputError('native acquisition date/sensor contradicts the selected catalog metadata')
        if records([path,aoi]) != report['inputs']:
            raise InputError('request or AOI changed during acquisition; new review required')
        write(output/'plan.json',review)
        result = {'schema':'terraproof.source-package/1','status':review['status'],'item':item_id,
            'selected_report_digest':recorded,'request':document,'source_report':str(report_path),
            'source_request_inputs':report['inputs'],'selected_candidate':candidate,'catalog_pages':report['catalog_pages'],
            'records':downloaded,'workflow':str(output/'workflow.json'),'approved':False,'processed':False,
            'next_steps':['Review the native-data plan, then explicitly approve its exact digest and inputs before running.']}
        write(output/'source-package.json',result)
        return result
    except Exception as error:
        write(output/'failure.json',{'status':'failed','error':str(error),'item':item_id,
                                     'records':downloaded,'approved':False,'processed':False})
        raise
