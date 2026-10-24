# Terraproof — Phase 4 Plan: Remote-sensing depth & reproducibility

> Status: **implemented scope and local release acceptance complete under the user's sole-agent review exception**. This includes real native Codex tool use after runtime recovery. GitHub Actions must verify the published checkpoint. Independent held-out generalization and independent expert review are not claimed.

## 1. Why this phase

Today Terraproof can tell an agent that a *result looks plausible* (CRS, geometry, value ranges). It cannot yet tell whether the **processing itself** was done right, whether a run can be **reproduced**, or catch mistakes **before** compute is spent. Phase 4 closes those three gaps for the remote-sensing workflows that matter most: optical preprocessing, SAR, time series, and accuracy assessment.

## Verification status and deferred gates

Implemented in this checkout: preflight rules and schema, provenance write/verify integration, processing-level checks, four skill manifests and registrations, deterministic candidate routing with optional offline semantic fallback, and the 27-task executable harness plus seven-rule synthetic preflight control group.

Evidence limits: independent held-out routing performance and independent expert review are not claimed. The user-approved internal review and fresh internal measurement are scoped below. The deterministic eval harness does not measure agent lift. Real native Codex tool use has now passed separately; hosted CI is checked on the published checkpoint.

User-approved review exception (2026-10-23): the user declined additional
reviewers and accepted this agent's internal content review ("انت كفاية").
The four skill contents were reviewed internally, with corrections to NDVI
observation counts, SAR change units, systematic-sample uncertainty and current
CLI examples. This satisfies the content-review step under that explicit
exception; it is not an independent expert review. It does not waive the routing
performance targets, successful real-host tool use or hosted CI. Historical v3
and v4 routing acceptance failed. A new frozen internal audit also missed the
unchanged thresholds: EN recall 0.95 with 12.5 forbidden selections per 100; AR
recall 0.8125 with 3.75 forbidden selections per 100. This same-agent audit is
not independent acceptance; see [its protocol](../../evals/routing/INTERNAL_20261023_PROTOCOL.md).

Subsequent completion request: that exposed internal set is now development
coverage. After scope/Arabic fixes, a separate frozen 100-item same-agent audit
met the unchanged per-language targets (EN recall 1.0, AR 0.98; forbidden rates
4/100 and 2/100). See [release audit](../../evals/routing/RELEASE_20261023_PROTOCOL.md).
This is explicitly internal evidence under the requested sole-agent process,
not an independent heldout pass. The full local Python suite passed 1037 tests.
After a supported runtime restart and a fresh app-bundled Python environment,
native Codex passed actual call/result checks for both allowed read-only MCP
tools and successful turn completion. No file-security labels or ownership were
changed, and the trace gate remains strict. Hosted CI is verified after the
checkpoint push. Current detail is in [the release checklist](../RELEASE_CHECKLIST.md).

## 2. Goals

1. **Preflight** — check a declared plan against the real inputs *before running*, so an agent fixes the plan instead of producing a wrong map.
2. **Provenance manifests** — every run can write a manifest (inputs + hashes, STAC item ids, tool versions, parameters, outputs + hashes) and be re-verified later.
3. **Processing-level checks** — move from range plausibility to input/output comparisons that prove a step was applied correctly.
4. **Four new skills** from the v1 catalog: `time-series-and-change`, `sar-basics`, `accuracy-assessment`, `stac-and-cloud-access`.
5. **Executable benchmark tasks** — every `evals/tasks/*.json` spec runs automatically against generated fixtures with a reference solution and seeded errors (the base for Phase 5 agent-lift measurement).

## 3. Scope

### 3.1 Preflight (`python -m terraproof preflight`, MCP tool `preflight`)
Input: datasets + a small JSON plan (`operation`, `target_crs`, `resampling`, `categorical`, `time_range`, `expect`, `combine` …). Output: the same evidence report format, graded, with check ids prefixed `preflight.*`. First rules:
- metric operation planned on a geographic/geocentric CRS (no reprojection step declared);
- inputs to be combined have different CRS / grids and no alignment step declared;
- categorical raster with a non-nearest/mode resampling method;
- integer reflectance with scale/offset metadata and no decode step declared;
- requested time range outside the STAC item datetimes;
- index requested on non-reflectance inputs (DN without decode);
- output CRS units incompatible with the requested measurement units.

### 3.2 Provenance manifests
- `python -m terraproof manifest write --inputs … --outputs … --params plan.json --out run.manifest.json` and `--manifest` on `check`.
- Manifest records: SHA-256 + size of every input/output, STAC item ids/hrefs/collection/datetime, Terraproof + library + GDAL versions, parameters, command line, timestamp **outside** the hashed core so the core stays deterministic.
- `python -m terraproof manifest verify run.manifest.json` → new check `provenance.reproducible` (pass when every recorded file re-hashes identically and tool versions match; warn on version drift; fail on content drift or missing files).
- Evidence rule change (proposed): **Decision-grade requires a verified manifest** when `--require-provenance` is set; default stays as today to avoid breaking users.

### 3.3 Processing-level checks (input/output pairs, deterministic)
| id | rule |
|---|---|
| `rs.scale_applied_once` | sampled output pixels ≈ input DN × scale + offset (from metadata or `--encoding s2-l2a\|landsat-c2-l2`); fail on missing or double application |
| `rs.cloud_mask_applied` | with an aligned SCL/QA raster: pixels flagged cloud/shadow (SCL 3, 8, 9, 10; Landsat QA_PIXEL bits 1–4) must be nodata in the output |
| `rs.temporal_scope` | STAC item / input datetimes fall inside `--time-range` |
| `sar.value_domain` | `--expect sigma0-db\|sigma0-linear`: sampled values in the plausible domain for the declared scale; flags dB/linear confusion |
| `sar.geocoded` | raster has a real CRS/geotransform (not GCP-only slant/ground-range geometry) before spatial analysis |
| `accuracy.sample_design` | reference sample covers every map class with a minimum count; stratified weights present when area estimates are reported |
| `accuracy.estimates` | computes overall/user's/producer's accuracy with confidence intervals and **area-adjusted** class areas (stratified estimator); flags reports that state accuracy without these |

