"""Opt-in, no-inference Docker smoke test with an outside-mount canary.

Creates a fresh task and private canary under --work; never mounts credentials.
The report proves these probes, not resistance to kernel/engine vulnerabilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import uuid

import contained_runtime

PROBE = r'''
import asyncio, importlib.util, json, os, pathlib, socket, subprocess, sys
from mcp import Client
from mcp.client.stdio import StdioServerParameters
checks = {}
checks['task_read'] = pathlib.Path('/workspace/input.txt').read_text() == 'public task input'
pathlib.Path('/workspace/result.txt').write_text('contained result')
checks['task_write'] = pathlib.Path('/workspace/result.txt').read_text() == 'contained result'
checks['nonroot'] = os.geteuid() != 0
checks['evaluator_import_absent'] = importlib.util.find_spec('terraproof.evals') is None
checks['docker_socket_absent'] = not pathlib.Path('/var/run/docker.sock').exists()
denied = []
for candidate in json.loads(sys.argv[1]):
    try:
        pathlib.Path(candidate).read_bytes()
    except (OSError, ValueError):
        denied.append(True)
    else:
        denied.append(False)
checks['private_read_denied'] = all(denied)
checks['private_path_probes'] = len(denied)
try:
    pathlib.Path('/outside-task-write').write_text('forbidden')
except OSError:
    checks['root_write_denied'] = True
else:
    checks['root_write_denied'] = False
try:
    with socket.create_connection(('1.1.1.1', 443), timeout=2):
        checks['external_network_denied'] = False
except OSError:
    checks['external_network_denied'] = True
version = subprocess.run(['agy', '--version'], capture_output=True, text=True, timeout=20)
checks['agent_binary_starts'] = version.returncode == 0
async def mcp_probe():
    async with Client(StdioServerParameters(command=sys.executable, args=['-I', '-m', 'terraproof.mcp'])) as client:
        tools = await client.list_tools()
        return sorted(t.name for t in tools.tools)
names = asyncio.run(mcp_probe())
checks['production_mcp_tools'] = names == ['find_guidance', 'inspect_dataset', 'list_skills', 'load_section', 'preflight', 'run_checks']
print(json.dumps({'checks': checks, 'tools': names, 'agent_version': version.stdout.strip()}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    root = args.work.resolve()
    root.mkdir(parents=True, exist_ok=False)
    project = root/'task'
    project.mkdir()
    (project/'input.txt').write_text('public task input', encoding='utf-8')
    private = root/('private-'+uuid.uuid4().hex+'.txt')
    private.write_text(uuid.uuid4().hex, encoding='utf-8')
    initial = hashlib.sha256(private.read_bytes()).hexdigest()
    drive, tail = private.drive.rstrip(':').lower(), private.as_posix()[3:]
    candidates = [str(private), '../'+private.name, '/'+private.name]
    if drive:
        candidates.extend(prefix+'/'+drive+'/'+tail for prefix in
            ('/run/desktop/mnt/host', '/host_mnt', '/mnt/host', '/mnt'))
    report = contained_runtime.run(args.image, project,
        ['python', '-I', '-c', PROBE, json.dumps(candidates)])
    if report['exit_code'] == 0:
        report['probe'] = json.loads(report.pop('stdout'))
    report['private_canary_unchanged'] = hashlib.sha256(private.read_bytes()).hexdigest() == initial
    report['host_task_write_verified'] = (project/'result.txt').read_text() == 'contained result'
    report['image'] = args.image
    report['model_calls'] = 0
    passed = (report['exit_code'] == 0 and not report['timed_out'] and not report['truncated']
        and report['private_canary_unchanged'] and report['host_task_write_verified']
        and all(report.get('probe', {}).get('checks', {}).values()))
    report['passed'] = passed
    (root/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
