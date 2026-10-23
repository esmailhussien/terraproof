# Terraproof

> evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents. *By Geova.*

> **Status:** Experimental — refocusing from AgentLayer v0.1

Terraproof is a focused collection of mapping and remote-sensing skills for AI coding agents, plus a deterministic router that selects the smallest useful set of them for a task. The direction is to make geospatial agents prove their work: inspect real datasets, apply section-level expert guidance, run executable checks, and attach an evidence grade to each result. Read the full plan in [`Terraproof_v1_PLAN.md`](Terraproof_v1_PLAN.md).

**Today:** 24 skills, a TypeScript router with 73 test scenarios, and a Python package with dataset inspection, checks, evidence grades, a skill router, a read-only MCP server, executable evals, and agent installers (see [Python core](#python-core-phase-1-experimental), [Skill router (Python)](#skill-router-python), [MCP server](#mcp-server), and [Install into your agent](#install-into-your-agent)).
**Planned, not implemented yet:** verification of the installers in real agent hosts (only Claude Code has been exercised end to end) and a fresh, independently written held-out routing set.

---

## Quick Start: Route a Real Task

Use a source checkout for this walkthrough; it does not depend on an npm release being available.

**Requirements:** Git and Node.js. Source checkout commands (`node router/index.ts ...`) need **Node.js 22.18+ or 24+** for native TypeScript support (see [Node.js TypeScript support](https://nodejs.org/api/typescript.html)). The built package (`npm run build`, `node bin/terraproof.js ...`) needs Node.js 20+. No model API key is needed for routing. A coding agent is needed separately to implement the task.

```bash
git clone https://github.com/esmailhussien/terraproof.git
cd terraproof
node router/index.ts --version
node router/index.ts validate
node router/index.ts route "Download Sentinel-2 imagery from a STAC catalog, compute NDVI, and map the change with MapLibre" --dry-run
```

**Expected result:** `--version` prints `terraproof v0.4.1`, and `validate` reports the current generated registry and collections. The route prints the task, selected skills grouped by layer, and rationale. Exact scores and selections are input- and registry-dependent; dry-run output also lists dropped candidates. It does not create files or call a model.

The walkthrough is illustrative, not a recorded execution. Exact selections and scores depend on the prompt, overrides, and registry revision. The commands that run offline were checked against this checkout. The download, NDVI, and MapLibre steps need network access and data, so they are illustrative only.

### Practical example: Sentinel-2 NDVI change map

The task needs satellite imagery, a spectral index, and a web map. First inspect the route above. If the recommendation misses a requirement, revise the prompt or use overrides.

Bundle the selected skills into one reviewable context file. The `--include` flags force four skills; the router also selects `spectral-indices` for the NDVI step, so the bundle holds five:

```bash
node router/index.ts bundle "Download Sentinel-2 imagery from a STAC catalog, compute NDVI, and map the change with MapLibre" --include geospatial-data-discovery --include geomaster --include geospatial-frontend --include verification --out ndvi-context.md
```

**Expected artifact:** `ndvi-context.md` in the current directory. The CLI prints `✓ Composed bundle written to: ndvi-context.md (5 skills, <N> bytes)`; the size in this checkout was 40130 bytes. The file starts with a header listing the task, the five skills, and their layers, then the universal engineering instructions and the skill text grouped by layer. Review it, then give it to your coding agent together with your project requirements. The file is instructions, not generated application code.

For agents that support project skill directories, export to a separate demo folder first. The `--dry-run` form prints the same recommendation with `Mode: DRY RUN (No changes made)` and writes nothing:

```bash
node router/index.ts apply "Download Sentinel-2 imagery from a STAC catalog, compute NDVI, and map the change with MapLibre" --include geospatial-data-discovery --include geomaster --include geospatial-frontend --include verification --target ../terraproof-demo/.agents/skills --dry-run

# After reviewing the recommendation, remove --dry-run to write files:
node router/index.ts apply "Download Sentinel-2 imagery from a STAC catalog, compute NDVI, and map the change with MapLibre" --include geospatial-data-discovery --include geomaster --include geospatial-frontend --include verification --target ../terraproof-demo/.agents/skills
```

**Expected files after a successful export** (the target is resolved from the directory you run the command in, so this folder appears next to the clone):

```text
terraproof-demo/
└── .agents/
    ├── AGENTS.md          # Generated manifest with installed skills and rationales
    ├── instructions/      # engineering.md, security.md, simplicity.md; copied only if this folder does not exist yet
    └── skills/            # One folder per selected skill; UPSTREAM.md is excluded
        ├── geomaster/
        ├── geospatial-data-discovery/
        ├── geospatial-frontend/
        ├── spectral-indices/
        └── verification/
```

Check the CLI output for copy errors and inspect the files. The CLI reminds you that nothing loads these skills automatically, so reference `.agents/skills` from your agent's instruction file (for example, a root `AGENTS.md`). Then ask the agent to read the manifest and the relevant skills before it implements anything. Verify the resulting work yourself, including the map rendering and the error states in the app.

### Check the result with the Python core

After the work produces a raster, run the Python checks on it. Setup (Python 3.10 or newer) and the full list of checks are in [Python core](#python-core-phase-1-experimental).

```bash
python -m terraproof check ndvi.tif --expect index --format md --lang ar --out ndvi_report_ar.md
```

`--expect index` checks that the sampled values fall within [-1, 1]. `--lang` only applies to the Markdown format, so `--format md --lang ar` writes an Arabic report. The exit code is `0` Decision-grade, `2` Review required, `3` Advisory only, or `1` for a usage error.

**Expected result (illustrative for `ndvi.tif`):** the grade and messages depend on your file. This command was run on a synthetic 64×64 NDVI GeoTIFF (EPSG:32636, striped, no overviews), not on a Sentinel-2 product. It produced the grade **يحتاج مراجعة** (Review required) and exit code `2`: `raster.cog_layout` warned that the file is not a tiled COG, while `crs.defined`, `raster.nodata_declared`, and `rs.index_range` passed.

### Experimental limits and safe use

- Routing is deterministic keyword/scoring logic, not semantic understanding. Confidence is a routing signal, not a probability that the implementation will succeed.
- Inspect recommendations before use. Prompt wording, conflicts, collection presets, and manual overrides can change the selected skills.
- The CLI is strict. Unknown options, options missing a value, `--include` or `--exclude` names that are not registered skills, unknown `--collection` names, and `--format` values other than `json` or `table` exit with status `1` and a message. `--help` lists the options.
- `apply` writes without an interactive confirmation; there is no `--yes` flag. It overwrites files that have the same names in the target and the manifest next to it (`<target>/../AGENTS.md`). Start in a disposable folder, or commit or back up existing files first.
- The generated manifest tells you to reference the skills from your agent's instruction file, because nothing loads `.agents/skills/` automatically.
- Use `route --dry-run` or `apply --dry-run` to inspect without exporting. `bundle --out` writes its file even when `--dry-run` is supplied, and it overwrites an existing output file.
- Routing uses local files. Cloning, dependency installation, and any tools that individual skills describe may need network access or their own dependencies.
- Exporting skills does not install GDAL, Python packages, browser tooling, or other domain dependencies, and it does not prove that an agent loaded or followed the instructions.

For development checks, see [Verify your change](CONTRIBUTING.md#verify-your-change) in `CONTRIBUTING.md`.

---

## Install & Usage

The npm package name `terraproof` is not published yet, so `npx terraproof` does not work from the registry. From a clone:

```bash
npm install          # dev dependencies (TypeScript)
npm run build        # compile router/ to dist/router/
node bin/terraproof.js route "Reproject a GeoTIFF to EPSG:3857 and build a COG with GDAL"
node bin/terraproof.js --version
```

Requirements:
- **Installed package (`dist/`):** Node.js 20 or newer.
- **Development and tests from source** (`node router/index.ts`, `npm run test:router`, `npm run typecheck`): Node.js 22.18 or newer, which strips TypeScript types natively.
- `npm run test:package` packs the repository, installs the tarball into a temporary project, and runs the installed CLI.

## Smart Skill Router

The router is deterministic and offline. It maps a task description to a short list of skills, each with a reason:

```bash
# Calculate the recommended skill composition
node router/index.ts route "Reproject GeoTIFF elevation tiles to EPSG:4326 and build COGs"

# Seed the selection from a preset collection
node router/index.ts route "Design a PostGIS schema for GPS tracks" --collection gis

# Inspect the result without changes, or print JSON for tooling
node router/index.ts route "Compute NDVI change for 2020-2024" --dry-run --format json

# Check registry integrity
node router/index.ts validate
```

For scoring weights, layers, and heuristics, see [`routing/ROUTER_DESIGN.md`](routing/ROUTER_DESIGN.md) and [`router/README.md`](router/README.md).

---

## Python core (Phase 1, experimental)

The Python package `terraproof` inspects geospatial datasets, runs deterministic checks, and writes an evidence report as JSON or Markdown (English or Arabic). It reads local files only and makes no network calls. `inspect` and `check` are not a port of the TypeScript router; the same package also provides the separate Python skill router, the MCP server, and the agent installers described in the next three sections. The `terraproof` npm command above is still the TypeScript router; the Python core runs as `python -m terraproof`.

Setup, from the repository root (Python 3.10 or newer):

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"    # Windows: .venv\Scripts\python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q tests/python
```

Examples (replace the paths with your own datasets):

```bash
# Print the inspection of one dataset as JSON
python -m terraproof inspect data/parcels.gpkg

# Run the checks and print a JSON evidence report
python -m terraproof check data/parcels.gpkg --operation area

# Compare record counts with the input and write a Markdown report in Arabic
python -m terraproof check outputs/clip.gpkg --compare-to data/parcels.gpkg --format md --lang ar --out report_ar.md

# Categorical raster: nearest or mode resampling passes, bilinear fails
python -m terraproof check landcover.tif --categorical --resampling nearest --format md
```

Inputs: vector (`.gpkg`, `.geojson`, `.json`, `.shp`, `.fgb`, `.parquet` where GDAL can read it), raster (`.tif`, `.tiff`, `.vrt`, `.jp2`), and local STAC Item JSON.

Checks cover CRS and units (`crs.defined`, `crs.consistent`, `crs.metric_operation`), geometry (`geometry.valid`, `geometry.non_empty`, `geometry.type_consistent`), record counts (`scope.record_count`), raster integrity (`raster.nodata_declared`, `raster.resampling`, `raster.grid_alignment`, `raster.cog_layout`), remote-sensing value ranges (`rs.reflectance_range`, `rs.index_range`), and STAC provenance (`stac.provenance`), with Phase4 processing, preflight, and reproducibility checks documented below. A check that does not apply to an input is left out; a check that applies but cannot run is reported as `not-run`.

### Phase 4 preflight, processing, and provenance

Preflight validates a declared JSON plan before processing. Supported fields include `operation`, `target_crs`, explicit `reproject`, `resampling`, `categorical`, `combine`, declared `alignment`, `decode`, product `encoding`, `time_range`, `expect`, `measurement_units`, and explicit `unit_conversion`. `target_crs` alone never implies reprojection; `alignment:true` and unit conversion must be declared, and malformed or reversed STAC intervals do not pass.

```bash
python -m terraproof preflight input.tif --plan plan.json
python -m terraproof check output.tif --reference-input input_dn.tif --encoding s2-l2a --manifest run.manifest.json
python -m terraproof manifest write --inputs input.tif --outputs output.tif --params plan.json --out run.manifest.json
python -m terraproof manifest verify run.manifest.json
```

Manifest verification covers every contributing path: primary, compare, reference, QA, samples, and class-area files. `--require-provenance` makes an absent or failed manifest advisory; CLI and MCP use the same coverage and malformed-manifest behavior. Processing checks include exact-once scale application, cloud masking, temporal scope, SAR domain/geocoding, and area-adjusted accuracy. Optional router semantic retrieval is offline-only and falls back to lexical retrieval when its dependency/model is unavailable; candidate mode defaults to eight deterministic candidates for optional host-side selection.

### Evidence grades

| Grade | Arabic label | Meaning |
|---|---|---|
| Decision-grade | جاهز للقرار | Every check in the run passed. |
| Review required | يحتاج مراجعة | At least one check warned; none failed and none could not run. |
| Advisory only | استرشادي فقط | At least one check failed or could not run (`not-run`). A run with no checks is also Advisory only. |

Exit codes: `0` Decision-grade, `2` Review required, `3` Advisory only, `1` usage error or unreadable input.

The grade describes the data path and the checks that ran. It is not a certification of survey, engineering, legal, or safety fitness.

Arabic Markdown reports translate the labels, headings, status words, and the limitation sentence. Check messages, file paths, check ids, and numbers stay as produced (messages are in English).

---

## Skill router (Python)

`python -m terraproof route` is the Python skill router (Phase 3). Given a task description, it returns the few skill sections worth reading, each with the reasons for its score. It is offline, deterministic, and lexical; there is no model call. Setup is the same as [Python core](#python-core-phase-1-experimental); text-only routing is dependency-light, because the inspectors load only when you pass `--data`.

How it ranks:

- **BM25 over skill sections.** Every section of `SKILL.md` and the reference files is indexed. A skill's score is its best-matching section plus a quarter of its second best, so a skill ranks on the passage that matches, not on its length.
- **Exact triggers.** The technology and capability phrases in each `skill.json` add deterministic boosts when they occur as whole phrases. A bare `map` is deliberately weak.
- **Explained data-aware rules.** With `--data`, each local dataset is inspected first: CRS, bands, dtype, scale/offset, geometry types, feature counts, STAC collection. The profile then adds or subtracts score, and the reason is printed. A geographic CRS under metric wording (area, buffer, distance, metres) promotes `crs-and-units`; an integer band with a non-identity scale/offset promotes `satellite-preprocessing`; several rasters promote `raster-processing`; a raster-only input penalises vector skills, and a vector-only input penalises raster skills; a print-figure request penalises the web-map skill; a STAC item already in hand for processing penalises the catalog-search skill.
- **Arabic and Egyptian dialect.** Text is normalized before matching: diacritics and tatweel are dropped, NFKC is applied, and `أ/إ/آ/ٱ → ا`, `ى → ي`, `ة → ه`. Attached conjunctions, prepositions, and articles are tried (`ال`, `وال`, `بال`, `لل`, `ف`, `ب`, `ل`, `و`), and a curated lexicon maps Arabic phrases, including Egyptian forms such as `نزل` (download) and `دور على` (look for), to English retrieval terms. Latin technical tokens (`Sentinel-2`, `SCL`, `NDVI`) are matched as written, which is how these prompts are usually typed.
- **Process skills are separate.** `brainstorming`, `writing-plans`, `systematic-debugging`, and `verification` are never mixed into the ranked domain skills. The `process` field lists the ones whose wording appears in the task, followed by `verification`.

CLI usage:

```bash
python -m terraproof route "TASK" [--data PATH ...] [--top-k N] [--mode ranked|candidates] [--semantic] [--format json|md]
```

`--data` takes one or more local datasets and can be repeated; `--top-k` defaults to 5 and `--format` to `json`. `--format md` prints a readable digest of the same result, and JSON stays the stable machine-readable form. The command exits `0` and writes nothing.

English example:

```bash
python -m terraproof route "Mask clouds in Sentinel-2 L2A with the SCL band, then compute NDVI" --format json
```

The result is deterministic for a fixed registry and input. Each reason names the matched section, lexical contributions, and any exact triggers that fired.

Arabic example:

```bash
python -m terraproof route "اضبط scale و offset لصور Sentinel-2 L2A قبل حساب NDVI" --format md
```

It reports `Language: ar` and shows the normalized Arabic expansion and selected sections. Only your task line and matched Arabic terms are Arabic: reasons and section excerpts remain the English skill text, and JSON keeps your prompt verbatim.

Evaluate a routing set with the bundled evaluator:

It prints JSON with `items`, `top_k`, recall, per-language recall, `must_not` violations, and every failing item, and exits `1` when mean recall is below `--min-recall` or a forbidden skill is ranked. `evals/routing/dev.jsonl` is the permitted tuning/regression set; independent held-out sets are not part of routine development or this acceptance run. The evaluator measures retrieval only, not agent performance.

Limits: this is lexical retrieval with hand-written rules, not semantic understanding. Candidate mode returns a deterministic recall-oriented list (default cap 8) for optional host-side selection; ranked mode retains its existing cap and thresholds. Dataset rules fire once per request and only from the keys the inspectors report, so a misleading or missing profile leads to a misleading boost.

---

## MCP server

The MCP server exposes the same inspectors, checks, skill sections, and router to any Model Context Protocol client, so an agent gets identical results whether it calls the CLI or a tool. It is read-only: it never writes files and never uses the network.

```bash
python -m pip install -e ".[mcp]"    # Windows: .venv\Scripts\python -m pip install -e ".[mcp]"
python -m terraproof.mcp             # serve over stdio
```

The `mcp` extra installs the official MCP Python SDK 2.x (`mcp>=2.3,<3`); the base install stays dependency-light, and `inspect`, `check`, and `route` keep working without it. Register the server in your client with a stdio entry whose command is the interpreter that has the package installed and whose arguments are `-m terraproof.mcp`, or let [`python -m terraproof.install --with-mcp`](#install-into-your-agent) write that entry for you.

Six tools:

- `preflight(paths, plan, lang?)` — validate a declared plan (a JSON object or local JSON file path) against inspected inputs and return the evidence report without running processing.
- `inspect_dataset(path)` — profile one local vector, raster, or STAC Item file: CRS and units, schema or bands, dtype, nodata, extent, resolution, and feature or pixel counts.
- `run_checks(paths, operation?, compare_to?, resampling?, categorical?, expect?, lang?, ...)` — run checks and return the grade, exit code, JSON report, and Markdown in `en` or `ar`. Phase 4 parameters are `reference_input`, `encoding`, `qa_path`, `qa_kind`, `time_range`, `sar_expect`, `accuracy_samples`, `class_areas`, `min_per_class`, `estimates_requested`, `manifest`, and `require_provenance`; CLI flags use hyphens, with `--qa` for `qa_path`. Samples accept CSV/JSON file paths (or records through MCP); class areas accept a JSON file path (or a mapping through MCP).
- `list_skills()` — list the registered skills with their layer, one-sentence explanation, section ids and titles, and the check ids they bear on.
- `load_section(skill, section_id)` — return one section's Markdown text, without reading the whole `SKILL.md`.
- `find_guidance(task, data_paths?, top_k?, mode?, semantic?)` — retrieve skill sections and inspect the given datasets; `mode="candidates"` provides host-selectable candidates and `semantic=true` enables the optional cached local model. This is the retrieval `python -m terraproof route` performs.

---

## Install into your agent

The installer writes Terraproof into one project in that agent's own format, instead of a shared `.agents/` folder:

```bash
python -m terraproof.install --agent {claude,cursor,codex,gemini,copilot,opencode} --skills a,b --target DIR [--with-mcp] [--dry-run]
python -m terraproof.install --agent cursor --task "NDVI change for 2020-2024" --target DIR
```

Give either `--skills` (comma-separated names from `routing/registry.json`) or `--task` (routed by the Python router), never both. `--target` must already exist. `--with-mcp` also registers the Terraproof MCP server, and `--dry-run` prints the planned writes and changes nothing. The command exits `0` on success and `1` for a usage error such as an unknown skill name or a missing target.

What each agent gets (`<skill>` stands for one selected skill):

| `--agent` | Skill files | MCP config with `--with-mcp` |
|---|---|---|
| `claude` | `.claude/skills/<skill>/` — the full skill folder | `.mcp.json` (`mcpServers`) |
| `cursor` | `.cursor/rules/terraproof-<skill>.mdc` — one rule per skill | `.cursor/mcp.json` (`mcpServers`) |
| `codex` | `.agents/skills/<skill>/` plus a block in `AGENTS.md` | `.codex/config.toml` (`[mcp_servers.terraproof]`) |
| `gemini` | a block in `GEMINI.md` with the skill text inline | `.gemini/settings.json` (`mcpServers`) |
| `copilot` | `.github/instructions/terraproof-<skill>.instructions.md` | `.vscode/mcp.json` (`servers`) |
| `opencode` | a block in `AGENTS.md` with the skill text inline | `opencode.json` (`mcp`) |

Every format above was checked against that agent's own documentation; the source URL is cited next to the writer in `src/terraproof/install/agents.py`.

Merge and idempotency: nothing is written outside `--target`. An existing JSON or TOML config is parsed and merged, so other servers, keys, and tables survive, and only the `terraproof` server entry is replaced. Markdown goes between agent-scoped markers (`<!-- terraproof:<agent>:begin -->` and `<!-- terraproof:<agent>:end -->`); a rerun replaces only that agent's block and leaves the rest of the file alone. If a legacy unscoped `<!-- terraproof:begin -->` / `<!-- terraproof:end -->` block exists, the installer migrates it to the current agent's scoped marker and prints a note. A rerun with the same inputs produces identical bytes, unchanged files are reported as `unchanged` and not rewritten, and the recorded MCP command is the interpreter that ran the installer. Skill copies skip `UPSTREAM.md` and `skill.json`.

Known limits:

- **Claude Code** (2.1.292) reads the generated `.mcp.json` and lists `terraproof`, but project MCP servers start as "Pending approval"; an interactive `claude` session is required to approve the server before it connects.
- **Codex CLI** (0.160.1) parses the generated `.codex/config.toml`, but only loads project-scoped config for trusted projects. Verified by copying the same TOML into an isolated `CODEX_HOME`: `codex mcp list` / `codex mcp get terraproof` show the stdio server correctly.
- **Gemini CLI** (0.62.0) reads the generated `.gemini/settings.json` and reports `terraproof` as a configured stdio server, but `gemini mcp list` suppresses all servers (project and user-level) in an untrusted folder. Trusting the workspace is required to list, enable, or connect to the server.
- The other three agents (`cursor`, `copilot`, `opencode`) are unit-tested against their documented file layouts (`tests/python/test_install.py`); they have not been loaded by those agents here.
- Writing the files does not prove the host loaded them or that the agent followed the guidance. Verify an installed setup in the agent itself, as you would verify any agent-generated work.

---

## Skills (v0.2.0)

### Process & Verification
- `brainstorming` — Explore intent, requirements, and design options before implementation.
- `writing-plans` — Produce detailed, executable task-by-task engineering plans.
- `systematic-debugging` — Structured root-cause investigation for bugs and errors.
- `verification` — Validate completeness and truthfulness before declaring work done.

### Mapping & GIS
- `gdal` — Raster and vector CLI recipes: reprojection, clipping, mosaics, and COGs.
- `design-postgis-tables` — PostGIS table design, geometry vs geography, spatial indexing.
- `geoparquet-validation` — GeoParquet metadata validation and cloud-native vector distribution.
- `geospatial-frontend` — MapLibre GL and geospatial visualization interfaces.
- `crs-and-units` — Coordinate reference systems, axis order, datum transformations, and measurement units.
- `raster-processing` — Raster reading, grid alignment, resampling, nodata and masks, and COG delivery checks.

### Remote Sensing & Earth Observation
- `geomaster` — Earth observation, satellite processing, spectral indices, terrain, and spatial ML.
- `geospatial-data-discovery` — Open geospatial data acquisition (STAC, OSM, Overture, Sentinel, Landsat, DEMs).
- `geozarr` — Multidimensional geospatial raster and cube arrays.
- `satellite-preprocessing` — Sentinel-2 L2A and Landsat Collection 2 surface reflectance decoding, QA masks, and composites.
- `spectral-indices` — NDVI, NDWI/MNDWI, NBR/dNBR, EVI, and SAVI from calibrated, masked reflectance.

### Spatial Analysis & Visualization
- `geopandas` — Vector operations, spatial joins, geometric overlays, and CRS transforms.
- `vector-quality` — Geometry validity and repair, duplicate and coverage audits, and join cardinality checks.
- `scientific-visualization` — Publication-ready figures with colorblind-safe palettes and multi-panel layouts.
- `statistical-analysis` — Hypothesis testing, assumption diagnostics, effect sizes, and power analysis.
- `networkx` — Graph structures, centrality, community detection, and shortest paths.

---

## Preset Collections

| Collection | Description | Included Skills |
|---|---|---|
| `gis` | Geospatial engineering and mapping | `geomaster`, `geopandas`, `gdal`, `geospatial-data-discovery`, `verification` |
| `data-analysis` | Statistical modeling and scientific figures | `statistical-analysis`, `scientific-visualization`, `verification` |
| `production` | Core engineering discipline and debugging | `brainstorming`, `writing-plans`, `systematic-debugging`, `verification` |
| `remote-sensing` | Optical satellite preprocessing, spectral indices, raster processing, and verification | `geospatial-data-discovery`, `satellite-preprocessing`, `spectral-indices`, `raster-processing`, `verification` |

---

## Repository Overview

- **`skills/`** — Task-specific instructions, scripts, and references (24 skills, each with a `skill.json` routing manifest).
- **`routing/`** — Skill registry generated from `skills/*/skill.json`, check catalog, scoring rules, and preset collections.
- **`router/`** — Deterministic TypeScript routing engine with CLI and programmatic API.
- **`evals/`** — 27 executable benchmark task specifications plus the deterministic harness and permitted routing regression set `evals/routing/dev.jsonl`, scored by `python -m terraproof.router.evaluate`.
- **`src/terraproof/`** — Python package: dataset inspectors, checks, evidence reports, the skill router and its evaluator, the read-only MCP server, and the native agent installers (`pyproject.toml`).
- **`instructions/`** — Universal engineering rules (engineering discipline, simplicity, security).
- **`tests/`** — Router test suites (73 scenarios), Python tests for the checks, router, MCP server, evals, and installers (`tests/python/`), and upstream fixtures.
- **`third_party/`** — Upstream licenses and notices for vendored material.
- **`sources/`** — Attribution log mapping each skill to its upstream source, commit SHA, and license.

---

## License

This project is licensed under the [MIT License](LICENSE). Vendored and adapted components keep their upstream licenses (MIT, Apache-2.0, 3-clause BSD) as documented in `third_party/` and `sources/SOURCES.md`.
