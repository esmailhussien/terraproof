# Separate-context scientific workflow acceptance

2026-11-03. The user requested a different reviewer to choose/write the test regions. One separate AI reviewer chose three new regions, fixed five workflow variants, and retained assessment criteria before native image/header access. The implementation candidate was frozen first at `77ce7aea9798f3622cec46d019a8267b52fb558a`. No product code, source choice, window, QA policy, date or threshold was changed to pass these cases.

**Result: all three prior main targets and all five variants passed bounded numerical/engineering acceptance.** The reviewer performed 346 final evidence comparisons with zero final failures. This number is not a test-suite size or model benchmark. Human scientific suitability and absolute physical accuracy were not established.

## Fixed requests and observed outcomes

All requests use native Landsat 8/9 Collection 2 Level-2 Surface Temperature, Celsius, QA_PIXEL rejection bits `[0,1,2,3,4,5,7]`, and omit `scene_coverage` to exercise the full-AOI default. Uncertainty exclusion is absent unless explicitly listed. These are single acquisitions, not monthly estimates.

| Variant | Fixed item / AOI | Independent native evidence | Outcome |
| --- | --- | --- | --- |
| R1-full | `LC08_L2SP_037037_20240616_02_T1`; Phoenix, WGS84 bbox `[-112.09,33.43,-112.05,33.47]`; June 2024; minimum .90 | 18,318 requested/acquired, 18,309 usable (99.950868%) | Admitted, engineering self-approved, delivered and verified; grade `checks-passed` |
| R2-corner-default | `LC09_L2SP_175083_20240208_02_T1`; fixed native northwest 10×10 corner; minimum .90; no cutoff | Exactly 100 requested in-grid centres, all QA fill; 0 acquired/usable | Unresolved before approval; no output |
| R2-corner-cutoff | Same frozen corner, explicit 2 K | Same 100 centres and zero acquisition support | Unresolved before approval; no output |
| R3-baseline | `LC08_L2SP_089079_20240831_02_T1`; Brisbane, WGS84 bbox `[153.01,-27.49,153.05,-27.45]`; August 2024; minimum .75 | 19,416 requested/acquired, 17,105 usable (88.097445%) | Admitted, engineering self-approved, delivered and verified; grade `checks-passed` |
| R3-strict | Same Brisbane AOI, explicit .005 K | All 17,105 base-usable candidates above the limit; 0 unknown exclusions and 0 retained | Unresolved before approval; no output |

The .005 K requirement deliberately stresses admission below the native .01 K uncertainty quantization; it is not a scientific recommendation. There was no automatic cutoff, QA relaxation, replacement scene or fallback.

The Cape Town source-search rectangle was `[18.40,-33.95,18.44,-33.91]`, February 2024, maximum scene cloud 20%. Its diagnostic corner was derived from the actual native header, with each native edge densified at .25-pixel intervals before WGS84 transformation, and frozen before corner pixel inspection. A pre-execution public clarification allowed unchanged acquire() to preflight the **separate search AOI** after scene selection. Other source-search cloud maxima were 10%. This procedural clarification amended the public document before execution, without changing sources, regions, windows, scientific requirements or criteria.

## Numerical evidence

The standalone reviewer checker imports no Terraproof code and does not use implementer count/statistic files as an oracle. It independently checked metadata eligibility/ranking, fixed asset identity, native headers/MTL groups, pixel-centre AOI membership, QA acquisition, validity, temperature scaling, uncertainty and provenance.

| Delivered result | Independent equal-pixel mean / range (C) | Product uncertainty mean / range (K) | Maximum delivered Celsius error against native decode |
| --- | --- | --- | --- |
| Phoenix | 57.9203635278 / 49.67682512–63.23611046 | 1.6600284013 / 1.58–3.24 | 0.000001906758 C |
| Brisbane | 32.0331001978 / 24.16130582–37.43347748 | 3.9072879275 / 2.53–6.04 | 0.000001906123 C |

AOI/acquisition/validity masks, uncertainty rasters, known/missing counts, percentiles and tails above 2/3/4 K agreed. Every valid cell of the full native decoded intermediates was also compared: 40,563,785 Phoenix and 39,872,406 Brisbane cells. Celsius tolerance was 1e-4 C, full-precision uncertainty summary tolerance 1e-8 K, admission fraction tolerance 1e-12, and integer counts were exact. Float32 uncertainty rasters were compared to their exact representable decoded float32 values; cutoff membership was not relaxed.

