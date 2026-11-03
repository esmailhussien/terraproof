# Scientific boundaries and additional real-data cases

**Coverage erratum:** native-plane source fractions in this historical record measure grid rectangles, not acquired image support. The [schema-3 correction](SCIENTIFIC_ACQUISITION_UNCERTAINTY.md) separates grid, QA acquisition and usable-pixel denominators and fixes admission before approval. Original artifacts remain unchanged.

Date: 2026-11-03. This is a primary-source engineering review by the implementation agent, **not independent scientific approval**. No model calls, active Phase 11 data, production code changes or publication were used in this batch.

## Review conclusion

The native-product route is useful for reproducible preparation, numeric verification and regeneration of derived outputs. It cannot establish upstream temperature truth from the same source. The additional cases support the implemented handling of holes, source clipping, unsupported regions and inadequate usable observations. They also expose a product-design boundary: **correct calculations within a scene do not establish that the requested AOI is completely covered**.

Independent scientific review is still pending. The next implementation batch should make AOI completeness an explicit scientific requirement and show result/coverage status directly in delivered reports. This must be a separately identified configuration, with compatibility and additional tests; do not retroactively regrade the frozen runs here.

## Primary-source review

| Topic | Assessment and boundary |
| --- | --- |
| Quantity | This is acquisition-time land surface temperature. It must not be described as air temperature, daily maximum or a heat-risk class. |
| Preparation/correction | The admitted input is a USGS Level-2 ST retrieval. Decoding the stored DN is necessary; reapplying an unspecified atmospheric correction is not justified by this route. |
| Missing observations | Missing ASTER emissivity can leave ST gaps. Retaining those gaps is correct source handling; inventing replacement values would require another reviewed method. |
| Cloud screening | QA_PIXEL bit rejection is an explicit engineering policy. It does not independently validate cloud truth or correct cloud-adjacency retrieval error. |
| Emissivity | USGS documents an emissivity vegetation-adjustment anomaly, particularly relevant to changed land cover. A passing decode cannot rule this out. No such error was established or corrected in our Luxor scene. |
| Product uncertainty | Preserve ST_QA as a difference magnitude. Its mean is not uncertainty of the spatial mean, a field-calibration result or proof of a universal error bound. |
| AOI and coverage | The denominator is selected pixel centres within the native scene. The separately reported native-plane outside-scene fraction is not a geodesic usable-area estimate. |
| Authority | Source hashes, metadata agreement and unsigned approvals provide consistency, not authenticated scientific approval. A separate numeric implementation is not independent expert review. |

