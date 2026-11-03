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
from rasterio.features import geometry_window
from rasterio.windows import Window, transform as window_transform
from shapely.geometry import mapping, box

from terraproof._common import InputError
from terraproof.checks import run_checks
from terraproof.evidence import build_report, input_record
from terraproof.inspect import inspect_dataset
from .intent import approved, aoi_definition, aoi_selector, digest, load, records, write, SCALE, OFFSET
from .render import render
from .support import uncertainty_ceiling, uncertainty_statistics

FILES = ('decoded_celsius.tif', 'temperature_celsius.tif', 'validity.tif', 'aoi.tif', 'acquired.tif',
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
            changed_crs = aoi_definition(paths['aoi'])[1] != src.crs
            region = geometry_window(src, [mapping(geometry)], pad_x=int(changed_crs), pad_y=int(changed_crs))
        except rasterio.errors.WindowError as error:
            raise InputError('AOI does not overlap this scene; select another scene') from error
        transform = window_transform(region, src.transform)
        grid_extent = box(*src.bounds)
        # Native-plane area is a descriptive geometric coverage ratio, not geodesic area.
        uncovered = 1.0 - geometry.intersection(grid_extent).area / geometry.area
    return approval, spec, paths, facts, geometry, region, transform, max(0.0, uncovered)


def _profile(src, *, transform=None, width=None, height=None, byte=False):
    return {'driver': 'GTiff', 'width': width or src.width, 'height': height or src.height,
            'count': 1, 'dtype': 'uint8' if byte else 'float32', 'crs': src.crs,
            'transform': transform or src.transform, 'nodata': 255 if byte else NODATA,
            'tiled': True, 'compress': 'deflate', 'blockxsize': 256, 'blockysize': 256}


def _statistics(total, count, minimum, maximum, selected, uncertain, uncertainty_total, uncovered,
                facts, acquired, base_count, histogram, exceeded, missing_excluded):
    requested = facts['support']['requested_count']
    post_histogram = histogram.copy(); ceiling = uncertainty_ceiling(facts)
    if ceiling is not None:
        post_histogram[ceiling+1:] = 0
    return {'valid_count': count, 'selected_count': selected,
            'requested_count':requested,'acquired_count':acquired,'outside_grid_count':requested-selected,
            'qa_fill_or_unknown_count':selected-acquired,'base_valid_count':base_count,
            'grid_fraction_of_requested':selected/requested if requested else None,
            'acquired_fraction_of_requested':acquired/requested if requested else None,
            'valid_fraction_within_grid':count/selected if selected else None,
            'valid_fraction_of_acquired':count/acquired if acquired else None,
            'mean_celsius': total/count if count else None,
            'min_celsius': minimum if count else None, 'max_celsius': maximum if count else None,
            'uncertainty_valid_count': uncertain,
            'mean_product_uncertainty_kelvin': uncertainty_total/uncertain if uncertain else None,
            'outside_grid_extent_fraction_native_plane': uncovered,
            'coverage_basis': 'native-grid AOI centres; acquired means QA bit 0 nonfill with available QA mask; grid extent is separate',
            'max_uncertainty_kelvin':facts['max_uncertainty_kelvin'],
            'uncertainty_exceeded_count':exceeded,'uncertainty_missing_excluded_count':missing_excluded,
            'uncertainty_before_filter':uncertainty_statistics(histogram,base_count-int(histogram.sum())),
            'uncertainty_delivered':uncertainty_statistics(post_histogram,count-uncertain),
            'temporal_support':'single-acquisition; not a period estimate',
            'weighting': 'equal valid pixels, not area weighted',
            'uncertainty_meaning': 'product uncertainty magnitude; not uncertainty of the mean'}


def _summary_matches(actual, expected):
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    for key, wanted in expected.items():
        got = actual[key]
        if isinstance(wanted,dict):
            if not _summary_matches(got,wanted):
                return False
        elif type(wanted) is int:
            if type(got) is not int or got != wanted:
                return False
        elif isinstance(wanted, float):
            if (type(got) not in (int, float) or not math.isfinite(got)
                    or not math.isclose(got, wanted, abs_tol=1e-8, rel_tol=1e-8)):
                return False
        elif got != wanted:
            return False
    return True


def _produce(approval_path, directory):
    approval, spec, paths, facts, geometry, region, transform, uncovered = context(approval_path)
    select_aoi = aoi_selector(paths['aoi'], facts['grid']['crs'])
    mask_bits = sum(1 << b for b in spec['intent']['reject_qa_bits'])
    ceiling = uncertainty_ceiling(spec['intent'])
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
        for name in ('temperature_celsius', 'validity', 'aoi', 'acquired', 'uncertainty_kelvin'):
            outputs[name] = stack.enter_context(rasterio.open(directory/(name+'.tif'), 'w',
                **dict(profile, dtype='uint8', nodata=255) if name in ('validity', 'aoi', 'acquired') else profile))
        outputs['temperature_celsius'].set_band_unit(1, 'degree_Celsius')
        outputs['uncertainty_kelvin'].set_band_unit(1, 'kelvin')
        count = selected = uncertain = 0
        acquired_count = base_count = exceeded = missing_excluded = 0
        histogram = np.zeros(32768,dtype='int64')
        total = uncertainty_total = 0.0
        minimum, maximum = math.inf, -math.inf
        for win in windows(int(region.width), int(region.height)):
            source_window = Window(win.col_off+region.col_off, win.row_off+region.row_off, win.width, win.height)
            raw, flags, uq = [dataset.read(1, window=source_window) for dataset in (src, qa, uncertainty)]
            aoi = select_aoi(window_transform(win, transform), raw.shape)
            acquired = aoi & ((flags & 1)==0) & (qa.read_masks(1,window=source_window)>0)
            base = acquired & (raw != 0) & (src.read_masks(1,window=source_window)>0) & ((flags & mask_bits)==0)
            known_before = base & (uq>=0) & (uncertainty.read_masks(1,window=source_window)>0)
            histogram += np.bincount(uq[known_before],minlength=32768)
            valid = base if ceiling is None else known_before & (uq<=ceiling)
            acquired_count += int(acquired.sum()); base_count += int(base.sum())
            if ceiling is not None:
                exceeded += int(np.count_nonzero(known_before & (uq>ceiling)))
                missing_excluded += int(np.count_nonzero(base & ~known_before))
            values = raw.astype('float64')*SCALE+OFFSET-273.15
            known_uncertainty = valid & (uq >= 0) & (uncertainty.read_masks(1, window=source_window) > 0)
            outputs['temperature_celsius'].write(np.where(valid, values, NODATA).astype('float32'), 1, window=win)
            outputs['validity'].write(valid.astype('uint8'), 1, window=win)
            outputs['aoi'].write(aoi.astype('uint8'), 1, window=win)
            outputs['acquired'].write(acquired.astype('uint8'),1,window=win)
            outputs['uncertainty_kelvin'].write(np.where(known_uncertainty, uq*0.01, NODATA).astype('float32'), 1, window=win)
            count += int(valid.sum()); selected += int(aoi.sum()); uncertain += int(known_uncertainty.sum())
            total += float(values[valid].sum()); uncertainty_total += float((uq[known_uncertainty]*0.01).sum())
            if valid.any():
                minimum, maximum = min(minimum, float(values[valid].min())), max(maximum, float(values[valid].max()))
    summary = _statistics(total,count,minimum,maximum,selected,uncertain,uncertainty_total,uncovered,
                          facts,acquired_count,base_count,histogram,exceeded,missing_excluded)
    summary.update({'quantity': spec['intent']['quantity'], 'unit': spec['intent']['unit'],
                    'product_id': facts['product_id'], 'date': facts['date'],
                    'scene_coverage_policy': facts['scene_coverage_policy']})
    write(directory/'summary.json', summary)
    calibration_evidence(directory, paths)
    render(directory,spec,facts,summary,geometry=geometry,review=approval['review'])


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
    select_aoi = aoi_selector(paths['aoi'], facts['grid']['crs'])
    findings = []
    def finding(requirement, passed, detail):
        findings.append({'requirement': requirement, 'status': 'pass' if passed else 'fail', 'detail': detail})
    missing = [f for f in FILES if not (directory/f).is_file()]
    if missing:
        return {'status': 'failed', 'grade': 'advisory-only', 'findings': [
            {'requirement': 'deliverables', 'status': 'fail', 'detail': 'missing: '+', '.join(missing)}]}
    count = selected = uncertain = 0
    acquired_count = base_count = exceeded = missing_excluded = 0
    histogram = np.zeros(32768,dtype='int64'); ceiling = uncertainty_ceiling(spec['intent'])
    total = uncertainty_total = 0.0
    minimum, maximum = math.inf, -math.inf
    mismatches = {'calibration':0,'support':0,'aoi':0,'acquired':0,'values':0,'uncertainty':0}
    with ExitStack() as stack:
        src, qa, uq = [stack.enter_context(rasterio.open(paths[k])) for k in ('temperature', 'qa', 'uncertainty')]
        decoded,temperature,validity,aoi_raster,acquired_raster,uout = [stack.enter_context(rasterio.open(directory/name))
            for name in ('decoded_celsius.tif','temperature_celsius.tif','validity.tif','aoi.tif','acquired.tif','uncertainty_kelvin.tif')]
        for dataset in (decoded,temperature,validity,aoi_raster,acquired_raster,uout):
            full = dataset is decoded
            byte = dataset in (validity,aoi_raster,acquired_raster)
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
            inside = select_aoi(window_transform(win, transform), raw.shape)
            acquired = inside & ((flags % 2)==0) & (qa.read_masks(1,window=sw)!=0)
            expected_support = acquired & (raw>0) & (src.read_masks(1,window=sw)!=0)
            # Deliberately decode each approved bit independently of the producer's combined mask.
            for bit in spec['intent']['reject_qa_bits']:
                expected_support &= (flags // (2**bit)) % 2 == 0
            base = expected_support.copy()
            known_before = base & (un>=0) & (uq.read_masks(1,window=sw)!=0)
            np.add.at(histogram,un[known_before],1)
            acquired_count += int(acquired.sum()); base_count += int(base.sum())
            if ceiling is not None:
                exceeded += int(np.count_nonzero(known_before & (un>ceiling)))
                missing_excluded += int(np.count_nonzero(base & ~known_before))
                expected_support &= known_before & (un<=ceiling)
            expected = raw.astype('float64') * facts['scale'] + (facts['offset_kelvin']-273.15)
            got = temperature.read(1, window=win, masked=True)
            delivered_support = ~np.ma.getmaskarray(got)
            mismatches['support'] += int(np.count_nonzero((delivered_support != expected_support)
                | (validity.read(1, window=win) != expected_support)))
            mismatches['aoi'] += int(np.count_nonzero(aoi_raster.read(1, window=win) != inside))
            mismatches['acquired'] += int(np.count_nonzero(acquired_raster.read(1,window=win)!=acquired))
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
    finding('preapproval-support-counts',acquired_count==facts['support']['acquired_count']
            and selected==facts['support']['selected_count'] and base_count==facts['support']['base_valid_count'],
            'QA acquisition and base-quality counts agree with the preapproval scan')
    expected_summary = _statistics(total,count,minimum,maximum,selected,uncertain,uncertainty_total,uncovered,
                                   facts,acquired_count,base_count,histogram,exceeded,missing_excluded)
    expected_summary.update({'quantity': spec['intent']['quantity'], 'unit': spec['intent']['unit'],
                             'product_id': facts['product_id'], 'date': facts['date'],
                             'scene_coverage_policy': facts['scene_coverage_policy']})
    actual = load(directory/'summary.json')
    finding('summary', _summary_matches(actual, expected_summary),
            'exact integer counts; floating statistics and identities recomputed from approved sources and support')
    if check_manifest:
        manifest = load(directory/'workflow.json')
        finding('run-completion', not (directory/'failure.json').exists()
                and manifest.get('verification', {}).get('status') != 'failed',
                'execution completed without an unresolved publication failure; otherwise regenerate a new run')
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
    insufficient = not acquired_count or not count or count/acquired_count < spec['intent']['min_valid_fraction']
    if insufficient:
        findings.append({'requirement': 'usable-coverage', 'status': 'not-run',
                         'detail':'No usable observations or post-uncertainty usable/acquired fraction below the approved minimum.'})
    status = 'failed' if failed else ('incomplete' if insufficient else 'verified')
    if check_manifest:
        marker = f'data-workflow-status="{status}"'
        finding('presentation-status', all(marker in (directory/name).read_text(encoding='utf-8')
                for name in ('report.html', 'map.svg')), 'HTML and SVG display the verified run status')
        if findings[-1]['status'] == 'fail':
            status = 'failed'
    return {'status':status,'grade':'checks-passed' if status == 'verified' else 'advisory-only',
            'scope': 'approved product decode, support, native-grid crop, statistics and artifact identity',
            'physical_accuracy_validated': False, 'usable_cells': count, 'selected_cells': selected,
            'coverage_sufficient': not insufficient, 'findings': findings,
            'scene_coverage_policy': facts['scene_coverage_policy'],
            'full_aoi_acquired':facts['full_aoi_acquired'],'acquired_cells':acquired_count,
            'outside_grid_extent_fraction_native_plane':uncovered,'review':approval['review'],
            'limitations': ['Not a field validation of temperature or the upstream retrieval.',
                            'Approval and manifests are unsigned; their trusted copies must be held by the reviewer.',
                            'Acquisition coverage uses QA-declared pixel support; grid extent is not the image footprint.',
                            'Review type is a self-declaration, not authenticated human approval.',
                            'Single-acquisition snapshot, not an estimate for the requested period.']}


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
    published = False
    try:
        _produce(approval_path, staging)
        result = verify(approval_path, staging, check_manifest=False)
        approval, spec, _, facts, geometry = approved(approval_path)
        render(staging,spec,facts,load(staging/'summary.json'),geometry=geometry,status=result['status'],review=approval['review'])
        listed = [{**r, 'path': Path(r['path']).name} for r in records(staging/f for f in FILES)]
        manifest = {'schema':'terraproof.workflow-run/3','spec_digest':approval['spec_digest'],
                    'approval': approval, 'intent_document': spec, 'product_facts': facts,
                    'verification': result, 'outputs': listed}
        write(staging/'workflow.json', manifest)
        staging.rename(output)
        published = True
        # Paths in a core evidence report refer to the published directory, not its temporary name.
        calibration_evidence(output, context(approval_path)[2])
        manifest['outputs'] = [{**r, 'path': Path(r['path']).name} for r in records(output/f for f in FILES)]
        write(output/'workflow.json', manifest)
        result = verify(approval_path, output)
        if result['status'] != manifest['verification']['status']:
            render(output,spec,facts,load(output/'summary.json'),geometry=geometry,status=result['status'],review=approval['review'])
            manifest['outputs'] = [{**r, 'path': Path(r['path']).name} for r in records(output/f for f in FILES)]
        manifest['verification'] = result
        write(output/'workflow.json', manifest)
        return result
    except Exception as error:
        # Keep failed staging as inspectable evidence, rather than deleting user data.
        if staging.exists():
            write(staging/'failure.json', {'status': 'failed', 'error': str(error), 'published': False})
        elif published:
            failure = {'status': 'failed', 'grade': 'advisory-only', 'findings': [
                {'requirement': 'run-completion', 'status': 'fail', 'detail': str(error)}]}
            manifest['verification'] = failure
            write(output/'workflow.json', manifest)
            write(output/'failure.json', {'status': 'failed', 'error': str(error), 'published': True})
            render(output,spec,facts,load(output/'summary.json'),geometry=geometry,status='failed',review=approval['review'])
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
