"""Native QA acquisition support and optional uncertainty filtering, before approval."""
from contextlib import ExitStack
from decimal import Decimal
import math

import numpy as np
import rasterio
from rasterio.features import geometry_window
from rasterio.windows import Window, transform as window_transform
from shapely.geometry import mapping

from terraproof._common import InputError


def uncertainty_ceiling(intent):
    value = intent.get('max_uncertainty_kelvin')
    if value is None:
        return None
    # Native ST_QA is integer hundredths of kelvin. Decimal avoids dropping 2.01 K
    # because binary floating point represents 2.01*100 just below 201.
    return 32767 if value >= 327.67 else int(Decimal(str(value))*100)


def uncertainty_statistics(histogram, missing):
    count = int(histogram.sum())
    result = {'known_count':count,'missing_count':int(missing),'minimum_kelvin':None,'maximum_kelvin':None,
              'mean_kelvin':None,'percentiles_kelvin':None,
              'fraction_above_2_kelvin':None,'fraction_above_3_kelvin':None,'fraction_above_4_kelvin':None}
    if not count:
        return result
    indices = np.flatnonzero(histogram); cumulative = np.cumsum(histogram)
    percentiles = {}
    for percentile in (5,25,50,75,95):
        rank = (count-1)*percentile/100
        lo,hi = math.floor(rank),math.ceil(rank)
        a,b = np.searchsorted(cumulative,[lo,hi],side='right')
        percentiles[f'p{percentile:02}'] = float((a+(b-a)*(rank-lo))/100)
    result.update(minimum_kelvin=float(indices[0]/100),maximum_kelvin=float(indices[-1]/100),
        mean_kelvin=float(np.dot(histogram,np.arange(32768,dtype='float64'))/count/100),percentiles_kelvin=percentiles,
        fraction_above_2_kelvin=float(histogram[201:].sum()/count),
        fraction_above_3_kelvin=float(histogram[301:].sum()/count),
        fraction_above_4_kelvin=float(histogram[401:].sum()/count))
    return result


def preflight(paths, geometry, select_aoi, intent):
    """Scan requested virtual-grid centres, including centres beyond the raster extent.

    QA fill/unknown is acquisition coverage; clouds and missing ST are quality support.
    Read only intersections with actual rasters. No thermal decoding/output is performed.
    """
    counts = dict(requested_count=0,selected_count=0,acquired_count=0,base_valid_count=0,
                  post_uncertainty_valid_count=0,uncertainty_exceeded_count=0,uncertainty_missing_excluded_count=0)
    histogram = np.zeros(32768,dtype='int64'); unknown = 0
    ceiling = uncertainty_ceiling(intent); reject = sum(1<<bit for bit in intent['reject_qa_bits'])
    with ExitStack() as stack:
        src,qa,uq = [stack.enter_context(rasterio.open(paths[k])) for k in ('temperature','qa','uncertainty')]
        region = geometry_window(src,[mapping(geometry)],pad_x=1,pad_y=1,boundless=True)
        if region.width*region.height > 110_000_000:
            raise InputError('requested AOI coverage audit exceeds 110 million native-grid cells; narrow or tile under a new intent')
        for y in range(0,int(region.height),256):
            for x in range(0,int(region.width),256):
                win = Window(region.col_off+x,region.row_off+y,min(256,region.width-x),min(256,region.height-y))
                shape = (int(win.height),int(win.width))
                inside = select_aoi(window_transform(win,src.transform),shape)
                counts['requested_count'] += int(inside.sum())
                if not inside.any():
                    continue
                r0,c0 = max(0,int(win.row_off)),max(0,int(win.col_off))
                r1,c1 = min(src.height,int(win.row_off+win.height)),min(src.width,int(win.col_off+win.width))
                if r0 >= r1 or c0 >= c1:
                    continue
                part = (slice(r0-int(win.row_off),r1-int(win.row_off)),slice(c0-int(win.col_off),c1-int(win.col_off)))
                selected = inside[part]; counts['selected_count'] += int(selected.sum())
                source_window = Window(c0,r0,c1-c0,r1-r0)
                raw,flags,un = [ds.read(1,window=source_window) for ds in (src,qa,uq)]
                acquired = selected & ((flags & 1)==0) & (qa.read_masks(1,window=source_window)>0)
                base = acquired & (raw>0) & (src.read_masks(1,window=source_window)>0) & ((flags & reject)==0)
                known = base & (un>=0) & (uq.read_masks(1,window=source_window)>0)
                counts['acquired_count'] += int(acquired.sum()); counts['base_valid_count'] += int(base.sum())
                histogram += np.bincount(un[known],minlength=32768)
                unknown += int(np.count_nonzero(base & ~known))
                valid = base if ceiling is None else known & (un<=ceiling)
                counts['post_uncertainty_valid_count'] += int(valid.sum())
                if ceiling is not None:
                    counts['uncertainty_exceeded_count'] += int(np.count_nonzero(known & (un>ceiling)))
                    counts['uncertainty_missing_excluded_count'] += int(np.count_nonzero(base & ~known))
    requested,selected,acquired = (counts[k] for k in ('requested_count','selected_count','acquired_count'))
    counts.update(outside_grid_count=requested-selected,qa_fill_or_unknown_count=selected-acquired,
        acquired_fraction_of_requested=acquired/requested if requested else None,
        grid_fraction_of_requested=selected/requested if requested else None,
        post_uncertainty_valid_fraction_of_acquired=counts['post_uncertainty_valid_count']/acquired if acquired else None,
        uncertainty_before_filter=uncertainty_statistics(histogram,unknown))
    return counts
