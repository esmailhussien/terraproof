"""Bundled slope/COG policies: fake provider, real MCP, independent artifact grading."""
from pathlib import Path
import json
import shutil
import urllib.request

import numpy as np
import pytest
import rasterio

from terraproof.evals import lift
from terraproof.evals.fixtures import write_cog
from terraproof.evals.lift import AgentRequest, WITH, WITHOUT
from test_api_agent import api_agent, driver, FakeModel, PRICES, FAKE_KEY, _project
from output_verification import VerificationPlan

PLANS = Path(__file__).resolve().parents[1] / 'verification_plans'
SLOPE = 'terrain-slope-map'
COG = 'raster-cog-delivery'
FILES = {SLOPE: 'terrain-slope-source-contract.json', COG: 'cog-delivery-screen.json'}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('A live HTTP request was attempted')
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
    monkeypatch.setenv('OPENAI_API_KEY', FAKE_KEY)


def prepare(tmp_path, task_id, condition=WITH):
    task = lift.lift_task(task_id)
    project = _project(tmp_path, condition, task_id=task_id)
    policy = VerificationPlan(PLANS / FILES[task_id])
    group = policy.groups(task_id, task.deliverable_names)[0]
    arguments = {'paths': group['paths'], **group['parameters']}
    output = project / 'outputs' / task.deliverable_names[0]
    shutil.copyfile(tmp_path / 'reference' / output.name, output)
    request = AgentRequest(task_id, condition, 0, project, 'brief', 120, 1.0)
    return task, project, policy, arguments, output, request


@pytest.fixture(params=[SLOPE, COG], ids=['slope', 'cog'])
def case(tmp_path, request):
    return prepare(tmp_path, request.param)


def run(case, turns):
    _, _, policy, _, _, request = case
    model = FakeModel(turns)
    result = api_agent.ApiAgentAdapter('openai', 'gpt-4o', PRICES, transport=model,
                                     verification_plan=policy).run(request)
    return result, model


def score(case, tmp_path):
    task, project, *_ = case
    return lift.score_outputs(task, lift._specs()[task.task_id], project / 'outputs', tmp_path / 'score',
                              {name: lift._digest(project / 'inputs' / name) for name in task.inputs})


def test_current_actual_evidence_and_independent_reference_pass(case, tmp_path):
    args = case[3]
    result, model = run(case, [[('terraproof_run_checks', args)], []])
    assert result.status == 'completed', result.turn
    assert result.turn['verification_status'] == 'verified'
    assert result.turn['required_verification']['checks'] == {
        'verified': 3 if case[0].task_id == SLOPE else 4, 'review-required': 0, 'unverified': 0}
    assert result.turn['verification_plan_sha256'] == case[2].sha256
    assert result.terraproof_tool_calls == 1
    assert score(case, tmp_path)['accepted']
    policy_message = next(m['content'] for m in model.requests[0]['messages']
                          if m.get('role') == 'system' and m['content'].startswith('Required output'))
    assert all(check in policy_message for check in case[2].groups(case[0].task_id, case[0].deliverable_names)[0]['checks'])


def test_missing_checks_block_completion(case):
    result, model = run(case, [[]])
    assert result.status == 'failed' and result.turn['verification_status'] == 'unverified'
    assert result.turn['required_verification']['checks']['unverified'] == (3 if case[0].task_id == SLOPE else 4)
    assert result.turn['completion_review_prompts'] == 2 and len(model.requests) == 3


