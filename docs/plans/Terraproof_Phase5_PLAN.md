# Terraproof — Phase 5 Plan: Agent-lift measurement

> Status: **the approved 54-invocation main run on Claude Code is complete (section 16). The pre-specified primary test is not significant (sign-flip p = 0.125), and no lift claim is made.**
> - **Isolation:** the "without" condition was imperfectly isolated (section 16). The harness now enforces neutral paths and a Terraproof-free interpreter for any future run.
> - **Earlier pilots:** sections 13–15.
> - **Next run:** none is proposed. Any further real run needs the user's explicit approval.

## 1. Why this phase

Phases 1–4 showed that Terraproof's checks, preflight and provenance catch specific seeded errors in fixture artifacts. They did not show that an **agent** produces correct geospatial artifacts more often when Terraproof is installed. The Phase 4 harness says so itself: it "does not measure agent lift". Phase 5 turns the 27 executable benchmark tasks into that measurement. The same tasks, inputs and independent oracles grade an agent's deliverables with and without Terraproof.

## 2. Question and hypotheses

- **Question.** On realistic remote-sensing and raster tasks, does installing Terraproof (router-selected skills, agent instructions and the MCP server, via its own installer) raise the probability that an agent's final artifact is correct?
- **H0:** the per-task acceptance rate is the same with and without Terraproof. **H1 (two-sided):** it differs. Any direction is reported. A negative effect is a result, not a failure of the harness.
- **Estimand:** the mean over tasks of the per-task difference in acceptance rate, `mean_t (p_with,t − p_without,t)`. It is intention-to-treat: a "with" run counts whether or not the agent actually opened a skill or called a tool.

## 3. Design

### 3.1 Paired conditions

| Condition | Project contents | Host configuration |
|---|---|---|
| `without` | `TASK.md`, `inputs/*`, empty `outputs/` | same host, same flags, no MCP server, no Terraproof instructions or skills |
| `with` | the same files, plus `python -m terraproof.install --agent <host> --task "<spec prompt>" --with-mcp` | same flags; MCP server registered with all six read-only tools approved |

A **pair** is one task, one run index and both conditions. The two runs get byte-identical inputs and the same `TASK.md`. They run back to back, so time, quota and host-version drift affect both. Which condition goes first alternates by task and run index (`schedule()`), so order effects such as warm caches or rate limits are counterbalanced and deterministic. Each project is deleted after scoring, so a later run cannot read an earlier run's outputs or installed skills.

The treatment is the product as a user installs it: the deterministic router picks the skills from the task's own prompt (for example `satellite-preprocessing`, `spectral-indices`, `geospatial-data-discovery`, `geomaster` for the Sentinel-2 task). It is not "every skill" and not a hand-picked skill. The report records the routed skills per task.

### 3.2 The agent's view (blinding)

`TASK.md` contains exactly: the spec's `prompt`, the list of supplied input files, and a **deliverable contract** for each output: file name, grid, dtype and nodata, for example "red surface reflectance, single-band float32 GeoTIFF on the input grid (same CRS, transform and shape), nodata -9999". The contract makes a correct answer gradable without telling the agent how to get it.

The agent never sees the spec's `inputs`, `acceptance` or `pitfall` text, the oracle's control values, the reference solution, or any seeded-wrong output. A unit test asserts this for all nine tasks: none of those strings or file names appears in the brief, and no file in either project has the bytes of a reference or seeded-wrong output. No reference or seeded artifact exists on disk while an agent runs. Calibration trees are deleted before the first run, and scoring regenerates the recipe only after the agent has finished.

### 3.3 Scoring: the existing oracles, unmodified

Scoring does not re-implement any task. For each run, the task's existing Phase 4 recipe runs again in a private scoring directory. When the recipe would write a deliverable (for example `ndvi.tif`), the agent's file is copied there instead (`_substitute`). The recipe's unchanged checks and independent oracle then grade the agent's artifact exactly as they grade the reference solution. A run is **accepted** only if its correct-control verdict is `accepted`: every `expected_checks` status is reproduced **and** every oracle assertion passes. No task spec, oracle or seeded-wrong output is modified.

A missing, oversized or symlinked deliverable is `missing`. A deliverable that makes the recipe raise (for example an unreadable file) is `error`. Inputs that regenerate with different bytes, or a deliverable that never reached the recipe, make the run `invalid`. None of these counts as accepted.

### 3.4 Calibration gate (runs before every experiment)

For each task the harness proves that substitution scoring is trustworthy:

1. inputs regenerate byte-identically in two independent recipe runs;
2. the reference deliverables are **accepted**;
3. each seeded-wrong deliverable from the spec's `pitfall` is **rejected**;
4. an echoed input (the first input copied as the first deliverable) is **rejected**;
5. no deliverables are reported as **missing**.

If any task fails, `run_lift` refuses to start. `python -m terraproof.evals lift --calibrate-only` runs the gate alone.

### 3.5 Task selection

All 27 recipes were probed by substituting every generated file into every same-type file slot. A task is in the Phase 5 pool only if (a) its inputs exist as fixture files, (b) its oracle reads the delivered file, and (c) substituting each of its seeded-wrong outputs makes the correct control fail. Nine tasks qualify, and all nine pass calibration:

| Task | Inputs → deliverables | Seeded errors that must be rejected |
|---|---|---|
| `indices-ndvi-physical-inputs` | red/NIR DN → `ndvi.tif` | unscaled DN ratio |
| `raster-cog-delivery` | analysis raster → `delivery.tif` | lossy JPEG COG; striped, no overviews |
| `raster-nodata-dtype-windowing` | two uint16 rasters → `difference.tif` | unsigned wraparound |
| `sar-db-linear-monthly-mean` | three dB dates → mean dB + valid-date count | dB averaged directly |
| `satellite-landsat-qa-once` | Landsat DN + QA_PIXEL → `landsat_sr.tif` | double decode; clear-bit-only mask |
| `satellite-s2-baseline-offset-mask` | S2 DN + SCL → `sr_red.tif`, `sr_nir.tif` | offset skipped; SCL mask skipped |
| `satellite-seasonal-harmonized-composite` | three dates + Item → composite + counts | cloudy date included; invalid pixel zero-filled |
| `stac-loader-double-decode` | DN + Item → `sr_red.tif` | double decode; DN 0 decoded as valid |
| `ts-phenology-matched-difference` | NDVI dates + SCL + Items → `difference_2023_2024.tif` | April-vs-July difference; clouds not masked |

The other 18 tasks are excluded for a stated reason, not dropped silently:

- **The deliverable is prose, estimates, a design or a refusal** (8): the three `accuracy-*` tasks, `crs-crossing-scope-preflight`, `sar-grd-gcp-only-preflight`, `vector-repair-inventory`, `vector-coverage-and-duplicates` and `ts-post-classification-change-validation`.
- **The inputs are not fixture files** (4): `indices-water-definition-grid` and `ts-monthly-ndvi-composite-counts` write only outputs, `vector-join-scope-and-geojson` has no owners table, and `crs-axis-datum-control` supplies the target points themselves as its input.
- **The oracle does not reject a substituted seeded error** (3): `indices-burn-evi-savi-ranges`, `crs-local-metric-buffer` and `stac-signed-windowed-cog-subset`.
- **The correct deliverable is never written as a file** (2): `raster-categorical-half-pixel` and `sar-orbit-consistent-log-ratio`.
- **The deliverable is a run record graded through manifests** (1): `stac-pinned-search-manifest`. File substitution cannot grade it.

Adding an LLM judge for prose tasks is out of scope (section 11).

### 3.6 Runs per condition

