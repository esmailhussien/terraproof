"""Run built-wheel APIs outside the checkout, with no install or network access.

The wheel is product-only (Phase 6 B1): the benchmark and the lift harness run from a
checkout, so the wheel must not contain `terraproof.evals` or the task specs.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import zipfile


PROBE = r'''
import contextlib, io, json, sys
from pathlib import Path
tree = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(tree))
import terraproof
assert Path(terraproof.__file__).resolve().is_relative_to(tree)
from terraproof._common import assets_root
from terraproof.router.index import find_root
assets = tree / 'terraproof' / 'data'
assert assets_root() == find_root() == assets
from terraproof.mcp.skills import list_skills, load_section
skills = list_skills()
assert len(skills) == 24
for skill in skills:
    for section in skill['sections']:
        assert load_section(skill['name'], section['id'])['text'].strip()
from terraproof.router import find_guidance
for task in ['Convert GeoTIFF to COG with GDAL.', 'حول GeoTIFF باستخدام GDAL']:
    assert 'gdal' in {skill['name'] for skill in find_guidance(task, semantic=False)['skills']}
import importlib.util
assert importlib.util.find_spec('terraproof.evals') is None
assert not (assets / 'evals').exists()
from terraproof.install import main as install
target = Path.cwd() / 'installed-agent'
target.mkdir()
with contextlib.redirect_stdout(io.StringIO()):
    assert install(['--agent', 'codex', '--skills', 'gdal', '--target', str(target)]) == 0
assert (target / '.agents' / 'skills' / 'gdal' / 'SKILL.md').is_file()
assert (assets / 'sources' / 'SOURCES.md').is_file()
assert (assets / 'third_party').is_dir()
# Exercise the new runtime modules from the extracted wheel, not checkout imports.
import math, shutil
import numpy as np
import rasterio
from rasterio.transform import from_origin
def write_raster_grid(path, data, *, transform, unit=None):
    with rasterio.open(path, 'w', driver='GTiff', height=data.shape[0], width=data.shape[1], count=1,
                       dtype=data.dtype.name, crs='EPSG:32636', transform=transform, nodata=-9999.0) as dst:
        dst.write(data, 1)
        if unit:
            dst.set_band_unit(1, unit)
    return str(path)
from terraproof.inspect import inspect_dataset
from terraproof.checks import run_checks
contracts = Path.cwd() / 'contract-probes'
contracts.mkdir()
row, col = np.indices((7,9))
dem = write_raster_grid(contracts/'dem.tif', (50+4*col+5*row).astype('float32'),
                        transform=from_origin(500000,5000000,20,30), unit='m')
slope = np.full((7,9), -9999, dtype='float32')
slope[1:-1,1:-1] = math.degrees(math.atan(math.hypot(4/20,5/30)))
out = write_raster_grid(contracts/'slope.tif', slope, transform=from_origin(500000,5000000,20,30))
assert next(c.status for c in run_checks([inspect_dataset(out)], dem=inspect_dataset(dem),
            slope_method='central-difference') if c.id=='terrain.slope_formula') == 'pass'
copy = contracts/'copy.tif'
shutil.copyfile(dem, copy)
assert next(c.status for c in run_checks([inspect_dataset(copy)], compare_to=inspect_dataset(dem),
            raster_identity=True) if c.id=='raster.source_identity') == 'pass'
print(json.dumps({'status':'pass','skills':len(skills),'all_sections_loaded':True,'bilingual_routing':True,'evals_excluded':True,'installer':True,'uses_checkout_assets':False,'package_assets_modified':False,'strict_raster_contracts':True}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path, help='wheel file or directory containing exactly one wheel')
    parser.add_argument('--temp-root', type=Path, help='writable temporary directory outside the checkout')
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if wheel.is_dir():
        candidates = list(wheel.glob('*.whl'))
        if len(candidates) != 1:
            parser.error('expected exactly one wheel in the artifact directory')
        wheel = candidates[0]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        required = ('terraproof/data/routing/registry.json',
                    'terraproof/data/routing/checks.json',
                    'terraproof/data/sources/SOURCES.md')
        missing = [name for name in required if name not in names]
        if missing:
            print(json.dumps({'status': 'fail', 'missing_runtime_assets': missing}))
            return 1
        harness = sorted(name for name in names
                         if name.startswith(('terraproof/evals/', 'terraproof/data/evals/')))
        if harness:
            print(json.dumps({'status': 'fail', 'harness_in_wheel': harness[:10]}))
            return 1
        checkout = Path(__file__).resolve().parents[2]
        temp_root = args.temp_root.resolve() if args.temp_root else Path(tempfile.gettempdir()).resolve()
        if temp_root.is_relative_to(checkout):
            temp_root = (Path(os.environ['LOCALAPPDATA']) / 'Temp').resolve() if os.name == 'nt' else Path('/tmp')
        if temp_root.is_relative_to(checkout):
            raise RuntimeError('Wheel smoke must run outside the checkout')
        work = Path(tempfile.mkdtemp(prefix='terraproof-wheel-smoke-', dir=temp_root)).resolve()
        if work.parent != temp_root or not work.name.startswith('terraproof-wheel-smoke-'):
            raise RuntimeError('Unexpected temporary directory ownership')
        try:
            tree = work / 'site-packages'
            for name in names:
                if not (tree / name).resolve().is_relative_to(tree):
                    raise ValueError('Wheel member escapes its extraction directory')
            archive.extractall(tree)
            result = subprocess.run([sys.executable, '-I', '-B', '-c', PROBE, str(tree)],
                                    cwd=work, capture_output=True, text=True, timeout=120)
            print(result.stdout, end='')
            if result.returncode:
                print(result.stderr, file=sys.stderr, end='')
            return result.returncode
        finally:
            # No chmod/permission-reset fallback, even on cleanup failure.
            shutil.rmtree(work)


if __name__ == '__main__':
    raise SystemExit(main())
