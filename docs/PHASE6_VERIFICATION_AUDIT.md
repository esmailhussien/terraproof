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
