"""Stage production-only code into a clean dependency venv; never copy evaluators.

This is import/package separation, not an operating-system filesystem sandbox.
No provider, credential store, package installer or model is invoked here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("__init__.py", "__main__.py", "_common.py", "_run_helpers.py", "cli.py", "preflight.py",
           "checks", "evidence", "inspect", "install", "mcp", "provenance", "router")
ASSETS = ("skills", "routing", "instructions", "sources", "third_party")
DEPENDENCIES = ("numpy", "rasterio", "pyogrio", "pyproj", "shapely")


def clean_env():
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(name, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


PROBE = r'''
import importlib.util, importlib.metadata, importlib.machinery, json, pathlib, sys, sysconfig
package = importlib.util.find_spec('terraproof')
location = pathlib.Path(package.origin).resolve().parent if package and package.origin else None
prefix = pathlib.Path(sys.prefix).resolve()
purelib = pathlib.Path(sysconfig.get_path('purelib')).resolve()
cfg = prefix/'pyvenv.cfg'
settings = dict(line.split('=',1) for line in cfg.read_text().splitlines() if '=' in line) if cfg.is_file() else {}
settings = {key.strip().lower():value.strip().lower() for key,value in settings.items()}
evaluators = bool(location and ((location/'evals').exists() or (location/'data/evals').exists()))
if location:
    evaluators = evaluators or importlib.machinery.PathFinder.find_spec('terraproof.evals', [str(location)]) is not None
exposed = any((pathlib.Path(p)/'terraproof/evals').exists() for p in sys.path if p)
dependencies = {}
for name in ('numpy','rasterio','pyogrio','pyproj','shapely'):
    try: dependencies[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: dependencies[name] = None
print(json.dumps({'venv':sys.prefix != sys.base_prefix and settings.get('include-system-site-packages') == 'false',
  'prefix':str(prefix), 'purelib':str(purelib), 'python':sys.version.split()[0], 'package':str(location) if location else None,
  'runtime_local':bool(location and location == purelib/'terraproof'),
  'evaluators_visible':evaluators or exposed, 'dependencies':dependencies}))
'''


def inspect_python(python):
    # Neutral cwd prevents the checkout's src or the run project shadowing imports.
    result = subprocess.run([str(python), "-I", "-c", PROBE], cwd=Path(python).resolve().parent,
                            env=clean_env(), capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode:
        raise ValueError("runtime Python probe failed")
    return json.loads(result.stdout)


def file_hashes(root):
    hashes = {}
    for path in sorted(Path(root).rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("runtime contains a link")
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def expected_files():
    files = {"data/LICENSE": hashlib.sha256((ROOT/"LICENSE").read_bytes()).hexdigest()}
    for relative in MODULES:
        path = ROOT / "src/terraproof" / relative
        if path.is_dir():
            files.update({relative + "/" + name: sha for name, sha in file_hashes(path).items()})
        else:
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for relative in ASSETS:
        files.update({"data/" + relative + "/" + name: sha for name, sha in file_hashes(ROOT / relative).items()})
    return files


def prepare(python):
    info = inspect_python(python)
    prefix = Path(info["prefix"])
    if not info["venv"] or info["package"] or prefix == ROOT or ROOT in prefix.parents:
        raise ValueError("use a clean separate dependency-only venv, outside the checkout")
    destination = Path(info["purelib"]) / "terraproof"
    destination.mkdir(exist_ok=False)
    for relative in MODULES:
        source = ROOT / "src/terraproof" / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copyfile(source, target)
    for relative in ASSETS:
        shutil.copytree(ROOT / relative, destination / "data" / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(ROOT/"LICENSE", destination/"data/LICENSE")
    if file_hashes(destination) != expected_files():
        raise ValueError("staged runtime differs from production sources")
    manifest = {"schema": "terraproof.agent-runtime/1", "files": file_hashes(destination),
                "scope": "production imports and MCP only; not filesystem isolation"}
    (prefix / "agent-runtime.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return {"prepared": True, "files": len(manifest["files"]), "model_calls": 0}


def validate_pair(with_python, without_python):
    """Fail closed before host start; return booleans only, no home/config content."""
    checks = {"separate_runtime_pythons": False, "runtime_only_product": False,
              "without_product": False, "evaluator_imports_absent": False, "matching_compute_dependencies": False}
    if not with_python or not without_python:
        return checks
    try:
        with_info, without_info = inspect_python(with_python), inspect_python(without_python)
        checks["separate_runtime_pythons"] = (with_info["venv"] and without_info["venv"]
            and with_info["prefix"] != without_info["prefix"]
            and ROOT not in Path(with_info["prefix"]).parents
            and ROOT not in Path(without_info["prefix"]).parents)
        package = Path(with_info["package"]) if with_info["package"] else None
        manifest = json.loads((Path(with_info["prefix"]) / "agent-runtime.json").read_text(encoding="utf-8"))
        checks["runtime_only_product"] = bool(package and with_info["runtime_local"]
            and manifest.get("schema") == "terraproof.agent-runtime/1"
            and file_hashes(package) == manifest.get("files") == expected_files())
        checks["without_product"] = without_info["package"] is None
        checks["evaluator_imports_absent"] = not (with_info["evaluators_visible"] or without_info["evaluators_visible"])
        checks["matching_compute_dependencies"] = (with_info["python"] == without_info["python"]
            and with_info["dependencies"] == without_info["dependencies"]
            and all(with_info["dependencies"].get(name) for name in DEPENDENCIES))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-python", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.target_python), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Runtime preparation refused: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