The quantity, existing Level-2 retrieval and missing/cloud caveats are described by [USGS Surface Temperature guidance](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature). The emissivity and blockiness limitations are documented in [USGS Collection 2 known issues](https://www.usgs.gov/landsat-missions/landsat-collection-2-known-issues). Native encodings/QA references remain in the [attribution registry](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature). The implications for Terraproof's scope above are this review's assessment, not an endorsement by USGS.

## Fixed batch and candidate

Protocol was written before selecting the new scene or downloading its pixels. The original six cases, frozen intent files, QA policy, source bytes and product candidate were retained throughout. Existing Luxor data were read without changing the prior experiment.

- Product correction commit: `753dc42`; wheel SHA-256 `70a6d83c8cff75bf4025f3d7b8ea6dd1a02777bc23dc1d089e80265c53634f97`. The isolated product-only interpreter is unchanged. The internal wheel version label 0.12.0 is not the published artifact.
- Existing scene: Landsat 9, Luxor, 2023-07-31, as in the [first real-scene record](SCIENTIFIC_WORKFLOW_REAL_SCENE_2026-11-03.md).
- New source: Landsat 8 product `LC08_L2SP_199023_20230715_20230724_02_T1`, acquisition `2023-07-15T10:39:20.609064Z`, reported scene cloud **48.99%**. Native grid: 7981 rows × 7881 columns, EPSG:32631.
- Selection: earliest acquisition, then item ID, among July 2023 Landsat 8 L2SP scenes intersecting WGS84 [4.9,51.9,5.1,52.1], scene cloud 20–80%, with all four required assets. Fifteen metadata items yielded three eligible scenes. The first was used; no outcome-driven replacement.
- Native MTL TXT, ST_B10, QA_PIXEL and ST_QA totalled **127,455,522 bytes**, below the 512 MiB cap. Original USGS assets were publicly distributed through Microsoft Planetary Computer; unsigned URLs, original metadata and hashes are retained. No source rewriting or dependency changes.
- All runs retain Celsius ST, July 2023, reject QA bits 0,1,2,3,4,5,7, no analytical resampling and no gap fill.

## Outcomes

| Case | Selected / valid centres | Product verdict | Independently assessed behavior |
| --- | ---: | --- | --- |
| B1: Luxor WGS84 rectangle with rectangular hole | 449,159 / 439,764 | verified | Hole/outer membership, all values, uncertainty and counts agree; 97.9083% usable within scene |
| B2: Luxor native rectangle crossing source edge | 769,026 / 638,974 | verified | 83.0887% usable within scene; outside-scene fraction correctly reports **1/6** |
| B3: no overlap, WGS84 [0,0,0.1,0.1] | — | unresolved | Refused before approval/execution; no output run |
| B4: antimeridian polygon | — | unresolved | Explicit unsupported-antimeridian refusal before execution |
| B5: new Netherlands scene, minimum 0.60 | 150,391 / 3,273 | incomplete | Only **2.1763%** usable within scene; **55.7045%** of AOI geometry outside source |
| B6: same source/AOI, minimum 1.0 | 150,391 / 3,273 | incomplete | Same correct support; repair refused to weaken the reviewed coverage requirement |

Each executed case was independently checked by scanning **every centre in its entire original source grid** in bounded windows, not just the delivered crop or an exterior ring. Direct rectangle/hole predicates in the original AOI CRS avoid producer geometry helpers. Checks cover omitted selected centres, native crop/grid, masks, temperature, uncertainty, units, statistics and coverage verdict. No selected centres were omitted; all final pixel/count/value comparisons agreed. Maximum temperature arithmetic difference was below 0.000002 °C.

The two incomplete runs are successful handling of insufficient observations, **not successful scientific maps of the requested AOI**. Their reported mean describes a small selected remnant and should not be presented as an estimate for the entire area. Scene cloud percentage alone did not determine acceptance.

## Preserve the two experiment-implementation errors

These corrections are disclosed rather than claiming an untouched six-of-six first-pass result:

1. The initial metadata selector used nonexistent `landsat:processing_level` instead of this catalog's `landsat:correction`. It incorrectly recorded zero eligible scenes. Before any new pixel download, the field was corrected using the same retained catalog response; location/date/cloud/platform/sort rules were unchanged. The initial script and receipt remain available.
2. The initial independent oracle incorrectly assumed zero outside-scene fraction for the new geographic rectangle merely because the catalog returned an intersecting scene. This was wrong: the scene's lower edge cuts the AOI. The initial batch returned **four accepted cases and two oracle failures**. In both failures the product had correctly reported its geometric outside fraction and `incomplete`; the sole failing oracle obligation was the erroneous expected outside fraction, not pixels, values, counts or verdict.

An independent Sutherland–Hodgman clip plus translated shoelace area calculation projected the declared rectangle into the native grid and measured the intersection. Densification from 512 to 8192 segments per edge converged from 0.5570450507648192 to **0.5570450513018439** outside fraction, within the fixed 1e-8 tolerance. The product reported 0.5570450511691647.

The original oracle, case file and failing receipts are unchanged. A second oracle version changes only the case-file/receipt names; the second case file changes only the two expected outside-fraction facts. No product output, policy, source or pixel acceptance threshold changed. The correction was recorded **after the B5 product result existed and before B6's result existed**, so this is explicitly an amended analysis, not a claim of blinded, entirely preregistered success. Both corrected independent checks pass. All six behaviors agree with the disclosed requirements after this oracle correction; that statement does not erase the first-pass failures.

## Supplemental checker controls

After the cohort, a separate control protocol was registered before making control copies. The same corrected oracle accepted an unchanged B1 copy, rejected a single flipped AOI pixel specifically on `aoi`, and rejected a valid temperature changed to NaN specifically on `temperature`. All **three control expectations** passed. They are checker reliability tests, not three extra cohort successes, product repairs or new native scenes. Original good artifacts were not modified.

## Evidence and reproduction

Evidence root:

```text
D:\AgentLayer-acl-recovery\scientific-workflow-batch-2026-11-03
```

It retains `PROTOCOL.md`, `freeze.json`, both selector versions/receipts, catalog search/selection, original downloaded inputs and hashes, all six intent/plan/receipt directories, four product outputs, original/corrected independent receipts, `coverage_amendment.py`/`coverage-amendment.json`, both oracle versions/case files, supplemental controls and the final audited summary/inventory.

The frozen original runner's nonzero completion and `batch-result.json` are retained as failures, not overwritten. The final audited summary separately records the original four-of-six result, the justified oracle correction, final per-case outcomes and controls. Replay into new receipt destinations or inspect the retained JSON; original processing destinations deliberately refuse overwrite. The corrected checker exits 3 on a failed comparison. The original whole-scene checker SHA-256 is `3428c984df8c8e00bb716cc1781f1575f5602c45a0fbaeb68ea3efb880eb154b`; corrected wrapper SHA-256 is `487e135be2deb727d35b8e776ef987c6e927765e7ef61176203585083edeaf60`.

No production Python changed in this batch. The earlier **2016 passed, 13 skipped** regression belongs to correction commit 753dc42; it was not rerun or relabelled as a new run here. This batch adds real-data checks, controls and documentation. Repository documentation validation is recorded separately.

## Next coherent implementation batch

1. Make **whole-AOI scene coverage** a reviewed requirement separate from usable QA coverage inside the scene. Recommended default for a future user-facing route: require full requested area, with partial delivery only by an explicit choice. User preference and compatibility must be recorded before choosing the API/default; the current batch remains frozen.
2. Make `verified`/`incomplete`/`failed`, requested-area coverage, usable coverage and quantity scope visible directly in the HTML/map delivery. They currently require reading the linked machine report and summary; that is insufficient for a future interactive scientific workflow.
3. When coverage is insufficient, propose a new source/scene or explicitly changed scientific intent for review. Never present lowering QA, inventing temperature, filling gaps, or silently combining acquisition dates as repair of the same approved measurement.
4. Obtain independent scientific review of those requirements and a concrete intended study before release. Atmospheric retrieval, emissivity correction, multi-date compositing and sensor expansion remain separate scientific routes.

This direction improves the chance of delivering a scientifically suitable output while retaining truthful limits, instead of treating a file-validity check as proof of complete analysis. No push, PR, merge, release or active Phase 11 changes were performed.