The default is **3 runs per condition per task**: 9 tasks × 3 runs × 2 conditions = **54 agent invocations**. Agents are stochastic, so repeated runs estimate each task's acceptance rate rather than one sample. Section 6 explains why more runs do not substitute for more tasks.

## 4. Metrics

**Primary:** per-run binary acceptance of the final deliverables (section 3.3). It is summarised as each condition's pass rate and the mean task-level difference.

**Secondary**, all from the same report (`summary.secondary`, per condition):

- **checker-caught vs oracle-only failures:** among rejected runs, whether Terraproof's own checks flagged the artifact (`rejected_by_checks`) or only the independent oracle did (`rejected_by_oracle_only`). This shows whether Terraproof's checks could have warned the agent;
- `missing_or_error`: no gradable artifact;
- `tool_calls`, `terraproof_tool_calls`, `skill_reads`: treatment delivery. A "with" run with zero Terraproof calls and zero skill reads received the treatment but did not use it;
- `input_tokens`, `output_tokens`, `cost_usd`: cost (Codex reports tokens only; Claude reports USD);
- `contaminated`: runs with a contamination label (section 7).

Per-run records also keep the failed oracle-assertion **names** and mismatched check ids, which show *which* pitfall an agent fell into. They never keep values from the agent's stream.

## 5. Statistics

All statistics are deterministic and implemented in `terraproof.evals.lift`. The bootstrap uses a fixed seed and only `random.random()`.

- **Unit of analysis: the task.** Runs of the same task share fixtures and difficulty, so they are not independent. The primary analysis works on the nine task-level differences `d_t = (accepted_with,t − accepted_without,t) / pairs_t`.
- **Primary test:** exact two-sided **sign-flip randomization test** of `mean(d_t)`, enumerating all 2⁹ = 512 sign assignments (exact for ≤ 20 tasks). Pre-specified α = 0.05.
- **Effect and CI:** `mean(d_t)` with a 95% **task-cluster percentile bootstrap** CI (10,000 resamples, seed 20261024).
- **Secondary test:** **exact McNemar** on all run-level pairs (binomial test on discordant pairs). It treats runs as independent, so it is anti-conservative under task clustering. It is reported for comparison and is never the headline result.
- **Minimum detectable effect.** The McNemar approximation of Connor (1987), `N = (z_{α/2}√ψ + z_β√(ψ−δ²))² / δ²` (α = 0.05, power = 0.8, ψ = discordant-pair proportion), gives:

| Runs per condition | Pairs | MDE at ψ = 0.2 | ψ = 0.3 | ψ = 0.5 |
|---|---|---|---|---|
| 1 | 9 | none | none | none |
| **3 (default)** | **27** | **none** | **0.28** | **0.36** |
| 5 | 45 | 0.18 | 0.22 | 0.29 |
| 10 | 90 | 0.13 | 0.16 | 0.21 |

  "none" means no difference reaches 80% power at that ψ: a paired difference cannot exceed the discordance (|P10 − P01| ≤ ψ). An earlier version searched up to √ψ and printed infeasible values (0.37/0.45/0.58 at 9 pairs, 0.23 at 27 pairs and ψ = 0.2); this was corrected after an independent review (2026-10-24).
  These are run-level numbers and are optimistic. At the task level, the exact sign-flip test with nine tasks reaches p < 0.05 only when at least 8 of 9 tasks improve (with similar magnitude) and none gets worse: for equal |d_t|, 8/9 gives p = 0.039 and 7/9 gives p = 0.18. **With nine tasks, only a large and consistent lift can be distinguished from chance.** A null result does not show that there is no lift. The report also prints the MDE at the observed discordance.
- **Incomplete pairs** (budget stop, install failure) are excluded from paired statistics and counted in `incomplete_pairs`.
- **Ceiling tasks (descriptive, pre-specified after pilot 3).**
  - **What is reported:** each task's `baseline_pass_rate` (its "without" acceptance rate) and a `ceiling` flag when every "without" pair was accepted. The summary lists `ceiling_tasks` and counts `tasks_with_headroom`.
  - **Effect on the primary analysis:** none. It stays the mean over all nine tasks, with no post-hoc exclusion.
  - **How the report reads it:** the effect is stated alongside the number of tasks with headroom. If most tasks are at ceiling, a null result means "no headroom to show lift on these tasks", not "no lift".
  - **What is not done:** no spec, oracle or seeded output is changed to remove a ceiling. Harder artifact tasks are a later option through the normal Phase 4 review (section 11).

## 6. Threats to validity

| Threat | Mitigation / how it is reported |
|---|---|
| **Few tasks** (9 clusters): low power, task-specific effects dominate | Task is the analysis unit; exact sign-flip test; MDE table above; per-task differences published. Adding artifact-gradable tasks is the main lever (section 11) |
| **Contract leaks the answer** | Contracts state format only (names, grid, dtype, nodata). A unit test asserts the brief contains no pitfall, acceptance criterion or seeded file name. The same brief is used in both conditions, so any leak lowers the measured lift |
| **Contract over-constrains** (an otherwise correct answer with NaN nodata fails) | Nodata/dtype are stated in the contract; the remaining arbitrary choices are the recipe's, equal in both conditions |
| **Oracle sensitivity is limited** to what the recipe asserts on the file | The calibration gate proves rejection of every seeded error, an echoed input and a missing file; the residual risk (a wrong artifact that the recipe does not inspect) is listed in `limitations` |
| **Contamination**: the agent reads the recipes, oracles or specs, which ship inside the installed `terraproof` package, or a previous run's outputs | Agents run in a temp directory outside the checkout. Each run's project is deleted after scoring, and no reference artifact is on disk during a run. The real-host driver labels any tool call that touches `terraproof/evals`, `evals/tasks`, `recipes/*.py`, `oracles`, `inspect.getsource`, seeded file names, parent traversal or the recordings directory, and any use of `terraproof` in the `without` condition. Contaminated runs never count as accepted, and their count is reported. A sensitivity analysis drops pairs containing one |
| **Shared environment**: the `without` agent's Python can also import `terraproof` | Same interpreter in both conditions (equal capability). Use in `without` is flagged as `terraproof-in-without` |
| **Host flag or skill discovery silently disables the treatment** | Treatment delivery is reported (`terraproof_tool_calls`, `skill_reads`). The pilot (section 9) must show a nonzero count in "with" before the main run is approved |
| **Per-run USD cap truncates longer "with" runs** (skills add context) | Pilot measures typical cost first. A timeout or budget stop is a failed run in either condition and is visible in `adapter_status` |
| **Model/host drift during the run** | Pairs run back to back; host versions are recorded at the start; one host per report |
| **Prompt sensitivity** (one wording per task) | Spec prompts are used verbatim; generalisation beyond these prompts is not claimed |
| **Single host / single model** | Results apply to the measured host and its default model only; a second host is a separate report |
| **Same-agent authorship** of contracts and harness | Contracts are short and published in the report. Independent review of the contracts before the main run is recommended, but under the user's sole-agent process it is not claimed |

## 7. Isolation, timeouts and sanitised traces (real hosts)

`tests/agent_lift.py` reuses `tests/release_validation.py` for the native-executable resolution, the auth probes (Claude `auth status`, Codex ChatGPT-subscription status with no paid-API fallback), and the Windows kill-on-close job object with suspended start. Differences from the release smoke test, which are needed because agents must compute:

- **Codex:** `exec --ignore-user-config --ignore-rules --strict-config --ephemeral --sandbox workspace-write` with `sandbox_workspace_write.network_access=false` and web search disabled.
  - Codex's own execution features (`shell_tool`, `unified_exec`, `unified_exec_tty`, `shell_snapshot`, `workspace_dependencies`) stay at their defaults. Only capabilities outside the task are disabled: browser, computer use, apps, plugins, sub-agents, memories, hooks and image generation.
  - `mcp_servers` is set explicitly in both conditions: the Terraproof server in `with`, an empty table in `without`.
  - `--codex-executable` selects a specific native `codex.exe`, such as the app runtime.
