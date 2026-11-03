# Schema 2: full requested-AOI coverage by default

**Historical limitation:** this gate checked the raster rectangle, including fill corners. It did not prove QA-declared acquisition coverage. See the [schema-3 correction](SCIENTIFIC_ACQUISITION_UNCERTAINTY.md); preserve these original results as the `/2` experiment, not the corrected gate.

Date: 2026-11-03. User decision: full requested-area scene coverage is required by default; partial-area delivery needs an explicit choice. Local implementation commit: `66e0f796b31b00f1bf053623878d0ae1bb0141d8`. No publication, model calls or active Phase 11 changes.

## Resulting behavior

- `terraproof.workflow/2` accepts optional `intent.scene_coverage`: `full-aoi` by default, or explicitly `allow-partial`. CLI `workflow init` writes the default; `--allow-partial` writes the explicit exception.
- A default request whose AOI extends outside the native scene is `unresolved` before approval or processing. The plan shows the outside fraction and actionable next steps: review a suitable covering source, or explicitly review partial delivery when scientifically acceptable. It does not fetch another scene, change dates or weaken QA automatically.
- Admission and approval reuse checks both enforce this gate. Changing the coverage choice invalidates the approved intent. Facts and summary record the effective policy.
- HTML and SVG directly display status, full/explicitly-partial scope, requested-AOI scene coverage and usable coverage within the scene. Incomplete/failed delivery says it is not an accepted scientific result. Published verification checks display status against the numerical verdict.
- Full scene footprint coverage does not mean all observations are valid or cloud-free. The separately required `min_valid_fraction` still controls usable within-scene observations.

## Configuration and compatibility

Intent, plan, approval and run formats move to `/2` because the acceptance rule changed. `/1` intents receive migration guidance; `/1` approvals cannot silently be reused. Copy an intent, choose/review the `/2` policy, obtain a new digest and approval, then use a new output directory. This is a new configuration, not a reinterpretation of earlier experiments. The original `/1` source, candidate wheels, approvals, artifacts, failures and oracle amendments remain unchanged.

Full coverage uses containment of the densified AOI geometry in the native scene footprint, with no implicit outside-area tolerance. Straight geographic edges can protrude beyond a native grid even when transformed vertices touch its edges. The KML/KMZ format fixtures now sit strictly inside the scene; a separate test retains and refuses the protruding-edge case. Format support was not replaced by an outside-area tolerance or a weakened assertion. The finite projected representation remains an engineering boundary, not a proof for projection singularities.

The internal candidate still bears package version 0.12.0; it is **not the published v0.12.0 artifact**. Installed wheel SHA-256:

```text
2b7942c475fc8b175687f16855f37518f4821e045b69e89c116a41a4d818199e
```

## Installed real-data verification

A separate new product-only environment runs the candidate. Workflow and CLI bytes match the source after CRLF normalization; evaluators are absent. Existing dependencies are reused read-only; this is not a fresh network dependency-resolution claim. No new source download was needed.

| Case | Expected and observed |
| --- | --- |
| C1: original Luxor complete AOI, coverage omitted | verified under full default; 493,549 selected / 480,625 valid |
| C2: prior native partial rectangle, coverage omitted | unresolved; 16.67% outside; approval refused; no processing/output |
| C3: same rectangle, explicit allow-partial | verified; visibly partial, 83.33% scene footprint and 83.09% usable within scene |
| C4: Netherlands rectangle, coverage omitted | unresolved; 55.70% outside; approval refused; no processing/output |
| C5: same Netherlands rectangle, explicit allow-partial | incomplete; visibly 44.30% scene footprint and 2.18% usable; weakening repair refused |
| C6: old `/1` intent and approval | migration/refusal; no silent reuse of the changed acceptance rule |

All six expected behaviors passed. The three executed outputs independently agree with the retained whole-source checker, whose SHA-256 is unchanged (`487e135be2deb727d35b8e776ef987c6e927765e7ef61176203585083edeaf60`). This reuses the **disclosed geometric oracle correction** from the [boundary review](SCIENTIFIC_WORKFLOW_BOUNDARY_REVIEW_2026-11-03.md), not a claim of a new blinded oracle. No Terraproof producer geometry helper is imported into that checker.

All five analytical GeoTIFFs in each executed case are **byte-identical to the corresponding prior configuration**: decoded intermediate, cropped temperature, AOI mask, validity and uncertainty. This batch changes acceptance/reporting and adds an explicit policy field to summaries; it does not improve or modify temperature retrieval. Original native asset hashes were checked before and after.

Actual installed CLI smoke tests also passed: default partial request exits 3 with an unresolved plan; `--allow-partial` creates a `/2` intent and ready-for-review plan with exit 0.

## Regression and visual checks

- Targeted workflow suite: **55 passed**.
- Complete Python suite at implementation commit 66e0f79: **2033 passed, 13 skipped**, 432.24 seconds.
- Coverage tests include default rejection before execution, consistent-approval bypass refusal, explicit partial verified/incomplete outcomes, strict field validation, intent drift, legacy refusal, actual CLI templates, full footprint with missing observations, and visible failed status after late verification/publication failures.
- The full-map, partial-map and incomplete HTML were rendered in a separate empty headless browser profile and visually inspected. Banners, scope, percentage labels and incomplete warning were readable without opening JSON. Appearance was not used as the numerical acceptance oracle.
- Repository integrity/link validation and diff checks passed. No extra full-suite run was needed for subsequent documentation-only changes.

Earlier targeted failures from the old edge-touching KML/KMZ fixtures are retained in the external validation logs. Those fixtures represented geographic edges outside the native footprint under the new strict rule; the revised format fixtures and explicit protruding-edge rejection test passed. No outside-area tolerance was added to hide that condition.

## Retained evidence and limits

```text
D:\AgentLayer-acl-recovery\scientific-workflow-coverage-v2-2026-11-03
```

Evidence includes the protocol, candidate/source/checker identities, frozen migrated intents, installed wheel/environment, per-case plans/results/independent receipts, CLI smoke receipts, targeted/full test logs, visual screenshots, final audited summary and artifact inventory. Old destinations were not overwritten. See [current workflow usage and migration](SCIENTIFIC_WORKFLOWS.md).

Scientific accuracy, atmospheric/emissivity retrieval, QA truth and independent human scientific review remain outside these engineering claims. Full requested-area scene coverage is not a geodesic usable-area metric or an authenticated quality certificate. Scene acquisition, scientifically reviewed compositing and automatic recovery through another source remain future work; the current plan offers reviewable next steps without silently changing the measurement.
