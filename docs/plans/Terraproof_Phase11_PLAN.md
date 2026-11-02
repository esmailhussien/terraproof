# Terraproof Phase 11 plan: one declaration per pipeline, tested on agents

> Status: **T1 done; T2 attempt 2 ran (12 of 12): adoption 11/12, 0 false assurance, 0 saves because no agent made a mistake. Reading: inconclusive, no push (2026-11-03).** It follows [Phase 10](Terraproof_Phase10_PLAN.md) and release 0.12.0.

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
