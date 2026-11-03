# Acquisition coverage, uncertainty and review provenance: schema 3

2026-11-03. This correction follows the user's review of the July source-recovery packet. The user correctly identified that `box(*src.bounds)` is the **grid extent**, including fill corners, not the acquired image footprint. Earlier artifacts/wheels remain frozen; their coverage labels need this erratum. July 8's numerical result is unchanged.

## Correct definitions

All fractions below count AOI **native-grid pixel centres**, including a virtual grid outside the file, not geodesic area:

| Field | Definition |
| --- | --- |
| `requested_count` | All native-grid centres selected by the original-coordinate AOI, including outside the raster |
| `selected_count` | Those centres within the raster rectangle; includes fill/unknown QA |
| `acquired_count` | Selected centres with QA_PIXEL bit 0 unset and QA mask available |
| `qa_fill_or_unknown_count` | Selected minus acquired |
| `outside_grid_count` | Requested minus selected |
| `grid_fraction_of_requested` | Selected / requested; not acquired coverage |
| `acquired_fraction_of_requested` | Acquired / requested |
| `base_valid_count` | Acquired, valid native temperature and approved QA flags, before optional uncertainty filtering |
| `valid_fraction_of_acquired` | Delivered valid / acquired, after optional uncertainty filtering; denominator for `min_valid_fraction` |
| `valid_fraction_within_grid` | Delivered valid / selected; retained separately as a diagnostic |

QA support is a source declaration, not independently authenticated proof of physical acquisition. Missing ST caused by upstream retrieval/emissivity is distinct from missing acquisition. The old native-plane rectangle fraction is now explicitly `outside_grid_extent_fraction_native_plane`; it must not be labelled scene footprint.

The default full-AOI gate requires geometric containment in the grid, at least one requested centre, and QA-declared acquisition for **every** requested centre. Fill/unknown corners inside the raster now produce unresolved before approval. An explicit partial exception still needs some acquisition support; zero-acquisition AOIs are unresolved. Admission scans bounded source windows, not metadata alone, with at most 110 million virtual bounding cells. No derived analysis is produced before approval.

## Independently reproduced July correction

A separate direct-coordinate script with no Terraproof imports reproduced:

| Metric | July 15 | July 8 |
| --- | ---: | ---: |
| Requested centres | 339,520 | 339,520 |
| Grid-selected centres | 150,391 | 339,520 |
| QA-acquired centres | 100,110 | 339,520 |
| Fill/unknown inside grid | **50,281** | **0** |
| Grid/request fraction | 44.2952% | 100% |
| Acquired/request fraction | **29.4857%** | **100%** |
| Valid temperature centres | 3,273 | 331,607 |
| Valid/grid fraction | 2.1763% | 97.6694% |
| Valid/acquired fraction | **3.2694%** | **97.6694%** |

The old 44.2955% was geometric grid-rectangle overlap; the nearby centre-count 44.2952% has a different definition. Neither is acquired coverage. Catalog polygon coverage is another metadata approximation, not a replacement for QA counts. Old and new acquisitions remain different days; none of this estimates a July monthly value.

## Optional uncertainty requirement

- No automatic ST_QA exclusion by default. No use-case classes choose a cutoff.
- Optional `intent.max_uncertainty_kelvin` must be finite and nonnegative; omission means report-only. It enters the digest; changing it requires new review.
- The source is native ST_QA integer hundredths of kelvin. Cutoffs are inclusive (`<=`), using exact decimal-to-native comparisons, including 2.01 K boundaries and valid zero values.
- With an active cutoff, base-valid pixels above it and pixels missing uncertainty are excluded with **separate counts**: `uncertainty_exceeded_count` and `uncertainty_missing_excluded_count`. Missing uncertainty is not silently invented or counted as below the bound.
- Apply `min_valid_fraction` before approval in **both** cases: `base_valid_count / acquired_count` without a cutoff, retained/acquired with one. Inadequate or zero usable support is unresolved before approval. An absent and a truly nonbinding cutoff must agree on status; known-bad plans do not wait for execution to become incomplete.
- Report both `uncertainty_before_filter` and `uncertainty_delivered`. The former population is base-valid AOI samples after temperature/base QA, before the optional cutoff, avoiding a hidden filtered-population summary.
- Each report includes known/missing counts, minimum/maximum/mean, linear-interpolation P05/P25/P50/P75/P95, and fractions strictly above 2, 3 and 4 K among known values. These diagnostics are not recommended acceptance thresholds.

Temperature and uncertainty summaries use equal pixels. The workflow does **not** calculate uncertainty of a spatial mean by dividing by sqrt(n), infer independent errors, or generate an absolute accuracy guarantee. It does not establish absolute comparisons finer than reported per-pixel uncertainty. Minimum ST_QA is an upstream estimate, not a guaranteed hard accuracy floor.

## Review declarations and grading

Approval records now distinguish `engineering-self-review` (default) and `declared-scientific-review`, always with `identity_authenticated: false`. CLI `--review-kind` exposes that declaration. A free-text name or declared role cannot authenticate a human; a dishonest caller can still misdeclare it. No identity/signing service is claimed.

