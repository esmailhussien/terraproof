"""Explicit scientific intent and admission of native USGS temperature products.

Approval records identity, not authentication. Never infer calibration from pixel values.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pyogrio.raw
import pyproj
import rasterio
import shapely

from terraproof._common import InputError, sha256_and_size

SCHEMA = 'terraproof.workflow/1'
APPROVAL = 'terraproof.workflow-approval/1'
SCALE = 0.00341802
OFFSET = 149.0


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _pairs(items):
    result = {}
    for k, v in items:
        if k in result:
            raise InputError(f'duplicate JSON key: {k}')
        result[k] = v
    return result


def load(path):
    path = Path(path).resolve()
    if path.stat().st_size > 4 * 1024 * 1024:
        raise InputError('workflow JSON exceeds 4 MiB')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(InputError('nonfinite JSON')))


def write(path, document):
    Path(path).write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False) + '\n', encoding='utf-8')


def keys(document, required, optional=()):
    if not isinstance(document, dict) or set(document)-set(required)-set(optional) or set(required)-set(document):
        raise InputError('missing or unknown workflow fields; expected: '+', '.join(required))


def local(path, base):
    if not isinstance(path, str) or not path or '\0' in path or '://' in path or path.startswith('/vsi'):
        raise InputError('workflows require explicit local paths')
    return (base / path).resolve()


def product_metadata(path):
    """Native MTL JSON, XML or grouped TXT; never evaluate metadata as code."""
    if path.suffix.lower() == '.json':
        return load(path)['LANDSAT_METADATA_FILE']
    if path.stat().st_size > 4*1024*1024:
        raise InputError('MTL exceeds 4 MiB')
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.xml':
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise InputError('MTL XML must not contain document types or entities')
        root = ET.fromstring(text)
        if root.tag != 'LANDSAT_METADATA_FILE':
            raise InputError('expected LANDSAT_METADATA_FILE XML root')
        def node(element):
            return _pairs((child.tag, node(child) if len(child) else (child.text or '').strip()) for child in element)
        return node(root)
    if path.suffix.lower() != '.txt':
        raise InputError('native MTL must be JSON, XML or TXT')
    document, stack, names = {}, [], []
    current = document
    for line in text.splitlines():
        line = line.strip()
        if not line or line == 'END':
            continue
        key, separator, value = line.partition('=')
        if not separator:
            raise InputError('invalid MTL text record')
        key, value = key.strip(), value.strip().strip('"')
        if key == 'GROUP':
            if value in current:
                raise InputError('duplicate MTL group')
            child = {}; current[value] = child; stack.append(current); names.append(value); current = child
        elif key == 'END_GROUP':
            if not stack or names.pop() != value:
                raise InputError('unbalanced MTL groups')
            current = stack.pop()
        else:
            if key in current:
                raise InputError('duplicate MTL field')
            current[key] = value
    if stack:
        raise InputError('unclosed MTL group')
    return document['LANDSAT_METADATA_FILE']


def _kml(path):
    if path.suffix.lower() == '.kmz':
        with zipfile.ZipFile(path) as archive:
            entries = [e for e in archive.infolist() if e.filename.lower().endswith('.kml')]
            if len(entries) != 1 or entries[0].file_size > 4*1024*1024:
                raise InputError('KMZ must contain one KML, at most 4 MiB; no extraction or linked resources')
            text = archive.read(entries[0]).decode('utf-8')
    else:
        if path.stat().st_size > 4*1024*1024:
            raise InputError('KML exceeds 4 MiB')
        text = path.read_text(encoding='utf-8')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise InputError('KML entities are not supported')
    root = ET.fromstring(text)
    if root.findall('.//{*}NetworkLink'):
        raise InputError('KML network links are not followed')
    def ring(boundary):
        if boundary is None:
            raise InputError('KML polygon is missing an outer boundary')
        coord = boundary.find('.//{*}coordinates')
        if coord is None or not coord.text:
            raise InputError('KML polygon has no coordinates')
        return [tuple(float(v) for v in item.split(',')[:2]) for item in coord.text.split()]
    polygons = [shapely.Polygon(ring(p.find('{*}outerBoundaryIs')),
                               [ring(h) for h in p.findall('{*}innerBoundaryIs')])
                for p in root.findall('.//{*}Polygon')]
    return polygons


def records(paths):
    expanded = set()
    for path in paths:
        path = Path(path)
        expanded.add(path)
        if path.suffix.lower() == '.shp':
            for ext in ('.shx', '.dbf', '.prj', '.cpg'):
                if path.with_suffix(ext).exists():
                    expanded.add(path.with_suffix(ext))
        for suffix in ('.msk', '.aux.xml', '.ovr', '-wal', '-shm'):
            if Path(str(path)+suffix).exists():
                expanded.add(Path(str(path)+suffix))
    return [{'path': str(p), 'sha256': sha256_and_size(p)[0], 'bytes': p.stat().st_size}
            for p in sorted(expanded)]


def aoi_definition(path):
    """Return the original polygon union and its CRS, without replacing its edge semantics."""
    if path.suffix.lower() not in ('.geojson', '.json', '.shp', '.gpkg', '.kml', '.kmz'):
        raise InputError('AOI must be local GeoJSON, Shapefile, GeoPackage, KML or KMZ; no VRT sources')
    if path.suffix.lower() in ('.kml', '.kmz'):
        objects, source_crs = _kml(path), 'EPSG:4326'
    else:
        if len(pyogrio.list_layers(path)) != 1:
            raise InputError('AOI must contain exactly one layer; select/export a layer explicitly')
        info = pyogrio.read_info(path)
        if not info['crs'] or info['features'] > 100000:
            raise InputError('AOI needs an explicit CRS and at most 100000 features')
        _, _, geometries, _ = pyogrio.raw.read(path, columns=[])
        if geometries is None:
            raise InputError('AOI contains no polygons')
        objects, source_crs = shapely.from_wkb(geometries), info['crs']
    if not len(objects):
        raise InputError('AOI contains no polygons')
    if any(g is None or g.is_empty or not g.is_valid or g.geom_type not in ('Polygon', 'MultiPolygon')
           for g in objects):
        raise InputError('AOI must contain valid, nonempty polygons; no automatic geometry repair')
    crs = pyproj.CRS(source_crs)
    geometry = shapely.force_2d(shapely.union_all(objects))
    return geometry, crs


def aoi_geometry(path, target_crs):
    """Densified projected boundary for conservative crop bounds and display, not membership."""
    geometry, crs = aoi_definition(path)
    def reproject(target):
        transformer = pyproj.Transformer.from_crs(crs, target, always_xy=True)
        return shapely.transform(geometry, lambda coords: np.column_stack(transformer.transform(coords[:, 0], coords[:, 1])))
    geographic = reproject(4326)
    if geographic.bounds[2]-geographic.bounds[0] > 180:
        raise InputError('antimeridian-spanning AOI is not supported by the native-grid route')
    if crs != pyproj.CRS(target_crs):
        bounds = geometry.bounds
        spacing = max(bounds[2]-bounds[0], bounds[3]-bounds[1])/1024
        geometry = shapely.segmentize(geometry, spacing)
    projected = reproject(target_crs)
    if not projected.is_valid or not all(math.isfinite(v) for v in projected.bounds):
        raise InputError('AOI cannot be transformed into the source CRS')
    return projected


def aoi_selector(path, grid_crs):
    """Test native pixel centres in the AOI's own CRS; inclusive polygon boundaries.

    Transforming only polygon vertices changes curved edges after reprojection.
    The authoritative inclusion test must retain the original coordinate-space polygon.
    """
    geometry, crs = aoi_definition(path)
    transformer = pyproj.Transformer.from_crs(grid_crs, crs, always_xy=True)
    def select(affine, shape):
        rows, cols = np.indices(shape, dtype='float64')
        x = affine.c+(cols+0.5)*affine.a+(rows+0.5)*affine.b
        y = affine.f+(cols+0.5)*affine.d+(rows+0.5)*affine.e
        x, y = transformer.transform(x, y)
        return shapely.intersects_xy(geometry, x, y)
    return select


def admit(spec_path):
    spec_path = Path(spec_path).resolve()
    document = load(spec_path)
    keys(document, ('schema', 'id', 'intent', 'source'))
    if document['schema'] != SCHEMA or not isinstance(document['id'], str) or not document['id'].strip():
        raise InputError('invalid scientific workflow identity')
    intent = document['intent']
    keys(intent, ('quantity', 'unit', 'aoi', 'acquired_between', 'reject_qa_bits', 'min_valid_fraction'))
    if intent['quantity'] != 'land-surface-temperature' or intent['unit'] != 'degree_Celsius':
        raise InputError('this route supports acquisition-time surface temperature in Celsius only')
    bits = intent['reject_qa_bits']
    if (not isinstance(bits, list) or not bits or 0 not in bits or len(set(bits)) != len(bits)
            or any(type(b) is not int or b not in range(8) for b in bits)):
        raise InputError('explicit QA bits 0..7 required, including fill bit 0; no inferred policy')
    minimum = intent['min_valid_fraction']
    if type(minimum) not in (int, float) or not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise InputError('min_valid_fraction must explicitly be a number from 0 to 1')
    interval = intent['acquired_between']
    if not isinstance(interval, list) or len(interval) != 2:
        raise InputError('declare acquired_between as two ISO dates')
    start, end = map(date.fromisoformat, interval)
    if start > end:
        raise InputError('acquisition interval is reversed')
    source = document['source']
    keys(source, ('metadata', 'representation'))
    if source['representation'] != 'usgs-native-dn':
        raise InputError('only original USGS integer ST products are supported; decoded suppliers need another adapter')
    metadata_path = local(source['metadata'], spec_path.parent)
    metadata = product_metadata(metadata_path)
    product, image = metadata['PRODUCT_CONTENTS'], metadata['IMAGE_ATTRIBUTES']
    if (product['PROCESSING_LEVEL'] != 'L2SP' or str(product['COLLECTION_NUMBER']).lstrip('0') != '2'
            or image['SPACECRAFT_ID'] not in ('LANDSAT_8', 'LANDSAT_9')):
        raise InputError('requires Landsat 8/9 Collection 2 L2SP with surface temperature')
    acquired = date.fromisoformat(image['DATE_ACQUIRED'])
    if not start <= acquired <= end:
        raise InputError('scene is outside the approved acquisition interval')
    calibration = metadata['LEVEL2_SURFACE_TEMPERATURE_PARAMETERS']
    if (float(calibration['TEMPERATURE_MULT_BAND_ST_B10']) != SCALE
            or float(calibration['TEMPERATURE_ADD_BAND_ST_B10']) != OFFSET):
        raise InputError('ST calibration contradicts the supported USGS Collection 2 definition')
    paths = {'metadata': metadata_path, 'aoi': local(intent['aoi'], spec_path.parent)}
    for role, field in (('temperature', 'FILE_NAME_BAND_ST_B10'), ('qa', 'FILE_NAME_QUALITY_L1_PIXEL'),
                        ('uncertainty', 'FILE_NAME_QUALITY_L2_SURFACE_TEMPERATURE')):
        name = product[field]
        if not isinstance(name, str) or Path(name).name != name or '\\' in name:
            raise InputError('MTL assets must be local filenames beside the metadata')
        paths[role] = local(name, metadata_path.parent)
    with rasterio.open(paths['temperature'], driver='GTiff') as src:
        if src.count != 1 or src.dtypes != ('uint16',) or not src.crs or src.transform.b or src.transform.d:
            raise InputError('ST must be a single uint16 band on a north-up declared grid')
        if src.transform.a <= 0 or src.transform.e >= 0 or src.width*src.height > 100_000_000:
            raise InputError('unsupported source grid or scene larger than 100 million cells')
        if (src.scales[0], src.offsets[0]) not in ((1.0, 0.0), (SCALE, OFFSET)) or src.nodata not in (None, 0):
            raise InputError('ST raster calibration conflicts with MTL')
        grid = {'width': src.width, 'height': src.height, 'transform': list(src.transform)[:6],
                'crs': src.crs.to_wkt()}
        geometry = aoi_geometry(paths['aoi'], src.crs)
        covered = geometry.intersection(shapely.box(*src.bounds)).area
        if covered <= 0:
            raise InputError('AOI does not overlap this scene; select another scene')
        outside = max(0.0, 1-covered/geometry.area)
        for role in ('qa', 'uncertainty'):
            with rasterio.open(paths[role], driver='GTiff') as other:
                dtype = ('uint16',) if role == 'qa' else ('int16',)
                if (other.count != 1 or other.dtypes != dtype or other.crs != src.crs
                        or other.transform != src.transform or other.shape != src.shape):
                    raise InputError(role+' must use its native product type on exactly the ST grid; never resampled')
                allowed_nodata = (None, 1) if role == 'qa' else (None, -9999)
                allowed_encoding = ((1.0, 0.0),) if role == 'qa' else ((1.0, 0.0), (0.01, 0.0))
                if other.nodata not in allowed_nodata or (other.scales[0], other.offsets[0]) not in allowed_encoding:
                    raise InputError(role+' has conflicting fill or calibration metadata')
    facts = {'product_id': product['LANDSAT_PRODUCT_ID'], 'sensor': image['SPACECRAFT_ID'],
             'date': acquired.isoformat(), 'scene_time': image.get('SCENE_CENTER_TIME'),
             'scale': SCALE, 'offset_kelvin': OFFSET, 'fill': 0, 'uncertainty_scale': 0.01,
             'grid': grid, 'representation': source['representation'],
             'outside_scene_fraction_native_plane': outside}
    return document, paths, facts, geometry


def plan(spec_path):
    """Read-only admission and actionable unresolved inputs; no outputs are created."""
    try:
        spec, paths, facts, _ = admit(spec_path)
        return {'schema': 'terraproof.workflow-plan/1', 'status': 'ready-for-review',
                'spec_digest': digest(spec), 'intent': spec['intent'], 'facts': facts,
                'inputs': records(paths.values()), 'stages': ['admit', 'decode', 'policy-mask', 'clip',
                                                            'summarize', 'render', 'verify'],
                'limitations': ['Product decode/support verification, not absolute physical accuracy.',
                                'Native grid, one scene, pixel-centre AOI, no temporal aggregation.']}
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError, zipfile.BadZipFile,
            pyogrio.errors.DataSourceError, rasterio.errors.RasterioError) as error:
        return {'schema': 'terraproof.workflow-plan/1', 'status': 'unresolved',
                'issues': [str(error)]}


def approve(spec_path, approval_path, *, reviewer, expected_digest):
    """Record explicit review of this exact plan and its input bytes; never auto-approve."""
    result = plan(spec_path)
    if result['status'] != 'ready-for-review' or result['spec_digest'] != expected_digest:
        raise InputError('plan is unresolved or changed since review')
    if not isinstance(reviewer, str) or not reviewer.strip() or Path(approval_path).exists():
        raise InputError('reviewer required; approval output must not already exist')
    document = {'schema': APPROVAL, 'spec': str(Path(spec_path).resolve()),
                'spec_digest': expected_digest, 'reviewer': reviewer, 'inputs': result['inputs'],
                'facts_digest': digest(result['facts'])}
    write(approval_path, document)
    return document


def approved(approval_path):
    approval = load(approval_path)
    keys(approval, ('schema', 'spec', 'spec_digest', 'reviewer', 'inputs', 'facts_digest'))
    if approval['schema'] != APPROVAL or not approval['reviewer']:
        raise InputError('invalid workflow approval')
    spec, paths, facts, geometry = admit(approval['spec'])
    if (digest(spec) != approval['spec_digest'] or records(paths.values()) != approval['inputs']
            or digest(facts) != approval['facts_digest']):
        raise InputError('approved intent, source bytes, sidecars or product facts changed; review again')
    return approval, spec, paths, facts, geometry