- **Preflight (no model call), before every run:**
  - The harness checks that inputs are present, `outputs/` is writable, the routed skills are installed and the MCP server is registered, and that no Terraproof files exist in `without`.
  - The Codex adapter then checks, still without a model:
    - **Sandboxed shell:** `codex sandbox -P :workspace` runs PowerShell → `python`, which must find numpy/rasterio, read an input and create and delete a file in `outputs/`.
    - **MCP registration:** `codex mcp list --json` with the same `mcp_servers` override.
    - **MCP tools:** the six Terraproof tools, listed by starting the server with the official MCP client.
    - **Skill and instruction visibility:** `codex debug prompt-input` renders the model-visible prompt locally, and the check reads only skill names and the presence of the AGENTS.md block from it. In `without`, none of these may be visible.
  - Any failure marks the run `preflight_failed` and starts no agent. `--preflight-only` runs all of this for every task and condition without approval.
  - Limits:
    - `codex sandbox -P :workspace` approximates exec's `workspace-write` policy.
    - The model-visible **tool list** cannot be rendered without a turn, so whether the shell tool is exposed is confirmed only by the next pilot's trace.
    - Claude Code has no model-free sandbox runner, so its Python/IO probe runs unsandboxed.
- **Claude Code:** `--print --restricted --tools Bash,Read,Write,Edit,Glob,Grep,Skill --permission-mode dontAsk --permission-prompts none --strict-mcp-config` with an empty MCP config in `without` and the installer-written `.mcp.json` in `with`, plus `--no-session-persistence`, hooks disabled and `--max-budget-usd <per-run cap>`.
- **"without" isolation (added after the main run, enforced by preflight):**
  - **Neutral paths:** run projects live under `%TEMP%\paired-run-*\runs\NNN\project`, so no path names Terraproof, the task or the condition.
  - **Terraproof-free interpreter:** the "without" agent's interpreter is `--agent-python-without`, a dependency-only Python on a neutral path, and `PYTHONPATH` is dropped. The preflight fails "without" unless that interpreter is set, cannot import `terraproof`, and the project and interpreter paths do not contain "terraproof".
  - **"with" is unchanged:** it keeps the driver's interpreter, with Terraproof installed, as part of the treatment.
  - **Creating the neutral venv** (once, by the user):

    ```powershell
    py -3.12 -m venv C:\Users\mrsom\.venvs\geo-agent-py312
    C:\Users\mrsom\.venvs\geo-agent-py312\Scripts\python -m pip install numpy rasterio pyogrio shapely pyproj
    ```
- **Contamination labels** distinguish real use from incidental text:
  - **Real use**, which forces rejection and keeps the underlying verdict in `accepted_before_contamination`: `terraproof-in-without:import`, `:module-or-cli`, `:mcp`, `:package-query`, `:skill` and `:mention`.
  - **Incidental:** "terraproof" appearing only inside path text becomes the diagnostic `terraproof-path-text`, not contamination.
- One invocation per run, no retries, per-run timeout (default 900 s), and the owned process tree is killed on every exit.
- Only fixed labels and numbers leave the stream:
  - per tool call: a tool label from a fixed set, its category (`shell`, `file_edit`, `file_read`, `skill`, `mcp:<tool>`, `mcp:other`, `web`, `agent`, `other`), status (`started`/`completed`/`failed`/`declined`), exit code and duration;
  - per turn: a status (`completed`, `error`, `refused`, `sandbox-denial`, `aborted`, `timeout`), a fixed reason, error-type labels from fixed patterns, and the count of Codex `error` items, which are not counted as calls.

  No prompts, model text, command lines, arguments, environment or file contents are persisted.
- **Run classification:** a host run that completes with no deliverable and no `shell` or `file_edit` call is reported as `adapter_status: no-attempt`, with the raw `host_status` kept. Each "with" run records `treatment_used`, and the summary reports `no_attempt`, `preflight_failed`, `treatment_not_used`, `calls_by_category` and `treatment_delivery`. Outputs and `result.json` are recorded to `.terracache/agent-lift-recordings/` (git-ignored), so `python -m terraproof.evals lift --adapter replay --recordings DIR` re-scores the run offline and deterministically.

## 8. Budget

- **Hard run cap:** the driver refuses to start unless `--approve-model-calls N` equals the planned invocation count exactly. `run_lift` refuses any model-calling adapter without `allow_model_calls=True` and an approved run count.
- **Claude:** a per-run cap (`--max-budget-usd`, default $1) and a total cap (default $54). Before each pair, the harness reserves two full per-run caps and stops if they would exceed the total. A run that reports no cost (timeout) is charged the full per-run cap. The host enforces its cap after a turn, so one run can overshoot by part of a turn; the harness total absorbs this.
- **Codex:** ChatGPT-subscription usage exposes no USD cap. The approved invocation count and the per-run timeout are the hard limits; tokens are reported.
- **Offline:** the scripted and replay adapters cost nothing; CI and the unit tests use only those.

## 9. Execution steps (each real step needs explicit user approval)

1. **Offline acceptance (done in this PR):** calibration 9/9 eligible; scripted reference-vs-seeded run gives pass rates 1.0 vs 0.0 with byte-identical reports across runs; unit tests for blinding, budget, contamination, replay and statistics.
2. **Pilot, 2 invocations** (one task, one pair), to check treatment delivery, cost per run and timeouts. Pilot 1 ran (section 13).
   - Use the Python 3.12 venv. The 3.14 interpreter behind `D:\AgentLayer\.venv` has a Low integrity label, its temp directory falls back to the checkout, and the driver correctly refuses that.
   - Use the app-bundled Codex runtime, the one that passed Phase 4 acceptance.
   - First run the free preflight. It must report no `preflight_failures`:

   ```powershell
   $env:PYTHONPATH="src"; C:\Users\mrsom\.venvs\terraproof-py312\Scripts\python tests\agent_lift.py --agent-host codex --runs 1 --task indices-ndvi-physical-inputs --codex-executable C:\Users\mrsom\AppData\Local\OpenAI\Codex\bin\37f54d68e5533a51\codex.exe --preflight-only --out .terracache\agent-lift-pilot2.json
   ```

   Then, only with approval, run pilot 2:

   ```powershell
   $env:PYTHONPATH="src"; C:\Users\mrsom\.venvs\terraproof-py312\Scripts\python tests\agent_lift.py --agent-host codex --runs 1 --task indices-ndvi-physical-inputs --codex-executable C:\Users\mrsom\AppData\Local\OpenAI\Codex\bin\37f54d68e5533a51\codex.exe --timeout 900 --approve-model-calls 2 --out .terracache\agent-lift-pilot2.json
   ```

   - **Expected calls:** 2 Codex `exec` invocations.
   - **Cost ceiling:** Codex subscription usage has no USD cap, so the limit is 2 invocations × 900 s.
   - **Claude alternative:** `--agent-host claude --runs 1 --task indices-ndvi-physical-inputs --max-usd-per-run 1 --max-usd-total 2 --approve-model-calls 2`, with a **$2** ceiling.
   - **Main run gate:** the pilot must show `shell` calls in `calls_by_category` for both conditions, at least one "with" run with `treatment_used: true`, and no `no-attempt`.

   **After pilot 2 (section 14), Codex is not used for lift runs on this machine.**
   - Every model in Codex 0.163's catalog is `code_mode_only`, and no non-inference command can show that a shell is reachable.
   - The Codex preflight therefore fails by construction (`codex_direct_tool_model_available: false`) and starts nothing.
   - **Pilot 3 uses Claude Code.** It needs `claude auth login` first; otherwise the driver reports `unavailable` and makes no call. The no-model preflight passes in both conditions.

   ```powershell
   $env:PYTHONPATH="src"; C:\Users\mrsom\.venvs\terraproof-py312\Scripts\python tests\agent_lift.py --agent-host claude --runs 1 --task indices-ndvi-physical-inputs --max-usd-per-run 2 --max-usd-total 4 --timeout 900 --approve-model-calls 2 --out .terracache\agent-lift-pilot3.json
   ```

   - **Ceiling:** 2 invocations, **$4 total** ($2 per run via `--max-budget-usd`; the harness reserves both caps before starting the pair).
   - **Why $2:** the per-run cap is $2 rather than the planned $1, so that a cap stop (labelled `error_max_budget_usd`) does not hide the result. The pilot's measured cost then sets the main-run caps.
