# Curated Sources & Attribution Registry

This file tracks upstream repositories, specifications, and references evaluated during the curation of AgentLayer (now being refocused as Terraproof; see the removals in `## Removed in 0.2.0` below).

---

## Sources

| Source | Area | Status |
|---|---|---|
| Agent Skills specification | Skill format | Research |
| Terraproof Native | CRS/units, vector quality, raster processing, satellite preprocessing, spectral indices | Authored for Terraproof by Geova, MIT; no upstream source: [crs-and-units](../skills/crs-and-units/SKILL.md), [vector-quality](../skills/vector-quality/SKILL.md), [raster-processing](../skills/raster-processing/SKILL.md), [satellite-preprocessing](../skills/satellite-preprocessing/SKILL.md), [spectral-indices](../skills/spectral-indices/SKILL.md). Primary references are documented in each skill; no upstream material is vendored. |
| Terraproof Native (Phase 4) | Time series and change, SAR basics, accuracy assessment, STAC and cloud access | Authored for Terraproof by Geova, MIT; no upstream source: [time-series-and-change](../skills/time-series-and-change/SKILL.md), [sar-basics](../skills/sar-basics/SKILL.md), [accuracy-assessment](../skills/accuracy-assessment/SKILL.md), [stac-and-cloud-access](../skills/stac-and-cloud-access/SKILL.md). Primary references (ESA Sentinel-1 documentation, STAC specifications, GDAL and library documentation, peer-reviewed methods papers) are cited in each skill's `## Sources`; no upstream material is vendored. |
| [obra/superpowers](https://github.com/obra/superpowers) | Planning, debugging, verification | Imported (`systematic-debugging`, `verification` (upstream name `verification-before-completion`), `brainstorming`, `writing-plans`) |
| [arjunprabhulal/agent-skills](https://github.com/arjunprabhulal/agent-skills) | Quality Assurance, Testing, TDD | Imported then removed in 0.2.0 (off-scope): `unit-testing`, `integration-testing`, `browser-testing`, `test-driven-development` |
| [vercel-labs/open-agents](https://github.com/vercel-labs/open-agents) | Frontend Design & UI Quality | Imported then removed in 0.2.0 (off-scope): `frontend-design` |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | React & Next.js Performance | Imported then removed in 0.2.0 (off-scope): `react-best-practices` |
| [mblode/agent-skills](https://github.com/mblode/agent-skills) | Codebase Architecture & Wayfinding | Imported then removed in 0.2.0 (off-scope): `codebase-architecture` |
| [supabase/agent-skills](https://github.com/supabase/agent-skills) | Database, Postgres, Supabase Platform | Imported then removed in 0.2.0 (off-scope): `supabase`, `supabase-postgres-best-practices` |
| [github/awesome-copilot](https://github.com/github/awesome-copilot) | Codebase Security Review & Vulnerability Audit | Imported then removed in 0.2.0 (off-scope): `security-review` |
| [isaaccorley/geospatial-skills](https://github.com/isaaccorley/geospatial-skills) | GIS, GDAL, GeoParquet, GeoZarr, MapLibre | Imported (`gdal`, `geoparquet-validation`, `geozarr`, `geospatial-frontend`) |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | Geospatial, Data Science, Statistics, Viz, Graphs | Imported (`geopandas`, `geomaster`, `statistical-analysis`, `scientific-visualization`, `networkx`); `exploratory-data-analysis` imported then removed in 0.2.0 (off-scope) |
| [timescale/pg-aiguide](https://github.com/timescale/pg-aiguide) | Spatial Database Design (PostGIS) | Imported (`design-postgis-tables`) |
| [jaakla/open-gis](https://github.com/jaakla/open-gis) | Open GIS Reference Stack | Rejected — license (no upstream license declared) |
| [JPeetz/agent-skills](https://github.com/JPeetz/agent-skills) | General Data Analysis | Rejected — overlap (K-Dense EDA/statistics/viz provide modular coverage) |
| [public-apis/public-apis](https://github.com/public-apis/public-apis) | Public & Free API Catalog Index | Research catalog reference for `api-discovery` (removed in 0.2.0) |
| AgentLayer Native | Public APIs & Open Data Orchestration | Created (`geospatial-data-discovery`); `api-discovery` and `api-integration` created, then removed in 0.2.0 (off-scope) |
| [vercel/ai](https://github.com/vercel/ai) | AI SDK (Chat, streaming, structured output, agents, tools, RAG) | Imported then removed in 0.2.0 (off-scope): `ai-sdk` |
| [openai/skills](https://github.com/openai/skills) | OpenAI Developer Docs & Codex manual | Research reference — not imported due to runtime/MCP tool coupling |
| [openai/plugins](https://github.com/openai/plugins) | Cloudflare Agents SDK & Integrations | Research reference — evaluated for agentic patterns |

---

## Imported Material Details

### systematic-debugging

- **Source Repository:** `https://github.com/obra/superpowers`
- **Upstream Path:** `skills/systematic-debugging/`
- **License:** MIT (see [third_party/superpowers/LICENSE](../third_party/superpowers/LICENSE))
- **Imported Commit SHA:** `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- **Import Date:** 2026-08-24
- **Local AgentLayer Paths:**
  - Production Skill: [skills/systematic-debugging/](../skills/systematic-debugging/) (`SKILL.md`, `condition-based-waiting.md`, `condition-based-waiting-example.ts`, `defense-in-depth.md`, `find-polluter.sh`, `root-cause-tracing.md`, `UPSTREAM.md`)
  - Test Scenarios: [tests/upstream/superpowers/systematic-debugging/](../tests/upstream/superpowers/systematic-debugging/) (`test-academic.md`, `test-pressure-1.md`, `test-pressure-2.md`, `test-pressure-3.md`, `README.md`)
  - License/Notice: [third_party/superpowers/](../third_party/superpowers/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:**
  - Implementation files: Unchanged (faithful vendoring).
  - Test files: Updated skill reference path to AgentLayer directory structure (`skills/systematic-debugging`).

### verification (upstream: verification-before-completion)

- **Source Repository:** `https://github.com/obra/superpowers`
- **Upstream Path:** `skills/verification-before-completion/`
- **License:** MIT (see [third_party/superpowers/LICENSE](../third_party/superpowers/LICENSE))
- **Imported Commit SHA:** `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- **Import Date:** 2026-08-24
- **Local AgentLayer Paths:**
  - Production Skill: [skills/verification/](../skills/verification/) (`SKILL.md`, `UPSTREAM.md`)
  - License/Notice: [third_party/superpowers/](../third_party/superpowers/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:**
  - Implementation file: Byte-for-byte faithful vendoring at import. In 0.2.0 only the frontmatter `name` was changed from `verification-before-completion` to `verification` so it matches the directory name; the rest of the file is unchanged.

### brainstorming

- **Source Repository:** `https://github.com/obra/superpowers`
- **Upstream Path:** `skills/brainstorming/`
- **License:** MIT (see [third_party/superpowers/LICENSE](../third_party/superpowers/LICENSE))
- **Imported Commit SHA:** `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- **Import Date:** 2026-08-24
- **Local AgentLayer Paths:**
  - Production Skill: [skills/brainstorming/](../skills/brainstorming/) (`SKILL.md`, `visual-companion.md`, `spec-document-reviewer-prompt.md`, `scripts/`, `UPSTREAM.md`)
  - Test Suites: [tests/upstream/superpowers/brainstorming/](../tests/upstream/superpowers/brainstorming/) (`brainstorm-server/`, `README.md`)
  - License/Notice: [third_party/superpowers/](../third_party/superpowers/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:**
  - Implementation files: Unchanged (faithful vendoring).
  - Test files: Unchanged (vendored from upstream `tests/brainstorm-server/`).

### writing-plans

- **Source Repository:** `https://github.com/obra/superpowers`
- **Upstream Path:** `skills/writing-plans/`
- **License:** MIT (see [third_party/superpowers/LICENSE](../third_party/superpowers/LICENSE))
- **Imported Commit SHA:** `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- **Import Date:** 2026-08-24
- **Local AgentLayer Paths:**
  - Production Skill: [skills/writing-plans/](../skills/writing-plans/) (`SKILL.md`, `plan-document-reviewer-prompt.md`, `UPSTREAM.md`)
  - License/Notice: [third_party/superpowers/](../third_party/superpowers/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:**
  - Implementation files: Unchanged (faithful vendoring).

### gdal

- **Source Repository:** `https://github.com/isaaccorley/geospatial-skills`
- **Upstream Path:** `skills/gdal/`
- **License:** Apache-2.0 (see [third_party/isaaccorley-geospatial-skills/LICENSE](../third_party/isaaccorley-geospatial-skills/LICENSE))
- **Imported Commit SHA:** `a203446cb997cd1dbf054918b1021a6040b69824`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/gdal/](../skills/gdal/) (`SKILL.md`, `references/`, `UPSTREAM.md`)
  - License/Notice: [third_party/isaaccorley-geospatial-skills/](../third_party/isaaccorley-geospatial-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### geoparquet-validation

- **Source Repository:** `https://github.com/isaaccorley/geospatial-skills`
- **Upstream Path:** `skills/geoparquet-validation/`
- **License:** Apache-2.0 (see [third_party/isaaccorley-geospatial-skills/LICENSE](../third_party/isaaccorley-geospatial-skills/LICENSE))
- **Imported Commit SHA:** `a203446cb997cd1dbf054918b1021a6040b69824`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/geoparquet-validation/](../skills/geoparquet-validation/) (`SKILL.md`, `references/`, `UPSTREAM.md`)
  - License/Notice: [third_party/isaaccorley-geospatial-skills/](../third_party/isaaccorley-geospatial-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### geozarr

- **Source Repository:** `https://github.com/isaaccorley/geospatial-skills`
- **Upstream Path:** `skills/geozarr/`
- **License:** Apache-2.0 (see [third_party/isaaccorley-geospatial-skills/LICENSE](../third_party/isaaccorley-geospatial-skills/LICENSE))
- **Imported Commit SHA:** `a203446cb997cd1dbf054918b1021a6040b69824`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/geozarr/](../skills/geozarr/) (`SKILL.md`, `UPSTREAM.md`)
  - License/Notice: [third_party/isaaccorley-geospatial-skills/](../third_party/isaaccorley-geospatial-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### geospatial-frontend

- **Source Repository:** `https://github.com/isaaccorley/geospatial-skills`
- **Upstream Path:** `skills/geospatial-frontend/`
- **License:** Apache-2.0 (see [third_party/isaaccorley-geospatial-skills/LICENSE](../third_party/isaaccorley-geospatial-skills/LICENSE))
- **Imported Commit SHA:** `a203446cb997cd1dbf054918b1021a6040b69824`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/geospatial-frontend/](../skills/geospatial-frontend/) (`SKILL.md`, `references/`, `UPSTREAM.md`)
  - License/Notice: [third_party/isaaccorley-geospatial-skills/](../third_party/isaaccorley-geospatial-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### geopandas

- **Source Repository:** `https://github.com/K-Dense-AI/scientific-agent-skills`
- **Upstream Path:** `skills/geopandas/`
- **License:** MIT (see [third_party/kdense-scientific-agent-skills/LICENSE](../third_party/kdense-scientific-agent-skills/LICENSE))
- **Imported Commit SHA:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/geopandas/](../skills/geopandas/) (`SKILL.md`, `UPSTREAM.md`)
  - Upstream Evals: [tests/upstream/kdense-scientific-agent-skills/geopandas/](../tests/upstream/kdense-scientific-agent-skills/geopandas/)
  - License/Notice: [third_party/kdense-scientific-agent-skills/](../third_party/kdense-scientific-agent-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### geomaster

- **Source Repository:** `https://github.com/K-Dense-AI/scientific-agent-skills`
- **Upstream Path:** `skills/geomaster/`
- **License:** MIT (see [third_party/kdense-scientific-agent-skills/LICENSE](../third_party/kdense-scientific-agent-skills/LICENSE))
- **Imported Commit SHA:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/geomaster/](../skills/geomaster/) (`SKILL.md`, `UPSTREAM.md`)
  - License/Notice: [third_party/kdense-scientific-agent-skills/](../third_party/kdense-scientific-agent-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Modified locally (2026-10-24): the `SKILL.md` "Terrain Analysis" snippet and `references/code-examples.md` example 68 are corrected to use real pixel spacing and vertical units (see [skills/geomaster/UPSTREAM.md](../skills/geomaster/UPSTREAM.md)). Everything else is unchanged from upstream.

### design-postgis-tables

- **Source Repository:** `https://github.com/timescale/pg-aiguide`
- **Upstream Path:** `skills/design-postgis-tables/`
- **License:** Apache-2.0 (see [third_party/timescale-pg-aiguide/LICENSE](../third_party/timescale-pg-aiguide/LICENSE))
- **Imported Commit SHA:** `b4f11a45907af3abda0f79e784aff9a6d5eef468`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/design-postgis-tables/](../skills/design-postgis-tables/) (`SKILL.md`, `UPSTREAM.md`)
  - License/Notice: [third_party/timescale-pg-aiguide/](../third_party/timescale-pg-aiguide/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### statistical-analysis

- **Source Repository:** `https://github.com/K-Dense-AI/scientific-agent-skills`
- **Upstream Path:** `skills/statistical-analysis/`
- **License:** MIT (see [third_party/kdense-scientific-agent-skills/LICENSE](../third_party/kdense-scientific-agent-skills/LICENSE))
- **Imported Commit SHA:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/statistical-analysis/](../skills/statistical-analysis/) (`SKILL.md`, `references/`, `scripts/`, `UPSTREAM.md`)
  - Upstream Evals: [tests/upstream/kdense-scientific-agent-skills/statistical-analysis/](../tests/upstream/kdense-scientific-agent-skills/statistical-analysis/)
  - License/Notice: [third_party/kdense-scientific-agent-skills/](../third_party/kdense-scientific-agent-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### scientific-visualization

- **Source Repository:** `https://github.com/K-Dense-AI/scientific-agent-skills`
- **Upstream Path:** `skills/scientific-visualization/`
- **License:** MIT (see [third_party/kdense-scientific-agent-skills/LICENSE](../third_party/kdense-scientific-agent-skills/LICENSE))
- **Imported Commit SHA:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/scientific-visualization/](../skills/scientific-visualization/) (`SKILL.md`, `assets/`, `references/`, `scripts/`, `UPSTREAM.md`)
  - Upstream Evals: [tests/upstream/kdense-scientific-agent-skills/scientific-visualization/](../tests/upstream/kdense-scientific-agent-skills/scientific-visualization/)
  - License/Notice: [third_party/kdense-scientific-agent-skills/](../third_party/kdense-scientific-agent-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### networkx

- **Source Repository:** `https://github.com/K-Dense-AI/scientific-agent-skills`
- **Upstream Path:** `skills/networkx/`
- **License:** 3-clause BSD (see [third_party/kdense-scientific-agent-skills/LICENSE](../third_party/kdense-scientific-agent-skills/LICENSE))
- **Imported Commit SHA:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import Date:** 2026-08-25
- **Local AgentLayer Paths:**
  - Production Skill: [skills/networkx/](../skills/networkx/) (`SKILL.md`, `references/`, `UPSTREAM.md`)
  - License/Notice: [third_party/kdense-scientific-agent-skills/](../third_party/kdense-scientific-agent-skills/) (`LICENSE`, `NOTICE.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### geospatial-data-discovery (AgentLayer Native)

- **Author:** AgentLayer Team
- **License:** MIT
- **Local AgentLayer Path:** [skills/geospatial-data-discovery/](../skills/geospatial-data-discovery/) (`SKILL.md`, `UPSTREAM.md`)
- **References:** OGC STAC/COG, OpenStreetMap (ODbL), Overture Maps, Copernicus Open Access

### time-series-and-change, sar-basics, accuracy-assessment, stac-and-cloud-access (Terraproof Native, Phase 4)

- **Author:** Geova (Terraproof)
- **License:** MIT (see [LICENSE](../LICENSE))
- **Local Paths:** [skills/time-series-and-change/](../skills/time-series-and-change/), [skills/sar-basics/](../skills/sar-basics/), [skills/accuracy-assessment/](../skills/accuracy-assessment/), [skills/stac-and-cloud-access/](../skills/stac-and-cloud-access/) (each `SKILL.md`, `references/`, `UPSTREAM.md`); benchmark specs in [evals/tasks/](../evals/tasks/)
- **Upstream:** none; no third-party text or code copied.
- **Primary references:** ESA SentiWiki Sentinel-1 pages and ESA-EOPG-CSCOP-TN-0002 (radiometric calibration); STAC Item, Item Search, Query/Filter and extension specifications; GDAL, rasterio, pystac-client, odc-stac, stackstac, xarray and Planetary Computer SDK documentation/source; Olofsson et al. 2014 and 2013, Stehman 2014, Stehman & Czaplewski 1998, Stehman & Foody 2019, FAO 2016; Verbesselt et al. 2010, Zhu & Woodcock 2014, Kennedy et al. 2010, Zhu 2017, Singh 1989; Small 2011, Lee 1980; ASF HyP3 RTC product guide. The `mapaccuracy` R package (by H. Costa) was consulted only to cross-check formulas; none of its code is included.
- **Internal review, 2026-10-23:** Olofsson et al. (2014), sections 2.1.3 and 4.3–4.4, support the systematic-sample variance caveat; the ASF guide supports the factor of ten between a plain log-power ratio and a dB difference. The NDVI example now counts only finite pairs with defined per-date NDVI. Corrections and CLI examples were authored locally; no upstream text or code was copied.

---

> [!IMPORTANT]
> Material must not be copied into AgentLayer until its license and attribution requirements have been reviewed.

---

## Removed in 0.2.0

In 0.2.0 the project was refocused as Terraproof and these off-scope skills were removed from `skills/`, together with their `third_party/` license folders and `tests/upstream/` fixtures. The entries below are kept as plain text for attribution. Local paths and `third_party/` references are no longer links because those files are no longer in the working tree. The `LICENSE` and `NOTICE.md` files and the imported material remain in git history at commit `69b395a24e2428c3b6226f5382a02a365ce9f9e0`.

### unit-testing

- **Source Repository:** `https://github.com/arjunprabhulal/agent-skills`
- **Upstream Path:** `skills/qa/unit-testing/`
- **License:** MIT — Copyright (c) 2026 Arjun Prabhulal (`third_party/arjunprabhulal-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `42dd24080fce6d731d00e2a1134f398c3da4171b`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/unit-testing/` (`SKILL.md`, `UPSTREAM.md`); upstream evals `tests/upstream/arjunprabhulal-agent-skills/unit-testing/`
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### integration-testing

- **Source Repository:** `https://github.com/arjunprabhulal/agent-skills`
- **Upstream Path:** `skills/qa/integration-testing/`
- **License:** MIT — Copyright (c) 2026 Arjun Prabhulal (`third_party/arjunprabhulal-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `42dd24080fce6d731d00e2a1134f398c3da4171b`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/integration-testing/` (`SKILL.md`, `UPSTREAM.md`); upstream evals `tests/upstream/arjunprabhulal-agent-skills/integration-testing/`
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### browser-testing

- **Source Repository:** `https://github.com/arjunprabhulal/agent-skills`
- **Upstream Path:** `skills/qa/browser-testing/`
- **License:** MIT — Copyright (c) 2026 Arjun Prabhulal (`third_party/arjunprabhulal-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `42dd24080fce6d731d00e2a1134f398c3da4171b`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/browser-testing/` (`SKILL.md`, `UPSTREAM.md`); upstream evals `tests/upstream/arjunprabhulal-agent-skills/browser-testing/`
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### test-driven-development

- **Source Repository:** `https://github.com/arjunprabhulal/agent-skills`
- **Upstream Path:** `skills/qa/test-driven-development/`
- **License:** MIT — Copyright (c) 2026 Arjun Prabhulal (`third_party/arjunprabhulal-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `42dd24080fce6d731d00e2a1134f398c3da4171b`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/test-driven-development/` (`SKILL.md`, `UPSTREAM.md`); upstream evals `tests/upstream/arjunprabhulal-agent-skills/test-driven-development/`
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### frontend-design

- **Source Repository:** `https://github.com/vercel-labs/open-agents`
- **Upstream Path:** `.agents/skills/frontend-design/`
- **License:** MIT — Copyright (c) 2026 Vercel, Inc. (`third_party/vercel-open-agents/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `cf865e94de7729751c747171785b6ce57e7b178c`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/frontend-design/` (`SKILL.md`, `UPSTREAM.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### react-best-practices

- **Source Repository:** `https://github.com/vercel-labs/agent-skills`
- **Upstream Path:** `skills/react-best-practices/`
- **License:** MIT — Copyright (c) 2026 Vercel, Inc. (`third_party/vercel-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `dd089a8c752c966dee8bf0f27cb625ba193ffd9e`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/react-best-practices/` (`SKILL.md`, `AGENTS.md`, `metadata.json`, `README.md`, `rules/`, `UPSTREAM.md`); upstream evals `tests/upstream/vercel/react-best-practices/`
- **Modification Status:** Unchanged (faithful vendoring).

### codebase-architecture

- **Source Repository:** `https://github.com/mblode/agent-skills`
- **Upstream Path:** `skills/codebase-architecture/`
- **License:** MIT — Copyright (c) 2026 Matthew Blode (`third_party/mblode-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `e97a3b383f5944f90d41eb92b24b4fb3b917a7f9`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/codebase-architecture/` (`SKILL.md`, `references/`, `UPSTREAM.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### supabase

- **Source Repository:** `https://github.com/supabase/agent-skills`
- **Upstream Path:** `skills/supabase/`
- **License:** MIT — Copyright (c) 2026 Supabase (`third_party/supabase-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `8331f910845103c08d51f6ca1d86ebb7d1f745e3`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/supabase/` (`SKILL.md`, `CHANGELOG.md`, `assets/`, `references/`, `UPSTREAM.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### supabase-postgres-best-practices

- **Source Repository:** `https://github.com/supabase/agent-skills`
- **Upstream Path:** `skills/supabase-postgres-best-practices/`
- **License:** MIT — Copyright (c) 2026 Supabase (`third_party/supabase-agent-skills/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `8331f910845103c08d51f6ca1d86ebb7d1f745e3`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/supabase-postgres-best-practices/` (`SKILL.md`, `CHANGELOG.md`, `references/`, `UPSTREAM.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### security-review

- **Source Repository:** `https://github.com/github/awesome-copilot`
- **Upstream Path:** `skills/security-review/`
- **License:** MIT — Copyright GitHub, Inc. (`third_party/github-awesome-copilot/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `8e03e6abebad103ad0b27fe66d8ec368264a7a22`
- **Import Date:** 2026-08-24
- **Former Local Paths:** `skills/security-review/` (`SKILL.md`, `references/`, `UPSTREAM.md`)
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### exploratory-data-analysis

- **Source Repository:** `https://github.com/K-Dense-AI/scientific-agent-skills`
- **Upstream Path:** `skills/exploratory-data-analysis/`
- **License:** MIT (see the K-Dense LICENSE, which is still kept at `third_party/kdense-scientific-agent-skills/LICENSE`)
- **Imported Commit SHA:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import Date:** 2026-08-25
- **Former Local Paths:** `skills/exploratory-data-analysis/` (`SKILL.md`, `references/`, `scripts/`, `UPSTREAM.md`); upstream evals `tests/upstream/kdense-scientific-agent-skills/exploratory-data-analysis/`
- **Modification Status:** Unchanged (byte-for-byte faithful vendoring).

### api-discovery (AgentLayer Native, removed)

- **Author:** AgentLayer Team
- **License:** MIT
- **Former Local Path:** `skills/api-discovery/` (`SKILL.md`, `references/source-catalogs.md`, `UPSTREAM.md`)
- **References:** `public-apis/public-apis`, `public-api-lists/public-api-lists` (both MIT)

### api-integration (AgentLayer Native, removed)

- **Author:** AgentLayer Team
- **License:** MIT
- **Former Local Path:** `skills/api-integration/` (`SKILL.md`, `references/integration-patterns.md`, `UPSTREAM.md`)
- **References:** RFC 9110 HTTP Semantics, IETF RateLimit Headers, OpenAPI 3.1

### ai-sdk

- **Source Repository:** `https://github.com/vercel/ai`
- **Upstream Path:** `skills/use-ai-sdk/SKILL.md`
- **License:** Apache-2.0 — Copyright (c) 2023 Vercel, Inc. (`third_party/vercel-ai/LICENSE`, `NOTICE.md`)
- **Imported Commit SHA:** `d354a4260d930759d9a45e5bcde260c13825a42a`
- **Import Date:** 2026-08-26
- **Former Local Paths:** `skills/ai-sdk/` (`SKILL.md`, `UPSTREAM.md`)
- **Modification Status:** Faithful vendoring of the official Vercel AI SDK skill.


## Native raster source-contract references

The `terrain.slope_formula` and `raster.source_identity` implementations are
original Terraproof/Geova code under this repository's MIT license. No upstream
implementation or prose is vendored. Technical references for reader semantics
and COG scope are the [Rasterio nodata-mask documentation](https://rasterio.readthedocs.io/en/stable/topics/masks.html)
and [GDAL COG driver documentation](https://gdal.org/en/stable/drivers/raster/cog.html).
The [versioned contract guide](https://github.com/esmailhussien/terraproof/blob/v0.7.3/docs/RASTER_CONTRACTS.md) describes the implemented
mathematics, tolerances, validity policy and limits.

## Native evaluation runtime separation

`tests/agent_runtime.py` and its regression tests are original Terraproof/Geova
code under the repository MIT license. No upstream implementation is copied.
Staged runtimes retain the production skills' attribution, `sources/` and
`third_party/` licenses. Evaluation recipes and reference assets are excluded
from the agent runtime, while the standard release package remains unchanged.

## Exhaustive processing and offline containment

The full calibration/QA checks, checker scorecard and Docker harness/probe are
original Terraproof/Geova MIT code. No external implementation is vendored.
Raster validity follows the [Rasterio mask API](https://rasterio.readthedocs.io/en/stable/topics/masks.html).
The optional local image uses an externally downloaded Antigravity executable
from Google's [official CLI installation distribution](https://antigravity.google/docs/install/),
verified against its official manifest hash. This executable is not committed,
redistributed by the Python/npm packages or relicensed under Terraproof's MIT
license. Its upstream terms continue to apply. The
[Google sandbox documentation](https://antigravity.google/docs/sandbox?tab=cli)
informs the distinction between a native terminal sandbox and the separate
whole-process Docker boundary. Existing production attribution is preserved.
