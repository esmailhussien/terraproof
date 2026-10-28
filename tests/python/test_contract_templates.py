"""The documented contract templates: a valid output verifies, a defect fails, missing evidence is incomplete."""
import json
import shutil
import warnings
from pathlib import Path

import numpy as np
import pyogrio.raw
import pytest
import rasterio
import shapely
from rasterio.transform import from_origin
from shapely.geometry import box

from terraproof.cli import main

TEMPLATES = Path(__file__).resolve().parents[2] / 'docs' / 'contract-templates'
ORIGIN = (500000.0, 5000000.0)


def raster(path, data, origin=ORIGIN, nodata=-9999.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.asarray(data)[np.newaxis]
    with rasterio.open(path, 'w', driver='GTiff', width=array.shape[2], height=array.shape[1], count=1,
                       dtype=array.dtype.name, crs='EPSG:32636', transform=from_origin(*origin, 10, 10),
                       nodata=nodata, tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(array)


def vector(path, geoms):
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        pyogrio.raw.write(str(path), [shapely.to_wkb(g) for g in geoms], [], [], geometry_type='Polygon',
                          crs='EPSG:32636', driver='GPKG')


def vector_case(project, case):
    parcels = [box(i * 20, 0, i * 20 + 10, 10) for i in range(3)]
    vector(project / 'inputs/parcels.gpkg', parcels)
    vector(project / 'outputs/parcels_area.gpkg', parcels[:2] if case == 'defect' else parcels)
    evidence = [] if case == 'missing' else ['--compare-to', 'inputs/parcels.gpkg']
    return ['outputs/parcels_area.gpkg', '--operation', 'area', *evidence]


def raster_case(project, case):
    classes = np.random.default_rng(0).integers(1, 6, (32, 32)).astype('uint8')
    raster(project / 'inputs/reference_grid.tif', classes, nodata=0)
    shifted = (ORIGIN[0] + 5, ORIGIN[1]) if case == 'defect' else ORIGIN
    raster(project / 'outputs/landcover_aligned.tif', classes, origin=shifted, nodata=0)
    evidence = [] if case == 'missing' else ['--resampling', 'nearest', '--categorical']
    return ['outputs/landcover_aligned.tif', 'inputs/reference_grid.tif', *evidence]


def index_case(project, case):
    rng = np.random.default_rng(1)
    nir = rng.uniform(.2, .6, (32, 32)).astype('float32')
    red = rng.uniform(.02, .2, (32, 32)).astype('float32')
    raster(project / 'inputs/nir.tif', nir)
    raster(project / 'inputs/red.tif', red)
    ndvi = (red - nir) / (nir + red) if case == 'defect' else (nir - red) / (nir + red)
    raster(project / 'outputs/ndvi.tif', ndvi.astype('float32'))
    evidence = [] if case == 'missing' else ['--nir', 'inputs/nir.tif', '--red', 'inputs/red.tif']
    return ['outputs/ndvi.tif', '--index-formula', 'ndvi', *evidence]


def stack_case(project, case):
    rng = np.random.default_rng(2)
    layers = [rng.uniform(0, 1, (32, 32)).astype('float32') for _ in range(3)]
    for number, layer in enumerate(layers, 1):
        raster(project / f'inputs/t{number}.tif', layer)
    reduced = np.mean(layers, axis=0) if case == 'defect' else np.median(layers, axis=0)
    raster(project / 'outputs/median.tif', reduced.astype('float32'))
    evidence = [] if case == 'missing' else [arg for n in (1, 2, 3) for arg in ('--stack', f'inputs/t{n}.tif')]
    return ['outputs/median.tif', '--stack-reduction', 'median', *evidence]


CASES = {'vector-metric-area': vector_case, 'raster-categorical-grid': raster_case,
         'index-ndvi': index_case, 'stack-median': stack_case}
# A dropped vector record is a warning (a filter may be intended), so the defect needs review rather than failing.
DEFECT = {'vector-metric-area': (2, 'review-required')}


def run(tmp_path, monkeypatch, template, case):
    project = tmp_path / template / case
    project.mkdir(parents=True)
    shutil.copyfile(TEMPLATES / f'{template}.json', project / 'contract.json')
    args = CASES[template](project, case)
    monkeypatch.chdir(project)
    code = main(['check', *args, '--contract', 'contract.json', '--out', 'report.json'])
    return project, code, json.loads((project / 'report.json').read_text(encoding='utf-8'))


def test_every_template_has_a_tested_case():
    assert sorted(path.stem for path in TEMPLATES.glob('*.json')) == sorted(CASES)


@pytest.mark.parametrize('template', sorted(CASES))
def test_valid_output_verifies_and_its_bundle_detects_a_changed_output(tmp_path, monkeypatch, template):
    project, code, report = run(tmp_path, monkeypatch, template, 'valid')
    assert code == 0 and report['verification']['status'] == 'verified'
    assert main(['evidence', 'write', 'report.json', '--root', '.', '--out', 'evidence.json']) == 0
    assert main(['evidence', 'verify', 'evidence.json']) == 0
    output = project / json.loads((project / 'contract.json').read_text())['requirements'][0]['paths'][0]
    output.write_bytes(output.read_bytes() + b'\0')
    assert main(['evidence', 'verify', 'evidence.json']) != 0


@pytest.mark.parametrize('template', sorted(CASES))
def test_defect_is_not_verified(tmp_path, monkeypatch, template):
    _, code, report = run(tmp_path, monkeypatch, template, 'defect')
    assert (code, report['verification']['status']) == DEFECT.get(template, (3, 'failed'))
    # CI uploads the evidence for a failing run too.
    assert main(['evidence', 'write', 'report.json', '--root', '.', '--out', 'evidence.json']) == 0
    assert main(['evidence', 'verify', 'evidence.json']) == 0


@pytest.mark.parametrize('template', sorted(CASES))
def test_missing_evidence_is_incomplete_and_named(tmp_path, monkeypatch, template):
    _, code, report = run(tmp_path, monkeypatch, template, 'missing')
    assert code == 3 and report['verification']['status'] == 'incomplete'
    assert all(r['status'] == 'missing' and (r['missing_bindings'] or r['parameter_mismatches'])
               for r in report['verification']['requirements'])