3. **Main run, 54 invocations** (9 tasks × 3 runs × 2 conditions), on Claude Code after pilot 3 passed the gate (section 15):

   ```powershell
   $env:PYTHONPATH="src"; C:\Users\mrsom\.venvs\terraproof-py312\Scripts\python tests\agent_lift.py --agent-host claude --runs 3 --claude-executable C:\Users\mrsom\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe --max-usd-per-run 1 --max-usd-total 54 --timeout 900 --approve-model-calls 54 --out .terracache\agent-lift-main.json
   ```

   - **Ceiling:** 54 invocations, **$54** (the harness reserves $2 per pair and stops before a pair that could exceed the total), and at most 13.5 hours of wall time.
   - **No approval, no run:** without `--approve-model-calls`, the same command prints this plan and starts nothing. `--preflight-only` runs the free checks first.
4. Report: publish the JSON report and per-task differences. State the result with its CI, p-values and MDE. Do not round a null or negative result into "lift".

## 10. Exit criteria

- Calibration 9/9 eligible on the run's own fixtures (recorded in the report).
- All planned pairs completed or explicitly reported as incomplete, with spend inside the approved ceiling.
- Primary analysis reported exactly as pre-specified in section 5: effect, CI, exact sign-flip p, the McNemar secondary, the MDE, treatment-delivery counts and contamination counts.
- Existing suites stay green: full Python suite, `python -m terraproof.evals run` (27/27, 0 false passes), `npm run test:router` (100%, deterministic), `python tests/validate_repo.py`.

## 11. Out of scope / later

- Prose and design tasks (accuracy reports, refusals, response designs) need a rubric or LLM judge with its own validity study.
- More artifact-gradable tasks, to raise the task count and power. New tasks need new specs and recipes and go through the normal Phase 4 review; existing specs are not edited to make them eligible.
- An "all skills" arm and a "skills without MCP" arm, to separate which part of Terraproof causes any lift.
- A second host or model, reported separately.

## 12. Decisions needed

No decision is open. The main run is complete (section 16), and no further run is proposed unless the user asks. The record below is kept for reference.

1. **Main run on Claude Code: approved and run on 2026-10-24.**
   - **Size:** 54 invocations (9 tasks × 3 runs × 2 conditions).
   - **Caps:** `--max-usd-per-run 1 --max-usd-total 54`, giving a $54 ceiling. About $14 was expected from pilot 3's cost, and $8.71 was actually spent.
   - **Command** (section 9, step 3):

   ```powershell
   $env:PYTHONPATH="src"; C:\Users\mrsom\.venvs\terraproof-py312\Scripts\python tests\agent_lift.py --agent-host claude --runs 3 --claude-executable C:\Users\mrsom\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe --max-usd-per-run 1 --max-usd-total 54 --timeout 900 --approve-model-calls 54 --out .terracache\agent-lift-main.json
   ```
2. **Runs per condition:** 3 (proposed, 54 invocations) or 5 (90 invocations, MDE ≈ 0.22 at ψ = 0.3, about $23 expected, with a cap of `--max-usd-total 90`).
3. **Ceiling risk accepted?** If Claude solves most tasks without Terraproof, the run will report headroom-limited results (section 5) rather than a lift estimate. Harder tasks would be a separate, reviewed addition, not a change to these specs.

Codex pilots are not proposed while every Codex catalog model is `code_mode_only` (section 14).

## 13. Pilot 1 findings (2026-10-24)

**What ran.** An approved 2-invocation Codex pilot at commit `880da93`:

- `python tests/agent_lift.py --agent-host codex --runs 1 --task indices-ndvi-physical-inputs --timeout 900 --approve-model-calls 2 --out .terracache/agent-lift-pilot.json`
- Python 3.12.10 venv `C:\Users\mrsom\.venvs\terraproof-py312` with an editable `.[dev,mcp]` install. A first attempt with the 3.14 venv was refused before any call with "work directory inside the checkout", which was correct.
- codex-cli 0.160.1 from PATH, logged in with ChatGPT.
- 00:24:46Z to 00:28:24Z (3 min 38 s for both runs). Status complete, `started_agent_runs` 2, `spent_usd` 0.0.

**Results.**

| | without | with |
|---|---|---|
| adapter_status | completed | completed |
| tool_calls (as counted at `880da93`) | 0 | 2 |
| terraproof_tool_calls / skill_reads | 0 / 0 | 0 / 0 |
| input / output tokens | 37,972 / 241 | 74,375 / 429 |
| `ndvi.tif` present / verdict | false / missing | false / missing |
| diagnostics | [] | [] |

Calibration was eligible: the reference was accepted, and the seeded `ndvi_dn_ratio.tif`, the echoed input and the missing file were all rejected. The recordings' `outputs/` was empty, and `result.json` held counts only, so the run could not be diagnosed from them. That gap is fixed above.

**Offline diagnosis.** No model or agent call was made. The tools used were `codex features list`, `codex sandbox`, `codex mcp list`, `codex debug prompt-input`, the Codex exec-event schema and Codex source.

1. **Neither agent executed a single command.** In `without`, 0 calls and 241 output tokens in one sampling round show that the agent never even read `TASK.md`.

   In `with`, the input tokens are about twice those of `without`, which fits two sampling rounds. The 2 counted "tool calls" are of unknown type: the `880da93` counter counted every non-message `item.completed`. That includes Codex `error` items, which are warnings, not calls (`ThreadItemDetails::Error` in `codex-rs/exec/src/exec_events.rs`). None of them was a Terraproof MCP call or a shell command.

2. **Most likely cause: the lift command overrode Codex's execution tools.** The release smoke test's disable list was reused minus `shell_tool`, so `unified_exec`, `unified_exec_tty`, `shell_snapshot` and `workspace_dependencies` stayed disabled.

   In Codex source, `add_shell_tools` (`codex-rs/core/src/tools/spec_plan.rs`, `main`) exposes either the unified exec tool or a one-shot fallback. It exposes no shell tool at all when the tool policy requires unified exec and `unified_exec` is disabled. Behaviour in 0.160.1 may differ from `main`.

   With no shell tool, an agent cannot read `TASK.md` or write a GeoTIFF, which matches both runs. This cannot be confirmed offline: `codex debug prompt-input` renders messages but not the tool list, and it was identical under both feature sets.

   **Fix:** lift runs now keep all five execution features at Codex defaults (a regression test enforces this).

