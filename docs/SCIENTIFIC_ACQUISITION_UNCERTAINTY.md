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
- Apply `min_valid_fraction` to the retained/acquired population after those exclusions. An active cutoff that leaves inadequate support is unresolved **before approval**, not a failed experiment followed by a silently relaxed threshold.
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
