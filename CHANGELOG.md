# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Phase 6 readiness (Amendment 3) and contract templates

- Tested contract templates for four workflows (vector area, categorical raster grid,
  NDVI from named bands, median stack) and an ordinary CI example; see
  `docs/CONTRACT_TEMPLATES.md`.
- MCP admission's production fingerprint reads CRLF as LF in text files, so one
  commit admits on Windows and Unix checkouts alike.
- Lift harness: an agent with its own interpreter no longer inherits an activated
  driver venv on `PATH` or in `VIRTUAL_ENV`. `tests/runtime_readiness.py` records
  the candidate runtime (R1) and what each condition's interpreter can read (R2).

### E2 runtime correction and verification contracts

- Explicit isolated MCP interpreter registration and real-host admission against
  the candidate product code/assets; reject harness/evaluator exposure before
  starting the registered server. This is package separation, not host filesystem containment.
- Remove stale private evaluator modules/assets from reused wheel build directories,
  with bounded-output/source-directory guards. Developer tests include the build backend.
- Optional per-output verification contracts in Python, CLI and MCP, with required
  check coverage, source/parameter binding, separate effective grade and structured
  next-step diagnostics. Legacy reports without contracts remain unchanged.
- Unsigned local evidence bundles bind reports/contracts to recorded file hashes
  and known companions, with an optional externally trusted report digest.
- Record the 96-run E2 development result, contamination and the distinction between
  accepted artifacts and unresolved completion review. Future API reports include
  fixed unresolved check/context labels without loosening completion rules.

### Added (Phase 6 C: source-aware checks)

- `rs.index_formula` now also verifies NBR, dNBR (pre-fire minus post-fire), McFeeters NDWI,
  MNDWI, Gao's NDMI, SAVI and EVI, besides NDVI. Source bands are named by role (CLI
  `--band ROLE=PATH`, `--band-number ROLE=N` for a multi-band source; Python and MCP `bands`
  and `band_numbers`), and each band's own scale/offset is applied. NDVI keeps its `--nir`
  and `--red` arguments, messages and evidence.
- New opt-in `rs.stack_reduction` (CLI `--stack`, `--stack-reduction`, `--stack-weight`,
  `--stack-min-count`; Python and MCP `stack`, `stack_reduction`, `stack_weights`,
  `stack_min_count`). It compares every output cell with a declared reduction of an ordered
  input stack: `median`, `count`, `weighted-sum` (rate x hours), `mean-power-db` or `ols-slope`
  against declared times. Cells without enough valid inputs must be nodata.
- Source-aware scorecard (`tests/checker_scorecard.py`, section `source_aware`). It regenerates
  the frozen task fixtures and runs these checks with the inputs a user would have. It is
  reported apart from the frozen benchmark, which is unchanged (33/33, 0 false passes,
  25 rejections, 25 blind spots).
  - **14 of the 25 frozen blind spots are rejected:** the 6 index seeds and 8 time and stack
    seeds.
  - **12 correct outputs pass** and there are **0 false passes**.
  - Three recipes now also write the source layers that a user would have (water and burn
    bands, per-date NDVI). Their frozen invocations, oracles and seeds are unchanged.

### Added (Phase 6 E1: headroom cohort)

- **Phase 6 E1: headroom-screened task cohort.** 36 offline candidate tasks in nine trap
  families (QA/SCL masking, scale/offset and baselines, nodata stored as zero, dtype overflow,
  categorical resampling, metric work in a geographic CRS, vertical units, dB vs linear,
  temporal scope). Prompts state the goal, not the method, and each trap is discoverable from
  the inputs' metadata. Each task has an array recipe, a separate scalar oracle that reads
  every delivered cell and mask, and at least one seeded wrong output per trap (64 in all);
  all 36 pass the calibration gate. A seeded split (seed 20261027, stratified by family),
  fixed before authoring, gives the `headroom-development` (12) and `headroom-confirmation`
  (24) lift cohorts. Specs live in `evals/headroom/`, so the frozen benchmark is unchanged
  (33/33, 0 false passes, 25 blind spots). No model was called.

### Fixed (before E2)

