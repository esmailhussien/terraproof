# Additional offline artifact cohort

This local extension adds six synthetic tasks to the v0.5.1 baseline without
changing its 27 task specs, existing recipe functions, numeric oracles or frozen
routing sets. The full catalog now contains **33 tasks in 11 files**; the lift
catalog contains the original nine plus these six. No live agent has been run on
the added cohort, so harder is a design goal, not a measured result.

| Task | User deliverable | Independently evaluated relation | Seeded mistakes |
| --- | --- | --- | --- |
| `landcover-summary-grid` | Categorical summary on the target grid | Per-cell overlap areas, valid support, modal class and deterministic tie policy | Nearest class; ignoring minimum valid area |
| `terrain-slope-map` | Slope angle on the elevation grid | Central differences using both pixel spacings and stored elevation units, with complete stencil masks | Ignoring vertical units; assuming square pixels |
| `population-grid-transfer` | Counts on the planning grid | Source/target rectangle overlap allocation with complete valid coverage | Bilinear interpolation; copying nearest source counts |
| `vegetation-change-rate` | Annual slope map | Per-pixel OLS over actual elapsed dates and the valid-observation set | Acquisition-index axis; missing observations replaced with zero |
| `storm-total-rainfall` | Total depth map | Interval-average rate integrated over each actual UTC interval | Summing rates; equal-duration weighting |
| `three-band-vegetation-index` | EVI on the band grid | Band-specific calibration, joint masks, finite denominator and standard EVI expression | Stored-value arithmetic; one calibration applied to all bands |

Input files and `request.json` contain ordinary user specifications and metadata,
including support policies and method definitions needed to make an answer
unambiguous. They contain no reference output or private oracle control values.
Each task delivers one raster. Spatial metadata, dtype and nodata contracts are
explicit; methods and data meaning belong to the request rather than a hidden
acceptance rule.

The new reference recipes use array operations. The separate
`harder_oracles.py` module reopens the declared inputs and submitted raster,
computes expected values with scalar arithmetic, and tests **every cell's value
and validity mask** plus shape and spatial metadata. It imports neither recipe
code nor check implementations. Calibration checks references, both seeded
mistakes, an echoed input, a missing output and byte-identical regenerated
inputs. The unchanged generic deliverable probe also tests zeroed, shifted-by-one
and row-flipped rasters; local one-cell numeric/mask errors have additional tests.

Run only offline checks:

```powershell
python -m terraproof.evals run
python -m pytest -q
python -c "from terraproof.evals import lift; r=lift.calibrate(); print(r['eligible'], [(t['task'],t['eligible']) for t in r['tasks']])"
```

The initial extended run reports **33/33 tasks, zero false passes and 27 checker
blind spots**: the existing 15 plus the new 12 seeded mistakes. No new production
check is claimed, and no existing blind spot is reclassified as closed.

The original Phase 5 results remain historical nine-task results. The two task sets
are separate cohorts and are never pooled: `run_lift` and both drivers select one
cohort, `original` by default, and refuse `--task` together with `--cohort`. To run
this set, pass `--cohort harder` and get its own approval. At three repeats that is
**36 agent invocations**; the Claude total cap defaults to the planned runs times
`--max-usd-per-run` (36 × $1 = $36 by default). Calibration and the offline probe
tests still cover all fifteen tasks. No approval gate, original result or
treatment-isolation rule was relaxed.

```bash
python tests/agent_lift.py --agent-host claude --runs 3 --cohort harder   # prints the plan only
``` Do not interpret calibration as evidence of baseline difficulty,
agent lift or generalization beyond this deliberately selected challenge set.
