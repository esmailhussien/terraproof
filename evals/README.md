# Terraproof executable benchmark harness

This directory holds the benchmark **specifications** (`tasks/*.json`) and their
**executable harness**: `python -m terraproof.evals run` generates deterministic fixtures,
runs the real Terraproof checks and provenance API, and reports whether each spec's
`expected_checks` and independent numeric oracles hold.

It is not an agent benchmark and produces no agent-lift score. There is no model, no prompt
run and no scoring of free-text answers. What it measures is narrower and concrete: for each
task, whether a generated *correct* artifact reproduces the spec's expected check statuses
and its independent numeric acceptance, and whether seeded *wrong* artifacts are rejected by
the checks, the oracle, or both.

## Commands

Run every spec (27 tasks, 9 files) and print JSON to stdout:

```powershell
.venv\Scripts\python -m terraproof.evals run
```

Write the JSON report to a file, run one task, or keep the generated fixtures:

```powershell
.venv\Scripts\python -m terraproof.evals run --out report.json
.venv\Scripts\python -m terraproof.evals run --only accuracy-stratified-area-olofsson-example
.venv\Scripts\python -m terraproof.evals run --specs path\to\tasks --keep
```

- Exit `0`: every task ran, reproduced its expected checks, passed its oracle, no wrong
  control was accepted, and the separate seven-rule preflight control group has exactly
  seven unique rules with passing correct controls and failing seeded controls.
- Exit `1`: at least one task failed, was unrunnable (missing recipe, fixture error), had a
  missing expected check, or a seeded-wrong control became a false pass.
- Exit `2`: usage error or invalid specs (bad JSON, duplicate task id, unknown check id,
  invalid status, wrong task count).
- `--only` is a diagnostic filter; it does not constitute a full pass.
- `--keep` leaves the temporary fixture tree in place and prints its path to stderr.
- Generated fixtures use `.terracache/` under the current working directory, so an installed wheel never needs to write beside its packaged assets.

The report is deterministic: no timestamps, no absolute paths. Fixture paths inside check
messages are replaced with `<fixtures>`, so two runs produce byte-identical JSON (the tests
assert this).

## Report format

```json
{
  "schema": "terraproof.evals/0.1",
  "command": "python -m terraproof.evals run",
  "summary": {
    "spec_files": 9, "tasks": 27,
    "tasks_passed": 27, "tasks_failed": 0, "tasks_unrunnable": 0,
    "controls_correct": 27, "controls_wrong": 38,
    "false_passes": 0,
    "wrong_controls_rejected_by_checks": "...",
    "wrong_controls_checker_blind_spots": "...",
    "missing_expected_checks": 0,
    "checks_exercised": ["..."],
    "preflight_control_group": {
    "controls": 7, "seeded_failures_rejected": 7, "valid": true
  },
    "spec_check_ids_not_in_catalog": [],
    "exit_code": 0
  },
  "tasks": ["..."],
  "limitations": ["..."]
}
```

Each task entry records its spec id and skill, status, the spec's `expected_checks`, the
evidence grade the checks produced, `automated_scope`, `remaining_requirements`, and its
controls. Each control records the modelled invocation, every check result (id, status,
message), the independent oracle assertions, and a verdict.

Per-control verdicts:

| verdict | meaning |
|---|---|
| `accepted` | the correct control reproduces the expected statuses and passes the oracle |
| `rejected` | a wrong control fails the expected statuses and/or the oracle |
| `rejected_by_oracle_only` | a wrong control passes the checks but the independent oracle rejects it: a **checker blind spot**, recorded on purpose |
| `false_pass` | a wrong control passes both layers; this fails the run and increments `false_passes` |
| `check_status_changed` | a wrong control's statuses differ but the oracle still accepts it; a fixture inconsistency to review |

For a wrong control, any extra failing check also counts as rejection, so the report does not
hide a check that fired outside the spec's `expected_checks`.

## How a task is executed

