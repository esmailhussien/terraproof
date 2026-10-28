"""No-inference admission of the actual registered, production-only MCP Python.

This verifies package/argv separation and source identity, not filesystem containment.
"""
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess


def fingerprint(package, assets):
    files = {}
    for path in sorted(package.rglob('*.py')):
        relative = path.relative_to(package)
        if relative.parts[0] in ('evals', 'data', '__pycache__') or path.name == '_build.py':
            continue
        if path.is_symlink():
            raise ValueError('linked production code')
        files['code/'+relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for folder in ('skills', 'routing', 'instructions', 'sources', 'third_party'):
        for path in sorted((assets/folder).rglob('*')):
            if path.is_symlink():
                raise ValueError('linked production asset')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                files['assets/'+folder+'/'+path.relative_to(assets/folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


PROBE = '''import hashlib,json,pathlib,sys,sysconfig,importlib.util
from pathlib import Path
import terraproof
from terraproof._common import assets_root
''' + inspect.getsource(fingerprint) + '''
root=Path(terraproof.__file__).resolve().parent
purelib=Path(sysconfig.get_path('purelib')).resolve()
cfg=Path(sys.prefix)/'pyvenv.cfg'
isolated_venv=sys.prefix!=sys.base_prefix and cfg.is_file() and 'include-system-site-packages = false' in cfg.read_text().lower()
print(json.dumps({'product_in_venv':isolated_venv and root.is_relative_to(purelib),
 'evals_absent':importlib.util.find_spec('terraproof.evals') is None and not (root/'data/evals').exists(),
 'fingerprint':fingerprint(root,assets_root())}))
'''


def admit_mcp(project, python, command, args):
    checks = {name: False for name in ('mcp_python_matches_agent', 'mcp_python_isolated',
        'mcp_product_in_venv', 'mcp_evals_absent', 'mcp_production_matches_checkout')}
    if not python or not isinstance(command, str) or not Path(command).is_absolute():
        return checks
    checks['mcp_python_matches_agent'] = Path(command).resolve() == Path(python).resolve()
    checks['mcp_python_isolated'] = args == ['-I', '-m', 'terraproof.mcp']
    if not checks['mcp_python_matches_agent'] or not checks['mcp_python_isolated']:
        return checks
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'):
        env.pop(key, None)
    try:
        run = subprocess.run([command, '-I', '-c', PROBE], cwd=project, env=env,
                             capture_output=True, text=True, timeout=60, check=False)
        info = json.loads(run.stdout) if run.returncode == 0 else {}
        import terraproof
        from terraproof._common import assets_root
        checks.update(mcp_product_in_venv=info.get('product_in_venv') is True,
            mcp_evals_absent=info.get('evals_absent') is True,
            mcp_production_matches_checkout=info.get('fingerprint') == fingerprint(Path(terraproof.__file__).parent, assets_root()))
        if isinstance(info.get('fingerprint'), str):
            checks['mcp_production_sha256'] = info['fingerprint']
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return checks