Both approvals declare `engineering-self-review` and `identity_authenticated: false`. Both delivered runs declare `physical_accuracy_validated: false`, numerical verification, single-acquisition scope and no scientific certification. None of the three unresolved variants has an approval or output. These observations are not a security/bypass-resistance test.

## Qualifications retained by the reviewer

- Unknown-uncertainty exclusion among otherwise usable candidates is **unexercised**: both useful AOIs contain zero such candidates. The fill corner's missing temperature/acquisition cannot substitute for this condition.
- Exact cutoff equality, a mixed retained/excluded uncertainty population, explicit partial delivery, out-of-grid requested centres and ranking ties were not exercised by this new batch. Existing regression/development evidence remains separate.
- The corner polygon's native roundtrip error was at most `4.65661287308e-11` pixel. Independent continuous area outside the ideal native footprint was `9.76530524591e-08` square metres. The product reports continuous outside fraction `1.75004699621e-9` and `grid_extent_covers_aoi: false`, while all 100 requested centres are in-grid. Correct refusal explicitly reports zero QA acquisition; this case does not isolate rejection causally from the continuous-extent predicate. No output was affected.
- Selection/criteria were written before native access, but the executable oracle was written after outcome freeze. This is separate AI-context review with prior criteria, not human expertise, cryptographic blinding or a fully blinded prewritten executable oracle.
- The first checker and evidence are preserved. Ten initial false comparison failures came from the checker flattening repeated MTL L1/L2 keys, assuming QA_PIXEL TIFF nodata 1 rather than actual absent nodata plus bit-0 semantics, and expecting the literal machine grade in the displayed numerical verification label. The corrected parser/interpretations and later provenance checks are disclosed; scientific formulas, criteria and tolerances were not changed. Do not describe this as a clean first-pass executable-oracle result.

## Frozen candidate, integrity and resources

- Product-only wheel SHA256: `c8e9fe9e5791c2becc6501f94aed88b98d733709e8d35bb6eb0a582c31e195d1`. Workflow/CLI bytes match the source; evaluators are absent. Its internal 0.12.0 label does not identify the published release artifact.
- Fresh full regression at `77ce7ae`: **2083 passed, 13 skipped**, 495.22 seconds. Affected workflow/source coverage is 105 tests. Repository validation passed; router code was unchanged (prior 87/87 evidence remains separate).
- Twelve fixed native files transferred **323,321,401 bytes (308.34 MiB)**, below the predeclared 512 MiB aggregate ceiling; zero retries/substitutions. All twelve anonymous HEAD lengths were checked before downloading, then exact per-case caps applied.
- All 119 outcome-inventory records and all 10 original reviewer-manifest members matched retained hashes. Outcome freeze SHA256: `779cc90c9aaf816cf5e5c41e4fc79202cae36d8656fa82a934604241ad6b67ea`.
- Original criteria JSON SHA256: `1b5111cdafdaf194b9f7399eff0d86945383c6ffffc6bcb7507fc35677f0b980`. Final public cases SHA256: `ae6a5051d5c56ad964cc254f10ea1094a10dbd2455a2d89c1ffc8319706b6621`.
- Assessment Markdown SHA256: `bc2635a036595da185d2736ee0fb1ffb3c0def066a867fdcb51afa31636e3d60`; JSON: `0ae30468a91b41ca0af56634087c46f99212a91d8161d60f672ef133a25e0c4e`.

Local evidence root: `D:\AgentLayer-acl-recovery\scientific-workflow-independent-acceptance-2026-11-03`. `REVIEW.html` links public requests, original outcomes, raw assets and delivered maps; `reviewer/ASSESSMENT.md`, `ASSESSMENT.json`, original/corrected checkers and evidence retain the separate assessment. Native imagery and interpreter/browser environments are external evidence, not repository payload.

No external model-host/API evaluation, active Phase 11 access, permission/ownership change, push, merge or release was performed. Source attribution and meaning remain those recorded in [scientific workflows](SCIENTIFIC_WORKFLOWS.md) and [sources](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature). The next step is review of this coherent local candidate, not a claim of general scientific correctness or immediate publication.
