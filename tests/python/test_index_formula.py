"""Production NDVI source/output contract, no frozen eval invocation changes."""
from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from terraproof.checks import run_checks
from terraproof.checks.index_formula import check_index_formula
from terraproof.cli import main
from terraproof.evals.fixtures import write_raster_grid
from terraproof.inspect import inspect_dataset
from terraproof.provenance import write_manifest

GRID = from_origin(500000, 5000000, 20, 20)
NODATA = -9999.0


def _case(tmp_path):
    rows, cols = np.indices((18, 19))
    n = (4000 + 13 * rows + 7 * cols).astype('uint16')
    r = (1800 + 3 * rows + 11 * cols).astype('uint16')
    n[2, 3] = 65535
    r[4, 5] = 65535
    nir = write_raster_grid(tmp_path / 'nir.tif', n, transform=GRID, nodata=65535, scales=[0.0001], offsets=[-0.1])
    red = write_raster_grid(tmp_path / 'red.tif', r, transform=GRID, nodata=65535, scales=[0.0002], offsets=[-0.1])
    # Independently assemble the expected physical index for these ordinary inputs.
    correct = np.full(n.shape, NODATA, dtype='float32')
    for row, col in np.ndindex(n.shape):
        if n[row, col] == 65535 or r[row, col] == 65535:
            continue
        nv, rv = float(n[row, col]) / 10000 - .1, float(r[row, col]) / 5000 - .1
        correct[row, col] = (nv - rv) / (nv + rv)
    out = write_raster_grid(tmp_path / 'ndvi.tif', correct, transform=GRID)
    with rasterio.open(out, 'r+') as dst:
        dst.build_overviews([2], rasterio.enums.Resampling.average)
    return out, nir, red, correct


def _check(out, nir, red, formula='ndvi'):
    return check_index_formula(inspect_dataset(out), formula,
                               inspect_dataset(nir) if nir else None,
                               inspect_dataset(red) if red else None)[0]


def test_correct_physical_index_passes_with_per_band_calibration(tmp_path):
    out, nir, red, _ = _case(tmp_path)
    found = _check(out, nir, red)
    assert found.status == 'pass'
    assert found.evidence['compared_cells'] == 18 * 19 - 2
    assert found.evidence['calibration']['red'] == {'scale': .0002, 'offset': -.1}
    assert found.evidence['mismatched_cells'] == found.evidence['unsupported_output_cells'] == 0


@pytest.mark.parametrize('mistake', ['stored-values', 'one-cell', 'source-mask', 'nan'])
def test_wrong_values_or_invalid_source_support_fail(tmp_path, mistake):
    out, nir, red, values = _case(tmp_path)
    if mistake == 'stored-values':
        with rasterio.open(nir) as n, rasterio.open(red) as r:
            nv, rv = n.read(1).astype(float), r.read(1).astype(float)
            values[values != NODATA] = ((nv - rv) / (nv + rv))[values != NODATA]
    elif mistake == 'one-cell':
        values[-1, -1] += .1
    elif mistake == 'source-mask':
        values[2, 3] = 0
    else:
        values[-1, -1] = np.nan
    write_raster_grid(out, values, transform=GRID)
    assert _check(out, nir, red).status == 'fail'


def test_extra_qa_mask_warns_and_empty_output_is_not_run(tmp_path):
    out, nir, red, values = _case(tmp_path)
    values[0, 0] = NODATA
    write_raster_grid(out, values, transform=GRID)
    assert _check(out, nir, red).status == 'warn'
    values[:] = NODATA
    write_raster_grid(out, values, transform=GRID)
    assert _check(out, nir, red).status == 'not-run'


@pytest.mark.parametrize('missing', ['nir', 'red', 'formula'])
def test_partial_contract_never_passes(tmp_path, missing):
    out, nir, red, _ = _case(tmp_path)
    assert _check(out, None if missing == 'nir' else nir, None if missing == 'red' else red,
                  None if missing == 'formula' else 'ndvi').status == 'not-run'


def test_unknown_formula_and_grid_mismatch_are_not_run(tmp_path):
    out, nir, red, values = _case(tmp_path)
    assert _check(out, nir, red, 'guess').status == 'not-run'
    write_raster_grid(out, values, transform=from_origin(500001, 5000000, 20, 20))
    assert _check(out, nir, red).status == 'not-run'


