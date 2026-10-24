# Terraproof — v1 Transformation Plan

> **Terraproof** — evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents. *By Geova.*
>
> Status: **proposal** — nothing in this document is implemented yet. It replaces the general-purpose AgentLayer direction with a focused geospatial one.

---

## 1. Why change

AgentLayer v0.1 is a curated set of 29 markdown skills plus a keyword router. Hands-on use shows the output is basic:

| Observed problem | Evidence in the current repo |
|---|---|
| Skills mostly restate what frontier models already know | 23 of 29 skills are prose only; only 6 ship scripts |
| The router reads only the prompt, never the data or project | `router/classify.ts` matches English regexes against the task text |
| Routing is fragile and tuned to its own tests | "Draw a line chart" selects `geopandas`; Arabic prompts miss most signals; phrases such as `map assistant` exist only to pass scenarios |
| Too much context, not the relevant part | `react-best-practices` is 239 KB / 77 files; `bundle` pastes whole skills |
| Nothing proves a skill improves results | 64 tests check *which* skills are picked, none check output quality |
| The published package does not run | `npx agentlayer` fails with `ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING` (TypeScript shipped into `node_modules`) |
| Scope is too broad to be best-in-class anywhere | React, Supabase, AI SDK, API, stats, and GIS skills share one registry |

The name is also already in use elsewhere.

---

## 2. Vision

Geospatial work fails silently. Code that buffers in degrees, joins layers in different CRSs, drops nulls, resamples a land-cover raster bilinearly, or forgets the Sentinel-2 reflectance offset still runs, still draws a map, and is still wrong. Today's coding agents write that code and declare success.

**Terraproof makes mapping and remote-sensing agents prove their work.**

It gives any coding agent:

1. **Data awareness** — it inspects the real datasets (CRS, extent, schema, bands, nodata, dtype, resolution, STAC metadata) instead of guessing.
2. **Focused expert knowledge** — section-level geospatial and remote-sensing guidance, only the part the task needs.
3. **Executable checks** — deterministic validators for CRS/units, geometry, topology, raster integrity, and remote-sensing preprocessing.
4. **An evidence grade on every result** — adapted from Geova AI's evidence labels:

| Grade | Meaning |
|---|---|
| **Decision-grade** | Complete inputs, all required checks passed, provenance recorded |
| **Review required** | Computation is exact, but a warning, excluded records, stale data, or an assumption needs a person |
| **Advisory only** | Uses estimates, samples, incomplete data, or a required check could not run or failed |

A grade describes the data path. It never replaces professional review; Terraproof does not certify survey, engineering, legal, or safety outcomes.

### Positioning

- **Not a web app.** A local, open-source assistive tool: CLI, Python library, and MCP server that plug into the agents people already use (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, QGIS users with Python).
- **Not another prompt collection.** Skills are paired with tools and checks, and their value is measured.
- **Offline and deterministic by default.** Network access only for explicit data discovery (STAC, OSM) and only when the user asks.

---

## 3. Design principles

1. **Evidence before claims** — no result is presented as correct without the checks that support it.
2. **Inspect data, don't assume** — CRS, units, nodata, scale/offset come from metadata, not from the model's memory.
3. **Smallest useful context** — retrieve sections, not whole skills, within a token budget.
4. **Deterministic core** — identical inputs produce identical routing, checks, and grades.
5. **Provenance always** — every output records sources, STAC item IDs, tool versions, and parameters so it can be re-run.
6. **Measured value** — a skill or check stays only if benchmarks show it helps.
7. **Upstream respect** — every adapted file keeps its license and attribution (`sources/SOURCES.md`, `third_party/`).
8. **Bilingual from day one** — English and Arabic prompts and reports.

---

## 4. Architecture

The geospatial ecosystem (GDAL, rasterio, pyproj, shapely, GeoPandas, xarray, pystac) is Python, and the checks must call it directly. Terraproof therefore becomes a **Python-first** project. Skills stay plain markdown so any agent can read them.

```text
terraproof/
├── skills/                    # sectioned SKILL.md files with manifest frontmatter
├── src/terraproof/
│   ├── inspect/               # dataset inspectors: vector, raster, STAC, GeoParquet, Zarr, GPKG, DXF
│   ├── checks/                # deterministic validators (see §6)
│   ├── evidence/              # grade engine + report (JSON, Markdown, Arabic/English)
│   ├── router/                # retrieval router: BM25 over sections + metadata rules
│   ├── provenance/            # run manifests: inputs, STAC IDs, versions, parameters
│   ├── adapters/              # native output for each agent
│   ├── mcp/                   # MCP server exposing the tools below
│   └── cli.py
├── evals/                     # benchmark tasks, small fixture datasets, graders
├── instructions/              # universal geospatial engineering rules
├── sources/  third_party/     # attribution and licenses (kept)
└── tests/
```

