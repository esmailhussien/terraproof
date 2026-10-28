"""Phase 6 readiness (Amendment 3), without model calls.

`record` (R1) builds the product wheel from a clean export of HEAD and from the checkout's reused build
directory, requires identical evaluator-free payloads, installs the clean wheel with its MCP extra into a
new venv, admits and starts its MCP server and records the runtime. `canary` (R2) records what each condition's interpreter can read outside
its task: a private canary file, the checkout's evaluator source and the driver interpreter.

    python tests/runtime_readiness.py record --venv NEW_VENV --out r1.json
    python tests/runtime_readiness.py canary --agent-python-with PY --agent-python-without PY --out r2.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_lift import host_env, mcp_tools_served  # noqa: E402
from runtime_admission import admit_mcp  # noqa: E402
from terraproof.evals.lift import WITH, WITHOUT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ('src', 'skills', 'routing', 'instructions', 'sources', 'third_party', 'pyproject.toml', 'MANIFEST.in')
MCP_ARGS = ['-I', '-m', 'terraproof.mcp']
EVALUATOR = ROOT / 'src' / 'terraproof' / 'evals' / 'headroom' / 'oracles.py'
STALE = Path('build') / 'lib' / 'terraproof' / 'evals' / '_stale_readiness_probe.py'


def _run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs).stdout


def wheel_payload(wheel: Path) -> dict:
    """File name -> SHA-256 for everything but RECORD, which differs only by its own build.

    Text is hashed with CRLF read as LF, as the admission fingerprint does: a checkout's line endings are
    not a product difference.
    """
    with zipfile.ZipFile(wheel) as archive:
        payload = {}
        for name in sorted(archive.namelist()):
            if not name.endswith('.dist-info/RECORD'):
                data = archive.read(name)
                payload[name] = hashlib.sha256(data if b'\0' in data else data.replace(b'\r\n', b'\n')).hexdigest()
        return payload


def has_evaluator(payload: dict) -> bool:
    return any(name.startswith(('terraproof/evals/', 'terraproof/data/evals/')) for name in payload)


def build_wheel(source: Path, outdir: Path) -> Path:
    _run([sys.executable, '-m', 'build', '--wheel', '--outdir', str(outdir), str(source)])
    return next(outdir.glob('*.whl'))


def record(venv: Path) -> dict:
    if venv.exists():
        raise SystemExit(f'refusing to reuse {venv}: R1 installs into a new venv')
    commit = _run(['git', 'rev-parse', 'HEAD'], cwd=ROOT).strip()
    dirty = _run(['git', 'status', '--porcelain', '--', *PRODUCTION], cwd=ROOT).splitlines()
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        export = temp / 'export'
        export.mkdir()
        archive = temp / 'head.tar'
        _run(['git', 'archive', '--format=tar', '-o', str(archive), 'HEAD'], cwd=ROOT)
        with tarfile.open(archive) as tar:
            tar.extractall(export, filter='data')
        clean = build_wheel(export, temp / 'clean')
        stale = ROOT / STALE
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text('stale evaluator left by an older build\n', encoding='utf-8')
        reused = build_wheel(ROOT, temp / 'reused')
        stale_dropped = not stale.exists()
        clean_payload, reused_payload = wheel_payload(clean), wheel_payload(reused)
        wheel = {'name': clean.name, 'sha256': hashlib.sha256(clean.read_bytes()).hexdigest(),
                 'payload_files': len(clean_payload)}
        _run([sys.executable, '-m', 'venv', str(venv)])
        python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        _run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', f'{clean}[mcp]'])
    project = Path(tempfile.mkdtemp(prefix='r1-project-'))
    admission = admit_mcp(project, str(python), str(python.resolve()), MCP_ARGS)
    packages = _run([str(python), '-m', 'pip', 'freeze', '--disable-pip-version-check']).splitlines()
    checks = {
        'production_tree_clean': not dirty,
        'reused_build_dropped_stale_evaluator': stale_dropped,
        'wheel_payloads_identical': clean_payload == reused_payload,
        'evaluator_absent_from_wheels': not has_evaluator(clean_payload) and not has_evaluator(reused_payload),
        **{name: value for name, value in admission.items() if isinstance(value, bool)},
        'mcp_tools_served': mcp_tools_served(str(python.resolve()), MCP_ARGS, project),
    }
    return {
        'commit': commit, 'production_changes': dirty, 'wheel': wheel, 'venv': str(venv),
        'python': _run([str(python), '-c', 'import sys; print(sys.version)']).strip(),
        'packages': packages, 'mcp_argv': [str(python.resolve()), *MCP_ARGS],
        'mcp_production_sha256': admission.get('mcp_production_sha256'),
        'checks': checks, 'ready': all(checks.values()),
    }


PROBE = '''import importlib.util, json, os, shutil, sys
canary, evaluator, driver = sys.argv[1:4]
def readable(path):
    try:
        with open(path, 'rb') as handle:
            return bool(handle.read(1))
    except OSError:
        return False
def importable(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError:
        return False
on_path = shutil.which('python')
print(json.dumps({'canary_readable': readable(canary), 'checkout_evaluator_readable': readable(evaluator),
    'driver_python_exists': os.path.exists(driver),
    'driver_python_on_path': bool(on_path) and os.path.normcase(os.path.realpath(on_path)) == os.path.normcase(os.path.realpath(driver)),
    'evals_importable': importable('terraproof.evals')}))
'''


def canary(agent_python_with: str, agent_python_without: str) -> dict:
    """Run each condition's interpreter as the agent would, from a task project, and record what it reads."""
    outside = Path(tempfile.mkdtemp(prefix='r2-canary-'))
    secret = outside / 'canary.txt'
    secret.write_text(secrets.token_hex(16), encoding='utf-8')
    project = Path(tempfile.mkdtemp(prefix='r2-project-'))
    conditions = {}
    for condition, python in ((WITH, agent_python_with), (WITHOUT, agent_python_without)):
        env = host_env(condition, agent_python_without, agent_python_with)
        run = subprocess.run([python, '-c', PROBE, str(secret), str(EVALUATOR), sys.executable], cwd=project,
                             env=env, capture_output=True, text=True, timeout=60, check=False)
        conditions[condition] = json.loads(run.stdout) if run.returncode == 0 else {'probe_error': run.stderr[-500:]}
    secret.unlink()
    exposed = any(value is True for observed in conditions.values() for value in observed.values()) or any(
        'probe_error' in observed for observed in conditions.values())
    return {
        'conditions': conditions,
        'host_builtin_readers': ('Not probed without a model. OpenCode `run --auto` auto-approves permissions '
                                 'that are not explicitly denied, and the harness config denies none, so its '
                                 'built-in readers are assumed able to open host files.'),
        'label': 'contamination screened' if exposed else 'evaluator-blind (interpreter route only)',
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    r1 = commands.add_parser('record', help='R1: build, install and admit a candidate runtime')
    r1.add_argument('--venv', type=Path, required=True)
    r1.add_argument('--out', type=Path, required=True)
    r2 = commands.add_parser('canary', help='R2: what each condition interpreter can read')
    r2.add_argument('--agent-python-with', required=True)
    r2.add_argument('--agent-python-without', required=True)
    r2.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'record':
        result = record(args.venv.resolve())
    else:
        result = canary(args.agent_python_with, args.agent_python_without)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result.get('checks', result.get('conditions')), indent=2))
    return 0 if result.get('ready', True) else 1


if __name__ == '__main__':
    sys.exit(main())
