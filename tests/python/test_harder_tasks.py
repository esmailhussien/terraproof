"""Offline adversarial checks for the added cohort, independent of whole-image probes."""
import shutil

import numpy as np
import pytest
import rasterio

from terraproof.evals import lift

TASKS = (
    'landcover-summary-grid', 'terrain-slope-map', 'population-grid-transfer',
    'vegetation-change-rate', 'storm-total-rainfall', 'three-band-vegetation-index',
)


@pytest.mark.parametrize('task_id', TASKS)
@pytest.mark.parametrize('corruption', ('one_numeric_cell', 'one_mask_cell'))
def test_new_oracles_reject_local_errors_with_correct_metadata(tmp_path, task_id, corruption):
    task = lift.lift_task(task_id)
    reference = tmp_path / 'reference'
    lift._generate(task, reference)
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    name = task.deliverable_names[0]
    shutil.copyfile(reference / name, outputs / name)
    with rasterio.open(outputs / name) as src:
        values = src.read(1)
        valid = np.argwhere(~np.ma.getmaskarray(src.read(1, masked=True)))
        profile = src.profile
    # A local interior observation, rather than a named recipe control point.
    row, col = valid[len(valid) // 2]
    if corruption == 'one_numeric_cell':
        values[row, col] += 1 if values.dtype.kind == 'u' else .125
    else:
        values[row, col] = profile['nodata']
    with rasterio.open(outputs / name, 'w', **profile) as dst:
        dst.write(values, 1)
    score = lift.score_outputs(task, lift._specs()[task_id], outputs, tmp_path / 'score',
                               {key: lift._digest(reference / key) for key in task.inputs})
    assert not score['accepted']
    assert score['contract_ok'] is True
    assert score['checks_ok'] is True  # a new oracle rejection, not a hidden production capability
    assert score['oracle_ok'] is False
    assert 'oracle' in score['caught_by']
