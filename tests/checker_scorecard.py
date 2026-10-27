"""Offline checker coverage: unchanged benchmark plus separate exhaustive and source-aware controls.

Never counts oracle-only rejection as product detection or measures agent lift. The source-aware
section (Phase 6 C) regenerates frozen task fixtures and runs extra check invocations that pass
the source inputs a user would have; its results are reported apart from the frozen counts.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from terraproof.checks import run_checks
from terraproof.checks.rs_processing import check_cloud_mask_applied, check_scale_applied_once
from terraproof.evals.harness import run_benchmark
from terraproof.evals.recipes import REGISTRY
from terraproof.inspect import inspect_dataset


def write(path, data, *, scales=None, offsets=None, nodata=-9999):
    with rasterio.open(path, 'w', driver='GTiff', height=data.shape[1], width=data.shape[2],
        count=data.shape[0], dtype=data.dtype, crs='EPSG:32636',
        transform=from_origin(500000, 5000000, 10, 10), nodata=nodata) as dst:
        dst.write(data)
        if scales:
            dst.scales = scales
            dst.offsets = offsets
    return path


def full_processing(root):
    records = []
    protected = []
    # Values are specified here rather than imported from the checker constants.
    calibrations = [('s2-l2a', [.0001]*2, [-.1]*2),
                    ('landsat-c2-l2', [.0000275]*2, [-.2]*2),
                    (None, [.0001, .0002], [-.1, -.2])]
    for index, (encoding, scales, offsets) in enumerate(calibrations):
        folder = root/f'calibration-{index}'
        folder.mkdir()
        raw = np.full((2, 129, 131), 12000, dtype='uint16')
        data = np.stack([raw[b].astype('float64')*scales[b]+offsets[b] for b in range(2)]).astype('float32')
        source = write(folder/'source.tif', raw, scales=scales, offsets=offsets, nodata=65535)
        protected.append((source, hashlib.sha256(source.read_bytes()).hexdigest()))
        for defect in ('reference', 'off-stride', 'small-sampled', 'other-band'):
            delivered = data.copy()
            location = (1, 1, 1) if defect == 'other-band' else (0, 0, 0) if defect == 'small-sampled' else (0, 1, 1)
            if defect != 'reference':
                delivered[location] += .125
            output = write(folder/(defect+'.tif'), delivered)
            # Scalar, exhaustive truth calculation is independent of checker helpers/tolerances.
            with rasterio.open(output) as dst:
                observed = dst.read()
            wrong = sum(abs(float(observed[b, r, c])-(12000*scales[b]+offsets[b])) > .00001
                        for b in range(2) for r in range(129) for c in range(131))
            assert wrong == (0 if defect == 'reference' else 1)
            arguments = (inspect_dataset(output), inspect_dataset(source))
            sampled = check_scale_applied_once(*arguments, encoding=encoding)[0]
            full = check_scale_applied_once(*arguments, encoding=encoding, full_scan=True)[0]
            records.append({'family': encoding or 'per-band-metadata', 'control': defect,
                'oracle_wrong_pixels': wrong, 'sampled': sampled.status, 'full': full.status})
    for kind, clear, flag in [('s2-scl', 4, 9), ('landsat-qa-pixel', 64, 8)]:
        folder = root/kind
        folder.mkdir()
        codes = np.full((1, 129, 131), clear, dtype='uint16')
        codes[0, 0, 0] = codes[0, 1, 1] = flag
        qa = write(folder/'qa.tif', codes, nodata=65535)
        protected.append((qa, hashlib.sha256(qa.read_bytes()).hexdigest()))
        for defect in ('reference', 'off-stride', 'other-band'):
            data = np.full((2, 129, 131), .3, dtype='float32')
            data[:, 0, 0] = data[:, 1, 1] = -9999
            if defect != 'reference':
                data[1 if defect == 'other-band' else 0, 1, 1] = .3
            output = write(folder/(defect+'.tif'), data)
            with rasterio.open(output) as dst:
                observed = dst.read(masked=True)
            wrong = sum(not bool(observed.mask[b, r, c]) for b in range(2) for r, c in ((0, 0), (1, 1)))
            assert wrong == (0 if defect == 'reference' else 1)
            arguments = (inspect_dataset(output), str(qa), kind)
            sampled = check_cloud_mask_applied(*arguments)[0]
            full = check_cloud_mask_applied(*arguments, full_scan=True)[0]
            records.append({'family': kind, 'control': defect, 'oracle_wrong_pixels': wrong,
                'sampled': sampled.status, 'full': full.status})
    wrong = [r for r in records if r['control'] != 'reference']
    correct = [r for r in records if r['control'] == 'reference']
    unchanged = all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in protected)
    summary = {'correct_controls': len(correct), 'wrong_controls': len(wrong),
        'correct_sampled_passes': sum(r['sampled'] == 'pass' for r in correct),
        'correct_full_passes': sum(r['full'] == 'pass' for r in correct),
        'sampled_rejections': sum(r['sampled'] == 'fail' for r in wrong),
        'full_rejections': sum(r['full'] == 'fail' for r in wrong), 'sources_unchanged': unchanged}
    assert unchanged and summary['correct_full_passes'] == len(correct) and summary['full_rejections'] == len(wrong)
    return {'summary': summary, 'controls': records}


def _band(path, number=None):
    return dict(inspect_dataset(str(path)), band=number)


def _index(formula, **roles):
    """run_checks kwargs for rs.index_formula with role -> path or (path, band)."""
    bands = {role: _band(*value) if isinstance(value, tuple) else _band(value) for role, value in roles.items()}
    return 'rs.index_formula', {'index_formula': formula, 'index_bands': bands}


def _dnbr_reference(folder):
    """Independent scalar pre-minus-post NBR from the written source bands (not checker code)."""
    names = ('pre_nir', 'pre_swir2', 'post_nir', 'post_swir2')
    bands = []
    for name in names:
        with rasterio.open(folder/f'{name}.tif') as src:
            bands.append(src.read(1).astype('float64'))
    pn, ps, qn, qs = bands
    out = np.full(pn.shape, -9999, dtype='float32')
    for r in range(pn.shape[0]):
        for c in range(pn.shape[1]):
            out[r, c] = (pn[r, c]-ps[r, c])/(pn[r, c]+ps[r, c]) - (qn[r, c]-qs[r, c])/(qn[r, c]+qs[r, c])
    with rasterio.open(folder/'nbr_prefire.tif') as grid:
        profile = grid.profile
    with rasterio.open(folder/'dnbr.tif', 'w', **profile) as dst:
        dst.write(out, 1)
    return 'dnbr.tif'


def _dnbr_roles(f):
    return _index('dnbr', pre_nir=f/'pre_nir.tif', pre_swir2=f/'pre_swir2.tif',
                  post_nir=f/'post_nir.tif', post_swir2=f/'post_swir2.tif')


def _evi_roles(f):
    return _index('evi', blue=(f/'bands.tif', 1), red=(f/'bands.tif', 2), nir=(f/'bands.tif', 3))


def _stack(reduction, files, weights=None, min_count=None):
    return 'rs.stack_reduction', {'stack': [inspect_dataset(str(f)) for f in files], 'stack_reduction': reduction,
                                  'stack_weights': weights, 'stack_min_count': min_count}


def _request(folder):
    return json.loads((folder/'request.json').read_text(encoding='utf-8'))


def _storm_roles(f):
    """Interval hours from the request's own ISO intervals."""
    request = _request(f)
    hours = [(datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600
             for start, end in request['intervals']]
    return _stack('weighted-sum', [f/name for name in request['files']], hours)


def _trend_roles(f):
    """Decimal years from the request's own dates and year length."""
    request = _request(f)
    first = datetime.fromisoformat(request['dates'][0])
    years = [(datetime.fromisoformat(d) - first).days / request['year_days'] for d in request['dates']]
    return _stack('ols-slope', [f/name for name in request['files']], years, request['minimum_observations'])


def _composite_roles(f):
    return _stack('median', [f/f's2_date{i}_red.tif' for i in (1, 2, 3)])


def _monthly_roles(f):
    return _stack('median', [f/f'ndvi_2024-06_date{i}.tif' for i in (1, 2, 3)])


def _sar_roles(f):
    return _stack('mean-power-db', [f/f'vv_date{i}.tif' for i in (1, 2, 3)])


# (task, output file or builder, correct?, frozen blind spot it targets or None, check kwargs builder)
SOURCE_AWARE = [
    ('indices-ndvi-physical-inputs', 'ndvi.tif', True, None,
     lambda f: _index('ndvi', nir=f/'nir_dn.tif', red=f/'red_dn.tif')),
    ('indices-ndvi-physical-inputs', 'ndvi_dn_ratio.tif', False, 'unscaled-dn-ratio',
     lambda f: _index('ndvi', nir=f/'nir_dn.tif', red=f/'red_dn.tif')),
    ('indices-water-definition-grid', 'ndwi_mcfeeters.tif', True, None,
     lambda f: _index('ndwi', green=f/'green.tif', nir=f/'nir.tif')),
    ('indices-water-definition-grid', 'mndwi.tif', True, None,
     lambda f: _index('mndwi', green=f/'green.tif', swir1=f/'swir1.tif')),
    ('indices-water-definition-grid', 'ndwi_mislabeled.tif', False, 'gao-moisture-mislabeled',
     lambda f: _index('ndwi', green=f/'green.tif', nir=f/'nir.tif')),
    ('indices-burn-evi-savi-ranges', 'nbr_prefire.tif', True, None,
     lambda f: _index('nbr', nir=f/'pre_nir.tif', swir2=f/'pre_swir2.tif')),
    ('indices-burn-evi-savi-ranges', 'nbr_postfire.tif', True, None,
     lambda f: _index('nbr', nir=f/'post_nir.tif', swir2=f/'post_swir2.tif')),
    ('indices-burn-evi-savi-ranges', 'nbr_swir1.tif', False, 'nbr-wrong-swir-band',
     lambda f: _index('nbr', nir=f/'pre_nir.tif', swir2=f/'pre_swir2.tif')),
    ('indices-burn-evi-savi-ranges', _dnbr_reference, True, None, _dnbr_roles),
    ('indices-burn-evi-savi-ranges', 'dnbr_reversed.tif', False, 'reversed-dnbr-sign', _dnbr_roles),
    ('three-band-vegetation-index', 'result.tif', True, None, _evi_roles),
    ('three-band-vegetation-index', 'stored-values.tif', False, 'stored-values', _evi_roles),
    ('three-band-vegetation-index', 'one-band-calibration.tif', False, 'one-band-calibration', _evi_roles),
    # Group 2: time- and stack-aware reductions.
    ('satellite-seasonal-harmonized-composite', 'composite.tif', True, None, _composite_roles),
    ('satellite-seasonal-harmonized-composite', 'composite_cloudy.tif', False, 'cloudy-dates-included', _composite_roles),
    ('ts-monthly-ndvi-composite-counts', 'ndvi_2024-06.tif', True, None, _monthly_roles),
    ('ts-monthly-ndvi-composite-counts', 'ndvi_2024-06_index_of_medians.tif', False, 'index-of-medians-composite',
     _monthly_roles),
    ('ts-monthly-ndvi-composite-counts', 'ndvi_2024-06_zero_filled.tif', False, 'all-invalid-zero-filled',
     _monthly_roles),
    ('sar-db-linear-monthly-mean', 'vv_monthly_mean_db.tif', True, None, _sar_roles),
    ('sar-db-linear-monthly-mean', 'vv_monthly_mean_naive_db.tif', False, 'naive-db-average', _sar_roles),
    ('storm-total-rainfall', 'result.tif', True, None, _storm_roles),
    ('storm-total-rainfall', 'sum-of-rates.tif', False, 'sum-of-rates', _storm_roles),
    ('storm-total-rainfall', 'equal-duration-mean.tif', False, 'equal-duration-mean', _storm_roles),
    ('vegetation-change-rate', 'result.tif', True, None, _trend_roles),
    ('vegetation-change-rate', 'equally-spaced-index.tif', False, 'equally-spaced-index', _trend_roles),
    ('vegetation-change-rate', 'missing-as-zero.tif', False, 'missing-as-zero', _trend_roles),
]


def source_aware(root, frozen_blind_spots):
    records = []
    folders = {}
    for task, output, correct, target, build in SOURCE_AWARE:
        if task not in folders:
            folders[task] = root/task
            folders[task].mkdir()
            REGISTRY[task](folders[task])
        folder = folders[task]
        name = output(folder) if callable(output) else output
        check_id, kwargs = build(folder)
        found = [r for r in run_checks([inspect_dataset(str(folder/name))], **kwargs) if r.id == check_id]
        status = found[0].status if found else 'missing'
        if target is not None:
            assert {'task': task, 'control': target} in frozen_blind_spots, (task, target)
        records.append({'task': task, 'output': name, 'correct': correct, 'frozen_blind_spot': target,
                        'check': check_id, 'status': status})
    wrong = [r for r in records if not r['correct']]
    correct = [r for r in records if r['correct']]
    summary = {'frozen_blind_spots': len(frozen_blind_spots),
               'targeted_blind_spots': len({(r['task'], r['frozen_blind_spot']) for r in wrong}),
               'rejected_blind_spots': len({(r['task'], r['frozen_blind_spot']) for r in wrong if r['status'] == 'fail'}),
               'correct_controls': len(correct), 'correct_passes': sum(r['status'] == 'pass' for r in correct),
               'false_passes': sum(r['status'] == 'pass' for r in wrong)}
    assert summary['correct_passes'] == len(correct) and summary['false_passes'] == 0, records
    return {'summary': summary, 'controls': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    baseline = run_benchmark(work_root=args.work/'benchmark')
    (args.work/'benchmark.json').write_text(json.dumps(baseline, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    strict = args.work/'full-processing'
    strict.mkdir()
    aware = args.work/'source-aware'
    aware.mkdir()
    report = {'schema': 'terraproof.checker-scorecard/1', 'model_calls': 0,
        'unchanged_benchmark': baseline['summary'], 'full_processing': full_processing(strict),
        'source_aware': source_aware(aware, baseline['summary']['checker_blind_spots']),
        'limitations': ['Synthetic controls chosen to expose sparse-sampling weaknesses; not an error-rate estimate.',
            'The frozen benchmark invocations remain unchanged; the new cohort does not relabel historical blind spots.',
            'No model was run. No agent benefit, token saving or general scientific correctness is established.']}
    (args.work/'scorecard.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({'benchmark': baseline['summary'], 'full_processing': report['full_processing']['summary'],
                      'source_aware': report['source_aware']['summary']}, indent=2))
    return baseline['summary']['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
