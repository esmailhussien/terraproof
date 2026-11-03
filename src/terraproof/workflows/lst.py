"""One complete local, native-grid ST workflow. All science reads are windowed.

The verifier re-reads original assets, not the producer's cached expected arrays.
Its scope is published-product decoding/support, not absolute thermal accuracy.
"""
from __future__ import annotations

from contextlib import ExitStack
import math
from pathlib import Path
import tempfile

import numpy as np
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.windows import Window, transform as window_transform
from shapely.geometry import mapping, box

from terraproof._common import InputError
from terraproof.checks import run_checks
from terraproof.evidence import build_report, input_record
from terraproof.inspect import inspect_dataset
from .intent import approved, digest, load, records, write, SCALE, OFFSET
from .render import render

FILES = ('decoded_celsius.tif', 'temperature_celsius.tif', 'validity.tif', 'aoi.tif',
         'uncertainty_kelvin.tif', 'summary.json', 'calibration-evidence.json', 'map.svg', 'report.html')
NODATA = -9999.0


def windows(width, height):
    for row in range(0, height, 256):
        for col in range(0, width, 256):
            yield Window(col, row, min(256, width-col), min(256, height-row))


def context(approval_path):
    approval, spec, paths, facts, geometry = approved(approval_path)
    with rasterio.open(paths['temperature']) as src:
        try:
            region = geometry_window(src, [mapping(geometry)])
        except rasterio.errors.WindowError as error:
            raise InputError('AOI does not overlap this scene; select another scene') from error
        transform = window_transform(region, src.transform)
        footprint = box(*src.bounds)
        # Native-plane area is a descriptive geometric coverage ratio, not geodesic area.
        uncovered = 1.0 - geometry.intersection(footprint).area / geometry.area
    return approval, spec, paths, facts, geometry, region, transform, max(0.0, uncovered)


def _profile(src, *, transform=None, width=None, height=None, byte=False):
    return {'driver': 'GTiff', 'width': width or src.width, 'height': height or src.height,
            'count': 1, 'dtype': 'uint8' if byte else 'float32', 'crs': src.crs,
            'transform': transform or src.transform, 'nodata': 255 if byte else NODATA,
            'tiled': True, 'compress': 'deflate', 'blockxsize': 256, 'blockysize': 256}


def _statistics(total, count, minimum, maximum, selected, uncertain, uncertainty_total, uncovered):
    return {'valid_count': count, 'selected_count': selected,
            'valid_fraction_within_scene': count/selected if selected else None,
            'mean_celsius': total/count if count else None,
            'min_celsius': minimum if count else None, 'max_celsius': maximum if count else None,
            'uncertainty_valid_count': uncertain,
            'mean_product_uncertainty_kelvin': uncertainty_total/uncertain if uncertain else None,
            'outside_scene_fraction_native_plane': uncovered,
            'coverage_basis': 'pixel-centre within scene; outside-scene fraction is native-plane geometry',
            'weighting': 'equal valid pixels, not area weighted',
            'uncertainty_meaning': 'product uncertainty magnitude; not uncertainty of the mean'}