3. **The prompt and treatment did reach the agent.** `codex debug prompt-input` in prepared projects shows the following.
   - **Prompt:** the user message "Read TASK.md in the current directory and complete the task it describes." The working directory is the project, and the shell is PowerShell.
   - **with:** the three routed skills (`spectral-indices`, `geomaster`, `statistical-analysis`) and the Terraproof AGENTS.md block are both visible.
   - **without:** neither is visible.
   - **MCP:** `codex mcp list --json` parses the `with` override, and the official MCP client lists all six tools.
4. **The Windows sandbox is not the blocker.** Under `codex sandbox -P :workspace` on 0.160.1 and 0.163.0-alpha.11.2, PowerShell runs the venv's `python`, which imports numpy/rasterio, reads `inputs/red_dn.tif` and creates `outputs/` files. Note that `%TEMP%` is writable as a whole (`:tmpdir`), so isolation between runs rests on deleting each run's project, as designed.
5. **Host version.** Pilot 1 used codex-cli 0.160.1, which had startup failures in Phase 4. Phase 4 native acceptance passed on the app runtime 0.163.0-alpha.11.2. Pilot 2 pins that runtime with `--codex-executable` and records the version in the report.
6. **Classification.** Under the new rules, both pilot 1 runs would be `no-attempt` rather than `completed`, and the "with" run would be `treatment_used: false`. Unit tests replay this pilot 1 shape.

Pilot 1 is a harness failure, not evidence about lift. Its two runs are excluded from any analysis.

## 14. Pilot 2 findings (2026-10-24)

**What ran.** An approved 2-invocation Codex pilot at commit `1172aff`:

- `tests/agent_lift.py --agent-host codex --runs 1 --task indices-ndvi-physical-inputs --codex-executable C:\Users\mrsom\AppData\Local\OpenAI\Codex\bin\37f54d68e5533a51\codex.exe --timeout 900 --approve-model-calls 2 --out .terracache\agent-lift-pilot2.json`
- Python 3.12.10 venv, `PYTHONPATH=src`, host `codex-cli 0.163.0-alpha.11.2`.
- `--preflight-only` just before reported `preflight_failures: []`.
- 00:53:00Z to 00:55:37Z (2 min 37 s for both runs). `started_agent_runs` 2, `spent_usd` 0.0.

**Results.**

| | without | with |
|---|---|---|
| adapter_status / verdict | no-attempt / missing | no-attempt / missing |
| calls_by_category | `{"mcp:other": 2}` | `{"mcp:other": 2}` |
| each call | `{"tool": "mcp", "category": "mcp:other", "status": "completed", "duration_ms": 0, "exit_code": null}` | same |
| terraproof_tool_calls / skill_reads | 0 / 0 | 0 / 0, treatment_not_used 1 |
| turn | completed / ok, error_items 0 | completed / ok |
| input / output tokens | 40,373 / 314 | 74,197 / 388 |

Gate: shell calls in 0 of 2 conditions, `treatment_used` 0, `no_attempt` 2. **Failed.**

**Offline diagnosis.** No model or agent call was made. Sources: Codex source at tag `rust-v0.163.0-alpha.11.2`, `codex debug models`, `codex debug prompt-input`, `codex mcp list` and `claude mcp list`.

1. **The two "mcp" items are Codex built-ins, not MCP servers.** `list_mcp_resources`, `list_mcp_resource_templates` and `read_mcp_resource` emit `McpToolCallBegin`/`End` with server `"codex"` when no server is named (`core/src/tools/handlers/mcp_resource/*.rs`). `exec` reports them as `mcp_tool_call` items.

   In "without" the server table is empty, so no real MCP call was possible. Two 0 ms "completed" calls in each condition fit an agent that, lacking a file or shell tool, looked for `TASK.md` as an MCP resource.

   **Fix:** they are now labelled `codex.<tool>` with category `mcp:codex-resource`, never counted as Terraproof or as an attempt. A third-party server reusing a Terraproof tool name is `mcp:other`.

2. **Every model in the catalog is code-mode-only.** `codex debug models` (a catalog render, no inference) lists `tool_mode: "code_mode_only"` for every listed model, including the default `gpt-6.1-sol`, and `shell_type: "unified_exec"`.

   `requested_tool_mode` takes the catalog's `tool_mode` over any feature flag (`core/src/tools/mod.rs`). In code-mode-only, the model sees only the JavaScript `exec`/`wait` entry points, and every other tool is a nested call. The `exec` wrapper itself is not emitted in exec JSONL (`event_processor_with_jsonl_output.rs` maps unknown items to `None`), so the trace sees only nested calls.

3. **Why no shell call: the shell tool is environment-dependent and not observable before a turn.** `add_shell_tools` (`core/src/tools/spec_plan.rs`) adds `exec_command` only if all of these hold:
   - the turn has a **Ready** execution environment, or `stable_environment_tools` is on;
   - `shell_tool` is on;
   - the model's `shell_type` is not disabled;
   - no policy requires unified exec while it is off.

   The argv now satisfies the static conditions: `shell_tool`/`unified_exec` stay at their defaults, no allow-list restricts tools (`enabled_tools` applies only to the Terraproof MCP server), and there is no `model_provider` override. `approval_policy="never"` and `workspace-write` do not remove tools, and `--ignore-user-config`/`--strict-config` only drop the user's config layer.

   Whether the environment was Ready inside `exec` at tool-planning time, and which nested tools code mode offered, cannot be rendered without a model turn. `codex debug prompt-input` builds the session and tool router but prints only the message input, which showed a Ready PowerShell environment. No Codex command prints the tool list.

   **The Phase 4 native acceptance is consistent with this:** it ran only MCP tools by design (`shell_tool` disabled) on the same runtime, and those calls work through code mode.

4. **Conclusion: on this machine Codex `exec` cannot be relied on to expose a shell tool, and that cannot be checked offline.** Two approved pilots (0.160.1 and 0.163.0-alpha.11.2) produced no shell or file call in either condition.

   Rather than proposing more Codex pilots, the Codex preflight now reads the catalog and fails (`codex_direct_tool_model_available: false`) while every listed model is `code_mode_only`. Codex lift runs therefore start nothing by construction.

5. **The Claude Code path was hardened offline.**
   - **MCP config:** Claude Code leaves an installer-written project `.mcp.json` server "Pending approval" (`claude mcp list`, no inference). "with" now passes an explicit `--mcp-config` copy of exactly that entry from outside the project, and "without" passes an empty one.
   - **Python probe bug:** the Claude preflight found that `subprocess.run(["python", …])` on Windows resolves `python` from the driver's PATH rather than the agent's, which picked an interpreter without rasterio. The probe now resolves `python` on the agent's PATH and passes in both conditions: Python, rasterio, input read and output write, plus all six MCP tools served in "with".
   - **Remaining limits:** Claude Code has no model-free sandbox runner or skill renderer, so skill visibility under `--restricted` is confirmed only by pilot 3's trace (`skill_reads`, `Skill` calls).

Pilot 2 is a harness/host failure, not evidence about lift, and is excluded from any analysis.

## 15. Pilot 3 findings (2026-10-24)

**What ran.** An approved 2-invocation Claude Code pilot, run from the parent session at commit `1e51940`:

- `tests/agent_lift.py --agent-host claude --runs 1 --task indices-ndvi-physical-inputs --max-usd-per-run 2 --max-usd-total 4 --timeout 900 --approve-model-calls 2 --out .terracache\agent-lift-pilot3.json`
- Python 3.12.10 venv, `PYTHONPATH=src`.
- Host Claude Code 2.1.292, the native `claude.exe` (`C:\Users\mrsom\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe`) put first on PATH.
- `claude auth status`: `loggedIn` true, `authMethod` `claude.ai`.
- `--preflight-only` reported `preflight_failures: []`.
- 01:23:08Z to 01:24:48Z (1 min 40 s for both runs). `started_agent_runs` 2, `spent_usd` 0.519151, budget $2 per run and $4 total.

