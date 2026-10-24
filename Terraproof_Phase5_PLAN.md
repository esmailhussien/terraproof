# Terraproof — Phase 5 Plan: Agent-lift measurement

> Status: **harness implemented and verified offline; one approved 2-invocation pilot ran and produced no gradable output (section 13).** The harness and driver were then fixed offline, with no model or agent call. Lift is still **unmeasured**. Each further real run needs the user's explicit approval of the command, call count and cost ceiling in section 9.

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
| 1 | 9 | 0.37 | 0.45 | 0.58 |
| **3 (default)** | **27** | **0.23** | **0.28** | **0.37** |
| 5 | 45 | 0.18 | 0.22 | 0.29 |
| 10 | 90 | 0.13 | 0.16 | 0.21 |

  These are run-level numbers and are optimistic. At the task level, the exact sign-flip test with nine tasks reaches p < 0.05 only when at least 8 of 9 tasks improve (with similar magnitude) and none gets worse: for equal |d_t|, 8/9 gives p = 0.039 and 7/9 gives p = 0.18. **With nine tasks, only a large and consistent lift can be distinguished from chance.** A null result does not show that there is no lift. The report also prints the MDE at the observed discordance.
- **Incomplete pairs** (budget stop, install failure) are excluded from paired statistics and counted in `incomplete_pairs`.

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
3. **Main run, 54 invocations** (9 tasks × 3 runs × 2 conditions), only after the pilot passes the gate above:

   ```powershell
   $env:PYTHONPATH="src"; C:\Users\mrsom\.venvs\terraproof-py312\Scripts\python tests\agent_lift.py --agent-host codex --runs 3 --codex-executable C:\Users\mrsom\AppData\Local\OpenAI\Codex\bin\37f54d68e5533a51\codex.exe --timeout 900 --approve-model-calls 54
   ```

   Ceiling: 54 invocations, at most 13.5 hours of wall time. For Claude, add `--max-usd-per-run 1 --max-usd-total 54`, giving a **$54** ceiling. Without `--approve-model-calls`, the same command prints this plan and starts nothing.
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

1. **Approve pilot 2** (section 9, step 2): Codex app runtime 0.163.0-alpha.11.2 proposed, 2 invocations, ceiling as stated.
2. **Runs per condition for the main run:** 3 (proposed, 54 invocations) or 5 (90 invocations, MDE ≈ 0.22 at ψ = 0.3).
3. **Claude caps** if Claude is used: $1 per run / $54 total proposed, or higher after the pilot shows typical cost.

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