Every check ships with a seeded failing fixture and a passing fixture; none may pass on wrong data (lesson from Phase 2's false passes).

### 3.4 New skills (Terraproof-native, primary-source cited)
- `time-series-and-change` — compositing, gap handling, change detection, seasonality, per-date vs. composite indices.
- `sar-basics` — Sentinel-1 GRD, calibration to σ⁰/γ⁰, dB vs. linear, speckle, terrain correction.
- `accuracy-assessment` — sampling design, confusion matrix, area-adjusted accuracy and area estimates.
- `stac-and-cloud-access` — STAC search, item/asset provenance, lazy/windowed cloud reads, signed URLs.
Each: sectioned `SKILL.md`, `skill.json` (sections + checks), 3+ eval task specs, independent expert review before merge, router registration + scenarios + dev items.

### 3.5 Router: break the lexical ceiling (deferred measurement gate)
Measured before Phase 4: on the fresh independent `heldout_v2` set the lexical router reaches recall@5 0.845 (EN 0.89, AR 0.80) with 18 forbidden picks; tightening precision cost recall. Two complementary changes:
- **Candidates + host re-ranking.** `find_guidance` returns a recall-oriented candidate list (e.g. top 8 with reasons and one-line explanations); the MCP host model — which already understands the task semantically — chooses which sections to load. Measured as recall@8 of candidates plus a simulated selection step.
- **Optional local semantic retrieval.** An optional extra (`[semantic]`) adds a small multilingual embedding model run locally (offline, deterministic, pinned version) and fuses its section scores with BM25. Off by default; the lexical path stays dependency-light.
- Exit target: recall@5 ≥ 0.90 in each language on a **new** held-out set (v3, written after these changes), with `must_not` violations ≤ 5 per 100. `heldout_v2` is used once, at the end, to report the change.

### 3.6 Executable benchmark tasks (`python -m terraproof.evals run`)
- Fixture recipes per task (generated, never committed as binaries), a reference "correct" output and the seeded "silent error" output.
- Runs the real checks/preflight and asserts each task's `expected_checks` and grade.
- Report: tasks passed, checks exercised, false passes (must be 0).

## 4. Workstreams and order

| # | Workstream | Depends on | Suggested lane |
|---|---|---|---|
| A | Provenance manifests + `provenance.reproducible` | — | Main Coding |
| B | Processing-level checks (3.3) without CLI wiring | — | Parallel Coding |
| C | Four new skills (content) | — | Hard Problems / default lane, then independent review |
| D | Preflight command + MCP tool + CLI wiring for A and B | A, B | Main Coding |
| E | Executable eval harness + fixtures for all task specs | B, D | Fast Worker |
| F | Register skills, router scenarios/dev items, measure on `heldout_v2` once | C, D | Hard Problems |
| H | Router: candidate mode + optional semantic retrieval (3.5), then held-out v3 written independently | — (parallel with A–C) | Hard Problems; v3 by the default lane |
| G | Docs, CHANGELOG 0.4.0, CI | all | Fast Worker |

A, B, C run in parallel (disjoint files); D after A+B; E and F after D; G last. Every workstream is reviewed and re-verified before the next starts.

## 5. Exit criteria

- Preflight catches every seeded plan error (≥ 7 types) before any processing.
- Manifest round-trip: verify passes on untouched outputs; fails on any changed byte; warns on version drift.
- Every new check: seeded fail + pass fixtures, **zero false passes**, independent review.
- 4 new skills merged, reviewed, routed; router recall on `heldout_v2` not lower than before Phase 4.
- `python -m terraproof.evals run` executes all task specs (existing 15 + ≥ 12 new) with 0 false passes.
- Full CI green (Python 3.11/3.13 × Ubuntu/Windows, Node 20/22/24 × 3 OS).

## 6. Decisions needed

1. **Provenance in the grade:** keep Decision-grade independent of manifests by default (proposed), or require a verified manifest for Decision-grade?
2. **SAR depth:** plausibility + geocoding checks and a knowledge skill (proposed), or also calibration-chain verification (needs Sentinel-1 metadata parsing, larger scope)?
3. **Accuracy method:** stratified area-adjusted estimation as the default (proposed, the accepted good-practice approach), plus simple confusion-matrix metrics.
4. **Router precision vs. recall:** keep the current precision-leaning router (fewer wrong picks, recall 0.845 on v2) until 3.5 lands, or restore the previous recall-leaning behaviour (recall 0.885, more wrong picks) now? Proposed: keep current, and fix recall properly through candidates + optional semantic retrieval.
5. **Semantic extra:** acceptable to add an optional local embedding model dependency (`[semantic]`, off by default)?

## 7. Risks

| Risk | Mitigation |
|---|---|
| Input/output checks need both files and aligned grids | Reuse `raster.grid_alignment`; clear `not-run` when the pair is missing |
| Manifests leak private paths | Store paths relative to a declared root; hashes, not contents |
| New checks overclaim | Same rule as Phase 2: messages describe what was measured; reviewer pass before merge |
| Heavier fixtures slow CI | Small synthetic rasters (≤ 256×256); fixtures generated in `tmp_path` |
