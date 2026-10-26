"""Install Terraproof into a fresh venv outside the checkout and use it as a user would.

`--wheel DIR_OR_FILE` installs a built wheel (its dependencies come from PyPI); `--index URL
--version X` installs `terraproof[mcp]==X` from a package index (TestPyPI or PyPI), retrying
while a fresh upload propagates. Either way the venv then runs `python -m terraproof inspect`
and `check` on a generated raster, lists the MCP tools through the official client, and
confirms the benchmark and lift harness (`terraproof.evals`) are not installed (Phase 6 B4).
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import venv

TOOLS = ["find_guidance", "inspect_dataset", "list_skills", "load_section", "preflight", "run_checks"]

PROBE = r'''
import asyncio, importlib.util, json, subprocess, sys
from pathlib import Path
import numpy as np, rasterio
from rasterio.transform import from_origin
import terraproof
assert not Path(terraproof.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert importlib.util.find_spec('terraproof.evals') is None
raster = Path.cwd() / 'probe.tif'
data = np.arange(64, dtype='float32').reshape(8, 8)
with rasterio.open(raster, 'w', driver='GTiff', height=8, width=8, count=1, dtype='float32',
                   crs='EPSG:32636', transform=from_origin(500000, 5000000, 10, 10), nodata=-9999.0) as dst:
    dst.write(data, 1)
inspected = json.loads(subprocess.run([sys.executable, '-m', 'terraproof', 'inspect', str(raster)],
                                      capture_output=True, text=True, check=True).stdout)
assert inspected['kind'] == 'raster' and inspected['crs']['epsg'] == 32636
checked = subprocess.run([sys.executable, '-m', 'terraproof', 'check', str(raster), '--format', 'json'],
                         capture_output=True, text=True)
assert checked.returncode in (0, 2, 3), checked.stderr
report = json.loads(checked.stdout)
assert {c['id'] for c in report['checks']} >= {'crs.defined', 'raster.nodata_declared'}
from mcp import Client, StdioServerParameters
async def tools():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'terraproof.mcp'])
    async with Client(params, raise_exceptions=False, read_timeout_seconds=60) as client:
        return sorted(tool.name for tool in (await client.list_tools()).tools)
names = asyncio.run(asyncio.wait_for(tools(), 120))
print(json.dumps({'version': terraproof.__version__, 'grade': report.get('grade'), 'mcp_tools': names}))
'''


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _install(python: Path, args) -> None:
    if args.wheel:
        wheel = args.wheel.resolve()
        if wheel.is_dir():
            wheels = sorted(wheel.glob("terraproof-*.whl"))
            if len(wheels) != 1:
                raise SystemExit("expected exactly one terraproof wheel")
            wheel = wheels[0]
        command = [str(python), "-m", "pip", "install", "--quiet", f"{wheel}[mcp]"]
        subprocess.run(command, check=True)
        return
    command = [str(python), "-m", "pip", "install", "--quiet", "--no-cache-dir", "--index-url", args.index,
               f"terraproof[mcp]=={args.version}"]
    if args.extra_index:
        command += ["--extra-index-url", args.extra_index]
    for attempt in range(args.attempts):
        if subprocess.run(command).returncode == 0:
            return
        time.sleep(30)  # a fresh upload can take a few minutes to appear in the index
    raise SystemExit(f"terraproof[mcp]=={args.version} did not install from {args.index}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", type=Path, help="built wheel, or a directory holding exactly one")
    source.add_argument("--index", help="package index URL to install terraproof[mcp] from")
    parser.add_argument("--version", help="exact version to install with --index")
    parser.add_argument("--extra-index", help="extra index for dependencies (TestPyPI needs PyPI)")
    parser.add_argument("--attempts", type=int, default=10)
    args = parser.parse_args()
    if args.index and not args.version:
        parser.error("--index needs --version")
    checkout = Path(__file__).resolve().parents[2]
    work = Path(tempfile.mkdtemp(prefix="clean-install-")).resolve()
    if work.is_relative_to(checkout):
        raise SystemExit("the clean install must run outside the checkout")
    try:
        venv.EnvBuilder(with_pip=True).create(work / "venv")
        python = _venv_python(work / "venv")
        _install(python, args)
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([str(python), "-I", "-c", PROBE, str(checkout)], cwd=work, env=env,
                                capture_output=True, text=True, timeout=600)
        if result.returncode:
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        if summary["mcp_tools"] != TOOLS or (args.version and summary["version"] != args.version):
            print(json.dumps({"status": "fail", **summary}))
            return 1
        print(json.dumps({"status": "pass", "evals_installed": False, **summary}))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
