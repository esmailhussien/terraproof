"""Explicit verification requirements; no inferred task, execution or repair."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from terraproof._common import InputError, assets_root, jsonable
from terraproof.evidence.grade import ADVISORY, DECISION, REVIEW

SCHEMA = 'terraproof.verification-contract/1'
FILE_PARAMETERS = {'compare_to', 'reference_input', 'dem', 'nir', 'red', 'qa_path',
                   'accuracy_samples', 'class_areas', 'manifest'}
PARAMETERS = FILE_PARAMETERS | set('operation resampling categorical expect encoding slope_method raster_identity '
    'index_formula index_bands stack stack_reduction stack_weights stack_min_count processing_full_scan qa_kind '
    'time_range sar_expect min_per_class estimates_requested require_provenance'.split())


def canonical(value):
    return json.dumps(jsonable(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _unique(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise InputError('duplicate JSON key in verification contract')
        document[key] = value
    return document


def path_key(value, base):
    if not isinstance(value, str) or not value or '\0' in value or '://' in value:
        raise InputError('contract paths must name local files')
    path = Path(value)
    return os.path.normcase(str((path if path.is_absolute() else base/path).resolve()))


def parameters(values, base):
    values = json.loads(canonical(values))
    if 'bands' in values or 'band_numbers' in values:
        if 'index_bands' in values or not isinstance(values.get('bands'), dict):
            raise InputError('use bands/band_numbers or index_bands, not both')
        numbers = values.pop('band_numbers', {})
        bands = values.pop('bands')
        if not isinstance(numbers, dict) or set(numbers) - set(bands):
            raise InputError('band_numbers must correspond to supplied bands')
        values['index_bands'] = {role: [path, numbers.get(role)] for role, path in bands.items()}
    if set(values) - PARAMETERS:
        raise InputError('unknown verification parameter: '+', '.join(sorted(set(values)-PARAMETERS)))
    for key in FILE_PARAMETERS:
        if isinstance(values.get(key), str):
            values[key] = path_key(values[key], base)
    if values.get('stack') is not None:
        if not isinstance(values['stack'], list):
            raise InputError('stack must be an ordered list of local paths')
        values['stack'] = [path_key(p, base) for p in values['stack']]
    if values.get('index_bands') is not None:
        if not isinstance(values['index_bands'], dict):
            raise InputError('index_bands must map roles to [path, band number or null]')
        for role, pair in values['index_bands'].items():
            if (not isinstance(pair, list) or len(pair) != 2 or
                    (pair[1] is not None and (type(pair[1]) is not int or pair[1] < 1))):
                raise InputError('invalid index source-band binding')
            values['index_bands'][role] = [path_key(pair[0], base), pair[1]]
    return values


def load_contract(value, *, with_record=False):
    """Resolve file contracts relative to their own folder; inline ones use cwd."""
    base = Path.cwd()
    record = None
    try:
        if isinstance(value, (str, os.PathLike)):
            path = Path(value).resolve()
            base = path.parent
            with path.open('rb') as source:
                raw = source.read(65537)
            if len(raw) > 65536:
                raise InputError('verification contract exceeds 64 KiB')
            value = json.loads(raw, object_pairs_hook=_unique)
            record = {'path': str(path), 'role': 'contract', 'kind': 'verification-contract',
                      'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        if (not isinstance(value, dict) or set(value) != {'schema', 'requirements'} or value['schema'] != SCHEMA
                or not isinstance(value['requirements'], list) or not value['requirements']):
            raise InputError('invalid verification contract schema')
        if len(json.dumps(value, allow_nan=False).encode('utf-8')) > 65536:
            raise InputError('verification contract exceeds 64 KiB')
        catalog = json.loads((assets_root()/'routing/checks.json').read_text(encoding='utf-8'))['checks']
        groups = []
        for group in value['requirements']:
            if (not isinstance(group, dict) or set(group) != {'paths', 'checks', 'parameters'}
                    or not isinstance(group['paths'], list) or not group['paths']
                    or not isinstance(group['checks'], list) or not group['checks']
                    or not all(isinstance(c, str) and c in catalog for c in group['checks'])
                    or len(set(group['checks'])) != len(group['checks'])
                    or not isinstance(group['parameters'], dict)):
                raise InputError('invalid verification requirement')
            paths = sorted(path_key(p, base) for p in group['paths'])
            if len(set(paths)) != len(paths):
                raise InputError('duplicate verification path')
            groups.append({'paths': paths, 'checks': sorted(group['checks']),
                           'parameters': parameters(group['parameters'], base)})
        if len({canonical(g) for g in groups}) != len(groups):
            raise InputError('duplicate verification requirement')
        shared = {}
        for group in groups:
            for key, value in group['parameters'].items():
                if key in shared and canonical(shared[key]) != canonical(value):
                    raise InputError('one contract describes one invocation; conflicting parameter: '+key)
                shared[key] = value
        normalized = {'schema': SCHEMA, 'requirements': sorted(groups, key=canonical)}
        return (normalized, record) if with_record else normalized
    except (OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, InputError):
            raise
        raise InputError(f'cannot read verification contract ({type(error).__name__})') from error


def _missing_bindings(check, values):
    needed = {
        'crs.metric_operation': ['operation'], 'raster.resampling': ['resampling', 'categorical'],
        'rs.scale_applied_once': ['reference_input', 'processing_full_scan'],
        'rs.cloud_mask_applied': ['qa_path', 'qa_kind', 'processing_full_scan'],
        'rs.stack_reduction': ['stack', 'stack_reduction'],
        'rs.index_formula': ['index_formula'], 'terrain.slope_consistent': ['dem'],
        'terrain.slope_formula': ['dem', 'slope_method'],
        'raster.source_identity': ['compare_to', 'raster_identity'],
        'provenance.reproducible': ['manifest'],
    }.get(check, [])
    missing = [key for key in needed if key not in values or values[key] is None]
    if check == 'rs.index_formula':
        from terraproof.checks.index_formula import FORMULAS
        roles = FORMULAS.get(values.get('index_formula'), ((),))[0]
        bound = set(values.get('index_bands') or {}) | {r for r in ('nir', 'red') if values.get(r)}
        missing += ['source_band:'+role for role in roles if role not in bound]
    if check == 'rs.stack_reduction' and values.get('stack_reduction') in ('weighted-sum', 'ols-slope'):
        if not values.get('stack_weights'):
            missing.append('stack_weights')
    return missing


def check_paths(check, base):
    evidence = check.get('evidence', {})
    paths = [evidence.get(key) for key in ('input', 'output')]
    if isinstance(evidence.get('inputs'), list):
        paths += evidence['inputs']
    found = set()
    for path in paths:
        if isinstance(path, str):
            try:
                found.add(path_key(path, base))
            except InputError:
                pass
    return found


def recheck_arguments(group):
    values = dict(group['parameters'])
    if values.get('index_bands'):
        pairs = values.pop('index_bands')
        values['bands'] = {role: pair[0] for role, pair in pairs.items()}
        values['band_numbers'] = {role: pair[1] for role, pair in pairs.items() if pair[1] is not None}
    return {'paths': group['paths'], **values}


def coverage(report, contract, base=None):
    """Bind every check to its output and declared context, never just its ID."""
    base = Path.cwd() if base is None else Path(base)
    actual = parameters(report['parameters'], base)
    outputs = {path_key(r['path'], base) for r in report['inputs'] if r['role'] == 'input'}
    rows = []
    for group in contract['requirements']:
        mismatched = [key for key, value in group['parameters'].items()
                      if key not in actual or canonical(actual[key]) != canonical(value)]
        for path in group['paths']:
            for check in group['checks']:
                missing = _missing_bindings(check, group['parameters'])
                found = [c for c in report['checks'] if c['id'] == check and path in check_paths(c, base)]
                statuses = {c['status'] for c in found}
                if path not in outputs or missing or mismatched or not found:
                    status = 'missing'
                elif 'fail' in statuses:
                    status = 'fail'
                elif 'not-run' in statuses:
                    status = 'not-run'
                elif 'warn' in statuses:
                    status = 'warn'
                else:
                    status = 'pass'
                rows.append({'path': path, 'check': check, 'status': status,
                    'scope': ('full-grid' if check in ('rs.index_formula', 'rs.stack_reduction',
                        'terrain.slope_formula', 'raster.source_identity') else
                        'full-grid' if any(c['evidence'].get('processing_full_scan') for c in found) else
                        'sampled' if check in ('rs.scale_applied_once', 'rs.cloud_mask_applied',
                            'rs.index_range', 'rs.reflectance_range') else 'check-defined') if found else 'not-run',
                    'missing_bindings': missing, 'parameter_mismatches': mismatched,
                    'recheck': {'tool': 'run_checks', 'arguments': recheck_arguments(group),
                                'required_checks': [check], 'contract_sha256': digest(contract)}})
    statuses = {r['status'] for r in rows}
    status = ('failed' if 'fail' in statuses else 'incomplete' if statuses & {'missing', 'not-run'}
              else 'review-required' if 'warn' in statuses else 'verified')
    if status == 'verified' and report['grade'] != DECISION:
        status = ('failed' if any(c['status'] == 'fail' for c in report['checks']) else
                  'incomplete' if report['grade'] == ADVISORY else 'review-required')
    grade = ADVISORY if status in ('failed', 'incomplete') else REVIEW if status == 'review-required' else report['grade']
    # Any other observed failure/warning remains material; a contract cannot bypass it.
    if report['grade'] == ADVISORY:
        grade = ADVISORY
    elif report['grade'] == REVIEW and grade == DECISION:
        grade = REVIEW
    return {'status': status, 'grade': grade, 'contract': contract, 'contract_sha256': digest(contract),
            'required': len(rows), 'passed': sum(r['status'] == 'pass' for r in rows), 'requirements': rows}


def diagnostics(report):
    """Measured conditions and bounded next steps; never an automatic patch."""
    findings = []
    for row in report['verification']['requirements']:
        if row['status'] == 'pass':
            continue
        matched = [c for c in report['checks'] if c['id'] == row['check']
                   and row['path'] in check_paths(c, Path.cwd())]
        findings.append({'check': row['check'], 'path': row['path'], 'status': row['status'],
            'observations': [{'message': c['message'], 'evidence': c['evidence']} for c in matched],
            'missing_bindings': row['missing_bindings'], 'parameter_mismatches': row['parameter_mismatches'],
            'action': 'supply-required-evidence-and-recheck' if row['status'] in ('missing', 'not-run')
                      else 'review-observations-correct-a-new-output-and-recheck',
            'recheck': row['recheck'], 'automatic_patch': False})
    covered = {(r['check'], r['path']) for r in report['verification']['requirements']}
    for check in report['checks']:
        paths = check_paths(check, Path.cwd())
        if check['status'] != 'pass' and not any((check['id'], p) in covered for p in paths):
            findings.append({'check': check['id'], 'paths': sorted(paths), 'status': check['status'],
                'observations': [{'message': check['message'], 'evidence': check['evidence']}],
                'action': 'review-additional-observed-finding', 'automatic_patch': False})
    return findings