Installed as `pip install terraproof` (extras: `[raster]`, `[rs]`, `[ml]`). An optional thin `npx terraproof` launcher can come later; the current TypeScript router is retired once the Python router reaches parity.

### MCP tools (what the agent calls while working)

| Tool | Purpose |
|---|---|
| `inspect_dataset(path_or_url)` | CRS, units, extent, schema/bands, nodata, dtype, resolution, feature/pixel counts, scale/offset, STAC properties |
| `find_guidance(task, datasets?)` | Ranked skill sections for the task, informed by the inspected data |
| `load_section(skill, section)` | Load one section on demand |
| `preflight(plan, datasets)` | Catch errors before running: CRS mismatch, buffer in degrees, categorical raster with bilinear resampling |
| `run_checks(outputs, profile)` | Execute the relevant validators on results |
| `evidence_report(run)` | Produce the grade and a human-readable report |
| `stac_search(...)` | Explicit, user-requested data discovery with provenance capture |

### CLI

```bash
terraproof inspect data/parcels.gpkg
terraproof route "Compute NDVI change for 2020-2024 over this AOI" --data aoi.geojson
terraproof check outputs/ --profile vector-analysis
terraproof report run.json --lang ar
terraproof install --agent claude|codex|cursor|copilot|gemini|opencode
terraproof mcp
```

---

## 5. Skill catalog v1

Skills are rewritten into **sections** (each independently retrievable) and each declares its checks.

### Keep and restructure (from the current repo)
`gdal`, `geopandas`, `geoparquet-validation`, `geozarr`, `design-postgis-tables`, `geospatial-data-discovery`, `geospatial-frontend`; `geomaster` is split into the focused skills below. Process skills `verification`, `systematic-debugging`, `writing-plans` stay as the universal layer.

### New core skills
| Area | Skill | Key content and checks |
|---|---|---|
| Foundations | `crs-and-units` | Choosing projected CRS for metric operations, datum transformations, EPSG lookup, antimeridian; checks: geographic CRS used for distance/area/buffer |
| Vector | `vector-quality` | Validity, `make_valid`, topology (gaps/overlaps), duplicate geometries, mixed types |
| Raster | `raster-processing` | rasterio/rioxarray, alignment, resampling choice by data type, nodata, COG + overviews |
| Remote sensing | `satellite-preprocessing` | Cloud/shadow masks (SCL, QA_PIXEL), scale/offset (Sentinel-2 L2A `BOA_ADD_OFFSET` from baseline 04.00; Landsat C2 L2 scale `0.0000275`, offset `-0.2`), harmonization |
| Remote sensing | `spectral-indices` | NDVI/NDWI/NBR/etc., valid ranges, band mapping per sensor |
| Remote sensing | `time-series-and-change` | xarray/odc-stac cubes, compositing, change detection, seasonality |
| Remote sensing | `sar-basics` | Sentinel-1 GRD, calibration, speckle, terrain correction |
| Remote sensing | `accuracy-assessment` | Sampling design, confusion matrix, area-adjusted accuracy and estimates |
| Remote sensing | `geoai-segmentation` | TorchGeo-style training/inference on imagery, tiling, leakage between tiles |
| Terrain | `terrain-analysis` | DEM sources, slope/aspect/hillshade, vertical datums, profiles |
| 3D | `point-clouds` | PDAL pipelines, classification, DTM/DSM |
| Cloud-native | `stac-and-cloud-access` | STAC search, signed URLs, lazy reads, provenance capture |
| Delivery | `vector-tiles-and-web` | PMTiles, tippecanoe, MapLibre styling |
| Delivery | `cartography-and-export` | Map layout, legends, scale bars, print/PDF export |
| Field/CAD (Geova DNA) | `field-data-exchange` | GeoPackage, SHP, DXF, KML/KMZ, GDB round-trips; what each format loses |
| Desktop | `pyqgis` | Processing algorithms, headless QGIS |
| Open data | `osm-and-overture` | Overpass, Overture, licensing (ODbL) |

### Move out of the core
`react-best-practices`, `frontend-design`, `supabase`, `supabase-postgres-best-practices`, `ai-sdk`, `api-*`, testing skills, `security-review`, data-science skills. Options: drop, or keep as an optional `extras` pack. **Decision needed** (§10).

---

## 6. Check catalog v1 (the heart of Terraproof)

Each check returns `pass | warn | fail | not-run`, with evidence. The grade engine maps results to a grade per profile.

