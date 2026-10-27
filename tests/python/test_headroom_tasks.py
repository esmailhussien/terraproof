"""Offline checks of the Phase 6 headroom cohort (E1): pool, seeded split, calibration and oracles."""
import ast
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import rasterio

from terraproof.evals import headroom, lift
from terraproof.evals.headroom.split import SPLIT_SEED, make_split, to_json
from terraproof.evals.specs import default_spec_dir, load_specs

SPEC_DIR = headroom.spec_dir()
POOL = json.loads((SPEC_DIR / "pool.json").read_text(encoding="utf-8"))["tasks"]
IDS = [task["id"] for task in POOL]


def test_split_file_is_the_seeded_function_of_the_pool():
    assert (SPEC_DIR / "split.json").read_text(encoding="utf-8") == to_json(make_split(POOL, SPLIT_SEED))
    split = headroom.frozen_split()
    assert split["seed"] == SPLIT_SEED == 20261027
    assert len(split["development"]) == 12 and len(split["confirmation"]) == 24
    assert not set(split["development"]) & set(split["confirmation"])
    assert sorted(split["development"] + split["confirmation"]) == sorted(IDS)
    families = {task["id"]: task["family"] for task in POOL}
    for family, counts in split["family_counts"].items():
        members = [task_id for task_id in IDS if families[task_id] == family]
        assert counts["development"] * 3 == len(members)
        assert sum(families[t] == family for t in split["development"]) == counts["development"]


def test_pool_has_36_candidates_in_nine_trap_families():
    assert len(IDS) == len(set(IDS)) == 36
    counts = {}
    for task in POOL:
        counts[task["family"]] = counts.get(task["family"], 0) + 1
    assert counts == {"qa-masking": 6, "scale-offset": 6, "nodata-zero": 6, "dtype-overflow": 3,
                      "categorical-resampling": 3, "geographic-metric": 3, "vertical-units": 3, "db-linear": 3,
                      "temporal-scope": 3}


def test_headroom_cohorts_stay_apart_from_the_frozen_benchmark():
    development, confirmation = lift.COHORTS["headroom-development"], lift.COHORTS["headroom-confirmation"]
    assert [t.task_id for t in development] == headroom.frozen_split()["development"]
    assert [t.task_id for t in confirmation] == headroom.frozen_split()["confirmation"]
    frozen = {t.task_id for t in lift.LIFT_TASKS}
    assert len(lift.LIFT_TASKS) == 15 and not frozen & set(IDS)
    assert not {spec.id for spec in load_specs(default_spec_dir())} & set(IDS)  # still the 33 benchmark tasks
    from terraproof.evals.recipes import REGISTRY
    assert not set(REGISTRY) & set(IDS)
    assert set(headroom.recipe_registry()) == set(IDS) == set(headroom.specs())


def test_every_candidate_passes_the_calibration_gate():
    report = lift.calibrate(IDS)
    failing = [record["task"] for record in report["tasks"] if not record["eligible"]]
    assert report["eligible"] and not failing
    for record in report["tasks"]:
        task = lift.lift_task(record["task"])
        seeded = [case for case in record["cases"] if case["case"].startswith("seeded:")]
        assert len(seeded) == len(task.seeded) >= 1
        assert all("oracle" in case["caught_by"] for case in seeded)  # rejected on the merits, not format


@pytest.mark.parametrize("task_id", IDS)
def test_brief_states_goal_and_format_without_the_trap(task_id):
    task, spec = lift.lift_task(task_id), headroom.specs()[task_id]
    text = lift.brief(task, spec)
    for _, wrong in task.seeded:
        assert wrong not in text and wrong[:-4] not in text
    assert spec.pitfall not in text
    assert all(criterion not in text for criterion in spec.acceptance)


@pytest.mark.parametrize("task_id", IDS)
@pytest.mark.parametrize("corruption", ("one_numeric_cell", "one_mask_cell"))
def test_oracles_reject_one_cell_errors_with_correct_metadata(tmp_path, task_id, corruption):
    task = lift.lift_task(task_id)
    reference = tmp_path / "reference"
    lift._generate(task, reference)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    name = task.deliverable_names[0]
    shutil.copyfile(reference / name, outputs / name)
    with rasterio.open(outputs / name) as src:
        values = src.read(1)
        valid = np.argwhere(~np.ma.getmaskarray(src.read(1, masked=True)))
        profile = src.profile
    row, col = valid[len(valid) // 2]
    if corruption == "one_numeric_cell":
        values[row, col] += 1 if values.dtype.kind in "ui" else 0.125 + 0.05 * abs(float(values[row, col]))
    else:
        values[row, col] = profile["nodata"]
    with rasterio.open(outputs / name, "w", **profile) as dst:
        dst.write(values, 1)
    score = lift.score_outputs(task, lift._specs()[task_id], outputs, tmp_path / "score",
                               {key: lift._digest(reference / key) for key in task.inputs})
    assert not score["accepted"] and score["contract_ok"] is True and score["oracle_ok"] is False


def test_oracles_import_no_recipe_or_check_code():
    source = (Path(headroom.__file__).parent / "oracles.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not {name for name in imported if name and ("recipes" in name or "checks" in name or name == "terraproof.evals.lift")}
