"""Six synthetic artifact tasks authored from the frozen pre-skill pitfall list.

Reference solutions use array operations; the separate oracle re-reads all inputs
and evaluates scalar cell relationships without importing these constructions.
"""
from datetime import datetime, timedelta, timezone
import json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject
from rasterio.enums import Resampling
from terraproof.evals.fixtures import write_raster_grid
from terraproof.evals.harder_oracles import grade
from terraproof.inspect import inspect_dataset
from terraproof.evals.recipes._util import check_step, correct, wrong, recipe
NODATA = -9999.0
GRID = from_origin(500000, 5000000, 10, 10)

def _request(root, **parameters):
    (root / 'request.json').write_text(json.dumps(parameters, sort_keys=True, indent=2) + '\n', encoding='utf-8')

def _finish(root, task_id, kind, expected, valid, transform, mistakes, *, dtype='float32', nodata=NODATA, dem=None):

    def control(name, values, support, is_wrong):
        data = np.where(support, values, nodata).astype(dtype)
        path = write_raster_grid(root / (name + '.tif'), data, transform=transform, nodata=nodata)
        if dem is None:
            steps = [check_step('check ' + name + '.tif', [path])]
        else:
            steps = [check_step('check ' + name + '.tif --dem ' + dem, [path], dem=inspect_dataset(str(root / dem)))]
        constructor = wrong if is_wrong else correct
        return constructor(name, 'Synthetic artifact evaluated cell-by-cell from declared input evidence.', steps, grade(kind, root, path))
    reference = control('result', expected, valid, False)
    seeded = [control(name, data, support, True) for name, data, support in mistakes]
    return recipe(task_id, reference, seeded, automated_scope=['Every delivered pixel and mask against independent scalar input arithmetic; spatial contract and raster checks.'], remaining=['Difficulty for a live agent is unmeasured; this is an offline synthetic artifact task, not scientific certification.'])

def landcover_summary(root):
    r, c = np.indices((24, 24))
    major = 1 + (r // 4 + 2 * (c // 4)) % 3
    source = major.copy().astype('uint8')
    source[r % 4 == 0] = 1 + major[r % 4 == 0] % 3
    source[:4, :4] = 255
    source[0, 0] = 2
    source[1, 1] = 2
    source[2, 2] = 1
    source[4:6, 4:8] = 3
    source[6:8, 4:8] = 2
    source[9, 13] = 255
    source_grid = GRID
    target_grid = from_origin(500000, 5000000, 40, 40)
    write_raster_grid(root / 'source.tif', source, transform=source_grid, nodata=255)
    write_raster_grid(root / 'target_grid.tif', np.zeros((6, 6), dtype='uint8'), transform=target_grid, nodata=255)
    _request(root, minimum_valid_fraction=0.5, tie_break='smallest code', quantity='categorical land cover')
    blocks = source.reshape(6, 4, 6, 4).transpose(0, 2, 1, 3).reshape(6, 6, 16)
    counts = np.stack([(blocks == label).sum(axis=2) for label in (1, 2, 3)])
    expected = 1 + np.argmax(counts, axis=0)
    support = (blocks != 255).sum(axis=2) >= 8
    nearest = source[::4, ::4]
    return _finish(root, 'landcover-summary-grid', 'landcover', expected, support, target_grid, [('nearest', nearest, support), ('coverage-ignored', expected, (blocks != 255).any(axis=2))], dtype='uint8', nodata=255)

def terrain_slope(root):
    r, c = np.indices((16, 16))
    z = (50 + 0.4 * c * c + 0.7 * r * r + 0.05 * r * c) / 0.3048
    z = z.astype('float32')
    z[5, 7] = NODATA
    z[10, 11] = NODATA
    transform = from_origin(500000, 5000000, 30, 60)
    write_raster_grid(root / 'elevation.tif', z, transform=transform, unit='ft')
    _request(root, method='central differences', output_units='degrees', edge_policy='nodata', stencil='center and four direct neighbours must be valid')
    valid = z != NODATA
    support = np.zeros(z.shape, bool)
    support[1:-1, 1:-1] = valid[1:-1, 1:-1] & valid[:-2, 1:-1] & valid[2:, 1:-1] & valid[1:-1, :-2] & valid[1:-1, 2:]

    def slope(factor, dy):
        values = z.astype('float64') * factor
        gx = (values[1:-1, 2:] - values[1:-1, :-2]) / 60
        gy = (values[2:, 1:-1] - values[:-2, 1:-1]) / (2 * dy)
        out = np.zeros(z.shape)
        out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(gx, gy)))
        return out
    return _finish(root, 'terrain-slope-map', 'slope', slope(0.3048, 60), support, transform, [('vertical-units-ignored', slope(1, 60), support), ('square-pixels-assumed', slope(0.3048, 30), support)], dem='elevation.tif')