Each task id maps to exactly one recipe in `src/terraproof/evals/recipes/`; a spec without a
recipe is reported `unrunnable` and exits non-zero (nothing is silently skipped), and a
recipe without a spec is a hard validation error. A recipe builds its fixtures in a fresh
temporary directory and returns:

- a **correct** control: the artifact set the spec describes, run through the real
  `run_checks` dispatcher (and `verify_manifest` where the task needs provenance), plus an
  independent oracle for the numeric acceptance criteria;
- one or more **seeded-wrong** controls: the silent errors named in the task's `pitfall`,
  each with the same oracle. Every wrong control must fail the oracle (otherwise its seed is
  not demonstrably wrong) and must not be a false pass.

The oracle recomputes values from first principles: the stratified area-adjusted estimator of
Olofsson et al. (2014) from the published matrix and mapped counts, `10**(dB/10)` power-domain
averaging, the Sentinel-2 and Landsat Collection 2 calibration formulas, NDVI/NDWI/MNDWI/NBR/
EVI/SAVI formulas, masked medians, log ratios, intersection/gap/hole geometry measurements,
geodesic and local azimuthal-equidistant area references, PROJ operation/grid availability,
and manifest hash determinism. Published spec constants (for example overall accuracy 0.947,
corrected area 21,158 ha) are the ground truth, not values read back from the checks.

The evidence grade is also recorded, and the harness reimplements the documented
status-to-grade rule to check it against the public `grade_for` rather than trusting one
implementation.

## Fixtures

All fixtures are generated locally with numpy/rasterio/pyogrio/shapely/pyproj: small
GeoTIFFs (16x16 to 256x256), COGs, GeoPackages, GeoJSON, STAC Item JSON, CSV samples, and a
GCP-only VRT for the ground-range case. No binary fixture is committed, no network is used,
and the temporary tree is removed after the run. Contents, shapes, seeds and transforms are
fixed, which is what makes the report deterministic.

## Spec format

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

`skill` equals the corresponding skill directory/frontmatter name. IDs are stable and unique
across the specs. `expected_checks` maps **registered** check ids to `pass`, `warn`, or
`fail`. A task's acceptance criteria name the artifact(s) to which the mapping applies; some
are intentionally failing **input preflights**, where a correct agent must report the seeded
failure instead of relabelling the input to make it pass.

`inputs` is a description, not a path; the recipe is the implementation of that description.

## Check IDs

The allowlist is derived at run time from `routing/checks.json` (the check catalog), not from
a hard-coded list in this harness. Specs that name an id the catalog does not register are
rejected. Twenty-three catalog ids are exercised by the 27 tasks:

```text
accuracy.estimates          accuracy.sample_design        crs.consistent
crs.defined                 crs.metric_operation          geometry.non_empty
geometry.type_consistent    geometry.valid                geometry.winding
provenance.reproducible     raster.cog_layout             raster.grid_alignment
raster.nodata_declared      raster.resampling             rs.cloud_mask_applied
rs.index_range              rs.reflectance_range          rs.scale_applied_once
rs.temporal_scope           sar.geocoded                  sar.value_domain
scope.record_count          stac.provenance
```

The seven registered `preflight.*` ids are exercised by a separate deterministic control group rather than task specs. The controls use synthetic inspection-profile dictionaries and call the public preflight API; they do not exercise dataset inspection or filesystem inspection:

```text
preflight.alignment          preflight.categorical_resampling  preflight.index_inputs
preflight.metric_crs         preflight.output_units            preflight.reflectance_decode
preflight.temporal_scope
```

The harness runs the current public `run_checks`, `provenance`, and `preflight` APIs. The
preflight group records seven correct controls and seven seeded plan failures separately;
its rejection count is checker-only and never treats oracle rejection as checker rejection.

`run_checks` is called directly for the processing-level options (`reference_input`,
`encoding`, `qa_path`, `qa_kind`, `time_range`, `sar_expect`, `accuracy_samples`,
`class_areas`) because the benchmark models the check layer, not a particular CLI flag set.
The `command` recorded for each step says which public call it models.

## Acceptance beyond checker output