- `terraproof install --task ... --with-mcp` no longer fails when the router ranks no skill for
  the task; it installs the checks and the MCP server with no skills and says so. Without
  `--with-mcp` it still stops, now suggesting `--with-mcp`. Three of the twelve Phase 6
  development tasks are worded like this ("How much did the ground surface change between
  the 2015 and 2023 surveys?"), so a real user asking that way got an error instead of the
  checks. The lift preflight still requires the MCP server in "with" and records the routed
  skill count.
- The lift driver's Python/IO preflight probe reads the task's first raster input, not
  whichever input comes first (some tasks list a STAC catalog first).

### Release record

- v0.8.0 shipped on 2026-10-27: tag `v0.8.0` on `9dabd84` (merge `a4ddda6`), PyPI through
  `publish-python.yml` after review, npm `terraproof@0.8.0` (shasum `27910c5e…`, identical to
  the tag), and GitHub release *Terraproof v0.8.0* with the npm tarball, wheel and sdist.

## [0.8.0] — 2026-10-27

### Phase 6 (in progress; see the [Phase 6 plan](docs/plans/Terraproof_Phase6_PLAN.md))

- **Product-only Python distributions.** The wheel and sdist leave out `terraproof.evals`
  (recipes, oracles, fixtures, the lift harness) and the task specs. The benchmark and lift
  harness run from a checkout, and an installed product can no longer import the oracles.
  `tests/package/python_smoke.py` now fails a wheel that contains them.
- **Clean-install CI.** A new job builds the wheel and installs it with the `mcp` extra into
  a fresh venv outside the checkout on Ubuntu, Windows and macOS (Python 3.11 and 3.13),
  then runs `inspect`, runs `check` on a generated raster, lists the six MCP tools through the
  official client and confirms `terraproof.evals` is absent
  (`tests/package/clean_install_smoke.py`).
- **PyPI publish workflow.** `.github/workflows/publish-python.yml` publishes a `v*` tag to
  TestPyPI and then PyPI with Trusted Publishing, verifying a clean install from each index.
  The one-time setup is done (pending trusted publishers on PyPI and TestPyPI, and GitHub
  environments `testpypi` and `pypi` with a required reviewer); the `v0.8.0` tag is its first run.
- **Lift driver `--agent-python-with`.** The "with" agent can get its own interpreter: a venv
  holding only the product wheel. Its preflight fails unless that interpreter is set, can
  import Terraproof and cannot import `terraproof.evals`. This closes the Antigravity
  finding that "with" agents read the oracles.
- **Docs.** Phase 5 is closed, with sections 18–19 as a frozen exploratory log and a post-hoc
  note on the ceiling arithmetic. The README shows the PyPI install for 0.8.0 onwards and
  labels skills as unmeasured; skill content is frozen during Phase 6.

### Added

- Lift driver host `--agent-host opencode` for the OpenCode CLI (checked against opencode-ai
  1.19.4), the one new host Phase 6 Amendment 1 allows. It runs `opencode run --format json
  --pure --auto --model <provider/model> --dir <project>` with the condition in the workspace
  (`AGENTS.md` and `opencode.json` from `--agent opencode`). Skills from `.claude`/`.agents`,
  Claude Code prompt files, external plugins and self-update are disabled. Preflight fails a
  run if OpenCode's global config, rules, skills, agents, commands or plugins, or any config
  above the run project, mention Terraproof. `opencode models` (no inference) confirms the model
  is configured. The trace keeps fixed labels from `tool_use` and `step_finish` events, with MCP
  tools named `terraproof_<tool>`. No USD cap; the approved run count and timeout are the limits.
  Tested offline with fake streams; no OpenCode model call was made.
- Phase 6 Amendment 1: E is measured on open and lower-cost models (OpenCode with an open model,
  Antigravity with Gemini, or GPT-4o), with one primary host and model fixed at E3. Claude Code
  is not used for E.
- Opt-in `--processing-full-scan` (Python and MCP `processing_full_scan=True`) for the
  calibration and cloud/QA relations: every corresponding band and pixel is checked in
  bounded windows instead of the sampled band-1 screen, which stays the default. A separate
  offline scorecard (`tests/checker_scorecard.py`) shows it rejecting single-pixel and
  other-band errors the sampled screen misses, without changing the frozen benchmark
  invocations or counts. See `docs/PROCESSING_FULL_SCAN.md`. Taken from PR #31 without its
  runtime-isolation and Docker harness parts, which the Phase 6 harness freeze leaves out.
- Installer format `--agent antigravity`: workspace skills in `.agents/skills/<skill>/`, an
  `AGENTS.md` block, and with `--with-mcp` a `mcpServers` entry in `.agents/mcp_config.json`
  (the workspace locations in Antigravity's skills, rules and MCP docs). Unit-tested only.
- Lift driver host `--agent-host antigravity` for the Antigravity CLI (`agy`, checked against
  1.3.0 and 1.4.7): headless `--print` with `stream-json` output, an explicit `--antigravity-model`
  (confirmed by the no-inference `agy models` listing, which also confirms cached sign-in)
  and optional `--antigravity-effort`. Each run's workspace carries its own condition: the
  "with" project gets the installer's skills, `AGENTS.md` and workspace MCP config, the
  "without" project none. Preflight refuses runs when Terraproof is visible to every
  workspace through agy's global MCP config, global skills, global rules or plugins, and the
  trace flags Terraproof tools offered in "without" and a host workspace other than the run
  project. Like Codex, agy reports no spend, so the approved run count and timeout are the
  only hard limits. Tests use fake streams in the documented shape; no agy model call was made.
  The no-model preflight on a real install (agy 1.4.7) passed every check in both conditions.

### Fixed

- Antigravity host: agy routes every MCP call through one built-in tool, `call_mcp_tool`, with
  `ServerName`, `ToolName` and `Arguments` in its arguments. The trace now labels those steps
  from `ServerName`/`ToolName` (`terraproof.<tool>` for Terraproof's tools, `mcp:other`
  otherwise; parameters or args, object or JSON string, also when they arrive on a later
  update). A Terraproof call in "without" is contamination. `init` lists only the generic
  tool, so `terraproof-tools-not-listed` now fires only when neither it nor Terraproof is
  listed. Found in the first approved pilot (2026-10-26, agy 1.4.7, `gemini-3.8-flash-high`,
  `terrain-slope-map`, one pair). Both conditions were accepted, but the report counted 0
  Terraproof calls where the "with" run made 7 (6 `run_checks`, 1 `inspect_dataset`), and it
  raised the diagnostic falsely. The verdicts did not depend on these labels.

- Lift driver isolation, from the Antigravity harder-cohort run: every host preflight left
  `preflight_probe.py` beside the run project, with an output probe named
  `.terraproof-preflight`. Two "without" agents read it, then searched the machine and the
  web for Terraproof. A shared `unsandboxed_probe` now removes the script before any agent
  starts (the Codex sandbox probe too), and both probe names are neutral.
- `python-introspection` contamination now requires the introspection to reach harness or
  oracle code (`evals`, oracles, recipes, specs or fixtures in the same call). Reading
  Terraproof's own product modules with `inspect.getsource`, which seven "with" runs did, is
  no longer contamination. Reading `terraproof.evals` stays contamination through
  `harness-source`/`oracle-source` too. This applies to future runs only; recorded reports
  keep their labels and their prespecified results.

### Results

- Antigravity harder-cohort measurement (2026-10-26, agy 1.4.7, `gemini-3.8-flash-high`,
  6 tasks x 3 runs, 36 runs in 2 h 52 min, about 7.4 M input and 0.8 M output tokens, no
  errors). All 36 deliverables passed the oracle, the checks and the contract.
  - Prespecified (contamination rule as frozen): with 7/18, without 16/18. Primary task-level
    sign-flip p = 0.125 (not significant); secondary, anti-conservative McNemar p = 0.012.
  - Post-hoc, labelled as such: product-only introspection not counted, giving 14/18 vs 16/18
    (primary sign-flip p = 0.75; McNemar p = 0.63).
  - Actual verdicts: 18/18 in both conditions. The cohort is at ceiling for this model, so
    there is no lift evidence either way; see Phase 5 plan section 19.

### Known limits

- agy's built-in tool names are matched by keyword; MCP calls are labelled from
  `call_mcp_tool` arguments as seen in agy 1.4.7. The `init` payload's exact shape is still
  unconfirmed beyond its tool listing. agy runs with
  `--dangerously-skip-permissions` and without `--sandbox`, so commands are not sandboxed (as
  for Claude Code), and agy may keep conversation history under `~/.gemini`; conditions
  alternate order to counterbalance this. agy updates itself (1.3.0 became 1.4.7 during this
  work); every report records the version the probe saw.

## [0.7.3] — 2026-10-25

### Added

- Opt-in `terrain.slope_formula`: explicit `--slope-method central-difference`
  with `--dem` verifies every calibrated slope value, complete four-neighbour
  support and nodata edges, including flat cells, using bounded window halos.
- Opt-in `raster.source_identity`: `--raster-identity --compare-to SOURCE`
  compares every band's valid samples and full validity masks plus exact grid
  and band metadata. CLI, Python, MCP and provenance use the same source context.
- Bundled slope and COG plans now require these stronger checks. Offline
  regressions reject the missing slope cell and altered COG pixel that their
  original screens could pass. English [contract](docs/RASTER_CONTRACTS.md) and
  [host-policy](docs/OUTPUT_VERIFICATION.md) guides explain support and limits.

### Compatibility and limits

- The original `--dem` heuristic and default vector `--compare-to` behaviour
  remain unchanged. Historical tasks, recipes, oracles, invocations and frozen
  experiments are preserved. New opt-in checks do not retroactively change the
  benchmark's declared blind-spot count. No routing trigger or skill was added.
- Source identity is decoded valid-data identity, not file-byte identity or full
  COG conformance. The explicit slope method assumes declared source units and
  its stated stencil/edge policy. No paid inference or new agent-lift claim.

### Verification

- Local final Python suite: 1483 passed, 1 skipped, three expected raster warnings.
  Router 87/87, packed npm install 8/8 and real CLI/installer/MCP stdio 20/20 pass.
  Candidate-wheel tests outside the checkout exercise both new contracts plus
  all skills/sections, bilingual routing, installer and the unchanged 33-task
  benchmark. No paid model request was made for this release batch.

## [0.7.2] — 2026-10-25

### Added

- Source-checkout API agents accept an opt-in required-output verification plan.
  Every declared deliverable needs explicit checks; only current matching MCP
  evidence can yield `verified`. Missing/stale evidence stays `unverified`, while
  current failures/warnings require review and prevent strict host completion.
  Whole data-tree content snapshots include masks and preserve original inputs.
  Existing session limits and the observed-failure guard remain active. The
  without condition receives no policy and stays unverified; independent artifact
  acceptance is unchanged. See [the policy guide](docs/OUTPUT_VERIFICATION.md).

### Verification and limits

- Offline Python verification: 1398 passed, 1 skipped. Local missing/stale/current
  evidence controls passed with real MCP and a scripted provider. In one fresh,
  prospectively frozen, directed GPT-4o session, an initial failed source check
  was followed by model repair, a current pass and independent acceptance with
  zero value/mask errors. Five requests cost approximately USD 0.058643 using
  cache-aware usage (USD 0.084723 uncached), below the approved USD 1 ceiling.
  No completion-review prompts were needed in the live session. This single
  engineering trial establishes no general repair reliability or agent lift;
  historical negative results and scientific checker limitations remain unchanged.

## [0.7.1] — 2026-10-25

### Fixed

- The API agent host reviews final answers when actual MCP checks have reported
  failures on declared deliverables. Up to two reminders allow repair and explicit
  rechecking within the existing per-session limits; unresolved failures prevent
  successful host completion. Input-only audit failures are excluded, warnings or
  unrelated passes cannot erase failures, and agent write attempts invalidate
  earlier resolutions. No checker or repair is run automatically. Reports keep
  this guard separate from independent artifact acceptance.
- The API agent host now forwards the configured MCP server's negotiated instructions
  in the treatment's system context and refuses missing, malformed or oversized
  instructions before a model request. Preflight checks both tool availability and
  instructions. Reports record delivery, character count and SHA-256, separately from
  actual tool calls; prompt reservations include the added text.
- Both API conditions receive the same final-output verification guidance. MCP
  guidance explains source-aware checks, calibrated NDVI, valid-data masks and
  unresolved check statuses. Instruction delivery alone does not enforce compliance or establish
  improved task performance; historical experiments and benchmarks remain unchanged.

### Verification and limits

- Offline completion regressions cover successful repair/recheck, unresolved
  termination, input-only audits, stale checks and original request limits.
  A directed live GPT-4o test exercised two review prompts and correctly stopped
  unresolved after three failing output checks; the model did not repair the mask.
  This is bounded-blocker acceptance, not a claim of reliable automatic repair or
  statistically demonstrated agent lift. Earlier exploratory results are retained.

## [0.7.0] — 2026-10-25

### Fixed

- API lift host: reserve a conservative complete-request allowance before each call,
  constrain requested output to remaining token/USD allowance, validate usage and
  reject over-limit terminal replies before any tool executes. Failed attempts and
  unknown usage retain their reservations. Reports and plans describe local limits
  rather than a guaranteed provider-side invoice cap. Non-finite budgets/prices
  are refused.
- Current evaluation documentation now records 33 tasks, 25 checker rejections and
  25 blind spots, and distinguishes real exploratory API pilots from offline tests.

### Added

- Opt-in `rs.index_formula`: `check OUTPUT --index-formula ndvi --nir NIR --red RED`
  (also Python/MCP) verifies every cell against calibrated source bands on the same
  grid, rejects unsupported valid output, and warns on extra masking. Source roles
  and calibration are supplied by the user. Provenance coverage includes both
  operands. Historical task invocations and benchmark scores remain unchanged.

### Changed

- CI runs on pull requests to main, pushes to main and manual dispatch. Feature-branch
  pushes no longer start a duplicate matrix before the pull-request matrix. All OS,
  Node and Python test combinations and the existing cancellation policy are retained.

## [0.6.0] — 2026-10-25

### Added

- Six harder agent-lift tasks, authored independently by Codex (a different model family): `landcover-summary-grid`, `terrain-slope-map`, `population-grid-transfer`, `vegetation-change-rate`, `storm-total-rainfall` and `three-band-vegetation-index`. Each has a spec, recipe, independent scalar oracle reading every cell and mask of the delivered file, and two seeded wrong outputs (see `docs/HARDER_TASKS.md`). The benchmark grows to 33 tasks with 0 false passes and 27 checker blind spots (the 15 existing plus 12 new oracle-only seeds). Their difficulty is not yet measured.
- API agent hosts for the lift driver: `--agent-host openai|groq` runs a small tool-calling agent (`tests/api_agent.py`) against any OpenAI-compatible chat API. It has project-confined file tools, a Python runner with a timeout, Terraproof's MCP tools in "with" only, keys only from `OPENAI_API_KEY` / `GROQ_API_KEY`, and per-run caps on model calls, tokens and USD at user-supplied prices. HTTP 429 rate limits (honouring `Retry-After`; `--rate-limit-retries`, `--max-retry-wait`) and Groq `tool_use_failed` are retried within the caps, and errors are recorded as short codes, never body text. Tested offline with a fake model; the small paid pilots run with it were smoke tests of the host, not lift measurements (see Phase 5 plan §18).
- `terrain.slope_consistent` check (`terraproof check SLOPE.tif --dem DEM.tif`, MCP `run_checks(dem=...)`): compares a slope-in-degrees raster with central differences on its DEM using the DEM's declared vertical unit (m, ft, US survey ft; none means horizontal units) and its real, possibly non-square, pixel spacing. It fails only when the slope instead matches a named mistake (vertical units ignored, square pixels assumed), warns when it matches neither (e.g. another stencil), and is not-run for geographic, unaligned or unknown-unit DEMs. It does not check the slope's mask or edge policy. The `terrain-slope-map` recipe now runs it, so its two seeded mistakes are rejected by the checks: 33/33 tasks, 0 false passes, 25 checker rejections, 25 checker blind spots, 31 exercised check IDs. Found by the API-host pilots, where GPT-4o (both conditions) and Qwen wrote slopes with the feet elevations read as metres and passed every check.
- Lift cohorts: `ORIGINAL_LIFT_TASKS` (the nine of the first run) and `HARDER_LIFT_TASKS` (the six above) are separate experiments. `run_lift`, `python -m terraproof.evals lift` and `tests/agent_lift.py` take `--cohort original|harder`, default `original`, and refuse `--task` together with `--cohort`; reports record the cohort. Calibration and the grader probe still cover all fifteen tasks.

### Fixed

- `geomaster` skill: the terrain snippet (`SKILL.md` "Terrain Analysis", and example 68 in `references/code-examples.md`) computed slope with `np.gradient(dem)` and no spacing, assuming 1-unit square pixels and equal vertical and horizontal units, and its hillshade swapped the sine and cosine of the slope. `terrain_metrics()` now uses the signed pixel size from the transform, converts the band's vertical unit to metres (or a given `z_factor`), refuses geographic, non-metre, rotated or sheared grids, masks nodata, and uses the standard hillshade. Found by the independent review; documented in `skills/geomaster/UPSTREAM.md` and `sources/SOURCES.md`. `tests/python/test_skill_snippets.py` runs the snippet from the skill text on synthetic DEMs (6 tests; all fail on the upstream snippet), and the router's snapshot test pins the snapshot-era text of the two edited files.

### Changed

- `tests/agent_lift.py`: the Claude total USD cap now defaults to the planned runs × `--max-usd-per-run` instead of a fixed $54, so a cohort's budget always covers its planned runs.

## [0.5.1] — 2026-10-24

### Fixed

Fixes for all eight findings of an independent review of v0.5.0 (Codex, 2026-10-24), each with a regression test in `tests/python/test_review_regressions.py`:

- Agent-lift grading: the `raster-nodata-dtype-windowing` oracle now reads every value and the mask from the delivered file (an all-zero answer with the right mask was accepted), and `score_outputs` enforces the deliverable contract (CRS, transform, shape, bands, dtype, nodata) against the task's own reference, so right values on the wrong grid are rejected (`contract_ok`, `contract_failures`, `caught_by: contract`).
- `raster.grid_alignment` compares rotation and shear terms and measures the origin offset in the reference grid's pixel coordinates; a sheared grid no longer passes as aligned, and matching rotated grids now align.
- Accuracy checks: a mapped class with positive area and no samples fails `accuracy.sample_design` and withholds area estimates; negative, non-finite or non-numeric class areas and a zero total are rejected; a reference class that is never mapped gets producer's accuracy 0 instead of a crash.
- `rs.temporal_scope` reports a STAC item whose start is after its end as unusable instead of inside the window.
- `mcnemar_mde` searches only feasible differences (≤ the discordance) and returns `None` when none reaches the power; the Phase 5 plan's MDE table and the main-run MDE (0.243 → none) are corrected.

### Evaluation

- All 72 saved Phase 5 main-run deliverables (54 runs) were re-graded offline with the fixed grader: 0 verdicts changed (with 27/27; without 24/27 on files, 21/27 with the contamination rule). The sign-flip p, bootstrap CI and McNemar p are unchanged.
- A generic probe found two more under-graded deliverables, now fixed: `sr_nir.tif` in `satellite-s2-baseline-offset-mask` was not graded, and a row-flipped `composite_counts.tif` in `satellite-seasonal-harmonized-composite` was accepted. Both oracles now grade every pixel and the mask from the delivered file, and a parametrized regression rejects zeroed, +1 and row-flipped versions of every deliverable of all nine lift tasks. Every saved historical output for both files matches the reference exactly, and re-grading the 72 main-run deliverables again changed 0 verdicts.

## [0.5.0] — 2026-10-24

### Added

- Phase 5 agent-lift harness (`python -m terraproof.evals lift`, `terraproof.evals.lift`) with its plan in `docs/plans/Terraproof_Phase5_PLAN.md`. Nine artifact-producing benchmark tasks run in paired without/with projects. The "with" project gets Terraproof through its own installer: router-selected skills plus the MCP server. Agents see only the task prompt, the input files and a format-only deliverable contract.
- The agent's deliverables are scored by substitution: they are copied into the existing recipe's correct-control slot, so the unmodified Phase 4 checks and independent oracles grade them. A calibration gate must pass first: inputs regenerate byte-identically, the reference is accepted, every seeded-wrong output and an echoed input are rejected, and a missing file is reported. All nine tasks pass it.
- Deterministic paired statistics: the primary analysis is an exact task-level sign-flip test with a seeded task-cluster bootstrap CI; exact McNemar is a secondary analysis; a Connor (1987) minimum-detectable-effect estimate is included. Reports are stable JSON.
- Offline `scripted` and `replay` adapters only; neither CI nor the tests call a model. The opt-in real-host driver `tests/agent_lift.py` (Codex or Claude Code) prints the plan and call count unless `--approve-model-calls N` matches it exactly. It reuses the release-validation isolation, auth probes and process-tree containment, and enforces per-run timeouts, a hard run count and Claude per-run/total USD caps. Traces are sanitised to counts and labels and include contamination labels.

- Pilot 1 follow-up:
  - Codex lift runs keep Codex's own execution features at their defaults instead of disabling `unified_exec`, and set `mcp_servers` explicitly in both conditions.
  - `--codex-executable` pins a native runtime.
  - A no-model preflight runs before every run. It probes the sandboxed shell, Python/rasterio, input reads and output writes, MCP registration and its six served tools, and checks that skills and AGENTS.md are visible only in "with". A failure starts no agent, and `--preflight-only` runs the preflight alone.
  - The trace now holds per-call tool label, category, status, exit code and duration, plus a turn status, reason and error-type labels. Codex `error` items no longer count as calls.
  - Runs that finish without a deliverable or any shell/edit call are reported as `no-attempt`, and "with" runs record `treatment_used`.
- Pilot 2 follow-up:
  - Codex built-in MCP resource tools (`list_mcp_resources`, `list_mcp_resource_templates`, `read_mcp_resource` on server `codex`) are labelled `mcp:codex-resource`, never as Terraproof calls or as attempts.
  - The Codex preflight reads `codex debug models` and refuses to start while every listed model is `code_mode_only`, because shell exposure cannot be shown without a model turn.
  - The Claude adapter passes an explicit MCP config copied from the installer entry, since project `.mcp.json` servers wait for approval in Claude Code.
  - The Claude preflight resolves `python` on the agent's PATH.
- Pilot 3 follow-up:
  - `--claude-executable` selects the native `claude.exe`; npm's `claude.cmd` wrapper is refused.
  - The lift summary reports each task's `baseline_pass_rate` and a descriptive `ceiling` flag, plus `ceiling_tasks` and `tasks_with_headroom`. The primary analysis is unchanged.
- Main-run follow-up (isolation for future runs):
  - Run projects use opaque `runs/NNN/project` paths under a neutral `paired-run-*` work directory.
  - `--agent-python-without` supplies a dependency-only interpreter, and `PYTHONPATH` is dropped in "without". The preflight requires that interpreter, that it cannot import Terraproof, and that paths are neutral.
  - Contamination now has sub-labels for real use (`import`, `module-or-cli`, `mcp`, `package-query`, `skill`, `mention`), separate from the path-only diagnostic `terraproof-path-text`.
  - Forced rejections keep `accepted_before_contamination`, and the summary adds a labelled, not-pre-specified `sensitivity_contamination_ignored`.
- `geometry.winding`: GeoJSON polygon rings must follow the RFC 7946 right-hand rule (counterclockwise exteriors, clockwise holes). It fails a non-conforming export, passes a conforming one, and does not run on other drivers. The vector inspection profile records `geometry.winding` for GeoJSON layers.

### Changed

- Repository layout: the design plans moved to `docs/plans/` and the release checklist to `docs/RELEASE_CHECKLIST.md`. `README.md` is rewritten as a shorter, current front page with an explicit evaluation status.
- `raster.cog_layout` now warns when a GeoTIFF uses JPEG compression, which is always lossy and changes stored pixel values. That is fine for visual products but not for analysis values. Lossy LERC (`MAX_Z_ERROR`) and WebP settings are not detected.

### Evaluation

- Pilot 1 (2 approved Codex 0.160.1 invocations) produced no `ndvi.tif` in either condition, with zero Terraproof use. It is diagnosed in `docs/plans/Terraproof_Phase5_PLAN.md` §13 as a harness failure, most likely from the disabled execution tools, and is excluded from any analysis. Pilot 2 (2 approved invocations on the Codex 0.163.0-alpha.11.2 app runtime) again made no shell call; its only calls were two built-in resource listings per condition (§14). Codex is blocked by preflight on this machine. Claude Code pilot 3 (2 approved invocations, $0.52 reported) passed the gate: both conditions produced an accepted, decision-grade `ndvi.tif`, and the "with" run used Terraproof (2 `inspect_dataset`, 2 `run_checks`, 1 skill read). This is the first end-to-end harness run. It shows a 0.0 difference on a ceiling task, not a lift estimate (§15). Main run (54 approved Claude Code invocations, $8.71 reported):
  - **Pre-specified result:** pass rate 1.0 with vs 0.778 without, mean task difference 0.222 (95% CI 0.037–0.444). **The primary exact sign-flip test gives p = 0.125, not significant, and no lift claim is made.** McNemar's secondary p = 0.031 is anti-conservative.
  - **Ceiling:** five of nine tasks are at ceiling.
  - **Contamination flags:** three of six "without" rejections came only from a `terraproof-in-without` flag that matched absolute `Read`-tool paths under the old `terraproof-lift-host-*` prefix. Whether those runs also used Terraproof for real cannot be determined from the sanitised trace.
  - **Sensitivity (not pre-specified):** without 0.889, difference 0.111, sign-flip p = 1.0.
  - **Robust exploratory finding:** Landsat QA, 3/3 with vs 0/3 without (§16).
- Deterministic evals: **27/27 tasks, 0 false passes, 15 checker blind spots** (down from 17), 23 checks rejected (up from 21), 30 exercised check IDs. Newly rejected by the checks: `raster-cog-delivery` / `lossy-jpeg-cog` (`raster.cog_layout` warns) and `vector-join-scope-and-geojson` / `clockwise-geojson-winding` (`geometry.winding` fails). No task spec, oracle assertion or seeded wrong output was changed; only the recipes' descriptive notes were updated. CLI/MCP parity tests cover both controls.
- The 15 remaining blind spots stay declared because the checker has no legitimate evidence for them in the invocation the spec defines. `docs/RELEASE_CHECKLIST.md` and `evals/README.md` give the reason for each.


## [0.4.1] — 2026-10-24

### Fixed

- Python routing no longer sends ordinary non-technical requests (writing, budgets, travel, general programming, maths concepts) to geospatial skills. A positive domain gate requires geospatial, remote-sensing or scientific-analysis wording; homonyms such as network, map, projection, layer and satellite count only without an everyday context, and phrases like "vector graphics" or "buffer overflow" are vetoed.
- Arabic routing recognises sound plurals and duals, transliterated tool names (جيوبانداز، ليفليت، ستاك…), Gulf and Egyptian phrasing, and more workflow phrases. Symptom wording now reaches the right skill for CRS mismatches, geometry defects, network connectivity, significance tests, multi-year change, validation samples and partial cloud reads. A descriptive "do not" ("the layers do not overlap") no longer truncates the request.
- GDAL is selected only with command, format or raster wording, and a strong wording penalty removes a skill that only matched a bare trigger.

### Evaluation

- New independent frozen set `evals/routing/heldout_v5.jsonl` (SHA-256 `5cc76cff…5ea891889`), written by a separate agent without access to the router or earlier sets and measured once: **EN recall 0.971, 3.75 forbidden per 100; AR recall 0.9625, 2.5 forbidden per 100; both pass** the per-language gate (recall ≥ 0.90, ≤ 5 forbidden per 100). It is agent-authored, not expert-adjudicated; earlier v3/v4 failures remain recorded in `docs/RELEASE_CHECKLIST.md`.
- Development routing set grew to 947 items (501 new, 200 of them negatives); 40 new Python routing scenarios.
- Review follow-up: exclusions in the middle of a clause ("I don't want SAR", "never include Sentinel-1") apply again. The Arabic comma now separates clauses. Location tasks in a business setting (nearest store per address, counts per district on a map) are no longer vetoed, and broad words such as scene, regression, pixel, elevation and geo- names now need domain context. The dev set has 962 items, and 15 more scenarios cover each fixed case. A v5 re-run after these fixes (EN 0.983 / 3.75, AR 0.9625 / 2.5 forbidden per 100) is a non-regression check on an already-measured set, not a new independent result.

## [0.4.0] — 2026-10-23

### Added

- Phase4 preflight plans and CLI/MCP parity for CRS/reprojection, grid alignment, categorical resampling, decode/encoding, temporal scope, index inputs, and measurement units.
- Provenance manifest write/verify integration with coverage checks for primary, compare, reference, QA, sample, and area inputs, plus optional `--require-provenance`.
- Four registered skills: `time-series-and-change`, `sar-basics`, `accuracy-assessment`, and `stac-and-cloud-access`.
- Executable deterministic eval harness for 27 task specs with independent oracles and a separate seven-case preflight control group.
- Router candidate mode with deterministic default cap 8 and optional offline semantic retrieval that falls back to lexical scoring.

### Fixed

- Python routing now distinguishes ordinary software/copy homonyms from explicit domain work, preserves inspected-dataset evidence for mixed tasks, and recognizes additional Arabic workflow phrases, named GDAL commands and web-map engines. The exposed 160-item internal audit is registered as development coverage without relabelling; a separate frozen 100-item same-agent release audit meets the original per-language numerical targets. Independent/generalisation limits remain explicitly reported.

- Corrected the time-series NDVI example so undefined observations cannot satisfy the minimum count; made SAR log-ratio/dB units explicit, qualified systematic-sample variance formulas, and updated the four Phase4 skills to the implemented CLI options.

- Python wheels now include the existing skills, routing/check catalogs, evaluation task specs, instructions and upstream attribution/license assets. Runtime asset lookup works outside the source checkout, and eval fixtures use the working project's cache instead of writing beside installed assets. CI builds and smoke-tests the wheel in the Python matrix.
- The Python build helper is importable from the `src` package layout, so isolated editable installs, wheel builds and sdist rebuilds use the same asset-packaging path.
- Native Codex release validation keeps its required host transport, approves only the two allowed read-only MCP tools per invocation, and retains the existing strict call/result and process-cleanup gates.
- Registered Unicode section anchors, including the SAR calibration heading containing `β⁰`, `σ⁰` and `γ⁰`, load through the skill API; path separators and control characters remain rejected.
- Registered the 40 bilingual intent development cases in the public Python scenarios, with a coverage/label consistency regression. Repository link validation ignores generated `.terracache` fixtures while still checking source documents.
- Provenance schema 0.1 now rejects malformed manifests and extra hashed-core fields (including creation timestamps with recomputed hashes) as check failures. Credential-bearing URLs in STAC metadata, nested parameters and command arguments are rejected by the writer without echoing secrets; verification also checks recorded local JSON run records. Use stable unsigned hrefs; ordinary acquisition/search time parameters remain allowed.
- `rs.scale_applied_once` checks source-nodata preservation over all first-band pixels in bounded windows, permits extra QA masking, and reports incompatible grids/shapes/rotation/shear or unavailable calibration as `not-run`. Numeric calibration remains stride-sampled, with the existing full-band numeric read unchanged.
- Optical/STAC eval recipes supply raw reference/calibration and recorded JSON manifests where needed. Same 27 tasks and 38 wrong controls: checker rejections increased from 15 to 21, oracle-only blind spots decreased from 23 to 17, with zero false passes and 29 exercised IDs. Production API and CLI/MCP parity regressions cover the six targeted controls; task specs and independent numeric oracles are unchanged.

### Known limits

- Eval reports measure deterministic checks and independent fixture oracles only; they do not measure agent lift, hosted CI, live MCP hosts, network/cloud behavior, or held-out routing performance. Oracle-only rejection is reported as a checker blind spot, not as checker rejection.

---

## [0.3.0] — Unreleased

### Added

- Python skill router (`src/terraproof/router/`, `python -m terraproof route "TASK" [--data PATH ...] [--top-k N] [--format json|md]`): deterministic, offline retrieval of skill sections by BM25 over the `SKILL.md` and reference sections (best section plus a quarter of the second), exact `skill.json` triggers, and explained data-aware boosts and penalties computed from inspected local datasets. Arabic and Egyptian-dialect normalization (diacritics and tatweel removal, NFKC, alef/ya/ta-marbuta folding, attached articles, conjunctions and prepositions) with a curated Arabic-to-English lexicon. Process and verification skills are returned separately in `process`, and every score carries its reasons.
- Router evaluator (`python -m terraproof.router.evaluate FILE [--top-k N] [--min-recall R]`): prints mean recall@k, per-language recall, `must_not` violations, and the failing items as JSON; exits 1 when recall is below the threshold or a prohibited skill is ranked.
- Routing evaluation sets (`evals/routing/`): `dev.jsonl` (115 items, for tuning and regression), the independent `heldout.jsonl` (80 items: 40 English, 40 Arabic), and a README with the schema, the metric, and the held-out policy. A second, fresh held-out set `heldout_v2.jsonl` (100 items: 50 English, 50 Arabic) gives the current honest estimate; see Known limits. The dev set has grown to 169 items.
- MCP server (`src/terraproof/mcp/`, `python -m terraproof.mcp`): a stdio server with five read-only tools (`inspect_dataset`, `run_checks`, `list_skills`, `load_section`, `find_guidance`) that return the same results as the command line. It writes no files and makes no network calls.
- Optional `mcp` extra (`pip install -e ".[mcp]"`, MCP Python SDK 2.x, `mcp>=2.3,<3`); the base install stays dependency-light.
- Native agent installers (`src/terraproof/install/`, `python -m terraproof.install --agent {claude,cursor,codex,gemini,copilot,opencode} --skills a,b | --task "..." --target DIR [--with-mcp] [--dry-run]`): writes the selected skills in each agent's own project format, merges existing JSON and TOML configs instead of replacing them, replaces only the agent-scoped Markdown block, and produces identical bytes on a rerun.
- CI `python` job installs `.[dev,mcp]`, so the router, MCP server, and installer tests run on Ubuntu and Windows with Python 3.11 and 3.13.

### Fixed

- Agent installer Markdown markers are now agent-scoped (`<!-- terraproof:<agent>:begin -->` / `<!-- terraproof:<agent>:end -->`), so `codex` and `opencode` can coexist in the same `AGENTS.md` and each rerun is idempotent for that agent. Legacy unscoped markers are migrated automatically.

### Known limits

- The router is lexical retrieval (BM25 plus hand-written rules), not semantic understanding, and it can over-select related skills. `heldout.jsonl` must not be used to tune it.
- Router generalization is below target: on the fresh independent `heldout_v2.jsonl` (100 items) mean recall@5 is 0.845 (English 0.890, Arabic 0.800) with 18 `must_not` violations. On `heldout.jsonl` (v1, already used once for category feedback) it is 0.913 with 0 violations. A relative cutoff (0.5) and intent guards reduced over-selection (v2 violations 25 → 18, mean ranked skills about 1.9) at a cost of about 4 points of v2 recall.
- Real-host MCP verification: Claude Code 2.1.292 lists `terraproof` from `.mcp.json` but keeps it pending approval; Codex CLI 0.160.1 parses `.codex/config.toml` only for trusted projects (verified via isolated `CODEX_HOME`); Gemini CLI 0.62.0 reads `.gemini/settings.json` but suppresses servers in untrusted folders. `cursor`, `copilot`, and `opencode` are unit-tested only.

---

## [0.2.0] — Unreleased

### Changed
- Renamed the project to **Terraproof**: evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents (see [`docs/plans/Terraproof_v1_PLAN.md`](docs/plans/Terraproof_v1_PLAN.md)). The package is now `terraproof` v0.2.0, the CLI is `terraproof` (`bin/terraproof.js`), and the CLI banner, help, and generated manifest or bundle text say Terraproof. The GitHub repository is renamed to `esmailhussien/terraproof`, and the license and package author are now "Terraproof Contributors".
- `apply` manifest no longer claims that Codex, Antigravity, Claude Code, or Cursor load `.agents/skills/` automatically; it says the skills must be referenced from the agent's instruction file.
- Registry narrowed to 15 skills across process, GIS, remote-sensing, and spatial-analysis work.
- Preset collections reduced to 3: `gis`, `data-analysis`, `production`.
- `verification` skill frontmatter `name` changed from `verification-before-completion` to `verification` to match its directory.
- Router test suite trimmed to 28 scenarios (14 core, 14 real-world), all passing.
- CLI argument parsing is strict: unknown options, options missing a value, `--format` other than `json` or `table`, unknown `--collection`, and unknown `--include` or `--exclude` skills exit with status 1 and a message. Unknown commands, extra positional arguments, and options passed to `validate` are rejected too.
- `--yes` / `-y` removed from the CLI (there was no confirmation prompt, so it is now an unknown option).
- Routing data: `data-analysis` collection description no longer mentions network analysis; removed skill names are dropped from `routing/rules.json` (`intentRules`, `riskBoundaries`, `verificationRules`). Routing results are unchanged.
- Ported the Quick Start (README), the contributing guide (`CONTRIBUTING.md`, including Python setup and checks), and the bug report and feature request issue forms to Terraproof.

### Fixed
- The published package failed to run: `npx agentlayer` ended with `ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING` because raw `.ts` router sources shipped inside `node_modules`. The router is now compiled to `dist/router/*.js` by `npm run build` (run automatically by `prepack`), and the CLI runs on Node 20 or newer. The package root is found by walking up from the module to the directory holding `package.json` and `routing/registry.json`.
- CI pytest on fresh checkouts: `tests/python/conftest.py` now creates the parent of the `--basetemp` directory (`.pytest_cache/basetemp`, set in `pyproject.toml`), which pytest does not create itself.
- Check false passes: `crs.metric_operation` now passes only projected horizontal CRSs in metre or foot units (geocentric CRSs fail, unconfirmable units warn); `rs.reflectance_range` and `rs.index_range` fail on non-finite scale, offset, or decoded values; `raster.cog_layout` is a layout heuristic with neutral wording that no longer warns about missing overviews for rasters that fit in one block.

### Added
- Experimental Python core (Phase 1, `pyproject.toml`, `src/terraproof/`): `python -m terraproof inspect` (vector, raster, and local STAC Item inspection, read-only, no network) and `python -m terraproof check` (checks for CRS and units, geometry, record counts, raster integrity, remote-sensing value ranges, and STAC provenance). Each run yields an evidence grade (Decision-grade, Review required, Advisory only) in a JSON or Markdown report; the Markdown report has English and Arabic (`--lang ar`) output. Exit codes: 0, 2, 3 for the grades and 1 for usage errors or unreadable inputs. Tests in `tests/python/` generate fixtures at test time.
- CI job `python` runs `pytest -q tests/python` on Ubuntu and Windows with Python 3.11 and 3.13.
- `tests/router/cli.test.ts`: CLI argument validation tests, wired into `npm run test:router`.
- `npm run test:package` (`tests/package/smoke.mjs`): packs the package, installs the tarball into a fresh project, and checks `--version`, `route --format json`, `validate`, and unknown-collection rejection.
- CI job `package-smoke` runs the package smoke test on Ubuntu, Windows, and macOS with Node 20, 22, and 24.
- Per-skill `skill.json` manifests in `skills/<name>/` (schema in `routing/SKILL_MANIFEST.md`), replacing hand-edited registry entries.
- Generated registry: `npm run registry:build` writes `routing/registry.json` from the manifests, and `npm run registry:check` verifies it. `npm run test:router` runs the same check.
- `routing/checks.json` check catalog, kept in sync with the Python check ids by `tests/python/test_check_catalog.py`.
- Data-driven explanations: each skill's routed explanation comes from its manifest.
- Five new skills: `crs-and-units`, `vector-quality`, `raster-processing`, `satellite-preprocessing`, and `spectral-indices`.
- 15 benchmark task specs in `evals/` (5 skills, 3 tasks each). These are specifications only; the harness is planned, not implemented.
- `remote-sensing` preset collection: `geospatial-data-discovery`, `satellite-preprocessing`, `spectral-indices`, `raster-processing`, and `verification`.
- 27 router scenarios (`scenario-30` to `scenario-56`) for the new skills, including precision cases where a new skill must not be selected; every trigger in the new manifests appears in at least one scenario prompt. Core suite: 41 scenarios; total with the real-world suite: 55.

### Removed
- Off-scope skills: `frontend-design`, `react-best-practices`, `codebase-architecture`, `supabase`, `supabase-postgres-best-practices`, `security-review`, `api-discovery`, `api-integration`, `ai-sdk`, `unit-testing`, `integration-testing`, `browser-testing`, `test-driven-development`, `exploratory-data-analysis`.
- Collections: `web-app`, `api-integration`, `supabase-app`, `ai-app`.
- Upstream fixtures for removed skills under `tests/upstream/`, and `third_party/` folders no longer used by any remaining skill (`arjunprabhulal-agent-skills`, `vercel-agent-skills`, `vercel-open-agents`, `mblode-agent-skills`, `supabase-agent-skills`, `github-awesome-copilot`, `vercel-ai`).
- Router scenarios that only exercised removed domains (20 core, 16 real-world).

### Attribution
- Attribution for removed material is kept in `sources/SOURCES.md` under "Removed in 0.2.0" (source repository, commit SHA, and license).

---

## [0.1.0] — 2026-08-26

### Added

**Smart Skill Router & Skills CLI**
- Deterministic, offline router with classify → score → resolve → explain pipeline
- 29 registered production skills across 5 layers (process, domain, implementation, risk, verification)
- 7 preset skill collections: `web-app`, `gis`, `data-analysis`, `api-integration`, `supabase-app`, `production`, `ai-app`
- Evidence-based confidence scoring with over-selection guardrails
- CLI with `route`, `apply`, `bundle`, `validate` commands and `--dry-run`, `--include`, `--exclude`, `--collection`, `--format`, `--target`, `--out`, `--version` flags
- `apply` command to copy selected skills and universal instructions into target projects (`.agents/skills/`) with automated `AGENTS.md` manifest generation
- `bundle` command to compile a single prompt context payload with layer grouping and universal instructions
- Clean export filtering (excludes internal provenance `UPSTREAM.md` from client projects)

**Skills — Process & Planning**
- `brainstorming` — Explore intent, requirements, and design options (from [obra/superpowers](https://github.com/obra/superpowers))
- `writing-plans` — Executable task-by-task engineering plans (from [obra/superpowers](https://github.com/obra/superpowers))
- `systematic-debugging` — 4-phase structured root-cause investigation (from [obra/superpowers](https://github.com/obra/superpowers))
- `verification` — Validate completeness and truthfulness before declaring done (from [obra/superpowers](https://github.com/obra/superpowers))

**Skills — Quality Assurance & Testing**
- `unit-testing` — Isolated unit test design and edge-case enumeration (from [arjunprabhulal/agent-skills](https://github.com/arjunprabhulal/agent-skills))
- `integration-testing` — Boundary verification against databases and dependencies (from [arjunprabhulal/agent-skills](https://github.com/arjunprabhulal/agent-skills))
- `browser-testing` — End-to-end browser user journeys (from [arjunprabhulal/agent-skills](https://github.com/arjunprabhulal/agent-skills))
- `test-driven-development` — Red-green-refactor TDD methodology (from [arjunprabhulal/agent-skills](https://github.com/arjunprabhulal/agent-skills))

**Skills — Frontend**
- `frontend-design` — Visual direction and aesthetic design quality (from [vercel-labs/open-agents](https://github.com/vercel-labs/open-agents))
- `react-best-practices` — React & Next.js performance optimization with 70 rules (from [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills))

**Skills — Architecture & Database**
- `codebase-architecture` — TypeScript codebase design, domain-informed deepening (from [mblode/agent-skills](https://github.com/mblode/agent-skills))
- `supabase` — Supabase platform integration: Auth, SSR, Realtime, Storage (from [supabase/agent-skills](https://github.com/supabase/agent-skills))
- `supabase-postgres-best-practices` — Postgres schema design, indexing, RLS (from [supabase/agent-skills](https://github.com/supabase/agent-skills))

**Skills — Security**
- `security-review` — Vulnerability scanning, secret detection, CVE audits (from [github/awesome-copilot](https://github.com/github/awesome-copilot))

**Skills — Geospatial Domain Pack**
- `gdal` — Raster/vector CLI operations, COGs, reprojection (from [isaaccorley/geospatial-skills](https://github.com/isaaccorley/geospatial-skills))
- `geopandas` — Vector spatial data, joins, overlays, CRS transforms (from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills))
- `geomaster` — Earth observation, remote sensing, spatial ML (from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills))
- `design-postgis-tables` — PostGIS table architecture and spatial indexing (from [timescale/pg-aiguide](https://github.com/timescale/pg-aiguide))
- `geoparquet-validation` — GeoParquet metadata and cloud-native distribution (from [isaaccorley/geospatial-skills](https://github.com/isaaccorley/geospatial-skills))
- `geozarr` — Multidimensional geospatial raster arrays (from [isaaccorley/geospatial-skills](https://github.com/isaaccorley/geospatial-skills))
- `geospatial-frontend` — MapLibre GL and geospatial visualization (from [isaaccorley/geospatial-skills](https://github.com/isaaccorley/geospatial-skills))
- `geospatial-data-discovery` — Open geospatial data acquisition: STAC, OSM, Sentinel (AgentLayer Native)

**Skills — Data & Analytics Domain Pack**
- `exploratory-data-analysis` — Tabular profiling, missingness audits, EDA scaffolds (from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills))
- `statistical-analysis` — Hypothesis testing, ANOVA, effect sizes, APA reporting (from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills))
- `scientific-visualization` — Publication-ready figures, colorblind-safe palettes (from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills))
- `networkx` — Graph analysis, centrality, community detection (from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills))

**Skills — APIs & Open Data**
- `api-discovery` — Public API discovery and documentation verification (AgentLayer Native)
- `api-integration` — Resilient HTTP clients with backoff and rate limits (AgentLayer Native)

**Skills — AI Foundations**
- `ai-sdk` — Unified AI SDK for streaming, structured output, tool loops, RAG (from [vercel/ai](https://github.com/vercel/ai))

**Infrastructure**
- GitHub Actions CI with repository validation and router scenario testing
- Complete source attribution in `sources/SOURCES.md` with upstream commit SHAs
- 11 third-party license directories covering all vendored material
- 3 universal instruction files: engineering, simplicity, security
- 64 automated test scenarios (34 core + 30 real-world) with 100% pass rate and determinism verification