def test_zero_denominator_requires_mask_not_filled_zero(tmp_path):
    n = write_raster_grid(tmp_path/'n.tif', np.array([[0., .6]], dtype='float32'), transform=GRID)
    r = write_raster_grid(tmp_path/'r.tif', np.array([[0., .2]], dtype='float32'), transform=GRID)
    out = write_raster_grid(tmp_path/'out.tif', np.array([[NODATA, .5]], dtype='float32'), transform=GRID)
    assert _check(out, n, r).status == 'pass'
    write_raster_grid(out, np.array([[0., .5]], dtype='float32'), transform=GRID)
    assert _check(out, n, r).status == 'fail'


def test_encoded_output_is_decoded_from_its_metadata(tmp_path):
    n = write_raster_grid(tmp_path/'n.tif', np.full((2, 2), .6, dtype='float32'), transform=GRID)
    r = write_raster_grid(tmp_path/'r.tif', np.full((2, 2), .2, dtype='float32'), transform=GRID)
    out = write_raster_grid(tmp_path/'out.tif', np.full((2, 2), 5000, dtype='int16'), transform=GRID, scales=[.0001])
    assert _check(out, n, r).status == 'pass'


def test_no_implicit_check_and_nonraster_is_not_run(tmp_path):
    out, nir, red, _ = _case(tmp_path)
    assert 'rs.index_formula' not in {c.id for c in run_checks([inspect_dataset(out)])}
    found = run_checks([{'kind':'unknown','path':'not-a-raster'}], index_formula='ndvi',
                       nir=inspect_dataset(nir), red=inspect_dataset(red))
    assert found[-1].id == 'rs.index_formula' and found[-1].status == 'not-run'


def test_multiband_sources_are_not_silently_reduced(tmp_path):
    out, nir, red, _ = _case(tmp_path)
    write_raster_grid(nir, np.ones((2,18,19), dtype='float32'), transform=GRID)
    assert _check(out, nir, red).status == 'not-run'


def test_large_window_last_cell_is_also_checked(tmp_path):
    n = write_raster_grid(tmp_path/'n.tif', np.full((513, 514), .6, dtype='float32'), transform=GRID)
    r = write_raster_grid(tmp_path/'r.tif', np.full((513, 514), .2, dtype='float32'), transform=GRID)
    values=np.full((513,514), .5, dtype='float32')
    values[-1,-1]=.25
    out=write_raster_grid(tmp_path/'out.tif',values,transform=GRID)
    found=_check(out,n,r)
    assert found.status=='fail' and found.evidence['mismatched_cells']==1
    assert found.evidence['compared_cells']==513*514


def test_cli_source_provenance(tmp_path, capsys):
    out, nir, red, _ = _case(tmp_path)
    args=['check',out,'--index-formula','ndvi','--nir',nir,'--red',red,'--format','json']
    assert main(args)==0
    cli=json.loads(capsys.readouterr().out)
    assert {'nir','red'} <= {record['role'] for record in cli['inputs']}
    assert cli['parameters']['index_formula']=='ndvi'
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps(write_manifest(inputs=[nir], outputs=[out], root=tmp_path, manifest_path=manifest)), encoding="utf-8")
    assert main(args+['--manifest',str(manifest)])==3
    denied=json.loads(capsys.readouterr().out)
    assert any(c['id']=='provenance.reproducible' and c['status']=='fail' for c in denied['checks'])
    manifest.write_text(json.dumps(write_manifest(inputs=[nir,red], outputs=[out], root=tmp_path, manifest_path=manifest)), encoding="utf-8")
    assert main(args+['--manifest',str(manifest)])==0
    capsys.readouterr()
    for lang in ('ar','en'):
        assert main(args[:-2]+['--lang',lang])==0
        assert 'rs.index_formula' in capsys.readouterr().out


@pytest.mark.parametrize('role', ['nir', 'output'])
def test_nonfinite_calibration_is_not_run(tmp_path, role):
    out, nir, red, _ = _case(tmp_path)
    with rasterio.open(nir if role == 'nir' else out, 'r+') as dst:
        dst.scales = (float('nan'),)
    assert _check(out, nir, red).status == 'not-run'
