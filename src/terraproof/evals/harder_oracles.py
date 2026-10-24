"""Independent scalar answers for the six added artifact tasks.

Only delivered files, declared input files and their metadata are observed here.
No reference arrays, recipe functions, seeded-output names or check verdicts are used.
"""
from datetime import datetime
import json
import math
import numpy as np
import rasterio
from terraproof.evals.oracles import Oracle

def _read(path):
    with rasterio.open(path) as src:
        return (src.read(masked=True), src.profile, src.scales, src.offsets, src.units)

def _bounds(transform, row, col):
    x0 = transform.a * col + transform.b * row + transform.c
    y0 = transform.d * col + transform.e * row + transform.f
    x1 = transform.a * (col + 1) + transform.b * (row + 1) + transform.c
    y1 = transform.d * (col + 1) + transform.e * (row + 1) + transform.f
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

def _overlap(first, second):
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(0.0, min(first[3], second[3]) - max(first[1], second[1]))

def answer(kind, root):
    """Compute every expected cell from declared inputs by scalar arithmetic."""
    params = json.loads((root / 'request.json').read_text(encoding='utf-8'))
    if kind in ('landcover', 'population'):
        data, source, *_ = _read(root / 'source.tif')
        _, grid, *_ = _read(root / 'target_grid.tif')
        expected = np.zeros((grid['height'], grid['width']), dtype='float64')
        valid = np.zeros(expected.shape, dtype=bool)
        mask = np.ma.getmaskarray(data)[0]
        for r, c in np.ndindex(expected.shape):
            target = _bounds(grid['transform'], r, c)
            cell_area = (target[2] - target[0]) * (target[3] - target[1])
            covered = value = 0.0
            classes = {}
            for sr, sc in np.ndindex(data.shape[1:]):
                source_bounds = _bounds(source['transform'], sr, sc)
                area = _overlap(target, source_bounds)
                if area == 0 or mask[sr, sc]:
                    continue
                covered += area
                if kind == 'landcover':
                    label = int(data[0, sr, sc])
                    classes[label] = classes.get(label, 0.0) + area
                else:
                    source_area = (source_bounds[2] - source_bounds[0]) * (source_bounds[3] - source_bounds[1])
                    value += float(data[0, sr, sc]) * area / source_area
            if kind == 'landcover':
                valid[r, c] = bool(classes) and covered / cell_area >= params['minimum_valid_fraction']
                if valid[r, c]:
                    expected[r, c] = min(classes, key=lambda label: (-classes[label], label))
            else:
                valid[r, c] = math.isclose(covered, cell_area, rel_tol=1e-10, abs_tol=1e-08)
                expected[r, c] = value
        return (expected, valid, grid)
    if kind == 'slope':
        data, grid, _, _, units = _read(root / 'elevation.tif')
        factor = {'ft': 0.3048, 'm': 1.0}[units[0]]
        expected = np.zeros(data.shape[1:])
        valid = np.zeros(expected.shape, bool)
        mask = np.ma.getmaskarray(data)[0]
        for r in range(1, expected.shape[0] - 1):
            for c in range(1, expected.shape[1] - 1):
                cells = [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
                if any((mask[y, x] for y, x in cells)):
                    continue
                dx = factor * (float(data[0, r, c + 1]) - float(data[0, r, c - 1])) / (2 * abs(grid['transform'].a))
                dy = factor * (float(data[0, r + 1, c]) - float(data[0, r - 1, c])) / (2 * abs(grid['transform'].e))
                expected[r, c] = math.degrees(math.atan(math.hypot(dx, dy)))
                valid[r, c] = True
        return (expected, valid, grid)
    if kind in ('trend', 'rain'):
        arrays = [_read(root / name) for name in params['files']]
        grid = arrays[0][1]
        expected = np.zeros(arrays[0][0].shape[1:])
        valid = np.zeros(expected.shape, bool)
        for r, c in np.ndindex(expected.shape):
            observations = [(i, float(a[0][0, r, c])) for i, a in enumerate(arrays) if not np.ma.getmaskarray(a[0])[0, r, c]]
            if kind == 'trend':
                if len(observations) < params['minimum_observations']:
                    continue
                start = datetime.fromisoformat(params['dates'][0])
                pairs = [((datetime.fromisoformat(params['dates'][i]) - start).total_seconds() / 86400 / params['year_days'], v) for i, v in observations]
                mx = sum((x for x, y in pairs)) / len(pairs)
                my = sum((y for x, y in pairs)) / len(pairs)
                expected[r, c] = sum(((x - mx) * (y - my) for x, y in pairs)) / sum(((x - mx) ** 2 for x, y in pairs))
                valid[r, c] = True
            elif len(observations) == len(arrays):
                expected[r, c] = sum((value * (datetime.fromisoformat(params['intervals'][i][1]) - datetime.fromisoformat(params['intervals'][i][0])).total_seconds() / 3600 for i, value in observations))
                valid[r, c] = True
        return (expected, valid, grid)
    if kind == 'evi':
        data, grid, scales, offsets, _ = _read(root / 'bands.tif')
        expected = np.zeros(data.shape[1:])
        valid = np.zeros(expected.shape, bool)
        for r, c in np.ndindex(expected.shape):
            if np.any(np.ma.getmaskarray(data)[:, r, c]):
                continue
            blue, red, nir = [float(data[i, r, c]) * scales[i] + offsets[i] for i in range(3)]
            denominator = nir + 6 * red - 7.5 * blue + 1
            if abs(denominator) <= 1e-12:
                continue
            expected[r, c] = 2.5 * (nir - red) / denominator
            valid[r, c] = True
        return (expected, valid, grid)
    raise ValueError(kind)

def grade(kind, root, delivered):
    expected, valid, grid = answer(kind, root)
    values, profile, _, _, _ = _read(delivered)
    oracle = Oracle('Every delivered cell, validity and spatial metadata against independent input arithmetic')
    shape_ok = values.shape == (1, *expected.shape)
    oracle.equal('delivered band count and shape', values.shape, (1, *expected.shape))
    oracle.require('delivered CRS', profile['crs'] == grid['crs'], str(profile['crs']), str(grid['crs']))
    oracle.equal('delivered affine grid', tuple(profile['transform']), tuple(grid['transform']))
    if not shape_ok:
        return oracle
    observed_valid = ~np.ma.getmaskarray(values)[0]
    oracle.equal('full delivered mask equals required support', int(np.count_nonzero(observed_valid != valid)), 0)
    actual = np.ma.getdata(values)[0].astype('float64')
    matches = np.isfinite(actual) & np.isclose(actual, expected, rtol=2e-06, atol=1e-06)
    oracle.equal('all supported delivered pixels match independent values', int(np.count_nonzero(valid & ~matches)), 0)
    return oracle