def _produce(approval_path, directory):
    _, spec, paths, facts, geometry, region, transform, uncovered = context(approval_path)
    mask_bits = sum(1 << b for b in spec['intent']['reject_qa_bits'])
    with ExitStack() as stack:
        src, qa, uncertainty = [stack.enter_context(rasterio.open(paths[k]))
                                for k in ('temperature', 'qa', 'uncertainty')]
        intermediate = stack.enter_context(rasterio.open(directory/'decoded_celsius.tif', 'w', **_profile(src)))
        intermediate.set_band_unit(1, 'degree_Celsius')
        for win in windows(src.width, src.height):
            raw = src.read(1, window=win)
            support = (raw != 0) & (src.read_masks(1, window=win) > 0)
            decoded = raw.astype('float64') * SCALE + OFFSET - 273.15
            intermediate.write(np.where(support, decoded, NODATA).astype('float32'), 1, window=win)
        profile = _profile(src, transform=transform, width=int(region.width), height=int(region.height))
        outputs = {}
        for name in ('temperature_celsius', 'validity', 'aoi', 'uncertainty_kelvin'):
            outputs[name] = stack.enter_context(rasterio.open(directory/(name+'.tif'), 'w',
                **dict(profile, dtype='uint8', nodata=255) if name in ('validity', 'aoi') else profile))
        outputs['temperature_celsius'].set_band_unit(1, 'degree_Celsius')
        outputs['uncertainty_kelvin'].set_band_unit(1, 'kelvin')
        count = selected = uncertain = 0
        total = uncertainty_total = 0.0
        minimum, maximum = math.inf, -math.inf
        for win in windows(int(region.width), int(region.height)):
            source_window = Window(win.col_off+region.col_off, win.row_off+region.row_off, win.width, win.height)
            raw, flags, uq = [dataset.read(1, window=source_window) for dataset in (src, qa, uncertainty)]
            aoi = ~geometry_mask([mapping(geometry)], out_shape=raw.shape,
                                  transform=window_transform(win, transform), all_touched=False)
            valid = (aoi & (raw != 0) & (src.read_masks(1, window=source_window) > 0)
                     & (qa.read_masks(1, window=source_window) > 0) & ((flags & mask_bits) == 0))
            values = raw.astype('float64')*SCALE+OFFSET-273.15
            known_uncertainty = valid & (uq >= 0) & (uncertainty.read_masks(1, window=source_window) > 0)
            outputs['temperature_celsius'].write(np.where(valid, values, NODATA).astype('float32'), 1, window=win)
            outputs['validity'].write(valid.astype('uint8'), 1, window=win)
            outputs['aoi'].write(aoi.astype('uint8'), 1, window=win)
            outputs['uncertainty_kelvin'].write(np.where(known_uncertainty, uq*0.01, NODATA).astype('float32'), 1, window=win)
            count += int(valid.sum()); selected += int(aoi.sum()); uncertain += int(known_uncertainty.sum())
            total += float(values[valid].sum()); uncertainty_total += float((uq[known_uncertainty]*0.01).sum())
            if valid.any():
                minimum, maximum = min(minimum, float(values[valid].min())), max(maximum, float(values[valid].max()))
    summary = _statistics(total, count, minimum, maximum, selected, uncertain, uncertainty_total, uncovered)
    summary.update({'quantity': spec['intent']['quantity'], 'unit': spec['intent']['unit'],
                    'product_id': facts['product_id'], 'date': facts['date']})
    write(directory/'summary.json', summary)
    calibration_evidence(directory, paths)
    render(directory, spec, facts, summary, geometry=geometry)


def calibration_evidence(directory, paths):
    # Reuse the public checker for the unmasked, same-grid intermediate. Workflow support is verified separately.
    target = directory/'decoded_celsius.tif'
    inspections = [inspect_dataset(target)]
    params = {'reference_input': str(paths['temperature']), 'decode_scale': SCALE, 'decode_offset': OFFSET,
              'unit_conversion': 'kelvin-to-celsius', 'processing_full_scan': True}
    results = run_checks(inspections, reference_input=inspect_dataset(paths['temperature']),
                         decode_scale=SCALE, decode_offset=OFFSET,
                         unit_conversion='kelvin-to-celsius', processing_full_scan=True)
    contract = {'schema': 'terraproof.verification-contract/1', 'requirements': [
        {'paths': [str(target)], 'checks': ['rs.scale_applied_once'], 'parameters': params}]}
    evidence = build_report(inputs=[input_record(str(target), 'input', 'raster'),
                                  input_record(str(paths['temperature']), 'reference-input', 'raster')],
                            results=results, parameters=params, contract=contract)
    write(directory/'calibration-evidence.json', evidence)


