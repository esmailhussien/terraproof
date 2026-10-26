"""Offline checker coverage: unchanged benchmark plus separate exhaustive controls.

Never counts oracle-only rejection as product detection or measures agent lift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from terraproof.checks.rs_processing import check_cloud_mask_applied, check_scale_applied_once
from terraproof.evals.harness import run_benchmark
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    baseline = run_benchmark(work_root=args.work/'benchmark')
    (args.work/'benchmark.json').write_text(json.dumps(baseline, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    strict = args.work/'full-processing'
    strict.mkdir()
    report = {'schema': 'terraproof.checker-scorecard/1', 'model_calls': 0,
        'unchanged_benchmark': baseline['summary'], 'full_processing': full_processing(strict),
        'limitations': ['Synthetic controls chosen to expose sparse-sampling weaknesses; not an error-rate estimate.',
            'The frozen benchmark invocations remain unchanged; the new cohort does not relabel historical blind spots.',
            'No model was run. No agent benefit, token saving or general scientific correctness is established.']}
    (args.work/'scorecard.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({'benchmark': baseline['summary'], 'full_processing': report['full_processing']['summary']}, indent=2))
    return baseline['summary']['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
