"""Unsigned local evidence bundles: content binding, not scientific certification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from terraproof._common import InputError, sha256_and_size
from terraproof.evidence.contract import canonical, coverage, digest, load_contract, path_key

SCHEMA = 'terraproof.evidence-bundle/1'
LIMIT = ('Unsigned record of supplied evidence and known local companions. Verification checks '
         'content binding, not authenticity, rerun correctness, complete lineage or external dependencies.')


def companions(path):
    found = {path}
    for suffix in ('.msk', '.aux.xml', '.ovr', '-wal', '-shm'):
        candidate = Path(str(path)+suffix)
        if candidate.is_file():
            found.add(candidate)
    if path.suffix.lower() == '.shp':
        for suffix in ('.dbf', '.shx', '.prj', '.cpg', '.qix', '.sbn', '.sbx'):
            candidate = path.with_suffix(suffix)
            if candidate.is_file():
                found.add(candidate)
    return found


def capture_companions(report, root):
    paths = set()
    for record in report['inputs']:
        path = Path(path_key(record['path'], root))
        paths.update(companions(path)-{path})
    records = []
    for path in sorted(paths):
        sha, size = sha256_and_size(path)
        records.append({'path': str(path), 'sha256': sha, 'bytes': size})
    return records


def file_records(report, root):
    current_companions = capture_companions(report, root)
    if canonical(current_companions) != canonical(report.get('companions', [])):
        raise InputError('companion evidence changed or was not captured in the report; rerun with a contract')
    paths = {}
    for record in report['inputs']:
        original = Path(record['path'])
        if original.is_symlink() or getattr(original, 'is_junction', lambda: False)():
            raise InputError('linked evidence files are not supported')
        path = Path(path_key(record['path'], root))
        if path.suffix.lower() == '.vrt':
            raise InputError('VRT external dependency capture is not supported by evidence-bundle/1')
        current, size = sha256_and_size(path)
        if current != record['sha256'] or size != record['bytes']:
            raise InputError('reported data changed before bundling: '+str(path))
        for item in companions(path):
            if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                raise InputError('linked evidence files are not supported')
            sha, size = sha256_and_size(item)
            paths[str(item)] = {'path': str(item), 'sha256': sha, 'bytes': size}
    if not paths:
        raise InputError('an evidence bundle needs at least one recorded file')
    return sorted(paths.values(), key=lambda r: r['path'])


def _verify_report(report, root):
    from terraproof.evidence.grade import grade_for
    from terraproof.checks.base import CheckResult
    if report.get('schema_version') != 'terraproof.evidence/0.1':
        raise InputError('unsupported evidence report schema')
    checks = [CheckResult(c['id'], c['family'], c['status'], c['message'], c['evidence']) for c in report['checks']]
    if grade_for(checks) != report['grade']:
        raise InputError('report grade disagrees with its checks')
    if 'verification' in report:
        previous = report['verification']
        contract = load_contract(previous['contract'])
        if canonical(coverage(report, contract, base=root)) != canonical(previous):
            raise InputError('report contract coverage disagrees with its evidence')


def build_bundle(report, root=None):
    from terraproof.provenance._core import _has_credentials
    report = json.loads(canonical(report))
    if _has_credentials(report):
        raise InputError('credential-bearing URLs cannot be persisted in an evidence bundle')
    root = Path.cwd() if root is None else Path(root).resolve()
    _verify_report(report, root)
    return {'schema': SCHEMA, 'report': report, 'report_sha256': digest(report),
            'root': str(root), 'files': file_records(report, root), 'limitation': LIMIT}


def verify_bundle(bundle, expected_report_sha256=None):
    """Check an existing bundle without replacing its original digests."""
    try:
        if (not isinstance(bundle, dict) or set(bundle) != {'schema', 'report', 'report_sha256', 'root', 'files', 'limitation'}
                or bundle['schema'] != SCHEMA or bundle['limitation'] != LIMIT
                or not Path(bundle['root']).is_absolute()):
            raise InputError('invalid evidence bundle schema')
        if digest(bundle['report']) != bundle['report_sha256']:
            raise InputError('report digest mismatch')
        if expected_report_sha256 is not None and bundle['report_sha256'] != expected_report_sha256:
            raise InputError('report does not match the externally trusted digest')
        _verify_report(bundle['report'], bundle['root'])
        if canonical(file_records(bundle['report'], Path(bundle['root']))) != canonical(bundle['files']):
            raise InputError('file or companion evidence changed')
        return {'status': 'pass', 'report_sha256': bundle['report_sha256'], 'limitation': LIMIT}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return {'status': 'fail', 'reason': str(error), 'limitation': LIMIT}


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(1, f'{self.prog}: error: {message}\n')
    parser = Parser(prog='terraproof evidence')
    sub = parser.add_subparsers(dest='command', required=True)
    write = sub.add_parser('write', help='bind an existing JSON report to its recorded files')
    write.add_argument('report', type=Path)
    write.add_argument('--root', type=Path, help='original data working directory (default current directory)')
    write.add_argument('--out', type=Path, required=True)
    verify = sub.add_parser('verify', help='verify an existing unsigned evidence bundle')
    verify.add_argument('bundle', type=Path)
    verify.add_argument('--expected-report-sha256', help='digest retained separately by a trusted caller')
    args = parser.parse_args(argv)
    if args.command == 'write':
        report = json.loads(args.report.read_text(encoding='utf-8'))
        bundle = build_bundle(report, args.root)
        protected = {Path(r['path']).resolve() for r in bundle['files']} | {args.report.resolve()}
        if args.out.resolve() in protected:
            raise InputError('bundle output must not overwrite recorded data or its report')
        args.out.write_text(json.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        print(json.dumps({'status': 'written', 'report_sha256': bundle['report_sha256'], 'limitation': LIMIT}))
        return 0
    result = verify_bundle(json.loads(args.bundle.read_text(encoding='utf-8')), args.expected_report_sha256)
    print(json.dumps(result))
    return 0 if result['status'] == 'pass' else 3
