# Terraproof

> evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents. *By Geova.*

> **Status:** Experimental — refocusing from AgentLayer v0.1

Terraproof is a focused collection of mapping and remote-sensing skills for AI coding agents, plus a deterministic router that selects the smallest useful set of them for a task. The direction is to make geospatial agents prove their work: inspect real datasets, apply section-level expert guidance, run executable checks, and attach an evidence grade to each result. Read the full plan in [`Terraproof_v1_PLAN.md`](Terraproof_v1_PLAN.md).

**Today:** 15 skills, a router with 28 test scenarios, and an experimental Python core for dataset inspection, checks, and evidence grades (see [Python core](#python-core-phase-1-experimental)).
**Planned, not implemented yet:** MCP server, sectioned skills, and a Python router.

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

**Expected result:** `--version` prints `terraproof v0.2.0`, and `validate` ends with `✓ Registry validation passed: 15 skills, 3 collections.` The route prints the task, a confidence score (75% for this prompt), the selected skill count (4), and the skills grouped by layer with a score and rationale: `geomaster`, `geospatial-data-discovery`, `geospatial-frontend`, and `verification`. Dry-run output also lists dropped candidates. It does not create files or call a model.

The walkthrough is illustrative, not a recorded execution. Exact selections and scores depend on the prompt, overrides, and registry revision. The commands that run offline were checked against this checkout. The download, NDVI, and MapLibre steps need network access and data, so they are illustrative only.

### Practical example: Sentinel-2 NDVI change map

The task needs satellite imagery, a spectral index, and a web map. First inspect the route above. If the recommendation misses a requirement, revise the prompt or use overrides.

Bundle the selected skills into one reviewable context file. The `--include` flags force the four registered skills:

```bash
node router/index.ts bundle "Download Sentinel-2 imagery from a STAC catalog, compute NDVI, and map the change with MapLibre" --include geospatial-data-discovery --include geomaster --include geospatial-frontend --include verification --out ndvi-context.md
```

**Expected artifact:** `ndvi-context.md` in the current directory. The CLI prints `✓ Composed bundle written to: ndvi-context.md (4 skills, <N> bytes)`; the size in this checkout was 27113 bytes. The file starts with a header listing the task, the four skills, and their layers, then the universal engineering instructions and the skill text grouped by layer. Review it, then give it to your coding agent together with your project requirements. The file is instructions, not generated application code.

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

The Python package `terraproof` inspects geospatial datasets, runs deterministic checks, and writes an evidence report as JSON or Markdown (English or Arabic). It reads local files only and makes no network calls. It is not yet a port of the router and it has no MCP server. The `terraproof` npm command above is still the TypeScript router; the Python core runs as `python -m terraproof`.

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

Checks cover CRS and units (`crs.defined`, `crs.consistent`, `crs.metric_operation`), geometry (`geometry.valid`, `geometry.non_empty`, `geometry.type_consistent`), record counts (`scope.record_count`), raster integrity (`raster.nodata_declared`, `raster.resampling`, `raster.grid_alignment`, `raster.cog_layout`), remote-sensing value ranges (`rs.reflectance_range`, `rs.index_range`), and STAC provenance (`stac.provenance`). A check that does not apply to an input is left out; a check that applies but cannot run is reported as `not-run`.

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

### Remote Sensing & Earth Observation
- `geomaster` — Earth observation, satellite processing, spectral indices, terrain, and spatial ML.
- `geospatial-data-discovery` — Open geospatial data acquisition (STAC, OSM, Overture, Sentinel, Landsat, DEMs).
- `geozarr` — Multidimensional geospatial raster and cube arrays.

### Spatial Analysis & Visualization
- `geopandas` — Vector operations, spatial joins, geometric overlays, and CRS transforms.
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

---

## Repository Overview

- **`skills/`** — Task-specific instructions, scripts, and references (15 skills).
- **`routing/`** — Declarative skill registry, scoring rules, and preset collections.
- **`router/`** — Deterministic routing engine with CLI and programmatic API.
- **`src/terraproof/`** — Experimental Python core: dataset inspectors, checks, and evidence reports (`pyproject.toml`).
- **`instructions/`** — Universal engineering rules (engineering discipline, simplicity, security).
- **`tests/`** — Router test suites (28 scenarios, 100% pass rate) and upstream fixtures.
- **`third_party/`** — Upstream licenses and notices for vendored material.
- **`sources/`** — Attribution log mapping each skill to its upstream source, commit SHA, and license.

---

## License

This project is licensed under the [MIT License](LICENSE). Vendored and adapted components keep their upstream licenses (MIT, Apache-2.0, 3-clause BSD) as documented in `third_party/` and `sources/SOURCES.md`.
