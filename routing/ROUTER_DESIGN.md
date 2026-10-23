# Terraproof Smart Router — Architectural Design

The **Terraproof Smart Skill Router** is a deterministic, fast, offline, and inspectable resolution engine that maps natural language task descriptions into minimal, high-precision compositions of Terraproof skills.

---

## 1. Core Principles

1. **Deterministic & Fast**: Zero runtime network calls, zero LLM dependencies, zero vector database dependencies.
2. **Minimalist (Smallest Useful Set)**: Recommends the exact skills necessary to complete the task (typically 2–7 skills) without over-selecting entire domains.
3. **Layered Architecture**: Every skill is organized into a primary layer ensuring structured engineering workflows.
4. **Transparent & Explainable**: Every selected skill has a human-readable reason explaining its relevance to the prompt.
5. **Inspectable & Testable**: Backed by a deterministic scoring formula, strict schema validation, and 100% passing scenario suites.

---

## 2. System Architecture

```text
Natural Language Task
         │
         ▼
┌─────────────────────────────────┐
│     router/classify.ts          │  -> Extract Intent, Domains, Tech, Capabilities, Risk Boundaries, Testing Needs
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     router/score.ts             │  -> Score against routing/registry.json (Tech +5, Cap +4, Domain +3, Triggers +3/+1)
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     router/resolve.ts           │  -> Apply Layer Policies, Intent Rules, Hard Requires, Recommendations, Exclusions
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     router/explain.ts           │  -> Attach Human-Readable Rationale for every selected tool
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     Selected Skill Set          │  -> Grouped into Process, Domain, Implementation, Risk, Verification
└─────────────────────────────────┘
```

---

## 3. The 5 Routing Layers

Every production skill has exactly one primary layer:

| Layer | Purpose | Core Skills |
|---|---|---|
| **1. Process** | Engineering discipline, exploration, and structured breakdown | `brainstorming`, `writing-plans`, `systematic-debugging` |
| **2. Domain** | Geospatial, remote-sensing, and data domain knowledge | `gdal`, `geopandas`, `geomaster`, `geozarr`, `geoparquet-validation`, `geospatial-data-discovery`, `statistical-analysis`, `scientific-visualization`, `networkx`, `crs-and-units`, `vector-quality`, `raster-processing`, `satellite-preprocessing`, `spectral-indices`, `time-series-and-change`, `sar-basics`, `accuracy-assessment`, `stac-and-cloud-access` |
| **3. Implementation** | Mapping frameworks and spatial database design | `geospatial-frontend`, `design-postgis-tables` |
| **4. Risk** | Security, vulnerability detection, and authorization audits | *(no skills in v0.2.0)* |
| **5. Verification** | Truthfulness and completion validation | `verification` |

---

## 4. Scoring Heuristics

Candidate skills are scored deterministically based on rule weights:

- **Technology Exact Match (+5)**: Prompt explicitly names technology (e.g. `postgis`, `gdal`, `networkx`).
- **Capability Match (+4)**: Prompt matches a specific engineering capability (e.g. `web-map`, `cog-conversion`, `spatial-join`, `hypothesis-testing`).
- **Domain Relevance (+3)**: Broad domain category alignment (e.g. `geospatial`, `data`, `frontend`, `database`, `api`).
- **Strong Trigger (+3)**: Exact multi-word or distinct trigger phrase match.
- **Weak Trigger (+1)**: Single keyword match.
- **Recommended Bonus (+2)**: Associated skill recommendation from a high-confidence selected skill.
- **Hard Dependency (+10)**: Explicit `requires` declaration.
- **Manual Include (+20)**: User `--include <skill>` override.
- **Manual Exclude (-50)**: User `--exclude <skill>` override.
- **Conflict Penalty (-50)**: Mutual exclusion between opposing skills.

---

## 5. Intent & Contextual Selection Rules

1. **New Feature Creation (`build`, `create app`, `scaffold`)**:
   - Injects `brainstorming` and `writing-plans`.
2. **Bug Fixing & Diagnostics (`fix`, `bug`, `error`, `401`, `500`)**:
   - Injects `systematic-debugging`. Suppresses heavy speculative planning.
3. **Trivial Edits (`button label`, `typo`, `color change`)**:
   - Suppresses process layers. Retains only necessary minimal verification.

---

## 6. CLI Usage & Overrides

### Basic Route
```bash
npx terraproof route "Build a React dashboard displaying live weather data on a map"
```

### Dry Run (Inspect without modifying project)
```bash
npx terraproof route "Fix intermittent 401 error when loading map tiles" --dry-run
```

### Manual Inclusions and Exclusions
```bash
npx terraproof route "Process GeoTIFF into COG" --include gdal --exclude geomaster
```

