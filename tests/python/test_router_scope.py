"""Exposed internal audit is now development coverage, never fresh acceptance."""
import hashlib
import json
from pathlib import Path

from terraproof.router import find_guidance

ROOT = Path(__file__).resolve().parents[2]


def test_exposed_audit_is_registered_once_without_relabelling():
    path = ROOT / 'evals/routing/internal_20261023.jsonl'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '743909b10d02110287aa715c682b6e4d643735a0c5445640044fbb1b8f501221'
    cases = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
    scenarios = json.loads((ROOT / 'tests/router/scenarios.json').read_text(encoding='utf-8'))['pythonScenarios']
    dev = [json.loads(line) for line in (ROOT / 'evals/routing/dev.jsonl').read_text(encoding='utf-8').splitlines() if line]
    for case in cases:
        registered = [s for s in scenarios if s['id'] == case['id']]
        authored = [s for s in dev if s['id'] == case['id']]
        assert len(registered) == len(authored) == 1
        assert authored[0] == case
        assert registered[0]['prompt'] == case['prompt']
        assert registered[0]['mustInclude'] == case['expected']
        assert registered[0]['mustExclude'] == case['must_not']


def test_inspected_profiles_keep_real_domain_work_in_software_requests():
    # Scope rejection is for unsupported text-only homonyms, not real data.
    profile = {'kind': 'raster', 'crs': {'epsg': 32636, 'is_projected': True},
               'bands': [{'dtype': 'float32'}]}
    result = find_guidance('Inspect the raster for a React application.', datasets=[profile], semantic=False)
    assert 'raster-processing' in {s['name'] for s in result['skills']}