def _verify(approval_path, directory, *, check_manifest=True):
    """Recompute expected relations from approved originals, using every delivered pixel."""
    directory = Path(directory).resolve()
    approval, spec, paths, facts, geometry, region, transform, uncovered = context(approval_path)
    findings = []
    def finding(requirement, passed, detail):
        findings.append({'requirement': requirement, 'status': 'pass' if passed else 'fail', 'detail': detail})
    missing = [f for f in FILES if not (directory/f).is_file()]
    if missing:
        return {'status': 'failed', 'grade': 'advisory-only', 'findings': [
            {'requirement': 'deliverables', 'status': 'fail', 'detail': 'missing: '+', '.join(missing)}]}
    count = selected = uncertain = 0
    total = uncertainty_total = 0.0
    minimum, maximum = math.inf, -math.inf
    mismatches = {'calibration': 0, 'support': 0, 'aoi': 0, 'values': 0, 'uncertainty': 0}
    with ExitStack() as stack:
        src, qa, uq = [stack.enter_context(rasterio.open(paths[k])) for k in ('temperature', 'qa', 'uncertainty')]
        decoded, temperature, validity, aoi_raster, uout = [stack.enter_context(rasterio.open(directory/name))
            for name in ('decoded_celsius.tif', 'temperature_celsius.tif', 'validity.tif', 'aoi.tif', 'uncertainty_kelvin.tif')]
        for dataset in (decoded, temperature, validity, aoi_raster, uout):
            full = dataset is decoded
            byte = dataset in (validity, aoi_raster)
            shape = src.shape if full else (int(region.height), int(region.width))
            wanted_transform = src.transform if full else transform
            okay = (dataset.count == 1 and dataset.shape == shape and dataset.crs == src.crs
                    and dataset.transform == wanted_transform and dataset.scales == (1.0,) and dataset.offsets == (0.0,)
                    and dataset.dtypes == (('uint8',) if byte else ('float32',))
                    and dataset.nodata == (255 if byte else NODATA))
            finding('grid:'+Path(dataset.name).name, okay, 'exact native grid/window, one band, identity output encoding')
        if any(f['status'] == 'fail' for f in findings):
            return {'status': 'failed', 'grade': 'advisory-only', 'findings': findings}
        for win in windows(src.width, src.height):
            raw = src.read(1, window=win)
            supported = (raw > 0) & (src.read_masks(1, window=win) != 0)
            got = decoded.read(1, window=win, masked=True)
            expected = np.add(np.multiply(raw.astype('float64'), facts['scale']), facts['offset_kelvin']-273.15)
            mismatches['calibration'] += int(np.count_nonzero(
                (np.ma.getmaskarray(got) != ~supported) | (supported & ~np.isclose(got.data, expected, atol=0.0001, rtol=0))))
        for win in windows(int(region.width), int(region.height)):
            sw = Window(region.col_off+win.col_off, region.row_off+win.row_off, win.width, win.height)
            raw, flags, un = [ds.read(1, window=sw) for ds in (src, qa, uq)]
            inside = geometry_mask([mapping(geometry)], out_shape=raw.shape,
                                   transform=window_transform(win, transform), invert=True, all_touched=False)
            expected_support = inside & (raw > 0) & (src.read_masks(1, window=sw) != 0) & (qa.read_masks(1, window=sw) != 0)
            # Deliberately decode each approved bit independently of the producer's combined mask.
            for bit in spec['intent']['reject_qa_bits']:
                expected_support &= (flags // (2**bit)) % 2 == 0
            expected = raw.astype('float64') * facts['scale'] + (facts['offset_kelvin']-273.15)
            got = temperature.read(1, window=win, masked=True)
            delivered_support = ~np.ma.getmaskarray(got)
            mismatches['support'] += int(np.count_nonzero((delivered_support != expected_support)
                | (validity.read(1, window=win) != expected_support)))
            mismatches['aoi'] += int(np.count_nonzero(aoi_raster.read(1, window=win) != inside))
            mismatches['values'] += int(np.count_nonzero(expected_support & ~np.isclose(got.data, expected, atol=0.0001, rtol=0)))
            usupport = expected_support & (un >= 0) & (uq.read_masks(1, window=sw) != 0)
            uncertainty = uout.read(1, window=win, masked=True)
            mismatches['uncertainty'] += int(np.count_nonzero((np.ma.getmaskarray(uncertainty) != ~usupport)
                | (usupport & ~np.isclose(uncertainty.data, un.astype('float64')/100, atol=0.0001, rtol=0))))
            count += int(expected_support.sum()); selected += int(inside.sum()); uncertain += int(usupport.sum())
            total += float(expected[expected_support].sum()); uncertainty_total += float((un[usupport]/100).sum())
            if expected_support.any():
                minimum, maximum = min(minimum, float(expected[expected_support].min())), max(maximum, float(expected[expected_support].max()))
        finding('units', decoded.units == temperature.units == ('degree_Celsius',) and uout.units == ('kelvin',),
                'temperature is Celsius; uncertainty is a difference magnitude, without Celsius offset')
    for key, value in mismatches.items():
        finding(key, value == 0, f'{value} mismatched cells')
    expected_summary = _statistics(total, count, minimum, maximum, selected, uncertain, uncertainty_total, uncovered)
    expected_summary.update({'quantity': spec['intent']['quantity'], 'unit': spec['intent']['unit'],
                             'product_id': facts['product_id'], 'date': facts['date']})
    actual = load(directory/'summary.json')
    summary_ok = set(actual) == set(expected_summary)
    for k, v in expected_summary.items():
        value = actual.get(k)
        summary_ok &= (isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) and math.isclose(value, v, abs_tol=1e-8, rel_tol=1e-8)
                       if isinstance(v, (int, float)) else value == v)
    finding('summary', bool(summary_ok), 'statistics and identities recomputed from approved sources and support')
    if check_manifest:
        manifest = load(directory/'workflow.json')
        current = records(directory/f for f in FILES)
        actual_files = [{**r, 'path': Path(r['path']).name} for r in current]
        finding('artifact-identity', manifest.get('outputs') == actual_files,
                'all rasters, evidence, map, report and summary match recorded bytes')
        finding('intent-identity', manifest.get('spec_digest') == approval['spec_digest'], 'approved scientific intent')
        finding('provenance', manifest.get('intent_document') == spec and manifest.get('product_facts') == facts
                and manifest.get('approval') == approval, 'stored intent, product facts and approval match trusted inputs')
    # Catch input/sidecar drift while scanning. This is not a filesystem lock.
    approved(approval_path)
    failed = any(f['status'] == 'fail' for f in findings)
    insufficient = not selected or not count or count/selected < spec['intent']['min_valid_fraction']
    if insufficient:
        findings.append({'requirement': 'usable-coverage', 'status': 'not-run',
                         'detail': 'No usable observations or within-scene pixel coverage below the approved minimum.'})
    status = 'failed' if failed else ('incomplete' if insufficient else 'verified')
    return {'status': status, 'grade': 'decision-grade' if status == 'verified' else 'advisory-only',
            'scope': 'approved product decode, support, native-grid crop, statistics and artifact identity',
            'physical_accuracy_validated': False, 'usable_cells': count, 'selected_cells': selected,
            'coverage_sufficient': not insufficient, 'findings': findings,
            'limitations': ['Not a field validation of temperature or the upstream retrieval.',
                            'Approval and manifests are unsigned; their trusted copies must be held by the reviewer.',
                            'Outside-scene coverage is native-plane geometry, not geodesic area.']}