def population_transfer(root):
    r, c = np.indices((16, 16))
    source = (12 + 2 * r + 3 * c).astype('float32')
    source[3, 4] = NODATA
    source[0, 0] = NODATA
    target = from_origin(499995, 5000005, 15, 15)
    write_raster_grid(root / 'source.tif', source, transform=GRID)
    write_raster_grid(root / 'target_grid.tif', np.zeros((11, 11), dtype='float32'), transform=target)
    _request(root, quantity='population count per source cell', within_cell_distribution='uniform', incomplete_coverage='nodata')
    sx = 500000 + np.arange(17) * 10
    tx = 499995 + np.arange(12) * 15
    sy = 5000000 - np.arange(17) * 10
    ty = 5000005 - np.arange(12) * 15
    wx = np.maximum(0, np.minimum(tx[1:, None], sx[None, 1:]) - np.maximum(tx[:-1, None], sx[None, :-1]))
    wy = np.maximum(0, np.minimum(ty[:-1, None], sy[None, :-1]) - np.maximum(ty[1:, None], sy[None, 1:]))
    support = source != NODATA
    expected = wy @ np.where(support, source / 100, 0) @ wx.T
    coverage = wy @ support.astype(float) @ wx.T
    valid = np.isclose(coverage, 225, rtol=0, atol=1e-08)
    mistakes = []
    for name, method in [('bilinear', Resampling.bilinear), ('nearest-count', Resampling.nearest)]:
        out = np.full((11, 11), NODATA, dtype='float32')
        reproject(source, out, src_transform=GRID, src_crs='EPSG:32636', src_nodata=NODATA, dst_transform=target, dst_crs='EPSG:32636', dst_nodata=NODATA, resampling=method)
        mistakes.append((name, out, valid))
    return _finish(root, 'population-grid-transfer', 'population', expected, valid, target, mistakes)

def vegetation_trend(root):
    dates = ['2019-12-01', '2020-02-29', '2020-10-15', '2021-08-20', '2023-06-15']
    t = np.array([(datetime.fromisoformat(d) - datetime.fromisoformat(dates[0])).days / 365.25 for d in dates])
    r, c = np.indices((16, 16))
    frames = []
    files = []
    for i, x in enumerate(t):
        values = (0.25 + 0.005 * r + 0.003 * c + (0.01 + 0.001 * r - 0.0007 * c) * x + 0.002 * ((r + c + i) % 3 - 1)).astype('float32')
        values[(r + 2 * c + i) % 7 == 0] = NODATA
        if i >= 2:
            values[0, 0] = NODATA
        name = f'observation-{i}.tif'
        files.append(name)
        write_raster_grid(root / name, values, transform=GRID)
        frames.append(values)
    _request(root, dates=dates, files=files, year_days=365.25, minimum_observations=3, method='ordinary least squares')
    y = np.array(frames, dtype='float64')
    valid = y != NODATA
    support = valid.sum(axis=0) >= 3

    def fit(axis, missing_zero=False):
        keep = np.ones_like(valid) if missing_zero else valid
        yy = np.where(valid, y, 0)
        xx = np.asarray(axis)[:, None, None]
        n = keep.sum(axis=0)
        mx = (xx * keep).sum(axis=0) / n
        my = (yy * keep).sum(axis=0) / n
        numerator = ((xx - mx) * (yy - my) * keep).sum(axis=0)
        denominator = ((xx - mx) ** 2 * keep).sum(axis=0)
        return np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)
    return _finish(root, 'vegetation-change-rate', 'trend', fit(t), support, GRID, [('equally-spaced-index', fit(np.arange(5)), support), ('missing-as-zero', fit(t, True), support)])

