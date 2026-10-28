# Terraproof — Phase 6 Plan: Ship the checks, find headroom

> Status: **in progress (2026-10-27)**. Implemented: A (Phase 5 closed), B1 (product-only wheel and sdist), B4 (clean-install CI from the built wheel), B5 (README install text), B6 (`--agent-python-with`) and D's "now" step (skills frozen and labelled unmeasured). B2 is done: `terraproof` is registered on PyPI and TestPyPI as pending trusted publishers for `publish-python.yml`, and the `pypi` environment needs the maintainer's review. B3's workflow first ran on the `v0.8.0` tag, and v0.8.0 shipped to PyPI and npm on 2026-10-27. C is in progress: the source-aware scorecard rejects 14 of the 25 frozen blind spots (groups 1 and 2) with 0 false passes, past the target of 12; group 3 is not started. E1 is done (headroom cohort calibrated and split; see the E1 record in §3.E). E2 is complete as a 96-run exploratory development shakedown; evaluator exposure and completion/coverage findings are recorded in the [E2 review](../E2_REVIEW.md). An offline corrective batch adds explicit MCP runtime admission and optional verification contracts before the E3 freeze. Amendment 2 fixes the primary model class and its selection rule; Amendment 3 adds the readiness workstream R before E3. E3–E6 have not started; no primary host/model is frozen. It follows the [Phase 5 measurement](Terraproof_Phase5_PLAN.md) and replaces open-ended host and harness work with five bounded workstreams. Every real model call still needs the user's explicit approval with an exact invocation count.
>
> Numbering follows the phase documents. The [v1 roadmap](Terraproof_v1_PLAN.md)'s "Phase 6 — Ecosystem" moves later.

## 1. Why this phase

Phase 5 answered its question. On Claude Code the pre-specified test was not significant (sign-flip p = 0.125). The harder cohort was at ceiling on Claude Code and on Antigravity with `gemini-3.8-flash-high`. Three facts shape what comes next.

- **The original cohort could not have shown lift.** Five of nine tasks were at ceiling, so only four task differences could be nonzero. With four nonzero differences, the smallest p the exact sign-flip test can return is 2/2⁴ = 0.125, which is the observed value. This is post-hoc arithmetic, not part of the pre-specified analysis. While the ceiling holds, more repeats or more hosts on these tasks cannot change it.
- **The tasks give away the method.** To stay gradable, the briefs and `request.json` files state the method. For example, `terrain-slope-map` gives central differences, the edge policy and the stencil. Terraproof is meant to help when a practitioner's prompt leaves a domain trap unstated. The one robust Phase 5 signal came from that kind of task: Landsat QA masking passed 3/3 with Terraproof and 0/3 without, and Terraproof's `rs.cloud_mask_applied` flagged all three "without" outputs.
- **Agents used the checks, but users cannot install them.** The 27 Claude "with" runs made 92 Terraproof MCP calls, mostly `run_checks` (46) and `inspect_dataset` (29). No skill file was read; skill content reached the agent only through 6 `load_section` calls. Yet the Python package that holds the checks and the MCP server is not on PyPI, so users must clone the repository.

Since the main run, much of the work went to new hosts (OpenAI/Groq, Antigravity) and to agent-loop features that exist only in [`tests/api_agent.py`](../../tests/api_agent.py): the completion review and the required-output policy. This phase stops that and puts the effort where the evidence points.

### Amendment 1 (2026-10-27): hosts for E

Decided by the maintainer before any E inference. It replaces decision 2 (§7) and narrows the harness freeze (A).

- **E is measured on open and lower-cost models, not on Claude Code.** Claude Code and Gemini Flash were at ceiling on the current tasks, and most people using a tool like Terraproof for GIS work will use cheaper or open models. Claude is excluded from E for cost and representativeness.
- **Candidate hosts:**
  - **OpenCode CLI** on the maintainer's OpenCode Go subscription with an open model (for example `opencode-go/glm-5.3` or `opencode-go/deepseek-v4.1-flash`). Its provider API stays a fallback.
  - **Antigravity** with Gemini.
  - **The API host** with GPT-4o.
