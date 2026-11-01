# Terraproof — Phase 8 Plan: Easy declarations, real data, real agents

> Status: **proposed (2026-11-01)**. Nothing is implemented. It follows [Phase 7](Terraproof_Phase7_PLAN.md) and release 0.9.0.

## 1. Why this phase

Phase 7 showed that Terraproof catches silent geospatial mistakes without false assurance, **when the user declares what they know**. On 48 sealed cases (V4b):

- 17 of 20 wrong outputs failed a required check.
- No wrong output was graded `decision-grade`, and 13 correct outputs were.
- No correct output raised a confirmed false alarm.

Three limits remain, and they decide whether this helps anyone in practice.

1. **Declaring is hard.** Every V4b miss came from an undeclared vertical unit. A user or an agent will rarely type `--qa-keep-code`, `--decode-scale` and `--dem-vertical-unit` unprompted. Yet most of those facts already sit in the data's own metadata: STAC `raster:bands` (scale, offset, nodata), band unit labels, QA asset roles, the CRS.
2. **The evidence is synthetic.** Both sealed sets were generated arrays. Real products have real metadata quirks:
   - fill values that are also valid codes;
   - scale and offset only in STAC;
   - QA layers on another grid;
   - missing or wrong unit labels.
3. **Agents were never measured on verification.** Phase 6 measured whether agents get better answers, and stopped at E5 because the models already did well. It never measured whether an agent that has Terraproof uses it to tell a good output from a bad one.

The aim is narrow: make the declared path the easy path, without guessing, and test it on real data and with a real agent.

## 2. Principles (unchanged from Phase 7)

- **Nothing is inferred from task text or file names.**
  - A proposal may only copy a fact that metadata states explicitly. It never infers one from value ranges or names.
  - The goal (which profile) is always the user's.
- **A proposal is not coverage.** A proposed binding counts only after the caller declares it, by passing the contract.
- **Cases first.** Held-out cases are sealed before any product code, measured once, then spent.
- **Mapping first.** Each measurement's mapping is committed before any result.

## 3. Workstreams

### P0. Seal a real-data held-out set (first)

- **What.** An independent agent authors at least 32 cases from small windows of public products:
  - Sentinel-2 L2A with SCL;
  - Landsat Collection 2 L2 with QA_PIXEL;
  - Copernicus or USGS DEMs, with metre and feet variants;
  - one NetCDF- or STAC-described packed product;
  - public vector boundaries.

  Wrong and correct outputs are derived from those real sources by scripts.
- **Data rules.**
  - No raster binaries are committed. The cases ship a fetch script with fixed URLs, byte ranges or windows, and the SHA-256 of every downloaded file, plus a deterministic derivation script and an independent oracle.
  - The data is cached locally. Tests skip without network or cache.
  - Licences and attribution go into [`sources/SOURCES.md`](../../sources/SOURCES.md), as AGENTS.md rule 10 requires.
- **Metadata as found.** Each case keeps the real metadata, including STAC items, so proposals can be measured on what products actually carry.
- **Sealing.** As in Phase 7: hashes of the committed files, plus a seal test. The content is not read for product work.

### P1. Contract proposals from metadata

- **Command and tool.** `python -m terraproof propose OUTPUT... --profile NAME [--source PATH|--stac ITEM]...` and an MCP tool `propose_contract`.
  - The caller names the goal profile or profiles and the sources.
  - Terraproof fills each binding the profile needs **only from explicit metadata**, such as STAC `raster:bands` `scale`/`offset`/`nodata`, a band's unit label, a QA asset's declared role and classes, or the dataset CRS.
  - Each binding records its evidence: file, field and value.
  - Bindings that no metadata states are listed as **still undeclared**, with the argument that would supply them.
- **Output.** A draft contract marked `"status": "proposed"`, which the caller saves or edits and then passes as `--contract`.
  - A proposed contract is never applied automatically.
  - `run_checks` without a contract may return the proposal beside `checks-passed`, labelled as a proposal.
- **Tests.** Every binding source gets a fixture where the metadata states it, and one where it does not; the latter must leave the binding undeclared, never filled. Fixtures with conflicting metadata, such as a file label against STAC, must report the conflict instead of choosing.

### P2. Remaining check gaps

- **Categorical resampling.** Output values must be a subset of the source's class codes. This catches the invented classes `bilinear` and `cubic` produce.
- **Domain of a SAR filter.** A declared filter (boxcar, mean) is recomputed in linear power, not dB.
- **Temporal labels.** A declared accumulation window is checked against the per-layer dates.
- **`geometry.winding` severity.** Decide whether ring orientation on otherwise correct deliverables stays `fail` or becomes `warn`. The decision is recorded before P3 and does not use P3 results.

Each new or changed check follows the Phase 4 rules: a fail fixture, a pass fixture, zero false passes on all regression sets, and CLI and MCP parity.

### P3. Measure once on the real-data set (offline)

Three configurations, each with its mapping committed first.

1. **Declared by hand.** As V4b, from each case's declaration.
2. **Proposed.** Only the profile and the source paths are given; every other binding comes from `propose`. This measures whether metadata alone gets users to verified coverage.
3. **Undeclared.**

Reported measures are Phase 7's five, plus:

- the share of required bindings that a proposal filled from metadata;
- the bindings it left undeclared;
- the conflicts it reported.

**Acceptance, fixed now.**

- In every configuration, zero false assurance: no wrong output graded `decision-grade`.
- Zero confirmed false alarms within declared coverage.
- In the proposed configuration, no binding filled from metadata that contradicts the case's ground truth.

Detection and the proposal fill rate are reported, not thresholded.

### P4. Agent verification behaviour (optional; separate approval)

- **Setup.** One OpenCode Go model, MiMo-V2.6-Flash as registered in Phase 6, with the Terraproof MCP server. It runs on a small set of real-data tasks drawn from P0's sources but not from its sealed cases.
- **Approval.** The exact invocation count is approved separately before any run.
- **What is measured.** Not lift, but:
  - whether the agent calls `propose_contract` or declares profiles;
  - the share of its outputs that reach assessed coverage;
  - false assurance on its outputs: wrong outputs it would hand over as `decision-grade`.
- **Trace handling.** Traces keep Phase 6's contamination labels, and results are labelled "contamination screened".

## 4. Order and delivery

1. P0 is sealed first, by an independent agent, from a brief kept outside the repository.
2. P1 and P2 follow, then P3. P4 runs only if approved.
3. **One branch and one PR for the whole phase.**
   - Commits accumulate locally, and the full local suite runs before any push.
   - The branch is pushed as a draft only when a CI signal is needed, and marked ready at the end.
   - Seals, measurement records and checklist ticks ride on the same PR.
4. **One release, 0.10.0**, after the PR merges, and only if P1 or P2 changed user-visible behaviour. Docs, evals and measurement records alone never trigger a release.

## 5. Out of scope

- New lift studies; Phase 6's E5 stop stands.
- A whole-process evaluator boundary, which is still required before any "evaluator-blind" claim.
- Large-data performance, spatial previews, automatic patches, signing and a public leaderboard.

## 6. Decisions needed

1. **Who authors P0.** The proposal is an independent agent from a brief, as for V0 and V0b.
2. **Whether to run P4**, and its exact invocation count, decided after P3.
