# Terraproof

> evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents. *By Geova.*

> **Status:** Experimental — refocusing from AgentLayer v0.1

Terraproof is a focused collection of mapping and remote-sensing skills for AI coding agents, plus a deterministic router that selects the smallest useful set of them for a task. The direction is to make geospatial agents prove their work: inspect real datasets, apply section-level expert guidance, run executable checks, and attach an evidence grade to each result. Read the full plan in [`Terraproof_v1_PLAN.md`](Terraproof_v1_PLAN.md).

**Today:** 15 skills, a router with 28 test scenarios, and an experimental Python core for dataset inspection, checks, and evidence grades (see [Python core](#python-core-phase-1-experimental)).
**Planned, not implemented yet:** MCP server, sectioned skills, and a Python router.

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