- **One primary host and model.** E2's development shakedown runs the candidates. Before E4, E3 fixes **one** primary host and model, chosen for treatment delivery and availability, not outcomes. Any other host is a separately reported secondary and never pooled.
- **Harness freeze exception:** the OpenCode CLI host (`--agent-host opencode`) is the only new host. It runs `opencode run --format json --pure --auto` with the condition in the workspace (`AGENTS.md` and `opencode.json`). It disables skills from `.claude`/`.agents`, Claude Code prompt files, external plugins and self-update. Preflight fails a run if OpenCode's global config, rules, skills, agents, commands or plugins, or any config above the run project, mention Terraproof.
- **Product side:** OpenCode is also the main open-model path for users. The `--agent opencode` installer format is checked end to end by the host's no-model preflight. A real MCP call is first seen in E2.
- **Costs:** OpenCode Go and Antigravity runs use subscription quota, so the harness limits are the approved run count and timeout. GPT-4o runs keep the API host's USD caps. The cost column below was written for Claude Code and is indicative only.

### Amendment 2 (2026-10-28): the primary is a mid-sized flash model

Decided by the maintainer before E3, with no confirmation-set inference. It narrows Amendment 1's primary choice and, for one input, replaces its "not outcomes" wording (rule 3 below). Amendment 1's host rules and harness freeze are unchanged.

- **Primary model class.** The E primary is a mid-sized, competitively priced flash model on OpenCode Go. The candidates are `opencode-go/glm-5.3-flash`, `opencode-go/deepseek-v4.1-flash` and `opencode-go/mimo-v2.6-flash`. This is the class of model most GIS users of a tool like Terraproof will run. GPT-4o (API host) and Gemini (Antigravity) are no longer primary candidates. If they are run at all, they are separately reported secondaries and never pooled.
- **The trade-off, stated now.** The class is chosen for the intended users, not for headroom. On the E2 development tasks the flash models were accepted 11/12 and 12/12 without Terraproof, and GPT-4o 5/12. Choosing the flash class makes a stop at E5 the likely outcome (see the headroom risk below). The maintainer accepts that, and GPT-4o is not reinstated after E4 is seen.
- **Selection rule, fixed now and applied at E3:**
  1. **Delivery on the corrected setup.** Terraproof MCP calls in every "with" run of the Amendment 3 readiness batch, with MCP admission passing and no contamination finding. E2's delivery counts for no candidate: every E2 "with" run registered MCP with the driver interpreter, so the exposure finding applies to all of them, not only to DeepSeek.
  2. **Availability.** OpenCode Go lists the model id at E3 and served it in the readiness batch.
  3. **Baseline headroom.** Among the candidates that pass (1) and (2), choose the fewest accepted "without" runs, pooling E2 development and the readiness batch. This is the one outcome input, and it is "without" only, as in E4's screen. "With" acceptance and with-minus-without differences are never selection inputs.
  4. **Tie-break.** The lexically first model id. On 12 single runs a one-task gap is noise and a tie is likely, so the tie-break is the expected deciding rule, not an edge case.
- **Development evidence so far (E2, before the corrective batch).** GLM 5.3 Flash: 11/12 accepted without Terraproof, with Terraproof calls in all 12 "with" runs. DeepSeek 4.1 Flash: 12/12 without, Terraproof calls in all 12 "with" runs, and one "with" run that read evaluator sources. MiMo-V2.6-Flash was not in E2. The "without" baselines stand for rule 3, because the "without" condition has no MCP and was not affected by the correction.
- **Headroom risk, stated before E4.** E5 keeps a task if at least one of its 2 screening runs is rejected. At an 11/12 per-run baseline that is 1 − (11/12)² ≈ 16% of tasks, about 4 of the 24 (roughly 3–6), and fewer at 12/12. The go/no-go needs at least 8. These are rough estimates from 12 tasks with one run each. **A stop at E5 is a valid result:** it would mean these flash models avoid the cohort's traps unaided. It is not rescued by switching models on the same screened set.
- **Open option, decided at E3 or not at all:** pre-register screening two candidate models (96 "without" invocations) and confirm on the one that keeps more tasks. Confirmation uses fresh runs, so this selection does not bias the paired comparison. It is allowed only if it is written into the E3 freeze before E4 starts.

