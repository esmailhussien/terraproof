"""Explicit central-difference slope contract, including every value and mask cell."""
from __future__ import annotations

import math
import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.terrain import VERTICAL_UNITS

CHECK_ID = 'terrain.slope_formula'
WINDOW_SIZE = 512
RTOL = 2e-6
ATOL = 1e-6


def check_slope_formula(output: dict, dem: dict | None, method: str | None) -> list:
    evidence = {'output': output.get('path'), 'dem': dem.get('path') if dem else None,
                'method': method, 'edge_policy': 'nodata',
                'tolerance': {'rtol': RTOL, 'atol_degrees': ATOL}}
    if method != 'central-difference' or dem is None:
        return [result(CHECK_ID, NOT_RUN, 'Declare slope_method=central-difference and supply a DEM.', **evidence)]
    if output.get('kind') != 'raster' or dem.get('kind') != 'raster':
        return [result(CHECK_ID, NOT_RUN, 'Slope verification requires an output raster and a DEM raster.', **evidence)]
    try:
        with rasterio.open(dem['path']) as src, rasterio.open(output['path']) as dst:
            if src.count != 1 or np.dtype(src.dtypes[0]).kind not in 'iuf':
                return [result(CHECK_ID, NOT_RUN, 'Supply one real-valued DEM band.', **evidence)]
            if src.crs is None or not src.crs.is_projected:
                return [result(CHECK_ID, NOT_RUN, 'The DEM needs a projected CRS with length units.', **evidence)]
            transform = src.transform
            if (not all(math.isfinite(v) for v in transform) or transform.b != 0 or transform.d != 0
                    or not math.isfinite(transform.determinant) or transform.a == 0 or transform.e == 0 or min(src.shape) < 3):
                return [result(CHECK_ID, NOT_RUN, 'Supply a finite, unrotated DEM grid at least 3 by 3.', **evidence)]
            unit = (src.units[0] or '').strip().lower()
            if unit and unit not in VERTICAL_UNITS:
                return [result(CHECK_ID, NOT_RUN, 'The DEM vertical length unit is unsupported.', **evidence)]
            horizontal = src.crs.linear_units_factor[1]
            scale, offset = src.scales[0], src.offsets[0]
            if not all(math.isfinite(v) for v in (horizontal, scale, offset)) or horizontal <= 0:
                return [result(CHECK_ID, NOT_RUN, 'DEM calibration and CRS unit conversion must be finite.', **evidence)]
            factor = VERTICAL_UNITS[unit] / horizontal if unit else 1.0
            if not math.isfinite(factor):
                return [result(CHECK_ID, NOT_RUN, 'Vertical unit conversion is outside finite arithmetic range.', **evidence)]
            evidence.update(vertical_unit=unit or None, vertical_factor=factor,
                            dem_calibration={'scale': scale, 'offset': offset})
            if (dst.count != 1 or np.dtype(dst.dtypes[0]).kind != 'f'
                    or dst.scales[0] != 1 or dst.offsets[0] != 0
                    or (dst.units[0] or '').strip().lower() not in ('', 'degree', 'degrees', 'deg')):
                return [result(CHECK_ID, FAIL, 'The output must be one floating band of physical degrees.', **evidence)]
            if dst.crs != src.crs or dst.transform != transform or dst.shape != src.shape:
                return [result(CHECK_ID, FAIL, 'Slope output CRS, affine and dimensions must exactly match the DEM.', **evidence)]
            dx, dy = abs(transform.a), abs(transform.e)
            compared = mismatched = extra_masked = unsupported = 0
            for row in range(0, src.height, WINDOW_SIZE):
                for col in range(0, src.width, WINDOW_SIZE):
                    height, width = min(WINDOW_SIZE, src.height-row), min(WINDOW_SIZE, src.width-col)
                    r0, c0 = max(0, row-1), max(0, col-1)
                    r1, c1 = min(src.height, row+height+1), min(src.width, col+width+1)
                    halo = Window(c0, r0, c1-c0, r1-r0)
                    raw = src.read(1, window=halo)
                    unmasked = src.read_masks(1, window=halo) > 0
                    if raw.dtype.kind in 'iu' and np.any(unmasked & ((raw > 2**53) | (raw < -2**53))):
                        return [result(CHECK_ID, NOT_RUN, 'DEM integers exceed exact float64 arithmetic range.', **evidence)]
                    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                        physical = (raw.astype('float64') * scale + offset) * factor
                    if np.any(unmasked & np.isfinite(raw) & ~np.isfinite(physical)):
                        return [result(CHECK_ID, NOT_RUN, 'DEM calibration overflow prevents a reliable comparison.', **evidence)]
                    valid = unmasked & np.isfinite(physical)
                    support = np.zeros(raw.shape, dtype=bool)
                    support[1:-1, 1:-1] = (valid[1:-1, 1:-1] & valid[:-2, 1:-1] & valid[2:, 1:-1]
                        & valid[1:-1, :-2] & valid[1:-1, 2:])
                    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                        # A constant offset cancels from derivatives. Subtract stored
                        # values first so a large offset cannot erase a real gradient.
                        stored = raw.astype('float64')
                        gx = ((stored[1:-1, 2:] - stored[1:-1, :-2])/2/dx) * scale * factor
                        gy = ((stored[2:, 1:-1] - stored[:-2, 1:-1])/2/dy) * scale * factor
                        angles = np.degrees(np.arctan(np.hypot(gx, gy)))
                    if np.any(support[1:-1, 1:-1] & (~np.isfinite(gx) | ~np.isfinite(gy))):
                        return [result(CHECK_ID, NOT_RUN, 'Slope arithmetic overflow prevents a reliable comparison.', **evidence)]
                    expected = np.full(raw.shape, np.nan)
                    expected[1:-1, 1:-1] = angles
                    section = np.s_[row-r0:row-r0+height, col-c0:col-c0+width]
                    expected, support = expected[section], support[section]
                    window = Window(col, row, width, height)
                    observed = dst.read(1, window=window)
                    output_unmasked = dst.read_masks(1, window=window) > 0
                    finite = np.isfinite(observed)
                    unsupported += int(np.count_nonzero(output_unmasked & (~support | ~finite)))
                    extra_masked += int(np.count_nonzero(support & ~output_unmasked))
                    keep = support & output_unmasked & finite
                    compared += int(np.count_nonzero(keep))
                    mismatched += int(np.count_nonzero(keep & ~np.isclose(observed, expected, rtol=RTOL, atol=ATOL)))
            evidence.update(compared_cells=compared, mismatched_cells=mismatched,
                            extra_masked_cells=extra_masked, unsupported_output_cells=unsupported)
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError) as error:
        return [result(CHECK_ID, NOT_RUN, f'Cannot compare slope rasters ({type(error).__name__}).', **evidence)]
    if mismatched or extra_masked or unsupported:
        return [result(CHECK_ID, FAIL, 'Slope values or complete stencil/edge validity disagree with the declared method.', **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, 'No complete finite DEM stencil could be compared.', **evidence)]
    return [result(CHECK_ID, PASS, 'Every slope value and mask cell matches the declared calibrated central-difference method.', **evidence)]