def test_output_tree_change_blocks_an_old_pass(case):
    result, _ = run(case, [[('terraproof_run_checks', case[3])],
        [('write_file', {'path': 'outputs/review-marker.txt', 'content': 'data membership changed'})], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'unverified'
    assert result.turn['completion_review_prompts'] == 2


def test_recheck_after_last_write_restores_current_evidence(case):
    result, _ = run(case, [[('terraproof_run_checks', case[3])],
        [('write_file', {'path': 'outputs/review-marker.txt', 'content': 'updated'})], [],
        [('terraproof_run_checks', case[3])], []])
    assert result.status == 'completed' and result.turn['verification_status'] == 'verified'
    assert result.turn['completion_review_prompts'] == 1


@pytest.mark.parametrize('target', ['output', 'input'])
def test_content_changes_with_restored_mtime_cannot_keep_a_pass(case, target):
    task = case[0]
    relative = ('outputs/' + case[4].name if target == 'output' else 'inputs/' + task.inputs[0])
    code = ('from pathlib import Path\nimport os\np = Path(' + repr(relative) + ')\n'
            's = p.stat()\np.write_bytes(p.read_bytes() + b"\\0")\n'
            'os.utime(p, ns=(s.st_atime_ns, s.st_mtime_ns))\n')
    turns = [[('terraproof_run_checks', case[3])], [('run_python', {'code': code})]]
    if target == 'input': turns.append([('terraproof_run_checks', case[3])])
    result, _ = run(case, turns + [[]])
    assert result.status == 'failed' and result.turn['verification_status'] == 'unverified'
    assert any(c['tool'] == 'run_python' and c['exit_code'] == 0 for c in result.calls)


@pytest.mark.parametrize('task_id,seed,check_id,verdict', [
    (SLOPE, 'vertical-units-ignored.tif', 'terrain.slope_formula', 'fail'),
    (SLOPE, 'square-pixels-assumed.tif', 'terrain.slope_formula', 'fail'),
    (COG, 'delivery_lossy.tif', 'raster.cog_layout', 'warn'),
    (COG, 'delivery_striped.tif', 'raster.cog_layout', 'warn'),
])
def test_known_mistakes_require_review(tmp_path, task_id, seed, check_id, verdict):
    case = prepare(tmp_path, task_id)
    shutil.copyfile(tmp_path / 'reference' / seed, case[4])
    result, model = run(case, [[('terraproof_run_checks', case[3])], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'review-required', result.turn
    assert result.turn['required_verification']['checks']['review-required'] >= 1
    assert result.turn['completion_review_prompts'] == 2
    # Inspect the actual local MCP result delivered to the scripted provider.
    replies = [m['content'] for m in model.requests[1]['messages'] if m.get('role') == 'tool']
    actual_checks = json.loads(replies[0])['report']['checks']
    assert [check['status'] for check in actual_checks if check['id'] == check_id] == [verdict]
    assert not score(case, tmp_path)['accepted']


def test_wrong_values_fail_the_explicit_slope_method(tmp_path):
    case = prepare(tmp_path, SLOPE)
    with rasterio.open(case[4], 'r+') as dst:
        values = dst.read(1); valid = dst.read_masks(1) > 0
        values[valid] *= .5; dst.write(values, 1)
    result, _ = run(case, [[('terraproof_run_checks', case[3])], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'review-required'
    assert result.turn['output_review'] == 'unresolved'
    assert result.turn['required_verification']['checks'] == {
        'verified': 2, 'review-required': 1, 'unverified': 0}


def test_no_complete_finite_stencil_remains_unverified(tmp_path):
    case = prepare(tmp_path, SLOPE)
    with rasterio.open(case[1] / 'inputs/elevation.tif', 'r+') as dst:
        dst.write(np.full((dst.height, dst.width), dst.nodata, dtype=dst.dtypes[0]), 1)
    with rasterio.open(case[4], 'r+') as dst:
        dst.write(np.full((dst.height, dst.width), dst.nodata, dtype=dst.dtypes[0]), 1)
    result, _ = run(case, [[('terraproof_run_checks', case[3])], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'unverified'
    assert result.turn['required_verification']['checks']['unverified'] == 1


@pytest.mark.parametrize('context', ['missing', 'other-source'])
def test_slope_pass_requires_declared_dem_context(tmp_path, context):
    case = prepare(tmp_path, SLOPE)
    args = dict(case[3])
    if context == 'missing': args.pop('dem')
    else:
        shutil.copyfile(case[1] / 'inputs/elevation.tif', case[1] / 'inputs/other-elevation.tif')
        args['dem'] = 'inputs/other-elevation.tif'
    result, _ = run(case, [[('terraproof_run_checks', args)], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'unverified'


def test_unreadable_output_cannot_be_verified(case):
    case[4].write_bytes(b'not a raster')
    result, _ = run(case, [[('terraproof_run_checks', case[3])], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'unverified'


@pytest.mark.parametrize('task_id', [SLOPE, COG])
def test_strict_policy_rejects_previously_oracle_only_errors(tmp_path, task_id):
    case = prepare(tmp_path, task_id)
    with rasterio.open(case[4]) as src:
        data = src.read(1); profile = src.profile
        row, col = np.argwhere(src.read_masks(1) > 0)[20]
    if task_id == SLOPE:
        data[row, col] = profile['nodata']  # the slope screen excludes missing delivered cells
        with rasterio.open(case[4], 'w', **profile) as dst: dst.write(data, 1)
    else:
        data[row, col] += 1  # valid COG layout cannot establish source pixel identity
        write_cog(case[4], data, crs=profile['crs'], origin=(profile['transform'].c, profile['transform'].f),
                  resolution=profile['transform'].a, nodata=profile['nodata'])
    result, _ = run(case, [[('terraproof_run_checks', case[3])], []])
    assert result.status == 'failed' and result.turn['verification_status'] == 'review-required', result.turn
    graded = score(case, tmp_path)
    assert not graded['accepted'] and not graded['oracle_ok'] and 'oracle' in graded['caught_by']
    assert graded['checks_ok']  # frozen benchmark still uses its original, limited checks


@pytest.mark.parametrize('task_id', [SLOPE, COG])
def test_plan_only_command_covers_the_selected_task_without_a_key(task_id, monkeypatch, capsys):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    code = driver.main(['--agent-host', 'openai', '--task', task_id, '--runs', '1',
        '--verification-plan', str(PLANS / FILES[task_id]),
        '--usd-per-million-input', '1', '--usd-per-million-output', '1'])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report['tasks'] == [task_id] and report['required_verification']['applies_to'] == 'with-only'
    assert report['required_verification']['plan_sha256'] == VerificationPlan(PLANS / FILES[task_id]).sha256


@pytest.mark.parametrize('task_id', [SLOPE, COG])
def test_plan_does_not_apply_to_without_condition(tmp_path, task_id):
    case = prepare(tmp_path, task_id, WITHOUT)
    result, model = run(case, [[]])
    assert result.status == 'completed' and result.turn['verification_status'] == 'unverified'
    assert not result.turn['verification_policy_applied']
    assert not any(m.get('content', '').startswith('Required output') for m in model.requests[0]['messages'])
