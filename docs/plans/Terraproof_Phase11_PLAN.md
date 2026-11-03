# Terraproof Phase 11 plan: one declaration per pipeline, tested on agents

> Status: **T1 done; T2 attempt 2 ran (12 of 12): adoption 11/12, 0 false assurance, 0 saves because no agent made a mistake; inconclusive, no push. T3 designed; its prerequisite B (declarations checked against their sources' metadata) built; T3 ran (14 of 14 scored, 15 invocations): adoption 14/14, 0 false assurance on faithful declarations, 1 save (by the cross-check), 1 belief certified; value bar not met, no push (2026-11-03).** It follows [Phase 10](Terraproof_Phase10_PLAN.md) and release 0.12.0.

## 1. Why

Phase 10 S5 showed again that Terraproof catches real mistakes without false assurance **when the requirement is declared**. Undeclared and proposed configurations caught nothing (0 of 20 in S5). The bottleneck is the declaration, not the checks.

- **T1** makes the declaration cheap: one project file per pipeline, one command, one exit code.
- **T2** asks whether that is worth releasing. Do agents write the file without being told to, and does it catch their mistakes?

Nothing is pushed, merged or published until T2 shows strong practical value (section 4).

## 2. T1. Project verification (done)

`terraproof.toml` (or `.json`) declares each deliverable's outputs, goals and bindings once. Two entry points run it:
- `terraproof verify` (`--plan` before any output exists);
- the MCP tool `verify_project`.

The MCP instructions ask an agent to write the file before producing outputs and to verify before reporting done. See [PROJECT_VERIFICATION.md](../PROJECT_VERIFICATION.md).

Shown on 6 real S0b outputs: 3 correct verified `decision-grade`, and 3 wrong failed with their findings. The full suite and the router pass.

## 3. T2. Agent trial

### Questions

1. **Adoption.** With a neutral brief, does the agent write a valid project file covering its deliverables and call `verify_project`?
2. **Catches.** When an output is wrong at the moment the agent verifies, is it flagged? Does the agent then fix it?
3. **Declaration faithfulness.** Does the agent declare the true requirement, or the same wrong belief it acted on? A wrong declaration is checked faithfully, so this is the main route to false assurance.

### Host and model

- Same as P4 and Q5.2: OpenCode 1.19.4 with `opencode-go/mimo-v2.6-flash`.
- The "with" condition only.
- This model's error rate on the Sentinel-2 offset trap is known: 4 of 4 P4 reflectance deliverables were wrong.

### Tasks

Three pipelines on cached sources. Every source belongs to a spent set (Q0, S0b), so no sealed case is read. Each task has several deliverables, which is the case the project file exists for.

| Task | Inputs (cache) | Deliverables | Truth (oracle: numpy, rasterio, pyproj) | Trap |
| --- | --- | --- | --- | --- |
| `t2-s2-pipeline` | Q0 `s2-v0`: `wa_B08` (NIR, 10 m), `wa_SCL` (20 m), STAC item. Earth Search `sentinel-2-l2a`, baseline 05.11, `boa_offset_applied: true` | `nir_reflectance.tif`; `usable_mask.tif` (SCL grid); `scene_summary.json` with `usable_share` and `mean_nir_reflectance` | Reflectance = DN × 1e-4, with 0 as fill. Usable = SCL 4, 5, 6, 11. Share = usable / all SCL cells. Mean over valid NIR cells | Offset −0.1 applied twice (P4: 4 / 4). Classes 2, 3, 7 or 10 kept (27 036 class-2 cells) |
| `t2-norway-terrain` | S0b `norway_win` (Copernicus DEM, EPSG:4326, 69.3° N) | `slope_deg.tif`; `elevation_ft.tif`; `terrain_summary.json` with `mean_elevation_m` and `max_elevation_m` | Slope on WGS84 ground spacing (central differences or Horn: median ≤ 0.2°, p95 ≤ 1°). Feet = m / 0.3048. Mean and max over all cells | Latitude ignored (cos 69° ≈ 0.36). Degrees treated as metres |
| `t2-socal-coast` | S0b `USGS_13_n33w118_win` (3DEP, 60 % fill, 39 % real zeros) and its XML | `elevation_ft.tif`; `coast_summary.json` with `valid_cell_count` and `mean_elevation_m` | Fill stays nodata. Real zeros count. Feet = m / 0.3048 | Fill converted or counted. Zeros dropped as nodata |

Every task has one or more traps. Deliverables without one serve as false-alarm controls.

### Brief and install

- **Brief.** The Q5.2 neutral brief (`brief()`): the task text and the deliverable list. It never mentions verification, Terraproof or a project file.
- **Install.** Terraproof is installed as a user would install it: router skills plus the MCP server.
- **The only nudge** toward the project file is the shipped MCP instructions.

### Snapshots (one disclosed deviation)

To know whether an output was wrong **at the moment it was verified**, the server command in the run project's `opencode.json` points to a wrapper outside the project.

- **What it does.** Before each `verify_project` or `run_checks` call, it copies `outputs/` and the project file to a snapshot directory outside the project. It then calls the unchanged server.
- **Preflight.** Preflight asserts that the wrapper's tool list, tool descriptions and instructions are byte-identical to the stock server's.

### Labels (names and enums only, as in Q5.2)

Per run:
- **Project file.** Whether it wrote one (`valid` / `invalid` / `none`), and whether it called `plan=true` before its first verify.
- **Declarations.** Deliverables declared out of those required. For each declared deliverable:
  - whether its goal matches the reference goal;
  - whether its key bindings agree with the reference: keep codes as a set, decode scale and offset, vertical units, slope unit, and summary statistic and source.
- **Calls.** Every `verify_project` and `run_checks` call, with each deliverable's status and grade.
- **Oracle.** The verdict on every snapshot, and on the final outputs.

Derived:
- **False assurance.** An oracle-wrong deliverable whose status the agent saw as `verified` or `decision-grade`. It is counted per call (certified wrong at any call) and on the final outputs.
- **Save.**
  - A deliverable that is oracle-wrong in a snapshot.
  - That call reported it `failed` (amended before any run; see Amendments).
  - It is oracle-correct at the end.
- **False alarm.** An oracle-correct deliverable in a snapshot that the call reported `failed`.
- **Shipped wrong.** An oracle-wrong final deliverable, and whether the agent's last call flagged it.
- **Reference check.** A project file registered before the run, verified on the final outputs. It separates the checker's power from the agent's declarations.

### Calibration and preflight (before any model call)

- **Oracles.** Each oracle accepts a right deliverable and rejects each trap's wrong deliverable.
- **Reference project file.** `verify --plan` is complete, the right outputs are `verified`, and every trap output is `failed`.
- **Projects.** All 12 projects pass the registered OpenCode preflight and the wrapper-identity check, with no model call.

If any of these fails, nothing starts.

### Count

- 3 tasks × 4 runs = **12 invocations**.
- 1200 s per run, because a run has several deliverables.
- No retries. Each task runs once, then again, four times over.
- The agent interpreter is a new venv, `agent-with-p11`. It holds the wheel built from the commit that carries the driver, with `terraproof.evals` excluded and R1-pinned dependencies.

### Known risk, registered before the run

`rs.scale_applied_once` checks the declared decode; it does not read the STAC item. Only `propose_contract` reports a conflict with `earthsearch:boa_offset_applied`.

So if an agent applies −0.1 and also declares `decode_offset = -0.1`, `verify` certifies the wrong reflectance. This is the false-assurance route T2 is built to expose. It is left in on purpose, so that any fix follows observed agent behaviour.

### Amendments from calibration (2026-11-02, before any run)

The first calibration (no host, no model) changed four things. Each one is fixed here before any agent runs.

1. **A layout warning holds every correct raster at review.**
   - On a plain striped GeoTIFF, which is what agents write, `raster.cog_layout` warns. So a correct raster is `review-required`, never `verified`.
   - Calibration therefore counts a right output as passing when it is `verified`, or `review-required` with the layout warning as its only non-pass finding.
   - For the same reason, "the call did not verify it" would hold for every raster. **A save now needs the call to have reported the deliverable `failed`** (a required check failed), and a correct final output.
   - A wrong output held only at review is reported as wrong-unflagged, not as a save.
2. **The NIR reference needed `expect = "reflectance"`.** `verify --plan` reported it missing, and calibration refused to start until it was added.
3. **Slope uses central differences.**
   - The calibration slopes are built with `numpy.gradient`. The reference fails the latitude-ignored slope as "longitude spacing not scaled by latitude".
   - **Known limit, registered:** on a Horn-stencil slope at 69° N, `terrain.slope_consistent` only warns, whether the slope is right (30 % of cells match central differences) or latitude-ignored (7 %).
   - The oracle accepts either stencil. An agent's Horn slope that ignores latitude will show as wrong-unflagged.
4. **The driver can stop after calibration.** `--calibrate-only` runs the oracles and the reference declarations with no host.

Calibration then passed on all three tasks. Every right output passed the reference, and every trap was oracle-wrong and reference-`failed`.

### Preflight (2026-11-02): all 12 projects ready; no model called

- **Driver.** The driver, wrapper and tests are in commit `82d8aa3`. Their 10 offline tests pass. One of them starts both servers and finds the wrapper's tools and instructions identical to the stock server's.
- **Agent interpreter.** `C:\Users\mrsom\.venvs\agent-with-p11`, Python 3.12.10.
  - It holds the wheel built from a clean `git archive` of `82d8aa3`: `terraproof-0.12.0-py3-none-any.whl`, SHA-256 `4a8f3eb880d52c61e03814dbe2662bd5f0716cfb5bdb885dd8be9bef14e39aed`.
  - `terraproof.evals` is absent.
  - Its dependencies are exactly `agent-with-p9`'s (R1-pinned).
  - Its product fingerprint matches the checkout: `a2378a0e…f126`.
- **Preflight.** `--preflight-only` ran on all 12 projects, with no model call. Report: `.terracache/phase11-t2-agent-preflight.json`.
  - Calibration passed again.
  - Every project passed every registered OpenCode check: isolation, admission, tools served, and no Terraproof in the global config.
  - Every project also passed the four wrapper checks: identical tools and instructions, the wrapper outside the project, the snapshots outside the project, and no snapshot before the run.
- **What the agent sees.**
  - The installed `AGENTS.md` names only `run_checks` (`check` on the command line). Its footer shows the stock server command.
  - The project file and `verify_project` appear only in the MCP instructions and the tool's own description. This is the nudge T2 measures.

### Run attempt 1 (2026-11-02): the driver crashed after 1 of 12 invocations

**What happened.**
- The approved command started. Calibration and preflight passed again, and the first run (`t2-s2-pipeline`, run 0) ran.
- After that run, the driver crashed before scoring it. `write_reference` wrote into a `reference/` folder that it never created. No other run started.
- **One invocation was used.** The approval covered that one command, so any rerun needs a new approval.

**What the run did.** The host stream was held only in memory and was lost with the crash. The following comes from OpenCode's own log (tool names and file names only):
- The run used the full 1200 s, in 18 model steps of roughly 30 to 80 s each. It wrote no output, no project file and no script, and made no verification call.
- It inspected the inputs (`inspect_dataset` twice) and read the STAC item.
- It engaged with the offset question: it searched the installed package for `boa_offset` and `decode_offset`, and read `OFFSET_APPLIED` in `evidence/propose.py`.
- **It tried to write a project file.** It searched for `terraproof.project/1` and read `project.py`. It then read the source for goal names (`contract.profiles`), check ids and summary fields (`checks/__init__.py`, `summary_value.py`, `evidence/contract.py`) until the timeout.
- **Reading.** One run is not a measurement. It is consistent with a gap: the format, goals and binding names cannot be found from the tool, so an agent reverse-engineers the package.

**Driver fixed** (no model was called):
- The reference folder is created.
- Each run's raw host stream is kept in `trace.jsonl` beside the project, not in the report.
- The report is written after every run.
- A new offline test drives the whole loop with a fake agent: calibration, install, preflight, wrapping, a wrong output fixed after a flagged verify, snapshots, scoring and checkpoints. It shows 5 saves and 0 false assurance across 8 deliverables.

### Amendment before attempt 2 (2026-11-02, registered before any run)

The user chose to fix the gap attempt 1 pointed to before spending the 12 runs.

**Product change: the format is discoverable from the tool.**
- Before a project file exists, `verify --plan` (MCP `verify_project` with `plan=true`) returns the guide to writing one, instead of an error. It exits `3`.
- **The guide holds:**
  - every goal, with its checks and required bindings;
  - every binding's value type, choices and meaning, taken from the `check` command's own help with flags renamed to binding names;
  - a template.
- The template uses goals that are in no T2 task (`metric-values`, and `summary-value` on a vector count), so it teaches the format and not a task answer.
- The tool description and the server instructions each say this in one clause. A missing project file's error says the plan describes the format.
- The known risk stays as registered. The guide says nothing about STAC offsets.

**Trial changes.**
- 1800 s per run instead of 1200 s, because attempt 1's model steps took 30 to 80 s each.
- A new agent interpreter, `agent-with-p11b`. It holds the wheel built from the commit that carries this change, built and checked as before.
- A new, empty work root.
- The bars, tasks, brief, labels and reading (section 4) are unchanged.
- **Count:** attempt 2 is 12 new invocations, so 13 in all with attempt 1. Attempt 1's single run is left out of the reading, because it ran on the earlier product.

### Preflight for attempt 2 (2026-11-02): all 12 projects ready; no model called

- **Change.** The guide is in commit `53ec8c7`, together with this amendment.
  - Two new tests: the guide covers every goal and binding, and the MCP, CLI and library agree; the template plans as complete.
  - The full Python suite passes (2008 passed, 6 skipped), and so do repository validation and the router suite.
- **Agent interpreter.** `C:\Users\mrsom\.venvs\agent-with-p11b`, Python 3.12.10.
  - It holds the wheel built from a clean `git archive` of `53ec8c7`: `terraproof-0.12.0-py3-none-any.whl`, SHA-256 `da937318148ac821baa56648e34c0b944f8bad0a8325c9b96bfed77b34e1c17c`.
  - `terraproof.evals` is absent.
  - Its dependencies are exactly `agent-with-p11`'s.
  - In an empty folder, its `verify_project(plan=true)` returns the guide: 8 goals and 66 bindings.
- **Preflight.** `--preflight-only` ran on a new work root, with no model call. Report: `.terracache/phase11-t2-agent-preflight2-preflight.json`.
  - Calibration passed on all three tasks: the right outputs pass, every trap is oracle-wrong and reference-`failed`, and every reference plan is complete.
  - All 12 projects passed every OpenCode check and every wrapper check, at 1800 s per run.
  - Every project's product fingerprint matches the checkout: `cac0ff82…f991`.

### Attempt 2 result (2026-11-02 to 11-03): adoption met, no mistake to catch; inconclusive

The approved command ran all 12 invocations, from 23:29 to about 02:20, and exited `0`. Report: `.terracache/phase11-t2-agent-run2.json`, with each run's host stream in `trace.jsonl` beside its project.

| Measure | Result | Bar |
| --- | --- | --- |
| False assurance (any call, and final) | **0** and **0** | 0, required: met |
| Adoption: a valid project file and at least one `verify_project` call | **11 of 12** | ≥ 6: met |
| Saves | **0**, in 0 runs | ≥ 2 in ≥ 2 runs: not met |
| Wrong snapshots | **0** of 31 verification calls | fewer than 2 |

**Reading (section 4): "adoption met, fewer than 2 wrong snapshots": the tasks were too easy. Inconclusive. No push.**

What happened:
- **The guide was used.** All 12 runs called the plan before their first verify. 11 wrote a valid project file. None wrote an invalid one.
- **Declarations were faithful.**
  - 29 of 32 deliverables were declared, all except the timed-out run's 3. 28 of them used goals covering the reference's.
  - One S2 run named the mask's check directly instead of the `qa-masked` goal.
  - Every S2 declaration bound `decode_offset = 0`, and no run applied −0.1. So the registered STAC-offset risk was never exercised.
  - Some differences from the reference are form, not substance: summary keys, and `qa_kind` instead of keep codes. The outputs they declare are still correct.
- **No agent wrote a wrong output at any verification call.** Every one of the 31 snapshots was oracle-correct, and the 11 runs that finished shipped 29 of 29 deliverables correct.
  - The checks raised no false alarm.
  - The reference project file agreed with the oracle on all 32 deliverables.
- **The layout warning was acted on.** In 5 runs, a first verify held a correct raster at `review-required`. The agent rewrote it, and the next call showed it `verified`. Every final raster passes the reference with no layout warning.
- **The one failure, `t2-s2-pipeline` run 0, timed out with no output.**
  - It called the plan once, and received the guide.
  - It then read the package's source (`propose.py`, `rs_processing.py`, `cli.py`, `contract.py` and others), as attempt 1 did, until 1800 s ran out.
  - The guide answered the format, but this run still went to the source for how the checks treat the S2 offset and QA codes.
- **The 3 deliverables shipped wrong unchecked** are that run's missing outputs.

**What this does and does not show.**
- **It shows** that, given the guide, an agent writes and uses the project file without being told to (11 of 12; 0 of 1 before the guide). It also shows that the checks gave no false assurance and no false alarm on 32 deliverables.
- **It does not show** that the file catches agents' mistakes, because this model made none on these tasks. That is the value bar, and it stays unmeasured.

## 4. Reading, registered before the run

| Measure | Bar |
| --- | --- |
| False assurance (any call, and final) | **0**. Required. |
| Adoption: a valid project file and at least one `verify_project` call | ≥ 6 of 12 runs |
| Value: saves (flagged `failed`, correct at the end) | ≥ 2, in ≥ 2 different runs |

| Outcome | Next |
| --- | --- |
| 0 false assurance, adoption and value met | **Push the branch, open the PR, prepare 0.13.0.** Strong practical value shown. |
| Any false assurance | Fix its route first. No push. |
| Adoption not met | The bottleneck is instructions or install, not checks. Work there. No push. |
| Adoption met, fewer than 2 wrong snapshots | The tasks were too easy. Inconclusive. No push. |
| Adoption met, wrong snapshots not flagged (and not certified) | A coverage gap. Record which checks. No push. |

Everything else is reported, not thresholded: the faithfulness of declarations, false alarms, and wrong deliverables shipped anyway.

**Not a lift claim.** There is no "without" condition, contamination is screened rather than evaluator-blind, and the sources are spent sets.

## 5. Order

1. The driver [`tests/phase11_t2_agent.py`](../../tests/phase11_t2_agent.py) (with each task's reference declaration), the wrapper [`tests/phase11_snapshot_server.py`](../../tests/phase11_snapshot_server.py) and their offline tests are committed before any run.
2. Calibration and preflight run with no model.
3. The user approves the exact command and the count (12).
4. The run follows; its record is committed before any product change.
5. All of it is on `geova/post-0.12.0`, one branch and one PR, pushed only per section 4.

## 6. Decisions needed

1. **T2 design.** The host and model, the 3 tasks, and 12 invocations at 1200 s.
2. **The known risk.** Run as registered (recommended), or fix the STAC-offset cross-check first.
3. **The run.** Approval of the exact command after preflight.

## 7. T3. A harder trial: agents that make mistakes (designed 2026-11-03, not built, not run)

T2 adopted well (11 of 12) but measured no value: the model made no mistake for `verify` to catch. T3 picks tasks where this model has made mistakes before, and asks one question: **when an agent writes the project file and gets an output wrong, does `verify` catch it?**

### Tasks: where MiMo erred before

The tasks are seven headroom tasks, each with one deliverable (`result.tif`). Each has an independent oracle and seeded wrong outputs, all already in `terraproof.evals.headroom`. The inputs are small synthetic rasters (12 × 12). They are spent tasks, so this is not a lift claim.

| Task | MiMo before (no Terraproof) | Mistake seen or seeded | Reference declaration |
| --- | --- | --- | --- |
| `hr-flood-depth-feet` | E4: 2 of 2 wrong | feet compared with a metre level; depth in feet | `vertical-units`, `depth-below-level` |
| `hr-modis-lst-quality` | E4: 2 of 2 wrong | kelvin delivered; one QC field read | `qa-masked` (keep codes) + `rs.scale_applied_once` (kelvin to Celsius) |
| `hr-landcover-change-fill` | E4: 1 of 2 wrong | fill 0 compared as a class | `nodata-support` (fill 0, rule all) |
| `hr-reanalysis-air-temperature` | E4: 1 of 2 wrong | packed integers used as kelvin; kelvin delivered | `rs.scale_applied_once` (file scale and offset, kelvin to Celsius) |
| `hr-s2-scl-red` | E4: 1 of 2 wrong | only cloud classes removed; offset ignored | `qa-masked` (keep 4, 5, 6) + `scaled-reflectance` (offset −0.1) |
| `hr-slope-geographic` | E4: 1 of 2 wrong | degrees as metres; latitude ignored | `slope-from-dem` |
| `hr-elevation-change-mixed-units` | R3: 2 of 24 wrong, both certified | ft survey treated as m; change in feet | `vertical-units`, `difference` |

In E4, these six tasks drew 8 wrong outputs in 12 runs. With Terraproof installed, the rate is expected to be lower (Q5.2 0 of 10, T2 0 of 11). Lower is still worth seeing.

### Calibration probe (2026-11-03, no model)

Each reference declaration was written and verified on the right output and on every seeded wrong output:
- **All 7 tasks:** the right output is `verified`, and **every one of the 15 seeded wrong outputs is `failed`**.
- So when the declaration states the task correctly, the checks catch every registered mistake.

### The finding that shapes T3: a declaration can repeat the mistake

The probe then declared each wrong output **with the belief that produced it** (for example `vertical_source_units = ["metre"]` for a DEM read as metres). **`verify` certified 10 of these 11.** Only the clouds-only S2 mask still failed. A check confirms the output against the declaration; when both carry the same mistake, they agree.

The 11 fall into two kinds:
- **The declaration contradicts the input's own metadata** (5 of 11). The DEM's band unit is `ft` but `metre` is declared (flood feet-as-metres, mixed units ignored). The file's scale and offset are 0.0018 and 285 but 1 and 0 are declared (packed values). The item lists offset −0.1 but 0 is declared (S2 no offset). The item marks class 0 as no data but no fill is declared (land cover).
  - Terraproof can see these, from the same explicit metadata `propose_contract` already reads.
- **The declaration states a wrong goal that no input contradicts** (6 of 11). Kelvin is delivered where Celsius was asked, a depth or change is given in feet, or a QA rule keeps codes the task excludes.
  - No file says the task asked for Celsius, so no check can see it.
  - Catching these needs the goal stated by someone other than the agent, which T3 does not test.

### Labels added to T2's

For every wrong snapshot:
- **Faithful declaration:** its relevant bindings match the reference.
- **Belief declaration:** they encode the mistake. Record whether explicit input metadata contradicts it.

The reading separates three cases: a check gap (faithful declaration, not flagged), a cross-check gap (belief contradicted by metadata, not flagged), and the limit (belief with no metadata against it).

### Count, host, bars

- **Host and model:** as T2 (OpenCode 1.19.4, `opencode-go/mimo-v2.6-flash`), with the same neutral brief and install, the same snapshot wrapper, and 1800 s per run.
- **Count:** 7 tasks × 2 runs = **14 invocations**.
- **Bars,** unchanged in kind:

| Measure | Bar |
| --- | --- |
| False assurance on a **faithful** declaration | **0**. Required. |
| False assurance on a belief declaration that input metadata contradicts | Reported, and decides option A or B below |
| Adoption | ≥ 7 of 14 |
| Saves (flagged `failed`, correct at the end) | ≥ 2, in ≥ 2 runs |

### Decision before building: A or B

- **A. Run T3 on the product as it is.** It measures how often agents' declarations repeat their mistakes. The likely result is false assurance on belief declarations, after which a cross-check is built and T3 runs again.
- **B. First make `verify` cross-check declarations against explicit input metadata, then run T3.** When a declared binding contradicts the input itself, report a conflict that fails the deliverable.
  - **What it compares:** band unit labels, GDAL scale and offset, nodata, and, when the project file names a STAC item, its `raster:bands` and `classification:classes`.
  - **What it leaves alone:** no task-specific rule; only bindings explicit metadata states, as `propose_contract` already does.
  - **Why now:** it follows behaviour already observed: R3's two certified mixed-unit errors, and P4's offset certified decision-grade twice.
  - **Cost:** it closes about half the belief cases before any run, and leaves the other kind as the measured limit.

**Recommendation: B.** The false-assurance route is known from earlier trials, so a 14-run trial that only re-shows it buys little. With B, T3 can meet its bars or show a real check gap.

Either way, the order stays the same:
1. Build the driver.
2. Calibrate and preflight.
3. Ask for approval of the exact command and the count of 14.

### B built (2026-11-03): a declaration its own sources contradict fails

The user chose B. No model was called.
- **What it does.** `verify` and `--plan` (MCP `verify_project`) compare declared bindings with explicit metadata about their own sources: a DEM's vertical unit, the reference input's decode scale and offset, each vertical source's unit, and each support source's fill.
  - The metadata is read from the source file. It is also read from any local STAC Item beside the project file or a source, when an asset's `href` points at that source, through `raster:bands`, or a `classification:classes` entry marked `nodata`.
  - A contradiction is listed by the plan as a conflict. `verify` turns it into a `project.declaration` failure.
  - Metadata that disagrees with itself, such as Earth Search's `boa_offset_applied` beside offset −0.1, is not held against the declaration.
- **The belief probe again.** The cross-check now **fails all 5** belief declarations that input metadata contradicts: flood feet-as-metres, mixed units ignored, packed values, S2 no offset, and land-cover fill.
  - The 6 that no metadata contradicts are still certified, as designed. Kelvin or feet were delivered against a stated goal, or a QA rule was narrowed. Five of the six are certified and one (S2 clouds-only) still fails its mask check. These are the limit T3 measures.
- **Tests.** 3 new tests; the full Python suite passes (2011 passed, 6 skipped), and so do repository validation and the router suite.
- **No false alarm found.**
  - The 7 T3 reference declarations still verify the right outputs and fail all 15 seeded wrong ones.
  - T2's real-data calibration still passes.
  - Replaying the 11 project files T2's agents actually wrote (33 deliverables) gives no conflict.

### T3 driver and preflight (2026-11-03): all 14 projects ready; no model called

- **Driver.** [`tests/phase11_t3_agent.py`](../../tests/phase11_t3_agent.py), in commit `8aee446`.
  - It reuses T2's wrapper, adapter, preflight and labels. T2's snapshot reader now takes the oracle as a parameter.
  - The oracle is each task's own: `score_outputs`'s `oracle_ok`. The format contract is reported apart.
  - The reading is applied as registered above. A belief certification is reported, not thresholded.
- **What each wrong snapshot records:** what the call showed; whether a `project.declaration` conflict flagged it; and whether the project file's declaration at that moment was faithful.
  - **Faithful** means the checks cover the reference's, and every key binding the reference sets matches.
  - Paths are compared by file name and in order, because order is the operation. Units are compared by meaning: `ft` is `foot`.
- **Tests.** 4 offline tests:
  - declarations;
  - wrong-snapshot labels;
  - the reading's bars;
  - the whole loop, with a fake agent that writes a seeded wrong output, verifies, fixes it and verifies again. On the mixed-units task its first declaration repeats the mistake. It shows 7 saves (6 by checks, 1 by the cross-check) and no false assurance.
- **Calibration.** It passed on all 7 tasks. Every right output is `verified`, every seeded wrong output is oracle-wrong and `failed`, and every reference plan is complete with no conflict.
- **Agent interpreter.** `C:\Users\mrsom\.venvs\agent-with-p11c`, Python 3.12.10.
  - It holds the wheel built from a clean `git archive` of `8aee446`, which carries the cross-check: SHA-256 `151efbe4c27872c7875911dab55a68c074739a1561f79ed3bdd84af120e9c07c`.
  - `terraproof.evals` is absent, and its dependencies are exactly `agent-with-p11`'s.
- **Preflight.** `--preflight-only` ran on a new work root: 14 of 14 projects passed every OpenCode check and every wrapper check, at 1800 s per run. Report: `.terracache/phase11-t3-agent-preflight.json`.
  - The product fingerprint matches the checkout: `d411525f…7fd75`.
  - **Routed skills,** recorded as given: `hr-elevation-change-mixed-units` routes none, and `hr-modis-lst-quality` routes `geopandas` and `design-postgis-tables` among its four.

### T3 attempt 1 (2026-11-03): stopped by a machine restart after 8 of 14

- The approved command started at 02:50. Calibration and preflight passed again, and 8 runs finished and were scored, the last at 04:03.
- The machine froze and was restarted during the 9th run (`hr-modis-lst-quality`, run 1). That run left no result. The other 5 runs of the second pass never started.
- **Invocations used: 9 of the approved 14.** The report after the 8th run is kept unchanged: `.terracache/phase11-t3-agent-run1.json`.
- No result has been read against the bars. The 8 finished runs are carried over as they are.

### Resume (registered before it runs)

- **The resume option.** `--resume REPORT` carries over the runs a report finished, and runs only the missing ones, in the registered order. The approval must equal their number.
  - A carried run is never redone.
  - The final report holds all 14 runs, and lists which ones were carried over.
  - An offline test interrupts a fake run after 4 runs and resumes it: an approval of 7 is refused, 3 start, and the summary covers all 7.
- **The missing runs:** 6, all second-pass runs: `modis` (interrupted, so run again from the start), `landcover`, `reanalysis`, `s2-scl-red`, `slope` and `mixed-units`.
  - That makes **15 invocations in all**.
  - The same interpreter (`agent-with-p11c`) is used, with the same product fingerprint (`d411525f…`) and a new work root.
- **Preflight.** `--preflight-only --resume` created and passed exactly those 6 projects, with no model call.

### T3 result (2026-11-03): high adoption, one cross-check save, one belief certified; the value bar not met

The resume ran the 6 missing runs and exited `0`. That makes 15 invocations in all, and 14 scored runs. Report: `.terracache/phase11-t3-agent-run2.json`. Its first 8 runs are carried over from `-run1.json`.

| Measure | Result | Bar |
| --- | --- | --- |
| False assurance on a faithful declaration | **0** | 0, required: met |
| Adoption | **14 of 14**, all valid project files | ≥ 7: met |
| Saves | **1**, in 1 run | ≥ 2 in ≥ 2 runs: not met |
| Wrong snapshots | 8, in 3 runs | — |
| Wrong calls certified on a belief declaration | **1** | reported |

**Reading (section 7): "adoption met, wrong snapshots not flagged or not fixed: record the gap"; no push.** One belief certification is reported.

What happened:
- **13 of 14 final outputs are correct.** 13 runs completed. All 14 met the format contract. The reference agreed with the oracle on all 14. There was no false alarm.
- **The save came from the cross-check** (`hr-flood-depth-feet`, run 0).
  - Before writing the project file, the agent called `run_checks` three times on a feet-as-metres output, with no bindings. The grade was `checks-passed`, so nothing was flagged.
  - It then declared the DEM's source unit as metre. `verify_project` failed the output on `project.declaration`, because the band unit says `ft`.
  - The agent fixed both the output and the declaration and finished `verified`.
- **The belief certification: `hr-modis-lst-quality`, run 0.**
  - The agent declared `qa_keep_codes = [0, 64]` and masked the output to match. Code 64 is an LST error of 1–2 K, which the task excludes. The other kept codes were missing too.
  - Its first `verify_project` failed on `raster.nodata_support`. After a fix, the second call `verified` the output, with decision-grade evidence. The QA rule was the agent's own, consistently declared.
  - The run timed out with that output. No file states the task's QA threshold, so this is the registered limit, not a check gap.
  - The run is also labelled `outside-project`: it read a file outside its project.
- **The other wrong snapshots:**
  - **`hr-flood-depth-feet`, run 1:** two `run_checks` calls before any project file was written (`checks-passed`, then `incomplete`). The agent fixed the output unprompted.
  - **`hr-modis-lst-quality`, run 0:** the `nodata_support` failure above. It counts as flagged, not as a save, because the final output stayed wrong.
- **Declarations, final.** 7 of 14 are faithful by the registered comparison. The other 7, all correct at the end, fall into three groups:
  - **Equivalent in substance (4):** land cover declared `support_source_nodata = ["0", "0"]` as strings, and S2 used `qa_kind = "s2-scl"` in place of keep codes 4, 5 and 6.
  - **A narrower QA rule (2):** MODIS keep codes `[0, 64]` and `[0]`.
  - **Under-declared (1):** `hr-reanalysis-air-temperature`, run 1, declared only `nodata-support` and never declared the scale or the kelvin conversion, so its verification could not have caught a kelvin output.

**What T3 shows.**
- **Adoption is solid:** 14 of 14 valid project files, and every run verified.
- **On a faithful declaration nothing wrong was certified.** On these tasks, though, the declarations were faithful mainly when the outputs were already right.
- **The cross-check made the one save,** on a mistake the checks alone would have certified against the agent's own declaration.
- **The gaps it records:**
  - `run_checks` without bindings gives an ungrounded `checks-passed` before a project file exists.
  - A QA rule the agent chooses itself is certified when its declaration and output share it.
  - An agent can declare less than the task needs.
- **The value bar (≥ 2 saves) is not met,** so no push under the registered reading.
