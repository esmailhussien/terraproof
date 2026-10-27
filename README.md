# Terraproof

> Evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents. *By Geova.*

[![npm](https://img.shields.io/npm/v/terraproof)](https://www.npmjs.com/package/terraproof) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Terraproof helps AI coding agents do geospatial work they can prove. It gives an agent three things:

- **Skills.** 24 focused guides (GDAL, CRS and units, satellite preprocessing, SAR, spectral indices, time series, accuracy assessment, and more), split into sections an agent can load one at a time.
- **A router.** It picks the smallest useful set of skills for a task, in English or Arabic, and explains why.
- **Checks with an evidence grade.** They inspect the real datasets an agent produced (CRS, nodata, value ranges, geometry, COG layout, provenance) and grade the result as decision-grade, review required, or advisory only.

Everything runs locally and offline. No model API key is needed.

**Status:** experimental (v0.8.0). See [Evaluation status](#evaluation-status) for what has and has not been measured.

---

## Quick start

Route a task with the published CLI (Node.js 20+):

```bash
npx terraproof route "Reproject a GeoTIFF to EPSG:3857 and build a COG with GDAL"
npx terraproof route "Download Sentinel-2 from a STAC catalog, compute NDVI, and map the change with MapLibre" --format json
```

Then check the data the work produced with the Python package (Python 3.10+). From the first PyPI release (0.8.0) it installs with `pip`:

```bash
pip install "terraproof[mcp]"
```

Until then, install it from a clone:

```bash
git clone https://github.com/esmailhussien/terraproof.git
cd terraproof
python -m venv .venv
.venv/bin/python -m pip install -e ".[mcp]"      # Windows: .venv\Scripts\python -m pip install -e ".[mcp]"

python -m terraproof check ndvi.tif --expect index --format md
python -m terraproof check outputs/clip.gpkg --compare-to data/parcels.gpkg --format md --lang ar --out report_ar.md
```

The exit code is the grade: `0` decision-grade, `2` review required, `3` advisory only, `1` usage error.

---

## Python checks

`python -m terraproof` reads local vector, raster and STAC Item files and makes no network calls.

| Command | What it does |
|---|---|
| `inspect PATH` | Profile one dataset: CRS and units, schema or bands, dtype, nodata, extent, counts. |
| `check PATHS` | Run the applicable checks and write a JSON or Markdown evidence report (English or Arabic). |
| `preflight PATHS --plan plan.json` | Check a declared processing plan against the real inputs before running it. |
| `manifest write` / `manifest verify` | Record and verify a deterministic run manifest (inputs, outputs, parameters). |
| `route "TASK" [--data PATH]` | Retrieve the skill sections worth reading, using the task text and inspected datasets. |

Checks cover CRS and units, geometry validity and GeoJSON winding, record counts, raster nodata, resampling, grid alignment and COG layout, reflectance and index ranges, scale/offset applied once, cloud masking, temporal scope, SAR domain, area-adjusted accuracy, and STAC provenance. A check that does not apply is left out; one that applies but cannot run is reported as `not-run`.

| Grade | Arabic label | Meaning |
|---|---|---|
| Decision-grade | جاهز للقرار | Every check that ran passed. |
| Review required | يحتاج مراجعة | At least one check warned; none failed or could not run. |
| Advisory only | استرشادي فقط | At least one check failed or could not run, or no check ran. |

The grade describes the data path and the checks that ran. It is not a certification of survey, engineering, legal, or safety fitness.

### Verify NDVI against its source bands

```bash
python -m terraproof check outputs/ndvi.tif --index-formula ndvi --nir inputs/nir.tif --red inputs/red.tif
```

This opt-in check compares every output cell with `(NIR-red)/(NIR+red)`, using each
raster's own scale/offset metadata. Supply single-band rasters on the same grid;
source-band roles and calibration must be declared correctly. Missing source data
and a zero denominator cannot become valid output values. Extra output masking
warns because its QA policy is not verified here. Source files are included in the
evidence report and must be covered when a provenance manifest is supplied.
See [the full contract and limits](docs/INDEX_FORMULA.md).

### Verify slope and lossless raster delivery

```bash
python -m terraproof check outputs/result.tif --dem inputs/elevation.tif --slope-method central-difference
python -m terraproof check outputs/delivery.tif --compare-to inputs/analysis.tif --raster-identity
```

The explicit slope method checks all required values, flat cells, stencil masks
and nodata edges. Raster identity checks every band's valid samples, complete
validity masks and grid/band metadata against the declared source. Full COG
conformance remains separate from this data comparison and the existing layout
screen. See [supported contracts and limits](docs/RASTER_CONTRACTS.md).
For final calibration/QA audits, `--processing-full-scan` checks every corresponding
band and pixel in bounded windows; see [scope, examples and measured controls](docs/PROCESSING_FULL_SCAN.md).


---

## Use it from your agent

### MCP server

```bash
python -m terraproof.mcp      # stdio server; needs the `mcp` extra
```

It is read-only and offline, with six tools: `preflight`, `inspect_dataset`, `run_checks`, `list_skills`, `load_section`, and `find_guidance`. CLI and MCP return the same reports.

### Install into a project

```bash
python -m terraproof.install --agent claude --task "NDVI change for 2020-2024" --target DIR --with-mcp
python -m terraproof.install --agent cursor --skills gdal,crs-and-units --target DIR --dry-run
```

| `--agent` | Skills are written to | MCP config (`--with-mcp`) |
|---|---|---|
| `antigravity` | `.agents/skills/<skill>/` and `AGENTS.md` | `.agents/mcp_config.json` |
| `claude` | `.claude/skills/<skill>/` | `.mcp.json` |
| `codex` | `.agents/skills/<skill>/` and `AGENTS.md` | `.codex/config.toml` |
| `cursor` | `.cursor/rules/terraproof-<skill>.mdc` | `.cursor/mcp.json` |
| `gemini` | `GEMINI.md` | `.gemini/settings.json` |
| `copilot` | `.github/instructions/terraproof-<skill>.instructions.md` | `.vscode/mcp.json` |
| `opencode` | `AGENTS.md` | `opencode.json` |

The installer only writes inside `--target`, merges existing configs, and is idempotent. Some hosts need you to approve or trust the project before its MCP server connects (Claude Code shows it as "Pending approval"; Codex and Gemini load project config only in trusted folders). Writing the files does not prove the agent loaded or followed them.

### Route and export with the Node CLI

```bash
npx terraproof route "Design a PostGIS schema for GPS tracks" --collection gis --dry-run
npx terraproof bundle "TASK" --out context.md                       # one reviewable context file
npx terraproof apply "TASK" --target ./demo/.agents/skills --dry-run   # export skill folders
npx terraproof validate
```

`apply` and `bundle --out` overwrite files without asking, so start in a disposable folder. Routing is deterministic keyword and section scoring, not semantic understanding; review the selection before you use it. Details: [`router/README.md`](router/README.md) and [`routing/ROUTER_DESIGN.md`](routing/ROUTER_DESIGN.md).

---

## Skills

| Area | Skills |
|---|---|
| Process | `brainstorming`, `writing-plans`, `systematic-debugging`, `verification` |
| Mapping and GIS | `gdal`, `crs-and-units`, `raster-processing`, `vector-quality`, `geopandas`, `design-postgis-tables`, `geoparquet-validation`, `geospatial-frontend`, `networkx` |
| Remote sensing | `satellite-preprocessing`, `spectral-indices`, `sar-basics`, `time-series-and-change`, `accuracy-assessment`, `geomaster`, `geozarr` |
| Data access | `geospatial-data-discovery`, `stac-and-cloud-access` |
| Analysis and figures | `statistical-analysis`, `scientific-visualization` |

Skills are **unmeasured**: no study has separated their effect from the MCP checks, and in the Phase 5 Claude Code runs no skill file was read. Their content is frozen during Phase 6 (factual fixes only, no new skills) until the skills decision in the [Phase 6 plan](docs/plans/Terraproof_Phase6_PLAN.md).

Each skill lives in `skills/<name>/` with a `SKILL.md`, references, and a `skill.json` routing manifest. Preset collections (`gis`, `remote-sensing`, `data-analysis`, `production`) are in [`routing/collections.json`](routing/collections.json).

---

## Evaluation status

- **Checks:** 33 executable eval tasks with independent oracles pass with 0 false passes. The benchmark runs from a clone; the Python package does not include it. Of 50 seeded wrong outputs, production checks reject 25; the other 25 are caught only by the independent oracle (declared blind spots). Passing the benchmark does not mean the production checks catch every wrong output. See [`evals/README.md`](evals/README.md).
- **Routing:** an independent, frozen 160-item set (v5) passed once in both languages: English recall 0.97 with 3.75 wrong picks per 100, Arabic recall 0.96 with 2.5. Earlier independent sets (v3, v4) failed and stay on record. The v5 set was written by an AI agent, not reviewed by an expert.
- **Agent lift:** in a 54-run Claude Code comparison on 9 tasks, runs with Terraproof passed 27/27 and runs without it 21/27. The pre-specified test is **not significant** (p = 0.125), and five tasks passed either way, so no lift is claimed. The clearest single result is Landsat QA masking (3/3 with, 0/3 without). See [`docs/plans/Terraproof_Phase5_PLAN.md`](docs/plans/Terraproof_Phase5_PLAN.md).
- **Harder cohort:** a one-repeat Claude Code screen passed all six tasks both with and without Terraproof. That small screen shows no observed benefit and is separate from the original nine-task study. API pilots are exploratory and do not establish lift.
- **Real hosts:** tool use through MCP has been verified with Codex, Claude Code and Antigravity (Gemini). OpenCode's install format passes a no-model check with the real CLI, but no real tool call has been recorded yet. Cursor and Copilot are unit-tested against their documented layouts only.

---

## Repository

| Path | Contents |
|---|---|
| `skills/` | The 24 skills |
| `routing/` | Generated skill registry, check catalog, rules, and collections |
| `router/` | TypeScript router and CLI (the npm package) |
| `src/terraproof/` | Python package: inspectors, checks, reports, router, MCP server, installers, evals |
| `evals/` | Eval task specs and routing sets |
| `tests/` | Router, Python, package, and release-validation tests |
| `instructions/` | Universal engineering rules shipped with the skills |
| `docs/` | [Release checklist](docs/RELEASE_CHECKLIST.md) and [design plans](docs/plans/) |
| `sources/`, `third_party/` | Upstream attribution and licenses |

To contribute, see [`CONTRIBUTING.md`](CONTRIBUTING.md). Changes are listed in [`CHANGELOG.md`](CHANGELOG.md).

## License

[MIT](LICENSE). Vendored and adapted components keep their upstream licenses (MIT, Apache-2.0, 3-clause BSD), documented in `third_party/` and [`sources/SOURCES.md`](sources/SOURCES.md).