The `acceptance` array is the full contract, and a check pass never satisfies all of it. Each
task entry lists:

- `automated_scope`: what the harness actually measured (specific check ids plus the oracle's
  numeric assertions);
- `remaining_requirements`: the parts that need written reasoning, expert review, a live
  service, a full external validator, or online reference imagery.

Do not read a green run as agent lift, scientific certification, or full task acceptance. In
particular the harness does not grade: prose explanations, band/loader choices stated only in
an answer, mask-policy justifications, COG validator warnings, live STAC search conformance,
SAS signing at read time, HTTP range reads, or validation against real reference imagery.
Some seeded-wrong controls may be rejected only by the oracle. Those are reported as
`wrong_controls_checker_blind_spots`, not treated as checker rejection or success; the exact
count is a run result, not a documentation claim.

## Task index

- [Accuracy assessment](tasks/accuracy-assessment.json): published stratified estimator, training points as a sample, response design for a change sample.
- [CRS and units](tasks/crs-and-units.json): metric buffers, axis/datum control, crossing/polar preflight.
- [Raster processing](tasks/raster-processing.json): categorical alignment, dtype/masks/windows, COG delivery.
- [Satellite preprocessing](tasks/satellite-preprocessing.json): Sentinel-2 offsets/SCL, Landsat QA/exact-once decode, harmonized composites.
- [Spectral indices](tasks/spectral-indices.json): calibrated NDVI, named water indices, burn/EVI/SAVI formulas and ranges.
- [SAR basics](tasks/sar-basics.json): dB/linear averaging, GCP-only GRD preflight, same-orbit log ratio.
- [STAC and cloud access](tasks/stac-and-cloud-access.json): pinned search manifest, double-decode loader, windowed signed-COG subset.
- [Time series and change](tasks/time-series-and-change.json): monthly composites and counts, phenology-matched difference, post-classification change assessment.
- [Vector quality](tasks/vector-quality.json): repair inventory, coverage/duplicates, join scope/GeoJSON.

## Current measured state

The local checkpoint baseline had 27/27 passing tasks, 38 wrong controls, 15 checker
rejections, 23 oracle-only blind spots, zero false passes and 29 exercised check IDs.
After the focused provenance/optical fixes: **27/27 tasks, the same 38 wrong controls,
21 checker rejections, 17 oracle-only blind spots, zero false passes, 29 check IDs**.
After the post-v0.4.1 compression and winding checks: **27/27 tasks, 38 wrong controls,
23 checker rejections, 15 oracle-only blind spots, zero false passes, 30 check IDs**.
The separate preflight group still rejects all seven seeded failures.

Eight controls now fail production checks (the independent numeric oracles remain independent):

- `stac-pinned-search-manifest`: `timestamp-inside-core` and `signed-href-leak` fail `provenance.reproducible`.
- `stac-signed-windowed-cog-subset`: `signed-href-stored` fails `provenance.reproducible` after the recipe supplies a manifest covering the unchanged signed JSON record.
- `satellite-landsat-qa-once`: `double-decoded-loader` fails `rs.scale_applied_once` with the original DN reference and `landsat-c2-l2` encoding.
- `satellite-s2-baseline-offset-mask`: `offset-skipped` fails `rs.scale_applied_once` with the original DN reference and `s2-l2a` encoding.
- `stac-loader-double-decode`: `zero-dn-decoded` fails `rs.scale_applied_once` because source nodata becomes valid output, including off-stride pixels.
- `raster-cog-delivery`: `lossy-jpeg-cog` warns on `raster.cog_layout` because the file is tagged with JPEG compression, which is always lossy in GeoTIFF. Lossy LERC and WebP settings are not detected.
- `vector-join-scope-and-geojson`: `clockwise-geojson-winding` fails `geometry.winding` because the export's own rings break the RFC 7946 right-hand rule. The check runs only on GeoJSON.

