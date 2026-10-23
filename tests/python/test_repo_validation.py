"""Repository link checks must distinguish source content from generated caches."""

import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    'repo_validation', Path(__file__).resolve().parents[1] / 'validate_repo.py')
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


def test_generated_cache_links_are_ignored_but_source_links_are_checked(tmp_path, monkeypatch):
    cache = tmp_path / '.terracache' / 'installer-fixture'
    cache.mkdir(parents=True)
    (cache / 'AGENTS.md').write_text('[fixture-only](missing-skill.md)', encoding='utf-8')
    (tmp_path / 'README.md').write_text('[broken source](missing-source.md)', encoding='utf-8')
    monkeypatch.setattr(validation, 'REPO_ROOT', tmp_path)
    errors = []
    validation.validate_markdown_links(errors, [])
    assert len(errors) == 1
    assert "'README.md'" in errors[0]
    assert 'missing-source.md' in errors[0]


def test_valid_source_link_still_passes_alongside_generated_cache(tmp_path, monkeypatch):
    cache = tmp_path / '.terracache'
    cache.mkdir()
    (cache / 'fixture.md').write_text('[fixture-only](missing.md)', encoding='utf-8')
    (tmp_path / 'guide.md').write_text('Valid guide.', encoding='utf-8')
    (tmp_path / 'README.md').write_text('[guide](guide.md)', encoding='utf-8')
    monkeypatch.setattr(validation, 'REPO_ROOT', tmp_path)
    errors = []
    validation.validate_markdown_links(errors, [])
    assert errors == []
