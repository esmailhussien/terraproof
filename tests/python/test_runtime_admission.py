"""The actual MCP interpreter, not merely the agent PATH, must be admitted."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from test_api_agent import driver
import runtime_admission as admission


@pytest.mark.parametrize('reason', ['wrong-python', 'not-isolated', 'evals', 'editable', 'drift', 'invalid-probe'])
def test_mcp_admission_refuses_exposed_or_mismatched_runtimes(tmp_path, monkeypatch, reason):
    called = []
    def probe(*args, **kwargs):
        called.append(args)
        info = {'product_in_venv': reason != 'editable', 'evals_absent': reason != 'evals',
                'fingerprint': 'changed' if reason == 'drift' else 'current'}
        return SimpleNamespace(returncode=0, stdout='not json' if reason == 'invalid-probe' else json.dumps(info))
    monkeypatch.setattr(admission.subprocess, 'run', probe)
    monkeypatch.setattr(admission, 'fingerprint', lambda *args: 'current')
    command = str(tmp_path/'wrong.exe') if reason == 'wrong-python' else sys.executable
    args = ['-m', 'terraproof.mcp'] if reason == 'not-isolated' else ['-I', '-m', 'terraproof.mcp']
    checks = admission.admit_mcp(tmp_path, sys.executable, command, args)
    assert not all(checks.values())
    if reason in ('wrong-python', 'not-isolated'):
        assert not called  # never execute a rejected registration


def test_clean_matching_probe_is_admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(admission, 'fingerprint', lambda *args: 'current')
    monkeypatch.setattr(admission.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0,
        stdout=json.dumps({'product_in_venv': True, 'evals_absent': True, 'fingerprint': 'current'})))
    assert all(admission.admit_mcp(tmp_path, sys.executable, sys.executable, ['-I', '-m', 'terraproof.mcp']).values())


@pytest.mark.parametrize('agent,filename', [('claude', '.mcp.json'), ('antigravity', '.agents/mcp_config.json'),
                                          ('opencode', 'opencode.json'), ('codex', '.codex/config.toml')])
def test_installer_registers_explicit_interpreter_in_every_study_format(tmp_path, agent, filename):
    from terraproof.install import main
    target = tmp_path/agent; target.mkdir()
    assert main(['--agent', agent, '--skills', 'gdal', '--target', str(target), '--with-mcp',
                 '--mcp-python', sys.executable]) == 0
    text = (target/filename).read_text(encoding='utf-8')
    assert '-I' in text and 'terraproof.mcp' in text
    if agent == 'opencode': argv = json.loads(text)['mcp']['terraproof']['command']
    elif agent != 'codex':
        server = json.loads(text)['mcpServers']['terraproof']; argv = [server['command'], *server['args']]
    else:
        assert str(Path(sys.executable).resolve()) in text
        assert "'-I'" in text
        return
    assert Path(argv[0]) == Path(sys.executable).resolve() and argv[1:] == ['-I', '-m', 'terraproof.mcp']


def test_codex_override_cannot_restore_harness_python(tmp_path):
    python = str(tmp_path/'product/python.exe')
    value = driver.codex_mcp_value('with', python)
    assert json.dumps(str(Path(python).resolve())) in value and '-I' in value
    assert driver.codex_mcp_value('without', python) == '{}'


def test_fingerprint_detects_asset_and_code_drift(tmp_path):
    package = tmp_path/'package'; package.mkdir()
    assets = tmp_path/'assets'
    for folder in ('skills', 'routing', 'instructions', 'sources', 'third_party'):
        (assets/folder).mkdir(parents=True)
    (package/'__init__.py').write_text('original')
    first = admission.fingerprint(package, assets)
    (package/'checks.py').write_text('new check')
    second = admission.fingerprint(package, assets)
    (assets/'sources/LICENSE').write_text('preserved attribution')
    assert len({first, second, admission.fingerprint(package, assets)}) == 3