| Family | Example checks |
|---|---|
| CRS & units | CRS defined; all inputs share a CRS or are explicitly transformed; metric operation in geographic CRS → fail; area/length units reported |
| Geometry | Valid, non-empty, expected type, no unintended multipart, winding for GeoJSON |
| Topology | Coverage gaps/overlaps, self-intersections, slivers |
| Scope & completeness | Input vs output record counts; rows dropped by nulls/joins reported; AOI clip extent; filter applied as stated |
| Raster integrity | nodata declared and honored; dtype overflow; grid alignment; resampling method suits data type; valid COG with overviews |
| Remote sensing | Cloud mask applied; scale/offset applied once; index values in physical range; acquisition dates within request; processing level matches claim |
| Provenance | STAC item IDs, data licenses, tool versions, parameters recorded |
| Positional accuracy | Accuracy statement present; GNSS phone data flagged as non-survey-grade |

Where possible, checks are also expressed as static patterns (e.g. ast-grep/Semgrep rules that flag `.buffer()` on an unprojected GeoDataFrame) so problems are caught in code before execution.

---

## 7. Evaluation harness (proof of value)

- **Benchmark tasks:** 50 → 200 realistic mapping and remote-sensing tasks with small fixture datasets and known correct answers (e.g. "area of parcels within 500 m of the river", "NDVI median composite for June", "reproject DEM and compute slope").
- **Runs:** each task with and without Terraproof, across several agents/models.
- **Graders:** numeric tolerance against ground truth, Terraproof checks, and reviewer rubric for reports.
- **Metrics:** task correctness, silent-error rate (wrong but confident), **skill lift** per skill, tokens per task, router recall@5 on a held-out prompt set (English + Arabic).
- **Rule:** a skill or check without measurable lift is revised or removed. Results are published in the repo.

---

## 8. Roadmap

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Rename & foundation** (1–2 wks) | Rename to Terraproof; fix packaging so the installed CLI runs; strict CLI argument validation; fix SKILL.md `name` mismatches (`verification`, `react-best-practices`); CI job that packs, installs, and runs the package | Installed package runs on Windows/macOS/Linux in CI; `npm run test:router` and `python tests/validate_repo.py` pass |
| **1 — Inspect & check core** (3–4 wks) | Python package; `inspect` for vector/raster/STAC; CRS/units, geometry, scope, raster checks; evidence grade + JSON/Markdown report | Checks catch every seeded error in a fixture suite; reports in English and Arabic |
| **2 — Skills v1** (4 wks) | Sectioned rewrite of kept skills; new core skills from §5; manifest frontmatter; registry generated from frontmatter | Every skill has sections, declared checks, and at least 3 benchmark tasks |
| **3 — Router & delivery** (3 wks) | Python retrieval router using inspected data; MCP server; native install for each agent | Recall@5 ≥ 90% on held-out EN/AR prompts; MCP verified in at least 3 agents |
| **4 — Remote sensing depth** (4 wks) | Preprocessing, indices, time series, SAR, accuracy checks; provenance manifests; preflight | RS benchmark tasks show positive lift; runs reproducible from manifests |
| **5 — Evaluation & release** (3–4 wks) | Full harness, published results, docs, v1.0 release | Public benchmark report; each certified skill shows measured lift |
| **6 — Ecosystem** (ongoing) | Skill/check contribution guide, import of compatible upstream skills with license gates, QGIS integration | External contributions merged with evals |

Durations are estimates for planning, not commitments.

---

## 9. Rename checklist (Phase 0)

- Claim on the same day: GitHub org `terraproof`, PyPI `terraproof`, npm `terraproof`, domain `terraproof.dev` (all were unclaimed on 2026-10-21; `.com` is taken).
- Run a trademark search (WIPO Global Brand Database, USPTO) before public launch; registry availability is not trademark clearance.
- Update `package.json`, `README.md`, `CHANGELOG.md`, CLI banner/help, `bin/`, CI workflow name, manifest text written by `apply`.
- Keep all `third_party/` licenses and `sources/SOURCES.md` entries unchanged.
- Update `AGENTS.md` rules 11–17 to the new router and evaluation model once Phase 3 lands.
- Add "by Geova" endorsement in README only, keeping the Geova commercial brand separate from the project name.

---

## 10. Decisions needed from the maintainer

1. **Non-geospatial skills:** drop them, or keep as an optional `extras` pack?
2. **Language:** confirm Python-first core (recommended) and retiring the TypeScript router after parity.
3. **License:** keep MIT for Terraproof's own code (recommended) — confirm.
4. **Geova endorsement:** README-level "by Geova" only, or a GitHub org under the Geova name?
5. **Network policy:** allow optional STAC/OSM discovery tools in the default install, or behind an extra?

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Heavy native dependencies (GDAL) hurt installation | Core checks use pure-wheel packages (pyproj, shapely, rasterio wheels); heavy tools are optional extras |
| False confidence from a "Decision-grade" label | Grades describe the data path only; reports list every check and assumption; professional-review disclaimer |
| Scope creep across all of GIS | Phase exit criteria; skills require benchmark tasks before merge |
| Upstream license conflicts on imported skills | License gate at import; attribution files mandatory |
| Benchmark overfitting | Held-out task and prompt sets never used for tuning |
