"""Strict raster contracts: scalar slope references, all-band identity, CLI/MCP parity."""
import math
import shutil

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.transform import from_origin

from terraproof.checks import run_checks
from terraproof.checks.slope_formula import check_slope_formula
from terraproof.checks.raster_identity import check_source_identity
from terraproof.evals.fixtures import write_raster_grid
from terraproof.inspect import inspect_dataset

NODATA = -9999.
GRID = from_origin(500000, 5000000, 30, 50)


def scalar_slope(source):
    """Independent scalar definition; imports no production formula/calculation."""
    with rasterio.open(source) as src:
        values, masks = src.read(1), src.read_masks(1)
        factor = {'ft': .3048, 'us-ft': 1200/3937, 'm': 1., None: 1.}[src.units[0]]
        factor /= src.crs.linear_units_factor[1]
        output = np.full(src.shape, NODATA, dtype='float32')
        for row in range(1, src.height-1):
            for col in range(1, src.width-1):
                cells = [(row,col),(row-1,col),(row+1,col),(row,col-1),(row,col+1)]
                z = [float(values[r,c])*src.scales[0] + src.offsets[0] for r,c in cells]
                if not all(masks[r,c] and math.isfinite(v) for (r,c),v in zip(cells,z)): continue
                gx = factor*src.scales[0]*(float(values[row,col+1])-float(values[row,col-1]))/(2*abs(src.transform.a))
                gy = factor*src.scales[0]*(float(values[row+1,col])-float(values[row-1,col]))/(2*abs(src.transform.e))
                output[row,col] = math.degrees(math.atan(math.hypot(gx,gy)))
        return output, src.profile


def slope_case(tmp_path, unit='ft', shape=(11,13), flat=False, scale=1., offset=0., crs='EPSG:32636'):
    row, col = np.indices(shape)
    data = (50 + .4*col*col + .7*row*row).astype('float32')
    if flat: data[:] = 50
    data[3,5] = NODATA
    source = write_raster_grid(tmp_path/'dem.tif', data, transform=GRID, unit=unit, scales=[scale], offsets=[offset], crs=crs)
    values, _ = scalar_slope(source)
    output = write_raster_grid(tmp_path/'slope.tif', values, transform=GRID, crs=crs)
    return source, output


def slope(source, output, method='central-difference'):
    return check_slope_formula(inspect_dataset(output), inspect_dataset(source) if source else None, method)[0]


def identity_case(tmp_path, dtype='float32', bands=1, shape=(13,15)):
    data = np.arange(bands*shape[0]*shape[1], dtype=dtype).reshape((bands,*shape)) + 1
    source = write_raster_grid(tmp_path/'source.tif', data, transform=GRID, nodata=0)
    output = str(tmp_path/'copy.tif'); shutil.copyfile(source, output)
    return source, output


def identity(source, output):
    return check_source_identity(inspect_dataset(output), inspect_dataset(source) if source else None)[0]


def rewrite(path, edit, **metadata):
    with rasterio.open(path) as src:
        data, profile = src.read(), src.profile
    edit(data)
    profile.update(metadata)
    with rasterio.open(path, 'w', **profile) as dst: dst.write(data)


@pytest.mark.parametrize('unit', ['ft', 'us-ft', 'm', None])
def test_strict_slope_matches_scalar_reference_and_calibration(tmp_path, unit):
    source, output = slope_case(tmp_path, unit=unit, scale=2.5, offset=17.)
    found = slope(source, output)
    assert found.status == 'pass', found.message
    assert found.evidence['mismatched_cells'] == found.evidence['extra_masked_cells'] == found.evidence['unsupported_output_cells'] == 0
    expected, _ = scalar_slope(source)
    assert found.evidence['compared_cells'] == np.count_nonzero(expected != NODATA)


@pytest.mark.parametrize('defect', ['value','edge','hole','neighbour','extra-mask','nan','inf'])
def test_strict_slope_rejects_each_local_value_or_support_error(tmp_path, defect):
    source, output = slope_case(tmp_path)
    with rasterio.open(output, 'r+') as dst:
        values = dst.read(1)
        if defect == 'value': values[2,2] += .125
        elif defect == 'edge': values[0,2] = 0
        elif defect == 'hole': values[3,5] = 0
        elif defect == 'neighbour': values[3,4] = 0
        elif defect == 'extra-mask': values[2,2] = NODATA
        else: values[2,2] = float(defect)
        dst.write(values, 1)
    assert slope(source, output).status == 'fail'