### Amendment 3 (2026-10-28): verified treatment delivery before E3

Decided by the maintainer before E3. It adds one bounded readiness workstream, **R**, between the E2 corrective batch ([#37](https://github.com/esmailhussien/terraproof/pull/37), merged) and the E3 freeze. A–C are not restarted and E2 is not rerun. The primary metric, sign-flip analysis, fresh paired confirmation, baseline-only screening and minimum-eight stop rule are unchanged.

- **R1. Lock the runtime.** Build a product-only candidate wheel from a known commit, from both a clean and a reused build directory. Record the wheel SHA-256, the production fingerprint that MCP admission reports (`mcp_production_sha256`), the Python, geospatial and MCP versions, and the registered MCP argv. A version label alone is not enough. The "without" interpreter stays dependency-only; any unavoidable tool-side difference is recorded, not called identical.
- **R2. The evaluator-access boundary.** MCP admission closes the registered-server route. The "with" and "without" environments also drop an activated driver venv from `PATH` and `VIRTUAL_ENV`, so the harness interpreter is not reachable by name. Neither makes other host files unreadable: the checkout and the driver interpreter remain readable by path. Before E3, a no-model check puts a benign canary file outside the task and records whether the agent's own Python and the host's built-in readers can open it. No ACL, ownership or integrity-label change is made. Unless a whole-process boundary is shown, confirmation results are reported as "contamination screened", never "evaluator-blind". The contamination labels keep rejecting runs either way.
- **R3. One live readiness batch (proposed, not approved).** It replaces the separate MiMo shakedown and delivery recheck:
  - MiMo-V2.6-Flash: 12 development tasks × 1 pair = 24 invocations.
  - GLM 5.3 Flash and DeepSeek 4.1 Flash: 4 development tasks × 1 pair each = 16 invocations. The 4 tasks are fixed by a rule that uses no outcome: the alphabetically first development task in each of the first four trap families alphabetically. They are `hr-landcover-shifted-grid`, `hr-sar-boxcar-db`, `hr-three-date-mean-8bit` and `hr-station-distance`.
  - Total 40 invocations on OpenCode Go quota, 900 s timeout, on the R1 candidate wheel. Retries count against the 40.
  - Failed and successful outputs are kept, with host completion, artifact acceptance and verification status reported apart. The batch is a readiness check, not an effect estimate. It needs the user's separate approval of the exact command.
- **Contract usability (F), bounded.** Before E3, only docs and examples that the agent does not see may land: workflow templates for the four existing check families, and one ordinary-CI example that fails a job on a missing or failed required check and uploads the evidence. Templates are matched to declared goals and data, never to benchmark task ids or oracle methods. A compact MCP response changes the treatment, so it waits until after E6.
- **Secondary reporting, registered at E3.** Reported beside the unchanged primary, never in its place:
  - artifact acceptance against verification completion, as a cross-table;
  - wrong outputs flagged by production checks against oracle-only rejections;
  - correct outputs left unverified, with the reason, kept apart from false alarms;
  - "with"/"without" cost, tokens, latency, contamination, infrastructure failures and timeouts.

  Any effect or cost threshold that will drive a product decision is fixed at E3, not after E6.
- **Deferred.** C group 3, large-data performance, spatial previews, automatic patches, signing and a public leaderboard wait until after E6 or a recorded user need. New hosts and skills stay out of this phase.
- **Order.** R1, R2 and the bounded F land offline in one PR. R3 runs only if approved. Then E3 freezes once, and E4 → E5 → E6 follow under the existing protocol.

#### Readiness record (2026-10-28, no model calls)

`tests/runtime_readiness.py` runs R1 (`record`) and R2 (`canary`).

- **R1 (`record`).** The candidate comes from commit `45230c7`, whose production files are identical to main after #37.
  - Wheel: `terraproof-0.8.0-py3-none-any.whl`, SHA-256 `a9e7cd34144ae263844db4d2bec68ebcdc79c60befa0443be9fd7ff729fc7713` (226 payload files). A rebuild gives a different wheel hash (archive timestamps) but the same payload.
  - Production fingerprint: `4bd44f33de3563c9e31d1b8acfb140808bf79274572fe254d24415e3f5a7daf4`.
  - Runtime: Python 3.12.10, numpy 2.5.4, rasterio 1.5.2, pyproj 3.8.0, shapely 2.2.0, pyogrio 0.13.0, mcp 2.3.0.
  - Venv: `C:\Users\mrsom\.venvs\agent-with-r1c`, MCP argv `<venv>\Scripts\python.exe -I -m terraproof.mcp`. The E2 venvs are unchanged.
  - All ten checks pass. The clean export and the reused build directory give identical, evaluator-free payloads, and the reused build dropped a planted stale evaluator. MCP admission passes and the server serves its tools. A no-model OpenCode preflight with this venv admits the same fingerprint.
  - The version label is still 0.8.0, but the code differs from the published 0.8.0, which is why the fingerprint, not the label, identifies the treatment.
- **R1 found two defects, both fixed here.**
  - The admission fingerprint hashed raw bytes, so the same commit failed admission on a checkout whose text files had CRLF line endings. Text is now hashed with CRLF read as LF; binary files are unchanged.
  - The wheel must be installed with its `mcp` extra, or the "with" venv has no MCP server.
- **R2 (`canary`).** The result is the same for both conditions:
  - Neither interpreter can import `terraproof.evals`, and the driver interpreter is not on `PATH`.
  - Both can read a private canary outside the task, the checkout's evaluator source and the driver interpreter by path.
  - OpenCode `run --auto` approves any permission that is not explicitly denied, and the harness denies none.

  Results are therefore labelled **contamination screened**, not evaluator-blind. The trace contamination labels remain the guard.
- **F.** The four [contract templates](../CONTRACT_TEMPLATES.md) and the CI example are tested on generated data. A valid output verifies, an intentional defect fails (a dropped vector record needs review) and missing evidence is incomplete. They are docs only; nothing the agent sees changed.

## 2. Goals

1. Close Phase 5 formally and freeze the lift harness.
2. Publish the Python package to PyPI as a product-only wheel.
3. Reduce checker blind spots with source-aware checks, and report them separately from the frozen benchmark.
4. Decide what happens to the skills, with a rule fixed now and evidence gathered during this phase.
5. Build a task cohort screened for headroom, with a held-out confirmation run.

## 3. Workstreams

### A. Close Phase 5 (docs only)

- Set the Phase 5 status to **closed 2026-10-27**: exit criteria (§10) met, no lift claimed, successor is this plan.
- Mark Phase 5 sections 18–19 as a frozen exploratory log. New results are recorded here, not appended there.
- Add the ceiling arithmetic from section 1 to Phase 5 as a post-hoc note.
- **Harness freeze.** No new agent hosts, adapter features or treatment variants. Instruction forwarding, the completion review and the required-output policy stay as they are: opt-in and confined to `tests/`. The only allowed harness changes are the "with" isolation in B6 and the OpenCode host in Amendment 1.

### B. Publish the Python package to PyPI

Today the CI wheel contains the product **and** `terraproof.evals` (recipes, oracles, fixtures), plus the task specs under `terraproof/data/evals/tasks`. This is also the open Phase 5 contamination issue: a "with" agent can import the oracles.

1. **Product-only wheel.** Exclude `terraproof.evals` and `evals/tasks` from the wheel. The benchmark and the lift harness run from a checkout. Update [`tests/package/python_smoke.py`](../../tests/package/python_smoke.py), which runs the evals from the wheel today, and any docs that say the evals run from an installed wheel.
2. **Name and publisher.** `terraproof` is unclaimed on PyPI (it returned 404 on 2026-10-27). The maintainer creates the PyPI project and configures Trusted Publishing for the GitHub release workflow. No API token is stored in the repository.
3. **Release path.** Publish to TestPyPI first, then PyPI, from a tag on `main`, using the wheel that CI tested. The first PyPI release is `0.8.0`, in step with npm.
4. **Clean-install CI.** Install `terraproof[mcp]` from the index into fresh venvs on Ubuntu, Windows and macOS (Python 3.11 and 3.13). Run `inspect`, run `check` on a generated raster, and list the MCP tools through the official client.
5. **Docs.** The README quick start leads with `pip install "terraproof[mcp]"`. The npm package stays published and unchanged; its retirement is a later decision (v1 plan §4).
6. **"with" isolation.** Add `--agent-python-with` to `tests/agent_lift.py`. The "with" agent gets a venv that holds only the published wheel, on a neutral path. Preflight fails "with" if `terraproof.evals` can be imported there.

### C. Reduce checker blind spots

Twenty-five seeded wrong outputs are rejected only by the independent oracle: the 15 listed in the [release checklist](../RELEASE_CHECKLIST.md) under "Checker blind spots", plus 10 seeds from the [harder cohort](../HARDER_TASKS.md). Almost all of them need evidence that the frozen invocation does not pass to the checks: the source bands, the per-date stack, the operands, or the method the request declares. A real agent has those inputs, so a source-aware check is legitimate as long as it uses only what a user has.

**Rules**

- A check may use the inputs and the parameters the request declares. It may never use oracle targets, reference outputs or `terraproof.evals` code. Checks and oracles never import each other.
- Frozen task invocations, specs, oracles and seeds do not change. Their counts (33 tasks, 25 blind spots) remain the historical benchmark.
- Each task gets an extra **source-aware** invocation that passes the inputs a user would have. Its results are reported next to the frozen counts and never merged into them.
- Every new check needs a seeded fail fixture, a pass fixture, zero false passes and CLI/MCP parity, as in Phase 4.

**Order by user value, not by count**

| Group | Check work | Blind spots it targets |
|---|---|---|
| 1 | Extend `rs.index_formula` beyond NDVI: NBR, dNBR sign, NDWI vs NDMI, EVI with per-band calibration | `unscaled-dn-ratio`, `reversed-dnbr-sign`, `nbr-wrong-swir-band`, `gao-moisture-mislabeled`, both `three-band-vegetation-index` seeds (6) |
| 2 | Time- and stack-aware checks: per-date QA, observation counts, power-domain SAR mean, date-aware trend and rate integration | `cloudy-dates-included`, `index-of-medians-composite`, `all-invalid-zero-filled`, `naive-db-average`, both `vegetation-change-rate` and both `storm-total-rainfall` seeds (8) |
| 3 | Operand and coverage contracts | `unsigned-wraparound`, `whole-scene-download`, `dissolve-away-identities`, `foot-radius-unit-confusion` (4) |
| Later | Grid-transfer contracts, multi-Item orbit and source-date checks | `landcover-summary-grid` and `population-grid-transfer` seeds, `descending-post-event`, `spring-to-summer-difference` (6) |

`swapped-axis-order` stays declared: its only evidence is the oracle's control points.

- **Target:** at least 12 of the 25 rejected under the source-aware invocations, with zero false passes and the frozen counts unchanged.
- **Timing:** checks are part of the treatment. C lands before the treatment freeze (E3) or waits until E6 ends.

### D. Decide what to do with the skills

**Evidence so far**

- Claude Code read no skill file in 27 "with" runs, and skill delivery under `--restricted` was never verified.
- Antigravity read skills 22 times in its 18 harder-cohort "with" runs.
- No measurement separates the skills from the MCP checks.
- The v1 plan's rule is that a skill without measured lift is revised or removed.

**Plan**

- **Now:** freeze skill content (factual fixes only, no new skills). The README labels skills as unmeasured.
- **During E2:** the development shakedown must show whether the chosen host reads skills at all (`skill_reads` > 0 in "with").
- **Measurement:** the skills ablation ("with" minus skills, MCP kept) runs only if E's primary result is significant, as a separately approved follow-up on the same confirmation tasks. Running it in the same study would split an already small task budget.
- **Default at phase end, if there is no skill evidence:** the installer's default becomes checks, MCP and the short instructions block. Skills move behind an opt-in flag (for example `--with-skills`) and stay published as reference. Any registry or routing change follows [AGENTS.md](../../AGENTS.md) rules 11–17, including `npm run test:router` at 100%.

### E. Headroom-screened cohort with held-out confirmation

**Task design**

- Prompts read like a practitioner's request. They state the goal in domain terms ("cloud-free surface reflectance for June"), not the method.
- The deliverable contract states format only: file name, grid, dtype, nodata and output units.
- Every trap must be discoverable from the inputs: metadata, QA bands, STAC properties or units. A task where a reasonable alternative method would also be correct is invalid and is dropped before freeze.
- Each task ships a recipe, an independent oracle and at least one seeded wrong output per trap, and it passes the Phase 5 calibration gate (§3.4). The template is `satellite-landsat-qa-once`.
- Trap families come from the v1 vision: QA/SCL masking, scale/offset and processing baselines, nodata stored as zero, dtype overflow, categorical resampling, metric work in a geographic CRS, vertical units, dB vs linear, and temporal scope.
- This cohort is separate from `original` and `harder` and is never pooled with them.

**Split before any inference.** Author a pool of 36 candidates. A seeded random split, stratified by trap family, gives a **development set** of 12 and a **confirmation set** of 24. Product work (checks, docs, instructions) may use the development set. Before E6, confirmation-set screening is used only for E5's accept/reject counts; its outputs and traces are not inspected.

**Steps** (each live step needs its own approval)

| Step | What runs | Invocations | Expected cost / cap |
|---|---|---|---|
| E1 Calibrate and freeze | Calibration gate on all 36 candidates; commit hash recorded | 0 | $0 |
| E2 Development shakedown | 12 development tasks × 1 pair; checks treatment delivery and skill reads | 24 | ≈ $4 / $24 |
| E3 Freeze treatment and analysis | Record the Terraproof version (the PyPI wheel), host, model, flags, screening rule and primary analysis in this plan | 0 | $0 |
| E4 Screen the confirmation set | "without" only, 2 runs per task | 48 | ≈ $6 / $48 |
| E5 Go/no-go | Keep a task if at least one screening run is rejected on its merits (not for contamination) | 0 | $0 |
| E6 Confirmation | Kept tasks, paired, 3 runs per condition, fresh runs | 6 per kept task (72 at 12) | ≈ $12 / $1 per run |

Costs scale from Phase 5 on Claude Code: about $0.12 per "without" run and $0.20 per "with" run. New tasks may cost more. With claude.ai sign-in these are Claude Code's reported figures, not necessarily separate charges.

**Rules that keep it honest**

- **Screen "without" only.** Screening "with" would select tasks where Terraproof happens to look good.
- **Use fresh runs.** Screening runs never enter the analysis, and confirmation uses fresh runs in both conditions. Selection therefore changes which tasks are included (tasks where the baseline sometimes fails), not how they are scored. The fresh baseline will probably pass more often than it did in screening (regression to the mean); that is expected.
- **Fix the host and model at E3.** Choose them for delivery and availability, plus Amendment 2's "without"-only baseline rule, never by observed effect, and do not change them after screening.
- **Freeze the product after E3.** No product change between E3 and the end of E6. A change invalidates the confirmation set, and a new one must be authored.
- **Go/no-go.** With fewer than 8 kept tasks, stop and report "insufficient headroom on this host" as the result. That is a finding, not a failure.

**Analysis.** Same as Phase 5 §5:

- **Primary:** the exact two-sided sign-flip test on task-level differences, α = 0.05.
- **Also reported:** a task-cluster bootstrap CI, exact McNemar as an anti-conservative secondary, and the contamination and treatment-delivery counts.

The table shows what the test can detect. It was computed with `terraproof.evals.lift.sign_flip_p`, assuming every task changes by the same amount:

| Kept tasks | Smallest pattern with p < 0.05 | Next pattern down |
|---|---|---|
| 8 | all 8 improve: p = 0.008 | 7 up, 1 down: p = 0.070 |
| 10 | 9 up, 1 down: p = 0.022 | 8 up, 2 down: p = 0.109 |
| 12 | 10 up, 2 down: p = 0.039 | 9 up, 3 down: p = 0.146 |

Tasks that show no difference drop out of the test, so 12 kept tasks with 4 flat behave like 8. The target is 12 kept tasks. A 2-run screen keeps a task with a 33% baseline failure rate about 55% of the time, which is why the confirmation pool is 24.

**E1 record (2026-10-27): done, offline, no model calls.**

- **Pool and split first.** The 36 candidate ids and their trap families were committed in [`evals/headroom/pool.json`](../../evals/headroom/pool.json) together with the split, in commit `38cc35d`, before any recipe, oracle or spec text existed. The split is `make_split` in [`headroom/split.py`](../../src/terraproof/evals/headroom/split.py): **seed 20261027**. Each family's sorted ids are shuffled by one `random.Random(seed)` stream, families in sorted order, and the first third goes to development. A test proves that [`split.json`](../../evals/headroom/split.json) is that function's output.
- **Per-family counts** (development / confirmation):

  | Family | Dev | Conf |
  |---|---|---|
  | QA/SCL masking | 2 | 4 |
  | Scale/offset and baselines | 2 | 4 |
  | Nodata stored as zero (and zero that is data) | 2 | 4 |
  | dtype overflow | 1 | 2 |
  | Categorical resampling | 1 | 2 |
  | Metric work in a geographic CRS | 1 | 2 |
  | Vertical units | 1 | 2 |
  | dB vs linear | 1 | 2 |
  | Temporal scope | 1 | 2 |
  | **Total** | **12** | **24** |

- **Development set:** `hr-dekad-rainfall`, `hr-elevation-change-mixed-units`, `hr-hls-nir-reflectance`, `hr-landcover-shifted-grid`, `hr-landsat-clear-red`, `hr-landsat-red-saturation`, `hr-landsat-undeclared-fill`, `hr-modis-ndvi-scaled`, `hr-rainfall-dry-days`, `hr-sar-boxcar-db`, `hr-station-distance`, `hr-three-date-mean-8bit`. The other 24 are the confirmation set. The lift cohorts are `headroom-development` and `headroom-confirmation`. Neither is pooled with `original` or `harder`.
- **Where it lives.** Specs and lift contracts are in [`evals/headroom/tasks.json`](../../evals/headroom/tasks.json), outside `evals/tasks`. Array recipes are in `src/terraproof/evals/headroom/recipes.py`, and scalar oracles that import no recipe or check code are in `headroom/oracles.py`. `python -m terraproof.evals run` therefore still reports the frozen 33 tasks, 25 blind spots and 0 false passes. The only `lift.py` change registers the two cohorts and looks up their specs and recipes. Scoring, calibration, the frozen cohorts and `LIFT_TASKS` (15) are unchanged.
- **Task design.** Prompts state the goal in domain terms. The deliverable contract gives format only (`result.tif`, grid, dtype, nodata, output units). Every trap is discoverable from the inputs: STAC `raster:bands`, `classification:bitfields`/`classes`, `s2:processing_baseline`, GeoTIFF scale/offset, band units and descriptions, CRS, and catalog start/end times.
- **Ambiguity review.** Each task was checked for a second defensible answer, and the fixtures avoid the cases that would create one. They contain no SCL classes 2 or 7, no ambiguous MODIS data-quality bits, no negative reflectance, no tied 2 × 2 blocks, and no accumulation interval that straddles the requested window. The shifted grid gives the same answer by centre lookup and by largest overlap. Geodesic tasks get tolerances that accept both spherical and ellipsoidal answers (oracle `TOLERANCES`). No task needed to be dropped, so the pool and split stand at 36. The plan still recommends an independent review of the briefs before E2.
- **Calibration gate.** All 36 tasks are eligible: references accepted, all 64 seeded-wrong outputs rejected by the oracle (21 development, 43 confirmation), echoed inputs rejected, missing outputs reported, and inputs regenerated byte-identically. Further tests reject a one-cell value error and a one-cell mask error for every task. The recipes run only generic `run_checks` (`crs.defined`, `raster.nodata_declared`), so the seeded mistakes are oracle-only for now. This cohort adds nothing to the frozen blind-spot count.
- **Authorship and blinding.** The same agent authored the tasks, references and seeds, so the confirmation prompts and references have been seen as an author. No confirmation-set agent output or trace exists. The rule that they are never inspected before E6 applies from E4 on.
- **Freeze commit:** `e839724` holds the calibrated cohort (pool and split from `38cc35d`). A later change to a headroom spec, recipe, oracle or input must be recalibrated and recorded here. A change to a confirmation task after E4 starts invalidates that task.

## 4. Order

| # | Workstream | Depends on | Notes |
|---|---|---|---|
| A | Close Phase 5 | — | First; docs only |
| B | PyPI product wheel | A | Packaging, CI, `--agent-python-with` |
| C | Source-aware checks | A | `src/terraproof/checks` and the separate source-aware report |
| E1 | Author and calibrate the cohort | A | New cohort files only |
| D | Skill freeze now; decision after E | — | |
| E2–E6 | Live steps | B, C, E1 | Each needs approval |

B, C and E1 touch disjoint files and can run in parallel.

## 5. Exit criteria

- Phase 5 is marked closed and its log is frozen.
- `pip install "terraproof[mcp]"` from PyPI works in clean venvs on Ubuntu, Windows and macOS in CI. The wheel contains no `terraproof.evals` or task specs.
- The source-aware report rejects at least 12 of the 25 blind spots with 0 false passes. The frozen benchmark is still 33/33 with 25 blind spots and 0 false passes.
- The cohort's 36 candidates are calibrated and frozen and the screening is reported. The confirmation is reported exactly as pre-specified, or the go/no-go stop is recorded as the result.
- The skills decision is recorded with its evidence.
- Suites stay green: `python -m pytest`, `python -m terraproof.evals run`, `npm run test:router` (100%, deterministic) and `python tests/validate_repo.py`.

## 6. Out of scope

- New agent hosts other than OpenCode (Amendment 1), new adapter features, or pooling second-host reports with the primary.
- Prose tasks graded by an LLM judge.
- New skills, or skill rewrites beyond factual fixes.
- Retiring the npm router.

## 7. Decisions needed

1. **Evals in the wheel:** leave them out (proposed), or publish a separate `terraproof-evals` distribution?
2. **Host for E:** decided in Amendments 1 and 2. The primary is a mid-sized flash model on OpenCode Go (GLM 5.3 Flash, DeepSeek 4.1 Flash or MiMo-V2.6-Flash), chosen at E3 by Amendment 2's selection rule. Claude Code is not used for E. Still open: whether to approve Amendment 3's 40-invocation readiness batch, and whether to pre-register a two-model screen.
3. **Pool size:** 36 candidates (proposed), or 24 (cheaper to author, but probably fewer than 12 kept tasks and less power).
4. **Skills default** if there is no evidence by phase end: an opt-in pack (proposed), or keep them in the default install labelled unmeasured.
5. **PyPI publisher:** the maintainer creates the project and the Trusted Publisher; confirm which GitHub repository it trusts.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Authoring 36 calibrated tasks is the largest cost | Reuse recipe and oracle patterns from Phase 4 and the harder cohort; use the smaller pool if decision 3 says so |
| Underspecified prompts become ambiguous | Every trap is discoverable from the inputs; each task gets an ambiguity review; a task with two defensible answers is dropped before freeze |
| The same agent authors the tasks, checks and harness | The split is made before inference; the product is frozen after E3; authorship is recorded; independent review of the briefs is recommended |
| Source-aware checks become a second oracle | They use only inputs and parameters a user has, share no code with the oracles, and are reported apart from the frozen counts |
| There is still no headroom | The go/no-go stop is the result. "Frontier agents avoid these traps unaided" is useful for deciding what the product claims |
| The PyPI name is taken before publication | Claim it first (B2) |


## E2 development record and offline corrective work (2026-10-27)

See the [E2 review](../E2_REVIEW.md) for the unchanged counts, spend, contamination
and the distinction between final-artifact acceptance and host completion.
The three contaminated runs remain rejected; seven unresolved GPT-4o completions
include three accepted artifacts. All six rejected GPT-4o with-artifacts were
rejected only by the independent oracle in final scoring. None of these
development observations is a confirmation result.

The corrective batch uses no model calls. Explicit candidate MCP Python and
production-fingerprint admission close the exposed interpreter route, with native
filesystem limits still declared. Optional [contracts](../VERIFICATION_CONTRACTS.md)
make missing required checks/source context explicit; legacy grades are preserved.
Completion review retains its strict rules and records fixed unresolved labels
for future audits. Do not tune against confirmation outputs. Finish development
readiness and freeze this changed treatment at E3 before E4/E6.