def storm_rainfall(root):
    durations = [1, 4.5, 7.5, 11]
    start = datetime(2024, 2, 28, 12, tzinfo=timezone.utc)
    intervals = []
    frames = []
    files = []
    r, c = np.indices((16, 16))
    for i, hours in enumerate(durations):
        end = start + timedelta(hours=hours)
        intervals.append([start.isoformat(), end.isoformat()])
        start = end
        values = (0.15 + 0.01 * r + 0.02 * c + 0.1 * i).astype('float32')
        if i == 1:
            values[2, 3] = NODATA
        if i == 3:
            values[5, 9] = NODATA
        name = f'interval-{i}.tif'
        files.append(name)
        frames.append(values)
        write_raster_grid(root / name, values, transform=GRID, unit='mm/h')
    _request(root, files=files, intervals=intervals, rate_units='mm/hour', incomplete_coverage='nodata')
    values = np.array(frames, dtype='float64')
    support = (values != NODATA).all(axis=0)
    expected = (values * np.array(durations)[:, None, None]).sum(axis=0)
    return _finish(root, 'storm-total-rainfall', 'rain', expected, support, GRID, [('sum-of-rates', values.sum(axis=0), support), ('equal-duration-mean', values.mean(axis=0) * 24, support)])

def vegetation_index(root):
    r, c = np.indices((16, 16))
    raw = np.array([1800 + 10 * r + 3 * c, 1500 + 8 * r + 4 * c, 12000 + 15 * r + 5 * c], dtype='uint16')
    raw[0, 8, 4] = 65535
    raw[1, 2, 7] = 65535
    raw[2, 3, 10] = 65535
    raw[:, 1, 1] = [2800, 850, 4400]
    raw[2, 0, 1] = 4016
    scales = np.array([0.0001, 0.0002, 5e-05])
    offsets = np.array([-0.08, -0.12, -0.02])
    write_raster_grid(root / 'bands.tif', raw, transform=GRID, nodata=65535, scales=scales, offsets=offsets, descriptions=('blue', 'red', 'nir'))
    _request(root, index='EVI', band_order=['blue', 'red', 'nir'], coefficients=[2.5, 6, 7.5, 1], undefined_denominator='nodata')
    physical = raw.astype('float64') * scales[:, None, None] + offsets[:, None, None]

    def index(values):
        blue, red, nir = values
        den = nir + 6 * red - 7.5 * blue + 1
        return np.divide(2.5 * (nir - red), den, out=np.zeros_like(den), where=np.abs(den) > 1e-12)
    denominator = physical[2] + 6 * physical[1] - 7.5 * physical[0] + 1
    support = (raw != 65535).all(axis=0) & (np.abs(denominator) > 1e-12)
    return _finish(root, 'three-band-vegetation-index', 'evi', index(physical), support, GRID, [('stored-values', index(raw.astype('float64')), support), ('one-band-calibration', index(raw.astype('float64') * scales[0] + offsets[0]), support)])
RECIPES = {'landcover-summary-grid': landcover_summary, 'terrain-slope-map': terrain_slope, 'population-grid-transfer': population_transfer, 'vegetation-change-rate': vegetation_trend, 'storm-total-rainfall': storm_rainfall, 'three-band-vegetation-index': vegetation_index}