### Seeding from Preset Collections
```bash
npx terraproof route "Custom GIS workflow" --collection gis
```

### JSON Output
```bash
npx terraproof route "Design PostGIS schema" --format json
```

---

## 7. Relationship to Existing Files

- **`routing/DOMAIN_ROUTING.md`**: Human-readable composition guidance and canonical architectural patterns.
- **`skills/<name>/skill.json`**: Routing metadata for each skill, the source of truth. To add or change a skill, add or edit its manifest, run `npm run registry:build`, and add scenarios to `tests/router/scenarios.json`. Field reference: [`routing/SKILL_MANIFEST.md`](SKILL_MANIFEST.md).
- **`routing/registry.json`**: Generated from the manifests by `npm run registry:build`. Do not edit it by hand; `npm run registry:check` verifies that it matches. The generated registry currently holds 24 skills: the 20 pre-Phase-4 skills plus the Phase 4 additions `time-series-and-change`, `sar-basics`, `accuracy-assessment` and `stac-and-cloud-access`.
- **`routing/checks.json`**: Check catalog listing the check ids that manifests may reference. It also carries the Phase 4 `provenance.reproducible` id and the `preflight.*` family; `tests/python/test_check_catalog.py` fails if the catalog and the emitting source disagree.
- **`routing/collections.json`**: Preset skill bundles (`gis`, `data-analysis`, `production`, `remote-sensing`).
- **`routing/rules.json`**: Scoring weights, intent heuristics, risk boundaries, and layer prioritization.
- **`router/`**: High-performance, deterministic TypeScript resolution engine and CLI runner.

---

## 8. Python candidate and optional semantic retrieval

The Python router keeps ranked mode's existing default cap of five and thresholds. `mode="candidates"` uses a deterministic default cap of eight, preserves the ranked choices, and fills remaining slots by relevance for optional host-side selection. Candidate output includes one-line skill explanations; it does not call a host model itself.

Before Python retrieval, a deterministic bilingual clause pass scopes BM25, exact triggers, wording signals and optional semantics to requested work. Editorial clauses (translation, email/copy drafting, button-label edits) do not make their quoted technology names executable tasks. Negative operation directives end at punctuation or contrast/sequence boundaries; later affirmative work survives. A `no Python` constraint removes the runtime preference, not a legitimate database, infrastructure or map task. Descriptive negatives such as raw values being “not reflectance” remain diagnostic evidence. Quotes outside editorial clauses may be actual operands and are retained. The public query text, normalized text and Arabic expansion metadata still describe the original input; dataset profiles retain their independent evidence.

Phase 4 guards distinguish SAR preparation from optical cloud/reflectance preprocessing, map-accuracy assessment from arbitrary sampling/numerical precision, temporal analysis from application edits, and cloud asset access from generic REST CRUD. Generic index wording requires a spectral/raster context; Arabic professional vocabulary uses curated whole-word forms and existing clitic normalization, not substring matches. Paired English/Arabic dev cases and `tests/python/test_router_intent.py` exercise these intent boundaries in both ranked and candidate modes. Every routing rule also requires a matching public scenario in the `pythonScenarios` section of `tests/router/scenarios.json` before freeze. The frozen 20-skill compatibility fixture is not regenerated for these changes. No held-out corpus or protocol informs the rules.

Semantic retrieval is optional and offline-only (`pip install -e ".[semantic]"`). It uses the pinned local dependency/model when available, and missing dependencies, models, or inference errors fall back to lexical retrieval with a warning. No model download occurs during ordinary routing or tests.

## 9. Future Optional LLM Fallback (Design Only)

The Python router now rejects text-only software/copy homonyms (for example an
API route, a fictional plot or a logo palette) unless the affirmative request
also names a domain capability. Inspected datasets remain positive evidence for
mixed software/geospatial work. Named GDAL commands, additional web-map engines,
explicit temporal/accuracy/cloud capabilities and curated Arabic workflow nouns
have registered regressions. The 160 exposed internal-audit cases are development
coverage; they are not reused as fresh acceptance. The subsequent
[release audit](../evals/routing/RELEASE_20261023_PROTOCOL.md) records both its
passing numeric thresholds and same-agent/sample-size limitations.

In future iterations, if a task prompt has very low classification confidence (< 50%) or ambiguous natural language:

```text
Ambiguous Task
      │
      ▼
Deterministic Router (Confidence < 0.50)
      │
      ▼
Optional LLM Classifier (Constrained JSON schema output)
      │
      ▼
Strict Registry Validator (Discard any hallucinated skill names)
      │
      ▼
Final Validated Recommendation
```

*Note: LLM fallback is strictly prohibited from inventing non-existent skills, modifying production weights, or bypassing the registry schema.*
