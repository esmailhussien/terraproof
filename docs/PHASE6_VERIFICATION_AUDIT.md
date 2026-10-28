# Phase 6 development verification audit

Recorded 2026-10-28, before E4. No model calls, product changes or confirmation-output inspection.

## What was measured

The existing R3 reports were counted without rewriting them. A deterministic replay generated only the 12 development tasks' 21 seeded mistakes and inspected their production check results. The replay used the source at `d216804` and Python 3.12.10 in the existing driver environment. It did not supply new source-aware parameters or verification contracts.

The calibration path is `_calibrate_task` → `score_outputs` → the substituted task recipe → `check_step` → public `inspect_dataset` and `run_checks`. Thus calibration **does execute production checks**. Headroom recipes call `check_step` with the output alone. The replay observed exactly `crs.defined`, `raster.nodata_declared` and `raster.cog_layout`, all passing on all 21 seeded mistakes. No vertical-unit conversion check was invoked.

All 21 mistakes were rejected by the independent oracle only, and all received the legacy `decision-grade` from those generic checks. This is **0/21 detection and 21/21 false assurance for this configured checking path**, not an estimate of the entire check catalog's sensitivity. The seven seeded cases in each smaller GLM/DeepSeek report overlap this development population and must not be added as independent cases.

## R3 final-artifact cross-table

Correct means `oracle_ok: true` and `contract_ok: true`; in this batch all remaining artifacts have `oracle_ok: false`, with structural contracts satisfied. The unit is one run's deliverable bundle, not a pixel or check.

| Candidate / condition | Correct, decision-grade | Correct, review-required | Wrong, decision-grade | Other grades |
| --- | ---: | ---: | ---: | ---: |
| MiMo / with | 10 | 1 | 1 | 0 |
| MiMo / without | 9 | 2 | 1 | 0 |
| GLM / with | 4 | 0 | 0 | 0 |
| GLM / without | 3 | 1 | 0 | 0 |
| DeepSeek / with | 4 | 0 | 0 | 0 |
| DeepSeek / without | 4 | 0 | 0 | 0 |

The only wrong task was `hr-elevation-change-mixed-units`, on MiMo in both conditions. Each record has `caught_by: ["oracle"]`, `checks_ok: true`, no mismatched checks and `evidence_grade: decision-grade`.

- Wrong-artifact detection by the configured final-scoring checks: **0/2** overall; **0/1** for MiMo with. These two runs are the same task, not independent coverage of two failure modes.
- False assurance conditional on wrong artifacts: **2/2** overall; **1/1** for MiMo with. Wrong artifacts among all decision-grade artifacts: **2/36** overall; **1/11** for MiMo with. Both denominators are reported to avoid hiding errors in the many correct outputs.
- Correct artifacts requiring review: **4/38** overall; **1/11** for MiMo with. This is review burden / potential false alarm, not four proven erroneous check findings. A numerically correct artifact can legitimately need review for another reason. Per-check adjudication is needed before calling a warning false.
- Explicit contract coverage: **not measured**, not zero incomplete results. These legacy final scores contain no explicit required-check coverage assessment. `advisory-only` can mean either a failing check or a check that could not run; it must not be relabelled `incomplete` without the underlying evidence.

`evidence_grade` is computed by the evaluator's final replay of production checks. The without agent never had Terraproof. Neither this field nor a count of MCP calls proves what grade an agent saw in an intermediate tool reply. Retained recordings do not include those full tool arguments/replies. Claims about agent-visible false assurance are therefore unmeasured here.

## Limits and follow-up

Legacy `decision-grade` means the emitted checks passed; omitted semantic checks do not lower it. It is not a certificate of scientific correctness. This is a known scope/communication limitation, even though the final combined benchmark verdict correctly rejects the wrong artifacts through its oracle. Label, selection, contract-default and MCP response changes would change the treatment and wait until E6 ends, or an E5 stop is recorded.

