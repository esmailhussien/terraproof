# Scientific workflow core workstream

Owner: this Codex implementation branch. Started 2026-11-03. This workstream runs separately from the Phase 11 agent trial; it is not a renumbering or replacement of that plan.

## Direction

Build a scientific execution core usable by a researcher, a deterministic pipeline or an agent. CLI, MCP, QGIS, web and desktop applications are consumers of that core. The long-term outcome is a reviewed scientific goal translated into appropriate data preparation, analysis, verified outputs and a map, with a bounded repair loop and explicit scientific limits.

## Delivered engineering scope

The first end-to-end route is local native Landsat 8/9 Collection 2 Level-2 Surface Temperature. It includes input admission from MTL, polygon AOI support, explicit quality choices, intent approval tied to data identity, windowed processing, source-relative verification, statistics, uncertainty, SVG cartography, HTML evidence and a bounded regenerate/recheck operation preserving old outputs.

It is based on published v0.12.0 commit `0467d4491fb3a7059b3e81f8e1097934a5d7b566`, not the running Phase 11 branch. Existing checks/contracts are reused and their narrow scope is retained. No generic plugin framework, new router rules, model dependency, cloud service or user-facing GUI is introduced. See [Scientific workflows](../SCIENTIFIC_WORKFLOWS.md).

## Gates

| Gate | Required evidence | State |
| --- | --- | --- |
| Engineering correctness | End-to-end generated inputs, independent hand values, invalid policies, source/intent drift, mask/window errors, missing observations, corrupted artifacts and one-pass repair | Implemented; local verification recorded in the external handoff |
| Product packaging | Candidate wheel contains workflow modules and excludes evaluators; isolated installed interpreter runs and repairs a synthetic example | Demonstrated; internal candidate retains 0.12.0 label and is not the published release |
| Regression safety | Existing Python suite, repository validation and router; shared interpreter issues isolated from the active trial | Results recorded in the handoff; no existing tests weakened |
| Real-scene route | Trusted native USGS scene, explicit reviewer-approved intent/QA policy, independently checked product conversion, support and summaries | **Pending; must not be implied by synthetic test results** |
| Scientific review | Independent review of measurement meaning, product identity/representation, quality policy, coverage and uncertainty limits | **Pending** |
| Release | Agreed scope and compatibility, fresh install and real-scene evidence; integrate with Phase 11 only after its frozen trial is closed | **Not requested or performed** |

## Next work, in order

1. Review the route's source/intent boundaries and the complete generated-data demonstration.
2. Select one real native scene and AOI with a scientist. Review its metadata and requested result before processing; do not manufacture approval from a model's own output.
3. Measure correctness/coverage and correction behavior on this route. This is separate from T3 and does not reuse its partial output as tuning data.
4. Resolve demonstrated shortcomings before adding more products or retrieval methods.
5. Add a second concrete scientific route, then extract genuinely shared requirements if needed. Multi-date thermal analysis, spectral-index preparation and sensor-specific corrections are candidates, not claimed capabilities.
6. Connect a UI when the core has shown practical value. Scene acquisition, remote catalogs, costs/quotas, map classification, PDF export and deployment need their own reviewed scope.

## Fixed boundaries

- No model calls, edits to active-trial sources or interpreter dependencies, ACL changes, push, merge or publication are needed for this engineering batch.
- Unauthenticated approval/digests are a consistency boundary, not protection against an actor allowed to rewrite both approval and data.
- A correct product decode does not validate upstream retrieval accuracy or the study's causal interpretation.
- Unsupported coverage and all-invalid data must remain visible; they cannot be repaired by lowering the accepted scientific requirement.