The workflow's verified numerical status is graded **`checks-passed`**, not `decision-grade`, regardless of declared reviewer kind. Reports display the declaration, unauthenticated identity, lack of scientific certification and single-acquisition scope. Other Terraproof command/contract grades are unchanged. The checker is a separate algorithm by the same implementation agent, not blinded independent expert validation; the development AOI/ranking was already known. This correction does not claim to remove those methodological limits.

## Compatibility and evidence

Workflow/plan/approval/run records use `/3`; source request/search/package records use `/2`. Earlier records require copied/migrated intent, fresh plan/digest/approval and new destinations. Retrospective data or grades are not overwritten. The original source files, old review page and prior independent checker remain intact.

The new regression fixtures explicitly distinguish QA fill from missing ST, catch fill corners before approval, exercise unknown QA masks, exact percentiles/tail boundaries, missing uncertainty, optional rejection counts, decimal boundaries, post-filter sufficiency, digest drift and declared review provenance. Real-data corrected evidence is retained separately in `D:\AgentLayer-acl-recovery\scientific-workflow-acquisition-fix-2026-11-03`.

Product meanings follow the [USGS QA guidance](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands), [USGS Surface Temperature guidance](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature) and native format reference in [sources/SOURCES.md](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature). The interpretation and gate design above are Terraproof engineering choices, not USGS certification.

## Completed validation

Implementation commit `641798315463ad6bc83aa2258d6b605e6a5e623c`. Targeted workflow/source tests: **101 passed**. Full suite: **2079 passed, 13 skipped**, 573.62 seconds. Product-only installed wheel SHA-256 `7c8f83a1e83a77bd63164249dd6f955d83724d15d7d31b3cb76c28b4c6a3049c`; internal package label 0.12.0, not the published artifact. Workflow/CLI bytes match source; evaluators are absent. No model calls or new downloads.

Eight retained-data behaviors passed, including a real 10×10 native fill corner entirely within the grid that is now unresolved before approval, and source/approval schema migration. July 15 explicit-partial output remains incomplete with corrected denominator; July 8 remains verified with numerical grade checks-passed. The same-agent separate-array checker matched requested/grid/acquired counts, masks, values and uncertainty statistics. All five pre-existing analytical GeoTIFFs are byte-identical to their earlier runs; only the new acquired-support mask/report/schema evidence is added.

For July 8, ST_QA before filtering has **331,607 known / 0 missing**, minimum **2.04 K**, maximum 6.57 K, mean 2.62898941 K. Linear percentiles P05/P25/P50/P75/P95 are **2.11 / 2.21 / 2.41 / 2.95 / 3.54 K**. Known-value proportions strictly above 2/3/4 K are **100% / 22.5203% / 2.7246%**.

Diagnostic preflights at 2/3/4 K retained **0 / 256,928 / 322,572** pixels, respectively, or **0% / 75.6739% / 95.0082%** of acquired centres. At the unchanged .60 minimum, the 2 K scenario is unresolved before approval; 3/4 K are ready for review. **No filtered run was approved and no cutoff was selected as a default/recommendation.** These scenarios illustrate the user-requested contract, not a new scientific policy.

The independent pre-correction count script, original datasets/candidate wheels and old review page remain unchanged. The corrected review packet is `D:\AgentLayer-acl-recovery\scientific-workflow-acquisition-fix-2026-11-03\REVIEW.html`; it links all cases, independent counts, optional-cutoff preflights, and corrected reports. The new scripts are not blinded or expert-independent, and the source ranking used known development data. Reviewer-kind declarations do not solve identity authentication; the product makes no such claim.

### Subsequent reviewer correction: unconditional quality admission

The 6417983 implementation above incorrectly bypassed preapproval `min_valid_fraction` when the optional uncertainty field was absent. The follow-up removes that bypass and uses `base_valid_count` in the no-cutoff case. Error/recovery messages now describe general usable coverage. Earlier incomplete-run artifacts are preserved under their original candidate; newly reviewed equivalent insufficient intents are now unresolved before approval.

Regression coverage pairs no cutoff with an explicit 1000 K nonbinding cutoff on entirely known 2 K uncertainty, at both sufficient and insufficient quality thresholds. Both have exactly 10 base/retained pixels out of 12 acquired, no uncertainty exclusions, identical plan status, and the insufficient cases refuse approval and consistent-record execution/repair bypasses. Tests for zero usable pixels and explicit partial requests now require preapproval refusal rather than an incomplete run.

Follow-up validation: **105 workflow/source tests passed**. Retained July 15 data now yields unresolved both without a cutoff and with the nonbinding 1000 K bound (3,273/100,110); July 8 remains ready in both (331,607/339,520). No approvals, analysis runs or source modifications were made by this follow-up check. Evidence: `quality-gate-followup/result.json` and `quality-gate-regression.log` under the correction evidence root above. The earlier full-suite result belongs to commit 6417983; it was not rerun or relabelled for this small follow-up.