**Results.**

| | without | with |
|---|---|---|
| verdict / adapter_status | accepted / completed | accepted / completed |
| `ndvi.tif` · checks_ok · oracle_ok · grade | present · true · true · decision-grade | present · true · true · decision-grade |
| tool calls | 4 × Bash (shell), ≈ 4.75 s | 9: 5 × Bash, 2 × `terraproof.inspect_dataset`, 2 × `terraproof.run_checks`, all completed, ≈ 5.0 s |
| terraproof_tool_calls / skill_reads | 0 / 0 | 4 / 1 (treatment_not_used 0) |
| cost_usd | 0.173413 | 0.345738 |
| output / input tokens | 2,924 / 10 | 4,324 / 16 |
| turn | completed / ok | completed / ok, no errors |

Summary: pass rate 1.0 with and 1.0 without; McNemar both 1, exact p = 1.0; mean task difference 0.0.

Gate: shell calls in both conditions ✔, at least one "with" run with `treatment_used` ✔, no `no-attempt` ✔. **Passed.**

**What this shows.** This is the first run in which the harness and treatment delivery work end to end:

- the agent read the brief, computed with Python and wrote the deliverable;
- the unmodified oracle and checks graded it;
- in "with", the Terraproof skill and MCP tools were actually used.

It is one pair on one task, so it is a harness check, not evidence about lift.

**Ceiling-effect risk.** Both conditions passed this task, so its lift is 0 by construction. If Claude solves most of the nine tasks without Terraproof, the main run cannot show positive lift, whatever Terraproof's true value.

The report therefore now gives each task's `baseline_pass_rate` and a `ceiling` flag, plus `ceiling_tasks` and `tasks_with_headroom` (section 5). The primary analysis is unchanged, and no spec, oracle or seeded output is altered. Harder artifact tasks are a later option through the normal review only.

**Projected main-run cost.**
- **Per pair:** about $0.52 on this task. "with" cost about 2× "without" ($0.35 vs $0.17), with more tool calls and skill/MCP context.
- **Main run:** 27 pairs (9 tasks × 3 runs) gives roughly **$14 expected**, well under the $54 cap. Other tasks may cost more or less.
- **Per-run cap:** $1 leaves about 3× headroom over the observed "with" run. A run that hits it is labelled `error_max_budget_usd`, and the harness charges the full cap when no cost is reported.
- **What the dollars mean:** with `authMethod` `claude.ai`, `cost_usd` is Claude Code's reported figure, not necessarily a separate charge.

**Known reporting limitation.** `input_tokens` of 10–16 almost certainly excludes cached input: Claude Code's `usage` reports cache reads and creation separately, and the driver keeps only `input_tokens`. Treat input-token counts as non-cached input only. Cost and output tokens are the usable cost signals.

**Operational note.** On Windows, npm puts the `claude.cmd` wrapper first on PATH, and the driver refuses it because it cannot guarantee bounded process cleanup. Pass the native binary with the new `--claude-executable` option (same style as `--codex-executable`; non-`.exe` paths are refused on Windows), or put its directory first on PATH. The main-run command above passes it explicitly.

## 16. Main run results (2026-10-24)

**What ran.** The approved main run on Claude Code, at commit `4c23f5b`:

- `tests/agent_lift.py --agent-host claude --runs 3 --claude-executable C:\Users\mrsom\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe --max-usd-per-run 1 --max-usd-total 54 --timeout 900 --approve-model-calls 54 --out .terracache\agent-lift-main.json`
- Venv `C:\Users\mrsom\.venvs\terraproof-py312`, `PYTHONPATH=src`. Host Claude Code 2.1.292, `authMethod` claude.ai.
- `--preflight-only` just before reported `preflight_failures: []`.
- 01:37:43Z to 02:16:32Z (38 min 49 s). `started_agent_runs` 54, status complete.
- **Spend:** `spent_usd` 8.71437 ("with" 5.411912, "without" 3.302458, about $0.32 per pair), against a $54 cap. With claude.ai auth this is Claude Code's reported figure, not necessarily a separate charge.
- **Completeness:** calibration 9/9 eligible. 27 complete pairs, 0 incomplete. `no_attempt` 0, `missing_or_error` 0, `treatment_not_used` 0.

The report is kept outside the repository: `D:\AgentLayer\.claude\worktrees\phase5-main-run\.terracache\agent-lift-main.json`.

### Pre-specified analysis (exactly as reported)

| Quantity | Value |
|---|---|
| pass rate with / without | **1.0 (27/27) / 0.777778 (21/27)** |
| mean task-level difference | **0.222222**, 95% CI [0.037037, 0.444444] (task-cluster bootstrap, 10,000 resamples, seed 20261024) |
| **primary test: exact sign-flip p** | **0.125, not significant at α = 0.05** |
| McNemar (secondary, anti-conservative) | both 21, with-only 6, without-only 0, neither 0; exact p = 0.03125 |
| observed discordance / MDE at it | 0.222 / none (corrected: the 0.243 first reported exceeds ψ and is infeasible; no difference reaches 80% power at 27 pairs and ψ = 0.222) |
| "with" Terraproof use | 92 Terraproof MCP calls (`run_checks` 46, `inspect_dataset` 29, `find_guidance` 11, `load_section` 6), 92 shell calls, **0 skill reads** |

| Task | with | without | note |
|---|---|---|---|
| indices-ndvi-physical-inputs | 3/3 | 3/3 | ceiling |
| raster-cog-delivery | 3/3 | 3/3 | ceiling |
| raster-nodata-dtype-windowing | 3/3 | 3/3 | ceiling |
| satellite-seasonal-harmonized-composite | 3/3 | 3/3 | ceiling |
| stac-loader-double-decode | 3/3 | 3/3 | ceiling |
| satellite-landsat-qa-once | 3/3 | 0/3 | all three "without" runs rejected by the oracle |
| sar-db-linear-monthly-mean | 3/3 | 2/3 | the "without" rejection is contamination-forced only |
| satellite-s2-baseline-offset-mask | 3/3 | 2/3 | the "without" rejection is contamination-forced only |
| ts-phenology-matched-difference | 3/3 | 2/3 | the "without" rejection is contamination-forced only |

**The primary test is not significant, and no lift claim is made.**
- **Ceiling:** five of nine tasks are at ceiling (`ceiling_tasks`), so only four tasks have headroom (`tasks_with_headroom` 4).
- **Why the CI and McNemar don't override this:** the bootstrap CI excludes 0 and McNemar is below 0.05, but neither is the pre-specified test. McNemar treats runs within a task as independent, and the CI rests on a 9-task bootstrap.

### Sensitivity analysis (NOT pre-specified)

All six "without" rejections carry `contamination: ["terraproof-in-without"]`, and `run_lift` forces a contaminated run to rejected. They split into two groups:

- **Rejected only because of the flag:** three runs had `checks_ok` and `oracle_ok` true (sar r1, s2 r1, ts r1).
- **Rejected by the oracle anyway:** the three landsat runs failed "cloud pixel (8,8) is nodata", "shadow pixel (16,16) is nodata" and the `rs.cloud_mask_applied` assertion.

If those three flags are false positives, scoring them by their checks and oracle gives:

| Quantity | Sensitivity value |
|---|---|
| pass rate with / without | 1.0 / 0.888889 (24/27) |
| mean task-level difference | 0.111111 (only landsat differs) |
| exact sign-flip p | 1.0 (one nonzero task) |
| McNemar | with-only 3, without-only 0; exact p = 0.25 |

The harness now computes this automatically as `summary.sensitivity_contamination_ignored`, labelled "not pre-specified". Recomputing the stored report reproduces both the primary numbers and these figures exactly.