def test_flat_slope_zero_cells_are_compared(tmp_path):
    source, output = slope_case(tmp_path, flat=True)
    assert slope(source, output).status == 'pass'
    with rasterio.open(output, 'r+') as dst:
        values=dst.read(1); values[2,2] = .001; dst.write(values,1)
    found = slope(source, output)
    assert found.status == 'fail' and found.evidence['mismatched_cells'] == 1


def test_slope_window_halo_and_last_tile_are_checked(tmp_path):
    source, output = slope_case(tmp_path, shape=(515,517))
    assert slope(source, output).status == 'pass'
    with rasterio.open(output, 'r+') as dst:
        values=dst.read(1); values[512,513] += .125; dst.write(values,1)
    found = slope(source, output)
    assert found.status == 'fail' and found.evidence['mismatched_cells'] == 1


@pytest.mark.parametrize('role', ['source','output'])
def test_external_masks_affect_slope_contract(tmp_path, role):
    source, output = slope_case(tmp_path)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(source if role == 'source' else output, 'r+') as dst:
            mask=dst.read_masks(1); mask[2,2] = 0; dst.write_mask(mask)
    assert slope(source, output).status == 'fail'


@pytest.mark.parametrize('defect', ['CRS','affine','shape','encoding','unit','bands'])
def test_slope_output_metadata_violation_fails(tmp_path, defect):
    source, output = slope_case(tmp_path)
    if defect == 'CRS': rewrite(output, lambda a: None, crs='EPSG:3857')
    elif defect == 'affine': rewrite(output, lambda a: None, transform=Affine(30,0,500015,0,-50,5000000))
    elif defect == 'shape':
        write_raster_grid(output, np.zeros((7,9),dtype='float32'), transform=GRID)
    elif defect == 'bands':
        write_raster_grid(output, np.zeros((2,11,13),dtype='float32'), transform=GRID)
    else:
        with rasterio.open(output,'r+') as dst:
            if defect == 'encoding': dst.scales=(.5,)
            else: dst.set_band_unit(1,'radian')
    assert slope(source, output).status == 'fail'


@pytest.mark.parametrize('defect', ['missing','method','unit','geographic','rotated','scale','no-support','wide-integer'])
def test_unsupported_slope_contract_is_not_run(tmp_path, defect):
    source, output = slope_case(tmp_path)
    if defect == 'missing': assert slope(None, output).status == 'not-run'; return
    if defect == 'method': assert slope(source,output,'horn').status == 'not-run'; return
    if defect == 'unit':
        with rasterio.open(source,'r+') as dst: dst.set_band_unit(1,'furlong')
    elif defect == 'geographic': rewrite(source,lambda a:None,crs='EPSG:4326')
    elif defect == 'rotated': rewrite(source,lambda a:None,transform=Affine(30,1,500000,1,-50,5000000))
    elif defect == 'scale':
        with rasterio.open(source,'r+') as dst: dst.scales=(float('nan'),)
    elif defect == 'no-support':
        rewrite(source,lambda a:a.fill(NODATA)); rewrite(output,lambda a:a.fill(NODATA))
    elif defect == 'wide-integer':
        write_raster_grid(source,np.full((11,13),2**54,dtype='uint64'),transform=GRID,nodata=0)
    assert slope(source, output).status == 'not-run'


def test_new_slope_mode_is_explicit_and_legacy_mode_unchanged(tmp_path):
    source, output = slope_case(tmp_path)
    ds, dem = inspect_dataset(output), inspect_dataset(source)
    assert 'terrain.slope_formula' not in {r.id for r in run_checks([ds], dem=dem)}
    selected = {r.id:r.status for r in run_checks([ds],dem=dem,slope_method='central-difference')}
    assert selected['terrain.slope_formula'] == 'pass' and 'terrain.slope_consistent' not in selected
    assert 'terrain.slope_consistent' in {r.id for r in run_checks([ds],dem=dem)}


@pytest.mark.parametrize('dtype', ['uint8','uint64','int64','float32','float64'])
def test_identity_exact_values_and_all_bands(tmp_path, dtype):
    source, output = identity_case(tmp_path,dtype=dtype,bands=2)
    assert identity(source,output).status == 'pass'
    rewrite(output,lambda a:a.__setitem__((1,-1,-1),a[1,-1,-1]+1))
    found=identity(source,output)
    assert found.status == 'fail' and found.evidence['mismatched_band_cells'] == 1