The existing R3 token medians were 7.9k → 34.4k for MiMo, 12.2k → 43.3k for GLM and 12.7k → 40.2k for DeepSeek (without → with). These are ratios of medians, about 4.4×, 3.5× and 3.2×, respectively, not paired median ratios. Whole-batch durations are available; per-run end-to-end latency is not. Subscription use is not economically free despite reported API spend of $0.

Future verification reporting follows the definitions in the [E3 registration](plans/Terraproof_Phase6_PLAN.md#e3-registration-2026-10-28-offline). Historical development evidence remains descriptive and separate from confirmation. Re-running the same generic checks cannot establish the sensitivity of checks that were never invoked. Any later explicit-contract or richer-context audit must be separately labelled as a different configuration, and must not replace these results.

## Evidence identity and reproduction

SHA-256 of the original report bytes:

| Local report in `.terracache/` | SHA-256 |
| --- | --- |
| `r3-mimo.json` | `dfc5589de8253ec8d384fbae779cc0ecd7d38ad54934faa9163d4043691afc08` |
| `r3-glm.json` | `4625432248db1492382081c8800b5f75b06eacbb96b92e2ec25469f6e34bca12` |
| `r3-deepseek.json` | `a62b515736dd8d1a31212665edc5695cbb4063e22fe2ed599d69935ee13e4f55` |

To reproduce the seeded-grade count offline from the repository root, using the driver Python with the repository `src` on its import path:

```python
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from terraproof.evals.lift import COHORTS, _generate
from terraproof.evidence.grade import grade_for

grades, checks = Counter(), Counter()
with TemporaryDirectory() as temp:
    for task in COHORTS["headroom-development"]:
        generated = _generate(task, Path(temp) / task.task_id)
        for control in generated.wrong:
            results = [r for step in control.steps for r in step.results]
            grades[grade_for(results)] += 1
            checks.update((r.id, r.status) for r in results)
print(grades)
print(checks)
```

Expected: 21 decision-grade controls and 21 passes for each of the three check IDs above. This uses internal evaluator helpers for an offline audit, not a public product API.

## E4 confirmation screen: registered verification secondaries

Recorded 2026-10-28, after the [E5 stop](plans/Terraproof_Phase6_PLAN.md#e4-and-e5-record-2026-10-28-stop) unsealed the E4 report.

- **Source.** The 48 E4 runs: MiMo-V2.6-Flash, "without" only, on the 24 confirmation tasks. These are confirmation-set results, kept apart from the development audit above.
- **What the agent had.** No agent had Terraproof.
- **What this measures.** The question is what Terraproof's configured final-scoring checks would have said about these baseline deliverables, judged against the independent oracle and the structural deliverable contract.
- **Not measured.** There is no "with" condition here. So nothing below describes what an agent saw from Terraproof, and nothing compares the two conditions.

**Population.**

- 47 uncontaminated runs:
  - 8 wrong artifacts. The oracle rejected each one, and each met its structural contract.
  - 39 correct artifacts.
- 1 contaminated run (`hr-slope-geographic`, run 0), tabulated apart.
  - Its artifact was correct and graded `decision-grade`, but the run is invalid.
- No run is missing, unreadable, or a host failure.

**Checks that actually ran.**

- A replay of the 48 recorded deliverables through each task's recipe reproduced every report grade.
- The configured checking path ran exactly 3 production checks on every artifact:
  - `crs.defined`
  - `raster.nodata_declared`
  - `raster.cog_layout`
- No other check ran on any artifact.

| Measure (uncontaminated runs) | Result |
| --- | --- |
| 1. Detection: wrong artifacts with an actual production `fail` | **0/8**. All three checks passed on all 8: 0 `fail`, 0 `warn`, 0 `not-run`. |
| 2. False assurance: wrong artifacts graded `decision-grade` | **8/8** |
| 2. Wrong artifacts among all `decision-grade` artifacts | **8/40 (20%)** |
| 3. Correct artifacts with `review-required` | **7/39**. Every one came from a `raster.cog_layout` `warn`, a file-layout finding. None came from a failed check or an inability to verify. |
| 3. Confirmed false alarms | **0**. A layout warning is review burden, not a contradicted defect claim. |
| 4. Explicit limits (`incomplete` coverage) | **Unassessed.** No run declared a verification contract, so required-check coverage was never assessed. This is not zero incomplete results. |

**The relevant checks that never ran.** The 8 wrong artifacts come from 6 tasks in 5 trap families:

- vertical units: `hr-flood-depth-feet`, 2 runs;
- QA masking: `hr-modis-lst-quality`, 2 runs, and `hr-s2-scl-red`, 1 run;
- scale and offset: `hr-reanalysis-air-temperature`, 1 run;
- nodata stored as zero: `hr-landcover-change-fill`, 1 run;
- metric work in a geographic CRS: `hr-slope-geographic`, 1 run.

The oracle rejected them for two reasons:

- the delivered values did not match independent values (6 artifacts);
- the delivered mask did not equal the required support (3 artifacts). One `hr-modis-lst-quality` artifact failed both ways.

None of these families is covered by the three generic checks. The headroom recipes call `check_step` with the output alone, so the source-aware checks from workstream C (index formulas, stack and per-date QA) were never invoked. This is the coverage gap the development audit found, now confirmed on held-out tasks: **0/21** seeded and **0/2** live in development, and **0/8** live in confirmation.

**5. Cost ("without" only).**

| Measure | Value |
| --- | --- |
| Input tokens | 450,982 |
| Output tokens | 123,321 |
| Total tokens | 574,303 |
| Median tokens per run | 8,414.5 |
| Reported spend | $0, on OpenCode Go subscription quota (quota use not measured) |
| Batch elapsed time | 90 min for 48 runs |

- There is no "with" condition, so a "with" against "without" ratio is unavailable.
- Per-run latency was not retained.

**What this means.**

- Under the configured invocation, Terraproof's final-scoring checks gave **no protection against these silent errors**: every wrong artifact received the strongest grade. This does not measure the sensitivity of the whole check catalogue.
- The grade certifies only that the three checks emitted passed. With semantic coverage unassessed, it must not be read as scientific correctness.
- The product work this points to is:
  - selecting checks from the inputs and the declared goal, so that vertical units, QA masks, scale and offset, nodata-as-zero and geographic metrics are actually checked;
  - a grade or response that states what was not checked;
  - default contracts, so coverage is assessed.

  Each is a treatment change. A new measurement of any of them is a new configuration, reported apart from these results.

**Reproduction.** Replay each recorded deliverable through its task's recipe with the scoring substitution, and collect the check results. Run this from the repository root, with the repository `src` on the import path and the local E4 report and recordings:

```python
import collections, json, tempfile
from pathlib import Path
from terraproof.evals.lift import _generate, _substitute, lift_task
from terraproof.evidence.grade import grade_for

report = json.loads(Path(".terracache/e4-screen.json").read_text(encoding="utf-8"))
counts = collections.Counter()
with tempfile.TemporaryDirectory() as temp:
    for task_report in report["tasks"]:
        task = lift_task(task_report["id"])
        for run in task_report["runs"]:
            outputs = Path(".terracache/e4-screen-rec") / task.task_id / "without" / f"run-{run['run']}" / "outputs"
            root, hits = Path(temp) / f"{task.task_id}-{run['run']}", set()
            with _substitute(root, {name: outputs / name for name in task.deliverable_names}, hits):
                recipe = _generate(task, root)
            results = [r for step in recipe.correct.steps for r in step.results]
            assert grade_for(results) == run["evidence_grade"]
            wrong = not (run["oracle_ok"] and run["contract_ok"])
            counts.update((wrong, r.id, r.status) for r in results)
print(sorted(counts.items()))
```

Expected:

- **Wrong artifacts:** 8 passes for each of the three checks.
- **The other 40 artifacts:** 40 passes each for `crs.defined` and `raster.nodata_declared`. `raster.cog_layout` passes 33 times and warns 7 times. These 40 are the 39 correct runs plus the contaminated run, which the expected output does not separate.
- **Report SHA-256:** `1188ef2dce93bacc38f08da57dec2c797e4a3ad03b40792c4046f691f62a3cac`.
