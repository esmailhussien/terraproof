# Scientific workflow core workstream

Owner: this Codex implementation branch. Started 2026-11-03. This workstream runs separately from the Phase 11 agent trial; it is not a renumbering or replacement of that plan.

## Direction

Build a scientific execution core usable by a researcher, a deterministic pipeline or an agent. CLI, MCP, QGIS, web and desktop applications are consumers of that core. The long-term outcome is a reviewed scientific goal translated into appropriate data preparation, analysis, verified outputs and a map, with a bounded repair loop and explicit scientific limits.

## Delivered engineering scope

The first end-to-end route is native Landsat 8/9 Collection 2 Level-2 Surface Temperature. It includes one bounded public catalog/discovery/acquisition route, local input admission from MTL, polygon AOI support, explicit quality choices, intent approval tied to data identity, windowed processing, source-relative verification, statistics, uncertainty, SVG cartography, HTML evidence and a bounded regenerate/recheck operation preserving old outputs. Source proposals remain separate from native scientific approval.

It is based on published v0.12.0 commit `0467d4491fb3a7059b3e81f8e1097934a5d7b566`, not the running Phase 11 branch. Existing checks/contracts are reused and their narrow scope is retained. No generic plugin framework, new router rules, model dependency, hosted backend or user-facing GUI is introduced. See [Scientific workflows](../SCIENTIFIC_WORKFLOWS.md).

## Gates

| Gate | Required evidence | State |
| --- | --- | --- |
| Engineering correctness | End-to-end generated inputs, independent hand values, invalid policies, source/intent drift, mask/window errors, missing observations, corrupted artifacts and one-pass repair | 105 workflow/source tests passed; unconditional quality admission, QA acquisition preapproval gate and optional uncertainty contract validated |
| Product packaging | Candidate wheel contains workflow modules and excludes evaluators; isolated installed interpreter runs and repairs a synthetic example | Demonstrated; internal candidate retains 0.12.0 label and is not the published release |
| Regression safety | Existing Python suite, repository validation and router; shared interpreter issues isolated from the active trial | 2083 passed, 13 skipped at frozen candidate 77ce7ae; prior unchanged router 87/87; repository validation passed |
| Real-scene route | Native USGS scenes, disclosed reviewer/intent/QA policy, independently implemented product conversion, support and summary check | Luxor Landsat 9 plus Netherlands Landsat 8; [first experiment](../SCIENTIFIC_WORKFLOW_REAL_SCENE_2026-11-03.md) and [six-case boundary review](../SCIENTIFIC_WORKFLOW_BOUNDARY_REVIEW_2026-11-03.md), including disclosed oracle correction; engineering review only |
| Scientific review | Independent review of measurement meaning, product identity/representation, quality policy, coverage and uncertainty limits | Separate AI-context acceptance passed three prior targets/five variants; [method and qualifications](../SCIENTIFIC_WORKFLOW_INDEPENDENT_ACCEPTANCE_2026-11-03.md). Human scientific suitability/field validation not established |
| Integration/release | Agreed scope and compatibility, fresh install and real-scene evidence; integrate with Phase 11 only after its frozen trial is closed | One review PR authorized 2026-11-04; no merge or publication performed. Keep the frozen trial isolated; reassess compatibility after parallel work lands |

## Next work, in order

Coverage decision recorded 2026-11-03: the user requires full requested-area scene coverage by default, partial delivery only through an explicit choice. This is implemented in intent/approval/run schema `/2`, a new configuration; prior `/1` experiments are retained under their original pinned wheels, not regraded. The API distinguishes this scene-footprint requirement from valid-observation coverage after QA.

User review found `/2` conflated raster extent with acquisition support. The [schema-3 correction](../SCIENTIFIC_ACQUISITION_UNCERTAINTY.md) now requires QA nonfill/available support before approval, distinguishes all denominators, and implements the user's report-only default uncertainty with optional explicit max, separate losses and post-filter sufficiency. Numerical workflow grade is checks-passed; review kind is declared and unauthenticated. Old configurations remain frozen. This is a tool-design contract, not a study-specific cutoff or monthly estimator.

1. Review the [separate-context acceptance](../SCIENTIFIC_WORKFLOW_INDEPENDENT_ACCEPTANCE_2026-11-03.md), including the two useful outputs, three preapproval refusals, unexercised uncertainty conditions, corner-boundary diagnostic sensitivity and retained oracle corrections. Keep its narrow numerical acceptance separate from human scientific suitability and absolute accuracy. The implementation agent's engineering approval does not authenticate a scientific reviewer.
2. Review the [completed schema-2 validation](../SCIENTIFIC_WORKFLOW_COVERAGE_V2_2026-11-03.md): full default and explicit partial acceptance, prominent status/coverage, six installed real-data behaviors, unchanged analytical pixels and preserved prior configurations.
   Review the [source-recovery packet](../SCIENTIFIC_SOURCE_RECOVERY_RESULT_2026-11-03.md): unchanged Netherlands AOI/month/QA, explicit new July 8 observation, full footprint and 97.6694% usable within scene. The user will review scientific suitability; engineering approval is not that review.
3. Expand predeclared scene/coverage cases after those requirements, retaining original failures and oracle amendments. This remains separate from T3 and does not reuse its partial output as tuning data.
4. Resolve demonstrated shortcomings before adding more products or retrieval methods.
5. Add a second concrete scientific route, then extract genuinely shared requirements if needed. Multi-date thermal analysis, spectral-index preparation and sensor-specific corrections are candidates, not claimed capabilities.
6. Connect a UI after scientific review of practical value. The single public Landsat catalog/acquisition route is implemented; multi-provider acquisition, costs/quotas, mosaics, map classification, PDF export and deployment need separate reviewed scopes.

## Fixed boundaries

- No model calls, edits to active-trial sources or interpreter dependencies, ACL changes, push, merge or publication are needed for this engineering batch.
- PR preparation was authorized separately on 2026-11-04: one branch push/review PR may package the existing core and byte-preserved evidence. This does not authorize altering the trial, merging into its frozen configuration, publishing packages or creating a release tag.
- Unauthenticated approval/digests are a consistency boundary, not protection against an actor allowed to rewrite both approval and data.
- A correct product decode does not validate upstream retrieval accuracy or the study's causal interpretation.
- Unsupported coverage and all-invalid data must remain visible; they cannot be repaired by lowering the accepted scientific requirement.
