# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — Unreleased

### Changed
- Renamed the project to **Terraproof**: evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents (see [`Terraproof_v1_PLAN.md`](Terraproof_v1_PLAN.md)). The package is now `terraproof` v0.2.0, the CLI is `terraproof` (`bin/terraproof.js`), and the CLI banner, help, and generated manifest or bundle text say Terraproof. The GitHub repository is renamed to `esmailhussien/terraproof`, and the license and package author are now "Terraproof Contributors".
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

### Added
- Experimental Python core (Phase 1, `pyproject.toml`, `src/terraproof/`): `python -m terraproof inspect` (vector, raster, and local STAC Item inspection, read-only, no network) and `python -m terraproof check` (checks for CRS and units, geometry, record counts, raster integrity, remote-sensing value ranges, and STAC provenance). Each run yields an evidence grade (Decision-grade, Review required, Advisory only) in a JSON or Markdown report; the Markdown report has English and Arabic (`--lang ar`) output. Exit codes: 0, 2, 3 for the grades and 1 for usage errors or unreadable inputs. Tests in `tests/python/` generate fixtures at test time.
- CI job `python` runs `pytest -q tests/python` on Ubuntu and Windows with Python 3.11 and 3.13.
- `tests/router/cli.test.ts`: CLI argument validation tests, wired into `npm run test:router`.
- `npm run test:package` (`tests/package/smoke.mjs`): packs the package, installs the tarball into a fresh project, and checks `--version`, `route --format json`, `validate`, and unknown-collection rejection.
- CI job `package-smoke` runs the package smoke test on Ubuntu, Windows, and macOS with Node 20, 22, and 24.

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
