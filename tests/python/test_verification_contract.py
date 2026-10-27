"""Task requirements cannot be satisfied by omitted, unrelated or differently bound checks."""
import copy
import json
from pathlib import Path

import pytest

from terraproof._common import InputError
from terraproof.checks.base import result
from terraproof.evidence.bundle import build_bundle, verify_bundle
from terraproof.evidence.contract import SCHEMA, digest, load_contract
from terraproof.evidence.report import build_report, input_record, render_markdown, report_exit_code


def contract(path, checks=None, parameters=None):
    return {'schema': SCHEMA, 'requirements': [{'paths': [str(path)],
        'checks': checks or ['crs.defined'], 'parameters': parameters or {}}]}


def report(path, *, checks=None, required=None, parameters=None):
    return build_report(inputs=[input_record(str(path), 'input', 'raster')],
        results=checks if checks is not None else [result('crs.defined', 'pass', 'defined', input=str(path))],
        parameters=parameters or {}, contract=required)


@pytest.fixture
def data(tmp_path):
    path = tmp_path/'result.tif'
    path.write_bytes(b'fixture bytes')
    return path


def test_omitted_scientific_check_blocks_contract_but_preserves_legacy_grade(data):
    r = report(data, required=contract(data, ['rs.index_formula'], {'index_formula': 'ndvi'}))
    assert r['grade'] == 'decision-grade' and r['verification']['grade'] == 'advisory-only'
    assert r['verification']['status'] == 'incomplete' and report_exit_code(r) == 3
    assert r['diagnostics'][0]['missing_bindings'] == ['source_band:nir', 'source_band:red']
    assert r['diagnostics'][0]['automatic_patch'] is False
    assert 'Verification contract' in render_markdown(r)
    assert 'عقد التحقق' in render_markdown(r, lang='ar')


@pytest.mark.parametrize('status,expected', [('pass', 'verified'), ('warn', 'review-required'),
    ('fail', 'failed'), ('not-run', 'incomplete')])
def test_required_result_statuses(data, status, expected):
    r = report(data, checks=[result('crs.defined', status, 'observed', input=str(data))], required=contract(data))
    assert r['verification']['status'] == expected
    assert len(r['diagnostics']) == (0 if status == 'pass' else 1)


def test_pass_on_another_output_or_unscoped_check_is_not_coverage(data, tmp_path):
    for evidence in ({'input': str(tmp_path/'other.tif')}, {}):
        r = report(data, checks=[result('crs.defined', 'pass', 'defined', **evidence)], required=contract(data))
        assert r['verification']['status'] == 'incomplete'


def test_parameter_binding_and_each_output_are_required(data, tmp_path):
    reference = tmp_path/'source.tif'
    params = {'reference_input': str(reference), 'processing_full_scan': True}
    req = contract(data, ['rs.scale_applied_once'], params)
    check = result('rs.scale_applied_once', 'pass', 'matches', output=str(data), processing_full_scan=True)
    for actual in ({}, {**params, 'processing_full_scan': False}, {**params, 'reference_input': str(data)}):
        r = report(data, checks=[check], required=req, parameters=actual)
        assert r['verification']['status'] == 'incomplete'
    r = report(data, checks=[check], required=req, parameters=params)
    assert r['verification']['status'] == 'verified'
    assert r['verification']['requirements'][0]['scope'] == 'full-grid'
    req['requirements'][0]['paths'].append(str(tmp_path/'uninspected.tif'))
    assert report(data, checks=[check], required=req, parameters=params)['verification']['status'] == 'incomplete'


def test_ordered_stack_context_cannot_be_swapped(data, tmp_path):
    paths = [str(tmp_path/'first.tif'), str(tmp_path/'second.tif')]
    params = {'stack': paths, 'stack_reduction': 'weighted-sum', 'stack_weights': [1, 4]}
    req = contract(data, ['rs.stack_reduction'], params)
    check = result('rs.stack_reduction', 'pass', 'matches', output=str(data))
    r = report(data, checks=[check], required=req, parameters={**params, 'stack': paths[::-1]})
    assert r['verification']['requirements'][0]['parameter_mismatches'] == ['stack']


def test_file_contract_paths_are_relative_to_contract_file(data, tmp_path, monkeypatch):
    path = tmp_path/'contract.json'
    path.write_text(json.dumps(contract('result.tif')))
    monkeypatch.chdir(tmp_path.parent)
    assert load_contract(path)['requirements'][0]['paths'] == [str(data).lower() if __import__('os').name == 'nt' else str(data)]
    r = report(data, required=str(path))
    assert r['verification']['status'] == 'verified'


