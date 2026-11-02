# Terraproof Phase 11 plan: one declaration per pipeline, tested on agents

> Status: **T1 done (local commit `460af3c`); T2 designed, not run (2026-11-02).** It follows [Phase 10](Terraproof_Phase10_PLAN.md) and release 0.12.0.

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
  - That call did not verify it.
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

## 4. Reading, registered before the run

| Measure | Bar |
| --- | --- |
| False assurance (any call, and final) | **0**. Required. |
| Adoption: a valid project file and at least one `verify_project` call | ≥ 6 of 12 runs |
| Value: saves | ≥ 2, in ≥ 2 different runs |

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

1. The driver `tests/phase11_t2_agent.py`, the wrapper and their offline tests are committed before any run, and so is the reference project file for each task.
2. Calibration and preflight run with no model.
3. The user approves the exact command and the count (12).
4. The run follows; its record is committed before any product change.
5. All of it is on `geova/post-0.12.0`, one branch and one PR, pushed only per section 4.

## 6. Decisions needed

1. **T2 design.** The host and model, the 3 tasks, and 12 invocations at 1200 s.
2. **The known risk.** Run as registered (recommended), or fix the STAC-offset cross-check first.
3. **The run.** Approval of the exact command after preflight.
