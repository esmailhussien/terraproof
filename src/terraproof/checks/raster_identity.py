"""Opt-in decoded raster identity: all bands, valid samples, masks and grid metadata."""
from __future__ import annotations

import math
import numpy as np
import rasterio
from rasterio.windows import Window

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result

CHECK_ID = 'raster.source_identity'
WINDOW_SIZE = 512


def check_source_identity(output: dict, source: dict | None) -> list:
    evidence = {'output': output.get('path'), 'source': source.get('path') if source else None,
                'comparison': 'exact valid samples; binary validity masks; decoded data, not file bytes'}
    if source is None or output.get('kind') != 'raster' or source.get('kind') != 'raster':
        return [result(CHECK_ID, NOT_RUN, 'Supply a raster output and compare_to source for raster_identity.', **evidence)]
    try:
        with rasterio.open(source['path']) as src, rasterio.open(output['path']) as dst:
            if any(np.dtype(dtype).kind not in 'iuf' for dtype in (*src.dtypes, *dst.dtypes)):
                return [result(CHECK_ID, NOT_RUN, 'Raster identity supports real integer and floating bands.', **evidence)]
            if src.crs is None or not all(math.isfinite(v) for v in src.transform) or not math.isfinite(src.transform.determinant) or src.transform.determinant == 0:
                return [result(CHECK_ID, NOT_RUN, 'The source needs a declared CRS and a finite nondegenerate grid.', **evidence)]
            if not all(math.isfinite(v) for v in (*src.scales, *src.offsets, *dst.scales, *dst.offsets)):
                return [result(CHECK_ID, NOT_RUN, 'Raster scale/offset metadata must be finite.', **evidence)]
            differences = []
            for label, same in [
                ('CRS', dst.crs == src.crs), ('affine', dst.transform == src.transform),
                ('dimensions', dst.shape == src.shape), ('band count', dst.count == src.count),
                ('band dtypes', dst.dtypes == src.dtypes), ('scales', dst.scales == src.scales),
                ('offsets', dst.offsets == src.offsets), ('band units', dst.units == src.units),
            ]:
                if not same: differences.append(label)
            nodata_equal = (len(dst.nodatavals) == len(src.nodatavals) and all(
                a == b or (a is not None and b is not None and math.isnan(a) and math.isnan(b))
                for a, b in zip(dst.nodatavals, src.nodatavals)))
            if not nodata_equal: differences.append('nodata')
            if differences:
                return [result(CHECK_ID, FAIL, 'Raster grid or band metadata differs from its declared source.',
                               metadata_differences=differences, **evidence)]
            compared = mismatched = mask_errors = 0
            for band in range(1, src.count+1):
                for row in range(0, src.height, WINDOW_SIZE):
                    for col in range(0, src.width, WINDOW_SIZE):
                        window = Window(col, row, min(WINDOW_SIZE, src.width-col), min(WINDOW_SIZE, src.height-row))
                        expected, observed = src.read(band, window=window), dst.read(band, window=window)
                        smask, dmask = src.read_masks(band, window=window) > 0, dst.read_masks(band, window=window) > 0
                        mask_errors += int(np.count_nonzero(smask != dmask))
                        keep = smask & dmask
                        equal = expected == observed
                        if expected.dtype.kind == 'f': equal |= np.isnan(expected) & np.isnan(observed)
                        compared += int(np.count_nonzero(keep))
                        mismatched += int(np.count_nonzero(keep & ~equal))
            evidence.update(compared_band_cells=compared, mismatched_band_cells=mismatched,
                            mask_mismatched_band_cells=mask_errors, bands=src.count)
    except (rasterio.errors.RasterioIOError, ValueError, OverflowError) as error:
        return [result(CHECK_ID, NOT_RUN, f'Cannot compare raster samples ({type(error).__name__}).', **evidence)]
    if mismatched or mask_errors:
        return [result(CHECK_ID, FAIL, 'Raster valid samples or complete band validity masks differ from the source.', **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, 'No jointly valid source/output sample could be compared.', **evidence)]
    return [result(CHECK_ID, PASS, 'Every valid sample, band validity mask and declared grid/band metadata matches the source.', **evidence)]