@pytest.mark.parametrize('defect', ['unknown-check', 'unknown-parameter', 'duplicate-path', 'empty', 'large'])
def test_contract_validation_is_fail_closed(data, defect):
    req = contract(data)
    if defect == 'unknown-check': req['requirements'][0]['checks'] = ['rs.imaginary']
    elif defect == 'unknown-parameter': req['requirements'][0]['parameters'] = {'encodign': 's2-l2a'}
    elif defect == 'duplicate-path': req['requirements'][0]['paths'] *= 2
    elif defect == 'empty': req['requirements'] = []
    else: req['requirements'][0]['parameters'] = {'encoding': 'x'*65536}
    with pytest.raises(InputError): load_contract(req)


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path/'contract.json'
    path.write_text('{"schema":"x","schema":"y","requirements":[]}')
    with pytest.raises(InputError, match='duplicate'): load_contract(path)


def test_band_aliases_and_band_numbers_have_canonical_bindings(data):
    req = contract(data, ['rs.index_formula'], {'index_formula': 'ndvi',
        'bands': {'nir': str(data), 'red': str(data)}, 'band_numbers': {'nir': 2, 'red': 1}})
    normalized = load_contract(req)
    params = normalized['requirements'][0]['parameters']
    r = report(data, checks=[result('rs.index_formula', 'pass', 'matches', output=str(data))],
               required=req, parameters=params)
    assert r['verification']['status'] == 'verified'
    assert r['verification']['contract_sha256'] == digest(normalized)


def test_contract_cannot_bypass_other_failures_or_have_conflicting_contexts(data):
    checks = [result('crs.defined', 'pass', 'defined', input=str(data)),
              result('geometry.valid', 'fail', 'invalid', input=str(data))]
    r = report(data, checks=checks, required=contract(data))
    assert r['verification']['status'] == 'failed' and report_exit_code(r) == 3
    assert any(d['check'] == 'geometry.valid' for d in r['diagnostics'])
    req = contract(data, parameters={'expect': 'index'})
    req['requirements'].append({'paths': [str(data)], 'checks': ['crs.defined'], 'parameters': {'expect': 'reflectance'}})
    with pytest.raises(InputError, match='conflicting'): load_contract(req)


def test_bundle_can_be_checked_against_an_external_digest(data):
    bundle = build_bundle(report(data))
    assert verify_bundle(bundle, bundle['report_sha256'])['status'] == 'pass'
    assert verify_bundle(bundle, '0'*64)['status'] == 'fail'


@pytest.mark.parametrize('mutation', ['data', 'report', 'contract', 'sidecar', 'new-sidecar', 'coverage'])
def test_bundle_detects_changes(data, mutation):
    sidecar = Path(str(data)+'.msk')
    if mutation == 'sidecar': sidecar.write_bytes(b'mask')
    r = report(data, required=contract(data))
    bundle = build_bundle(r)
    assert verify_bundle(bundle)['status'] == 'pass'
    if mutation == 'data': data.write_bytes(b'changed')
    elif mutation == 'report': bundle['report']['checks'][0]['message'] = 'altered'
    elif mutation == 'contract': bundle['report']['verification']['contract']['requirements'][0]['checks'] = ['geometry.valid']
    elif mutation in ('sidecar', 'new-sidecar'): sidecar.write_bytes(b'new mask')
    else:
        bundle['report']['verification']['status'] = 'incomplete'
        bundle['report_sha256'] = digest(bundle['report'])
    assert verify_bundle(bundle)['status'] == 'fail'


def test_bundle_refuses_data_changed_since_report_and_grade_forgery(data):
    r = report(data)
    bad = copy.deepcopy(r); bad['grade'] = 'advisory-only'
    with pytest.raises(InputError, match='grade'): build_bundle(bad)
    data.write_bytes(b'changed')
    with pytest.raises(InputError, match='changed'): build_bundle(r)


@pytest.mark.parametrize('existed', [False, True])
def test_companion_cannot_change_between_report_and_bundle(data, existed):
    sidecar = Path(str(data)+'.msk')
    if existed: sidecar.write_bytes(b'original mask')
    r = report(data, required=contract(data))
    sidecar.write_bytes(b'changed mask')
    with pytest.raises(InputError, match='companion'): build_bundle(r)


def test_contract_source_file_is_bound_and_bundle_cannot_overwrite_it(data, tmp_path, capsys):
    from terraproof.cli import main
    source = tmp_path/'contract.json'; source.write_text(json.dumps(contract(data)))
    r = report(data, required=str(source))
    assert any(i['role'] == 'contract' for i in r['inputs'])
    bundle = build_bundle(r)
    saved = tmp_path/'report.json'; saved.write_text(json.dumps(r))
    before = source.read_bytes()
    assert main(['evidence', 'write', str(saved), '--out', str(source)]) == 1
    assert source.read_bytes() == before
    source.write_text('{}')
    assert verify_bundle(bundle)['status'] == 'fail'


def test_evidence_usage_errors_keep_cli_exit_one():
    from terraproof.cli import main
    with pytest.raises(SystemExit) as error:
        main(['evidence', 'verify'])
    assert error.value.code == 1
