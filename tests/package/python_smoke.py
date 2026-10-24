"""Run built-wheel APIs outside the checkout, with no install or network access."""

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
from terraproof.evals import load_specs, run_benchmark
task_count = len(load_specs())
assert task_count >= 27
evaluation = run_benchmark()
assert evaluation['summary']['exit_code'] == 0
assert evaluation['summary']['tasks_passed'] == task_count
assert not (assets / '.terracache').exists()
from terraproof.install import main as install
target = Path.cwd() / 'installed-agent'
target.mkdir()
with contextlib.redirect_stdout(io.StringIO()):
    assert install(['--agent', 'codex', '--skills', 'gdal', '--target', str(target)]) == 0
assert (target / '.agents' / 'skills' / 'gdal' / 'SKILL.md').is_file()
assert (assets / 'sources' / 'SOURCES.md').is_file()
assert (assets / 'third_party').is_dir()
print(json.dumps({'status':'pass','skills':len(skills),'all_sections_loaded':True,'bilingual_routing':True,'eval_tasks':task_count,'false_passes':evaluation['summary']['false_passes'],'checker_blind_spots':evaluation['summary']['wrong_controls_checker_blind_spots'],'installer':True,'uses_checkout_assets':False,'package_assets_modified':False}))
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