def test_identity_does_not_round_uint64_differences_to_float(tmp_path):
    source, output = identity_case(tmp_path,dtype='uint64')
    for path in (source,output): rewrite(path,lambda a:a.fill(2**54))
    assert identity(source,output).status == 'pass'
    rewrite(output,lambda a:a.__setitem__((0,2,2),2**54+1))
    assert identity(source,output).status == 'fail'


def test_identity_last_tile_and_valid_zero(tmp_path):
    source, output = identity_case(tmp_path,shape=(513,514))
    for path in (source,output):
        rewrite(path,lambda a:a.__setitem__((0,2,2),0),nodata=-9999)
    assert identity(source,output).status == 'pass'
    rewrite(output,lambda a:a.__setitem__((0,-1,-1),-1))
    found=identity(source,output)
    assert found.status == 'fail' and found.evidence['mismatched_band_cells'] == 1


@pytest.mark.parametrize('role', ['source','output'])
def test_identity_external_mask_differences_fail(tmp_path,role):
    source, output = identity_case(tmp_path)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(source if role=='source' else output,'r+') as dst:
            mask=dst.read_masks(1); mask[2,2]=0; dst.write_mask(mask)
    found=identity(source,output)
    assert found.status == 'fail' and found.evidence['mask_mismatched_band_cells'] == 1


@pytest.mark.parametrize('defect', ['CRS','affine','dtype','nodata','scale','offset','unit','bands','shape'])
def test_identity_metadata_differences_fail(tmp_path,defect):
    source, output=identity_case(tmp_path)
    if defect=='CRS': rewrite(output,lambda a:None,crs='EPSG:3857')
    elif defect=='affine': rewrite(output,lambda a:None,transform=Affine(30,0,500030,0,-50,5000000))
    elif defect=='dtype': rewrite(output,lambda a:None,dtype='float64')
    elif defect=='nodata': rewrite(output,lambda a:None,nodata=-9999)
    elif defect=='bands': write_raster_grid(output,np.ones((2,13,15),dtype='float32'),transform=GRID,nodata=0)
    elif defect=='shape': write_raster_grid(output,np.ones((9,11),dtype='float32'),transform=GRID,nodata=0)
    else:
        with rasterio.open(output,'r+') as dst:
            if defect=='scale': dst.scales=(.5,)
            elif defect=='offset': dst.offsets=(17.,)
            else: dst.set_band_unit(1,'ft')
    assert identity(source,output).status == 'fail'


def test_identity_nan_and_invalid_payload_semantics(tmp_path):
    source,output=identity_case(tmp_path)
    for path in (source,output):
        rewrite(path,lambda a:a.__setitem__((0,2,2),float('nan')))
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
            with rasterio.open(path,'r+') as dst:
                mask=dst.read_masks(1); mask[3,3]=0; dst.write_mask(mask)
    with rasterio.open(output,'r+') as dst:
        a=dst.read(1); a[3,3]=37; dst.write(a,1)
    assert identity(source,output).status == 'pass'  # masked payload is outside the declared relation


@pytest.mark.parametrize('defect', ['missing','empty','complex'])
def test_identity_unavailable_evidence_is_not_run(tmp_path,defect):
    source,output=identity_case(tmp_path)
    if defect=='missing': assert identity(None,output).status=='not-run'; return
    if defect=='empty':
        for path in(source,output): rewrite(path,lambda a:a.fill(0))
    else: write_raster_grid(source,np.ones((13,15),dtype='complex64'),transform=GRID,nodata=0)
    found = (check_source_identity(inspect_dataset(output), {'kind':'raster','path':source})[0]
             if defect=='complex' else identity(source,output))
    assert found.status=='not-run'


def test_raster_identity_is_opt_in(tmp_path):
    source,output=identity_case(tmp_path)
    ds,ref=inspect_dataset(output),inspect_dataset(source)
    assert 'raster.source_identity' not in {r.id for r in run_checks([ds],compare_to=ref)}
    found={r.id:r.status for r in run_checks([ds],compare_to=ref,raster_identity=True)}
    assert found['raster.source_identity']=='pass'




def test_large_constant_dem_offset_cannot_erase_a_gradient(tmp_path):
    source, output = slope_case(tmp_path, scale=.5, offset=1e30)
    assert slope(source, output).status == 'pass'
    with rasterio.open(output,'r+') as dst:
        a=dst.read(1); a[dst.read_masks(1)>0]=0; dst.write(a,1)
    assert slope(source,output).status == 'fail'


def test_horizontal_feet_and_vertical_metres_are_converted(tmp_path):
    source, output = slope_case(tmp_path, unit='m', crs='EPSG:2263')
    assert slope(source, output).status == 'pass'