No task specs or expected statuses were weakened or changed. Recipe processing calls use
public `run_checks` with inspected `reference_input` data and the stated `encoding`.
Without the raw reference/calibration, the range screen alone cannot reject offset or double
decoding; without a manifest covering the JSON run record, raster checks cannot detect its
signed href. Nodata preservation checks all band-1 pixels in bounded windows; numerical
calibration still samples a fixed stride. Additional output masking (for example QA) is allowed.
Unsupported differing shapes/transforms, rotated/sheared grids and missing/non-finite calibration
return `not-run`, not evidence of correct processing. The existing numeric reader still reads
the full first band before stride sampling; this work does not claim to fix that memory limit.

Manifest schema 0.1 has exactly five core keys: `files`, `stac_items`, `tool_versions`,
`parameters`, `root_rule`; run creation time belongs in `context`, while acquisition/search
time fields within parameters remain valid. The writer **rejects**, rather than strips,
credential-bearing URLs in STAC hrefs, nested parameters and command arguments before returning
a manifest. Record a stable unsigned URL (non-secret query fields are preserved); signing is
an ephemeral read-time operation. Verification rejects credential-bearing URLs in the manifest
and all recorded local `.json` documents, including standalone run records. Errors do not echo
credential values. Detection covers URL userinfo, SAS signatures/tokens, AWS/Google signed query
fields and common token/API-key fields; it is not a general secret scanner for arbitrary text,
opaque encodings, non-JSON files or unrecognized credential conventions.

Remaining oracle-only controls (15 total; none is claimed closed). In the invocation the spec defines, the checker has no legitimate evidence for any of them. The per-control reasons are in [`docs/RELEASE_CHECKLIST.md`](../docs/RELEASE_CHECKLIST.md) under "Checker blind spots":

- Optical/time-series: `cloudy-dates-included`, `index-of-medians-composite`, `all-invalid-zero-filled`, `spring-to-summer-difference`: require observation-stack/count/composite-rule or phenology-reference checks, not one-output range screens.
- Spectral indices: `reversed-dnbr-sign`, `nbr-wrong-swir-band`, `unscaled-dn-ratio`, `gao-moisture-mislabeled`: require named formula, band identity and calibrated source comparisons.
- SAR: `naive-db-average`, `descending-post-event`: require power-domain aggregation and orbit metadata comparisons.
- Raster/STAC: `unsigned-wraparound`, `whole-scene-download`: require pre-cast reference values and a requested-window coverage contract.
- CRS/vector: `swapped-axis-order`, `foot-radius-unit-confusion`, `dissolve-away-identities`: require control-point positions (the oracle's targets), the radius unit, and an identity/topology reference.

The full run remains the source of truth for counts. The harness does not claim hosted-CI
execution, real agent-host verification, or performance on held-out routing sets.

## Agent lift (Phase 5)

`python -m terraproof.evals lift` reuses nine of these tasks to compare an agent with and
without Terraproof. The agent's output files are graded by the same recipe checks and oracles
described above. The command runs only offline adapters (`--adapter scripted` or
`--adapter replay --recordings DIR`) and never calls a model. `--calibrate-only` proves that
scoring accepts each reference and rejects each seeded-wrong output. Real agent hosts run
only through the opt-in `tests/agent_lift.py` driver, after explicit approval. Design,
statistics, budget and threats to validity are in
[docs/plans/Terraproof_Phase5_PLAN.md](../docs/plans/Terraproof_Phase5_PLAN.md).

## Adding a task

1. Add the spec JSON (three tasks per file) with a registered `expected_checks` mapping.
2. Add a recipe in `src/terraproof/evals/recipes/` whose `RECIPES` entry uses the same task
   id, returns a correct control and at least one seeded-wrong control, and states its
   `automated_scope` and `remaining_requirements`.
3. Give both controls independent oracle assertions, and make every wrong control fail the
   oracle without relying on the check implementation under test.
4. Run `python -m pytest -q tests/python/test_evals.py --basetemp=.pytest_cache/bt-e` and
   `python -m terraproof.evals run`. A duplicate or orphan recipe, unknown check id, missing
   expected check, new false pass, or unrunnable task fails the run.