def verify(approval_path, directory, *, check_manifest=True):
    # Input drift is a review problem, not an output repair opportunity.
    context(approval_path)
    try:
        return _verify(approval_path, directory, check_manifest=check_manifest)
    except (OSError, ValueError, KeyError, TypeError, rasterio.errors.RasterioError) as error:
        return {'status': 'failed', 'grade': 'advisory-only', 'findings': [
            {'requirement': 'readable-artifacts', 'status': 'fail', 'detail': str(error)}]}


def execute(approval_path, output):
    """Publish a new run directory only; never overwrite source or prior evidence."""
    output = Path(output).resolve()
    context(approval_path)  # admit before creating anything
    if output.exists():
        raise InputError('output already exists; use verify or repair into a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name+'.partial-', dir=output.parent))
    try:
        _produce(approval_path, staging)
        result = verify(approval_path, staging, check_manifest=False)
        approval, spec, _, facts, _ = approved(approval_path)
        listed = [{**r, 'path': Path(r['path']).name} for r in records(staging/f for f in FILES)]
        manifest = {'schema': 'terraproof.workflow-run/1', 'spec_digest': approval['spec_digest'],
                    'approval': approval, 'intent_document': spec, 'product_facts': facts,
                    'verification': result, 'outputs': listed}
        write(staging/'workflow.json', manifest)
        staging.rename(output)
        # Paths in a core evidence report refer to the published directory, not its temporary name.
        calibration_evidence(output, context(approval_path)[2])
        manifest['outputs'] = [{**r, 'path': Path(r['path']).name} for r in records(output/f for f in FILES)]
        write(output/'workflow.json', manifest)
        return verify(approval_path, output)
    except Exception as error:
        # Keep failed staging as inspectable evidence, rather than deleting user data.
        if staging.exists():
            write(staging/'failure.json', {'status': 'failed', 'error': str(error), 'published': False})
        raise


def repair(approval_path, previous, output):
    """One bounded regeneration; keep the old run. Scientific choices never auto-change."""
    before = verify(approval_path, previous)
    if before['status'] == 'verified':
        raise InputError('run is already verified; no repair is justified')
    if before['status'] == 'incomplete':
        raise InputError('coverage is insufficient; another scene or changed scientific policy needs new review')
    result = execute(approval_path, output)
    write(Path(output)/'repair.json', {'previous': str(Path(previous).resolve()), 'attempts': 1,
                                     'before': before, 'after': result, 'policy_changed': False})
    return result
