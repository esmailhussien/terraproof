# Terraproof skill benchmark specifications

These are benchmark **specifications**, not executed benchmarks, fixture datasets,
or proof of skill improvement. An automated harness, fixture implementation and
graders come in a later phase. The current repository validator checks links and
skill frontmatter; parsing these JSON files does not execute their tasks.

## Format

Each file in `tasks/` describes one skill and contains exactly three task specs:

```json
{
  "skill": "skill-directory-name",
  "tasks": [
    {
      "id": "stable-unique-task-id",
      "prompt": "A realistic user request",
      "inputs": "Fixture contents, metadata, seeded defects and independent controls needed",
      "acceptance": ["Observable output, numeric or reporting criterion"],
      "expected_checks": { "crs.defined": "pass" },
      "pitfall": "The silent error the fixture is designed to catch"
    }
  ]
}
```

The example shows one task for readability; production files contain three.
`skill` equals the corresponding skill directory/frontmatter name. IDs are stable
and unique across the specs. `inputs` is a description, not an existing file path
or a claim that fixtures have been generated. Future fixtures must provide
independent ground truth, explicit numeric tolerances, software requirements,
and deterministic seeds where relevant. Tolerances must not be selected by
observing the candidate output.

## Interpret expected checks

`expected_checks` maps **existing** check IDs to `pass`, `warn`, or `fail`. Each
task's acceptance criteria names the artifact(s) and command(s) to which the
mapping applies. Some are intentionally failing **input preflights**: a correct
agent must report the seeded failure, not make the unsafe input pass by changing
its metadata. Other mappings describe the corrected output. They are subsets of
the report, not an assertion that no additional checks or warnings will occur.

For multi-input checks, the expected status applies to every result with that
listed ID in the designated command(s). Checks whose statuses would differ by
input must be evaluated with separate, explicitly named commands rather than
flattening a mixed report into one misleading status.

Allowed IDs currently are:

```text
crs.defined
crs.consistent
crs.metric_operation
geometry.valid
geometry.non_empty
geometry.type_consistent
scope.record_count
raster.nodata_declared
raster.resampling
raster.grid_alignment
raster.cog_layout
rs.reflectance_range
rs.index_range
stac.provenance
```

Checks that cannot run return `not-run`, but that status is not an expected
successful benchmark outcome in these specs. Fixture/environment setup must
make each named check applicable. A missing check is not a pass. Review the
[implemented check dispatcher](../src/terraproof/checks/__init__.py) and
[CLI](../src/terraproof/cli.py) before implementing a grader; the planned catalog
is broader than the current implementation.

## Acceptance beyond checker output

The acceptance array is the full contract. A plausible range does not prove
correct calibration, a record count does not prove preserved IDs, and individual
geometry validity does not prove coverage topology. Manual or future numeric
validators must assess masks, band/formula choice, source-pixel arithmetic,
projection fitness, repair fidelity and provenance when a task requires them.

Do not manufacture nonexistent check IDs for these gaps. Use the task's
observable acceptance criteria and retain reports, output artifacts, parameters
and independent reference comparisons. Record actual check statuses separately
from reviewer/numeric acceptance. Run with and without the skill under matched
conditions only when the later harness exists; no lift or accuracy scores are
claimed here.

## Local check-ID confirmation

The following PowerShell command was run with the bundled Python. It checks all
five specifications, three tasks per file, unique task IDs, and the existing
14-ID allowlist; it does not execute benchmarks.

```powershell
@'
import json
from pathlib import Path
allowed = set('''crs.defined crs.consistent crs.metric_operation
geometry.valid geometry.non_empty geometry.type_consistent scope.record_count
raster.nodata_declared raster.resampling raster.grid_alignment raster.cog_layout
rs.reflectance_range rs.index_range stac.provenance'''.split())
ids = []
files = sorted(Path('evals/tasks').glob('*.json'))
assert len(files) == 5
for path in files:
    spec = json.loads(path.read_text(encoding='utf-8'))
    assert set(spec) == {'skill', 'tasks'}
    assert spec['skill'] == path.stem
    assert len(spec['tasks']) == 3
    for task in spec['tasks']:
        assert set(task) == {'id', 'prompt', 'inputs', 'acceptance', 'expected_checks', 'pitfall'}
        assert all(isinstance(task[key], str) and task[key] for key in ('id', 'prompt', 'inputs', 'pitfall'))
        assert task['acceptance'] and all(isinstance(c, str) and c for c in task['acceptance'])
        assert task['expected_checks'] and set(task['expected_checks']) <= allowed
        assert set(task['expected_checks'].values()) <= {'pass', 'warn', 'fail'}
        ids.append(task['id'])
    print(f'{path}: 3 tasks; all expected_checks IDs/statuses valid')
assert len(ids) == len(set(ids))
print(f'PASS: {len(files)} files, {len(ids)} tasks, {len(allowed)} allowed check IDs')
'@ | & 'C:\Users\mrsom\AppData\Roaming\ZadLoop\harness\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe' -
```

## Task index

- [CRS and units](tasks/crs-and-units.json): metric buffers, axis/datum control, crossing/polar preflight.
- [Vector quality](tasks/vector-quality.json): repair inventory, coverage/duplicates, join scope/GeoJSON.
- [Raster processing](tasks/raster-processing.json): categorical alignment, dtype/masks/windows, COG delivery.
- [Satellite preprocessing](tasks/satellite-preprocessing.json): Sentinel-2 offsets/SCL, Landsat QA/exact-once decode, harmonized composites.
- [Spectral indices](tasks/spectral-indices.json): calibrated NDVI, named water indices, burn/EVI/SAVI formulas and ranges.