**Either way there is no statistically supported lift.** The robust, task-specific observation is Landsat QA: 3/3 with Terraproof versus 0/3 without, where the "without" outputs left QA_PIXEL cloud and shadow pixels valid. In all three, Terraproof's own `rs.cloud_mask_applied` check also failed. It is outside that task's `expected_checks`, so it appears under `unexpected_failures` and not in `rejected_by_checks`, but it is exactly the error the "with" agents could check for. It is one task with three pairs, and it is reported as exploratory.

### Why `terraproof-in-without` fired

This was investigated offline from code and the sanitised report; no host was re-run.

- **The rule at `4c23f5b`:** `contamination_labels` added the flag whenever a "without" tool call's input text matched `terraproof` case-insensitively.
- **The trigger:** in the stored trace, every flagged "without" run, and only those, used Claude Code's `Read` tool. That is 6 of 6 flagged runs versus 0 of 21 unflagged runs (one flagged landsat run also used `Write`).
- **Why `Read` fires:** `Read` and `Write` take an absolute `file_path`, and every run project then lived under `%TEMP%\terraproof-lift-host-*\runs\<task>\run-k\without\project\`. So any `Read` call matches `terraproof` by construction. A synthetic replay of that call shape reproduces the flag under the old rule and yields only the diagnostic `terraproof-path-text` under the new one.
- **What cannot be ruled out:** the sanitised recordings keep labels, not text. It is therefore **undeterminable** whether any of these runs, or any other "without" run, also used Terraproof for real (`import terraproof`, `python -m terraproof`, `pip list`). The "without" agent's Python was the same Terraproof venv, so Terraproof was genuinely importable there.

The "without" condition of this run was therefore not guaranteed to be Terraproof-free, in two ways:

- the package was importable, and its name appeared in the venv path;
- the run paths named the task and the condition (for example `satellite-landsat-qa-once`, `without`), which is a blinding leak common to both conditions.

### Isolation fixes for any future run

These are in this PR, offline-tested, and were not used in the main run:

- **Opaque run directories:** `runs/NNN/project`, under a neutral `%TEMP%\paired-run-*` work directory, with a neutral `host.mcp.json` name.
- **Terraproof-free "without" interpreter:** set with `--agent-python-without`, with `PYTHONPATH` dropped in "without".
- **Preflight checks for "without":** `without_agent_python_set`, `without_terraproof_not_importable` and `without_paths_neutral`.
- **Real use separated from path text:** contamination sub-labels as in section 7.
- **Underlying verdict kept:** forced rejections record `accepted_before_contamination` and `contamination_forced_rejection`, so a sensitivity analysis never depends on inference.
- **Replay tests:** they reproduce this run's shape and its primary and sensitivity numbers, and the `Read`-path false positive.

### Other observations

- **Skills unused:** "with" used Terraproof through MCP only. `skill_reads` was 0 across all 27 "with" runs, so skill delivery under `--restricted` remains unverified.
- **Cost:** "with" cost about 1.6× "without" overall.
- **Token counts:** `input_tokens` remains non-cached input only (section 15).

## 17. Independent review and re-grading (2026-10-24)

An independent review by Codex (a different model family; it disclosed earlier contributions to Phase 4) reported eight findings, all reproduced and fixed. Two concerned this harness: the `raster-nodata-dtype-windowing` oracle graded reference-side arrays instead of the delivered file, and `score_outputs` did not enforce the deliverable contract's grid. A third was the MDE search bound (section 5 table and section 16 corrected).

- **Re-grading:** all 72 saved main-run deliverables were scored again with the fixed grader, offline. **0 verdicts changed.** The pre-specified result in section 16 stands (sign-flip p = 0.125, not significant; no lift claimed); only the MDE line changes, to none feasible at 27 pairs and ψ = 0.222.
- **Two more gaps, fixed in a follow-up:** a generic probe (zeros, +1 and row-flipped outputs per deliverable) found `sr_nir.tif` in `satellite-s2-baseline-offset-mask` ungraded and a row-flipped `composite_counts.tif` in `satellite-seasonal-harmonized-composite` accepted. Both oracles now grade the full delivered file, and the probe is a regression test over every deliverable of all nine tasks. Every saved historical output for both files matches the reference pixel for pixel; re-grading the 72 deliverables again changed 0 verdicts.

## 18. API agent hosts: OpenAI and Groq (2026-10-25)

Claude Code solved all six harder tasks with and without Terraproof in a one-repeat screen (12 runs, $1.74). This small screen has no observed headroom; it does not establish that lift is impossible for that host on other tasks or repetitions. Weaker models may leave room. OpenAI (e.g. GPT-4o) and Groq expose plain chat APIs rather than agents, so `tests/api_agent.py` supplies the agent loop:

- **Tools:** `list_files`, `read_file`, `write_file` (confined to the run project: no absolute paths or `..`) and `run_python` (one script per call, the condition's interpreter, the project directory, a 120 s timeout with process-tree cleanup). In "with" only, Terraproof's six MCP tools come from the installer-registered server, as for the other hosts; `load_section` calls and reads of installed skill files count as skill reads.
- **Instruction delivery (v0.7.1):** both API conditions receive the same general instruction to verify saved outputs against task/source values, masks, grid and metadata before finishing, and to report unresolved requirements. In "with" only, the adapter also forwards the configured MCP server's negotiated instructions as a labelled system message, before the unchanged task prompt. The server describes guidance retrieval, final `run_checks`, source-aware NDVI options and check limitations. It does not automatically load installed skill files, root `CLAUDE.md` or other local instruction files. Claude installation creates skill files and `.mcp.json`, not a root `CLAUDE.md`. Preflight checks tools and nonempty, valid UTF-8 instructions (at most 20,000 characters) on one connection; execution rechecks before a provider request. Missing/invalid instructions fail without inference. The whole message is included in token/USD reservations. `turn.mcp_instructions_delivered`, `mcp_instructions_chars` and `mcp_instructions_sha256` record host submission to the transport, not model attention, successful provider receipt, actual checking or accepted outputs. Tool-use evidence remains in the call trace. A final answer with no observed output failure can still complete without checks; the independent deliverable grader decides acceptance. The bounded completion review described below prevents completion after unresolved observed output failures. This changes the treatment and common host prompt for future experiments only, not saved pilot results. OpenAI's [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) documents system messages as instruction context, separately from tool definitions.
- **Not a sandbox:** `run_python` executes model-written code on the local machine with the user's permissions. Run it on a machine where that is acceptable.
- **Keys:** only from `OPENAI_API_KEY` / `GROQ_API_KEY`, read when a request is sent; never stored, logged or reported. Errors are reported as status labels (`http 401`), never response bodies. A missing key refuses the run before any request.
- **Local admission limits per run:** model calls (`--max-model-calls-per-run`, default 40), reserved/reported tokens (`--max-tokens-per-run`, default 300,000), at most 4,096 output tokens per request and USD (`--max-usd-per-run`). Before sending, reserve the complete conversation and tool schemas using their UTF-8 size plus framing allowance, then shrink requested output to the remaining token/USD allowance. This is conservative accounting, not a provider tokenizer or a provider-side invoice cap. Post-response usage is validated before completion or tool execution; an over-limit or malformed-usage reply fails. Missing usage and failed attempts retain their admitted reservation (including retries); reports separate reported usage from reserved unknown usage. Prices are explicitly supplied (`--usd-per-million-input/-output`), not guessed. Provider overhead, prices and returned usage can differ, so no absolute invoiced-dollar guarantee is made. The harness reserves complete pairs within the configured total budget and retains the explicit invocation-approval gate.
- **API errors and rate limits:** HTTP 429 is retried at most 3 times per run by default (`--rate-limit-retries`), waiting for `Retry-After` when given, else 2, 4, 8 s; each wait is capped at 60 s by default (`--max-retry-wait`) and never runs past the per-run timeout. Every attempt counts against the model-call cap. Errors are reported as the status plus a short code from the error body, such as `http 400 (tool_use_failed)` or `http 429 (rate_limit_exceeded)`. The code must match `[a-z0-9_.-]{1,40}`; message text is never kept. HTTP 400 `tool_use_failed` (the provider could not parse the model's tool call) is retried at most 2 times per run, without waiting, and also counts against the model-call cap. Other errors are not retried.
- **Isolation:** the same preflight and "without" rules apply: a dependency-only Python via `--agent-python-without`, no Terraproof importable, neutral paths. Calls made through the tools are checked with the same contamination labels.
- **Offline tests:** `tests/python/test_api_agent.py` drives the loop with a scripted fake model and blocks real HTTP. That test suite makes no API requests. Separately, saved local OpenAI/Groq pilots did make requests; these were exploratory host smoke tests, not a confirmatory lift study.

```bash
python tests/agent_lift.py --agent-host openai --runs 1 --task terrain-slope-map --usd-per-million-input <price> --usd-per-million-output <price>   # plan only
```


### Current exploratory results and next measurement

The saved Claude harder screen (`harder-screen.json`) has six complete pairs,
6/6 accepted in both conditions, no contamination flags and zero skill reads.
The GPT-4o terrain pilot (`api-pilot-openai.json`) rejected both outputs. Groq/Qwen
terrain pilots also include missing outputs and host/API errors; these cannot be
interpreted as geospatial computation errors or positive lift. Pilot outcomes
motivated the slope check and must not be reused as independent confirmation of
that change. The new local budget fixes and NDVI source-contract tests use no
live model; no new inference experiment is implied by this maintenance work.

Before a further live study, freeze its model, tasks, treatment, errors/exclusions,
primary analysis and budget, verify treatment actually reaches and is used by the
agent, and keep exploratory screening separate from held-out confirmation. Do not
pool the original and harder cohorts or select a host merely because observed
outcomes look favourable. Additional real calls require a separately specified
budget and explicit user approval.


### Bounded completion review (v0.7.1)

The separate exploratory instruction-delivery follow-up completed two GPT-4o
sessions on fresh data. Treatment received the MCP instructions and used the NDVI
source contract on both saved outputs; both returned `fail`, and both delivered
rasters remained unacceptable because of four mask errors each. This motivates a
host completion guard, not a change to those frozen results or the grader.

When `run_checks` returns a failed requirement for a task's explicitly declared
`outputs/<deliverable>` paths, the API adapter remembers that requirement. A final
answer while requirements remain unresolved receives at most two fixed review
messages asking the model to repair and recheck. Every additional request passes
the existing call, token, USD and timeout checks; there is no new session, budget
reset, automatic checker invocation or host-written data repair. Exhausted review
attempts end with adapter status `failed` and reason `output verification unresolved`.
Earlier cap, timeout, transport and refusal outcomes retain their original reasons.

Only a subsequent explicit `pass` for the same check, output and option/source
context resolves an observed failure. Multi-input checks retain their referenced
path group. Context options must be identical (except paths and report language);
changing source options, omitting the failed check, warning, not-run, tool errors,
malformed reports and unrelated passes cannot establish that it passed. Errors or
invalid reports on submitted deliverables also require a valid same-context report.
Clearly scoped failures on original/source files are excluded; unscoped failures
in a report containing deliverables conservatively apply to those deliverables.

Any `write_file` or `run_python` attempt invalidates earlier resolutions, including
failed operations that could have partially written. This is intentionally
conservative: even a read-only Python script requires another explicit recheck
after an earlier failure was resolved. It is not a file snapshot and does not
detect out-of-band edits by other processes. The guard does not require checks
that were never attempted, certify warnings, validate every task requirement or
replace the independent grader. `turn.output_review` is `no-failure-observed`,
`unresolved` or `resolved`, with requirement/unresolved counts and the number of
review prompts. No filenames, check prose or source arguments enter saved reports.

The guard changes future treatment behaviour and must be frozen as such in any
later study. No additional live experiment is implied or authorized by these
offline changes. Historical pilot code, tasks, outputs and negative verdicts stay
unchanged. Tool definitions and subsequent tool-result messages follow the
[official Chat Completions message contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).


### Exploratory and controlled API observations — 2026-10-25

These operator-recorded trials were frozen before inference and kept separate
from the original/harder study and from one another. Requested alias: GPT-4o;
all actual responses reported `gpt-4o-2024-08-06`. They establish no general lift
or causal before/after improvement. Each paired trial used one shared synthetic
scene; products and cells are not independent repeats.

| Exploratory pair | Full acceptance without / with | Relevant observed behaviour |
| --- | --- | --- |
| Published v0.7.0 host, first NDVI audit | fail / fail | Treatment used inspections, no source checks; both final rasters had mask errors. |
| Forwarded MCP instructions, fresh scene | fail / fail | Treatment used source checks on saved outputs; both failed and remained unrepaired. |
| Completion guard, another fresh scene | fail / pass | Treatment audited originals, then delivered correct values/masks/verdicts. It did not check final outputs; zero review prompts, so the recovery branch was not exercised. |

A separately approved, directed engineering test then seeded a four-cell mask
error in a single declared output and explicitly requested an initial check and
status before repair. This is not a blind task or a lift measurement. In one
GPT-4o session the real checker failed, the host issued two review prompts, and
two model-written Python attempts and real rechecks did not fix the mask. All
three output checks failed. The host correctly stopped with adapter `failed`,
reason `output verification unresolved`, rather than successful completion.
The independent grader still rejected the output (zero value errors, four mask
errors). This demonstrates the bounded-blocker branch live, not successful
automatic repair. Scripted offline regressions separately cover successful
repair followed by an explicit passing recheck.

The directed session used 10 provider requests, approximately $0.110100 in
cache-aware recorded-usage cost ($0.182580 conservative uncached accounting),
within its approved $1 local ceiling. No replacement session, HTTP retry, hidden
repair or post-result artifact alteration occurred. The older negative results,
frozen source/input hashes and output hashes remain preserved. Private host
reports and conversations are not committed; this paragraph is the sanitized
release summary. Usage estimates are not provider invoices or billing guarantees.


### Required output policy (v0.7.2)

Future API experiments can opt into an explicit required-output contract with
`--verification-plan`; see [the policy guide](../OUTPUT_VERIFICATION.md) and its
NDVI example. Every selected task's declared deliverables must be covered. The
with-condition host requires matching current MCP evidence before completion,
using `verified`, `review-required` and `unverified` states. Source files remain
bound to their initial content; whole-tree hashes include output masks and
invalidate evidence after data changes. The without condition receives no policy
and remains unverified. This is an explicit treatment change, not a replacement
for independent grading or a retrospective change to the trials above.

The offline implementation was followed by a separately frozen, directed
engineering acceptance trial on 2026-10-25: one GPT-4o session, five requests,
real source-check fail -> model repair -> current pass, host `verified` completion,
and zero value/mask errors under an independent oracle. All source inputs stayed
unchanged. Three separate scripted local controls covered absent, stale and
current evidence; the live session needed zero review prompts and did not
exercise those blocked-completion branches. Recorded usage was approximately
USD 0.058643 cache-aware (USD 0.084723 uncached) under the approved USD 1 ceiling.
This single directed synthetic-scene result establishes neither general repair
reliability nor lift. Historical negative outcomes remain unchanged.
