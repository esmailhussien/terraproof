# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

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
