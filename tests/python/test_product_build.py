"""A reused build directory must not reintroduce excluded private evaluators."""
from pathlib import Path

import pytest


def builder(monkeypatch):
    pytest.importorskip('setuptools')
    from setuptools import Distribution
    from setuptools.command.build_py import build_py
    from terraproof._build import BuildPy
    monkeypatch.setattr(build_py, 'run', lambda self: None)
    command = BuildPy(Distribution())
    command.copy_tree = lambda *args: None
    return command


def test_reused_build_directory_drops_private_packages_and_assets(tmp_path, monkeypatch):
    command = builder(monkeypatch)
    library = tmp_path/'lib'
    for suffix in ('terraproof/evals', 'terraproof/data/evals'):
        path = library/suffix
        path.mkdir(parents=True)
        (path/'private.py').write_text('private evaluator')
    product = library/'terraproof/__init__.py'; product.write_text('product')
    command.build_lib = str(library)
    command.run()
    assert not (library/'terraproof/evals').exists() and not (library/'terraproof/data/evals').exists()
    assert product.read_text() == 'product'


def test_build_refuses_source_output_before_copying(monkeypatch):
    command = builder(monkeypatch)
    from terraproof import _build
    command.build_lib = str(Path(_build.__file__).resolve().parents[2]/'src')
    with pytest.raises(RuntimeError, match='source checkout'):
        command.run()
