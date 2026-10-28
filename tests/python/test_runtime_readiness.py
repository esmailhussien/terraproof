"""Readiness R1/R2 helpers: wheel payload comparison, a fresh venv, and an honest canary label."""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime_readiness as readiness  # noqa: E402


def wheel(path, files):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def test_payload_ignores_record_and_flags_evaluators(tmp_path):
    first = wheel(tmp_path/'a.whl', {'terraproof/cli.py': 'x', 'terraproof-1.dist-info/RECORD': 'one'})
    second = wheel(tmp_path/'b.whl', {'terraproof/cli.py': 'x', 'terraproof-1.dist-info/RECORD': 'two'})
    assert readiness.wheel_payload(first) == readiness.wheel_payload(second)
    assert not readiness.has_evaluator(readiness.wheel_payload(first))
    for leaked in ('terraproof/evals/lift.py', 'terraproof/data/evals/task.json'):
        assert readiness.has_evaluator(readiness.wheel_payload(wheel(tmp_path/'c.whl', {leaked: 'x'})))


def test_record_refuses_an_existing_venv(tmp_path):
    with pytest.raises(SystemExit, match='new venv'):
        readiness.record(tmp_path)


def test_canary_reports_contamination_screened_when_the_interpreter_can_read_it():
    result = readiness.canary(sys.executable, sys.executable)
    assert result['label'] == 'contamination screened'
    for observed in result['conditions'].values():
        assert observed['canary_readable'] is True
    assert 'Not probed without a model' in result['host_builtin_readers']
