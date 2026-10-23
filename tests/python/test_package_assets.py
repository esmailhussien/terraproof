"""Installed assets must not depend on the checkout or a writable package tree."""

from pathlib import Path

import pytest

from terraproof import _common
from terraproof.evals import specs
from terraproof.evals.harness import run_benchmark
from terraproof.evals.recipes import REGISTRY
from terraproof.mcp.skills import SectionError, load_section


def test_common_and_eval_locators_find_assets_beside_installed_package(tmp_path, monkeypatch):
    package = tmp_path / 'site-packages' / 'terraproof'
    assets = package / 'data'
    (assets / 'routing').mkdir(parents=True)
    (assets / 'skills').mkdir()
    (assets / 'evals' / 'tasks').mkdir(parents=True)
    (assets / 'routing' / 'registry.json').write_text('{}', encoding='utf-8')
    (assets / 'routing' / 'checks.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(_common, '__file__', str(package / '_common.py'))
    assert _common.assets_root() == assets
    assert specs.repo_root() == assets
    assert specs.default_spec_dir() == assets / 'evals' / 'tasks'
    assert specs.catalog_path() == assets / 'routing' / 'checks.json'


def test_default_eval_fixtures_use_working_project_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = run_benchmark(only=[sorted(REGISTRY)[0]])
    assert report['summary']['exit_code'] == 0
    cache = Path.cwd() / '.terracache' / 'evals'
    assert cache.is_dir()
    assert list(cache.iterdir()) == []


def test_registered_unicode_heading_anchor_is_loadable():
    section = load_section('sar-basics', 'calibrate-to-β⁰-σ⁰-or-γ⁰-with-the-product-luts')
    assert section['text'].strip()
    assert section['skill'] == 'sar-basics'


@pytest.mark.parametrize('identifier', ['../SKILL.md', 'σ⁰/../SKILL.md', 'σ⁰\\SKILL.md', 'quick-reference\n', 'σ⁰\x00'])
def test_unicode_identifier_support_still_rejects_paths_and_control_characters(identifier):
    with pytest.raises(SectionError, match='invalid section name'):
        load_section('sar-basics', identifier)
