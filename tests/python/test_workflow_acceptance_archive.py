"""Protect archived acceptance evidence; no oracle execution or remote access."""
import hashlib
import json
from pathlib import Path


def test_scientific_acceptance_archive_retains_original_bytes():
    archive = Path(__file__).resolve().parents[1] / 'workflow_acceptance' / '2026-11-03'
    for name in ('SHA256_MANIFEST.json', 'ASSESSMENT_SHA256.json'):
        manifest = json.loads((archive / 'reviewer' / name).read_text(encoding='utf-8'))
        for record in manifest['files']:
            path = archive / 'reviewer' / record['path']
            data = path.read_bytes()
            assert len(data) == record['bytes'], record['path']
            assert hashlib.sha256(data).hexdigest() == record['sha256'], record['path']

    assessment = json.loads((archive / 'reviewer' / 'ASSESSMENT.json').read_text(encoding='utf-8'))
    frozen_path = archive / 'OUTCOMES_FROZEN.json'
    assert hashlib.sha256(frozen_path.read_bytes()).hexdigest() == assessment['outcome_freeze_sha256']
    original = {r['file']: r for r in json.loads(frozen_path.read_text(encoding='utf-8'))['records']}
    for name in ('outcomes.json', 'transfer-ledger.json', 'candidate.json',
                 'EXECUTION_PROTOCOL.md', 'COMMANDS.json', 'execute_acceptance.py'):
        data = (archive / name).read_bytes()
        assert len(data) == original[name]['bytes'], name
        assert hashlib.sha256(data).hexdigest() == original[name]['sha256'], name
