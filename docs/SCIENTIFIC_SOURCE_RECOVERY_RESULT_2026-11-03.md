# Public source recovery: Netherlands July 2023

Date: 2026-11-03. Local implementation commit `241397379dde0da2ad89b89bdbd64126085e0d62`. This is an engineering demonstration on a previously studied region/period, not a blinded benchmark. The user authorized the source-selection/completion workstream and will review the result. No user or independent scientific approval is claimed yet.

## Practical outcome

The new [source-selection route](SCIENTIFIC_SOURCE_RECOVERY.md) searched 15 catalog scenes, retained three eligible full-footprint alternatives, selected exactly metadata rank 1 under a predeclared order, acquired its native files, passed local source admission, then produced a verified full-AOI result under unchanged scientific requirements.

| Measure | Earlier unsuitable source | Newly selected source |
| --- | --- | --- |
| Acquisition date | 2023-07-15 | **2023-07-08** |
| Requested AOI inside native scene footprint | 44.2955% | **100%** |
| Usable observations within scene after the same QA policy | 2.1763% | **97.6694%** |
| Default full-coverage acceptance | unresolved before processing | verified after native-data approval and processing |
| Explicitly partial earlier result | incomplete | full coverage; no partial exception needed |

These are different observations within the same requested month. This is recovery of a suitable source for that allowed request, **not correction of the July 15 observation, a temperature-accuracy comparison, a temporal average or a mosaic**. Scene footprint fraction and usable within-scene fraction have different denominators and must remain separate.

## Fixed request and selection

- Netherlands WGS84 rectangle: longitude 4.9–5.1, latitude 51.9–52.1.
- Acquisition interval July 1–31 2023, inclusive. Land surface temperature in Celsius; full AOI by default.
- Reject QA_PIXEL bits 0,1,2,3,4,5,7; minimum usable within-scene fraction 0.60; no analytical resampling/gap fill.
- Both supported Landsat 8/9 L2SP platforms allowed; reported scene cloud limit 100%. Lowest reported cloud, then latest acquisition, then item ID among eligible footprints. No pixel-based reselection or fallback.
- Fixed protocol/candidate/input hashes were retained before live calls. The known region/period is development data, not a new held-out cohort.

The selected item was `LC08_L2SP_198024_20230708_02_T1`, acquisition `2023-07-08T10:33:32.143343Z`, scene cloud metadata 0.23%. Other eligible alternatives were July 24 Landsat 8 (39.6% scene cloud) and July 16 Landsat 9 (81.88%). Scenes with lower cloud metadata but incomplete AOI footprints were rejected; low cloud alone did not win. Unsupported Landsat 7 scenes were also retained with rejection reasons.

Native product: **`LC08_L2SP_198024_20230708_20230718_02_T1`**, USGS Landsat 8 Collection 2 L2SP, publicly distributed by Microsoft Planetary Computer. Four complete original assets totalled **120,640,169 bytes**, below the 512 MiB cap. No metadata/source pixel rewriting, account credentials or signed URL retention. Downloaded native identity/date/sensor and actual scene coverage were rechecked; catalog coverage was not accepted as proof.

## Numerical and engineering evidence

- Selected AOI centres: **339,520**. Valid temperature/uncertainty centres: **331,607**. Outside-scene native-plane fraction: **0**.
- Reported product-decode mean surface temperature: 34.77703824 °C; range 23.88102818–54.51674144 °C. Mean upstream uncertainty magnitude: 2.62898941 K, not uncertainty of that spatial mean.
- The retained checker scanned all **61,478,781 original source-grid centres**, using original-coordinate rectangle membership and independent DN/bit/uncertainty arithmetic. All ten obligations passed, including no omitted selected centres, exact masks/counts, native crop, statistics and coverage verdict. Maximum temperature arithmetic difference: **0.0000019073 °C**.
- Checker SHA-256 remained `487e135be2deb727d35b8e776ef987c6e927765e7ef61176203585083edeaf60`. Its prior geometric-oracle amendment is disclosed in the [boundary review](SCIENTIFIC_WORKFLOW_BOUNDARY_REVIEW_2026-11-03.md); there was no new oracle modification here.
- The installed product contains no evaluators and its workflow/CLI module bytes match source after CRLF normalization. Internal 0.12.0 wheel label, **not the published v0.12.0 artifact**. Wheel SHA-256: `fea5ee99b9a0d2e0c4a94fc632fe4abb822ca78e63bb38ce38b19e8dc4092ca1`.
- Existing workflow tests: **55 passed**; new source-route tests: **25 passed**. Full repository suite at commit 2413973: **2058 passed, 13 skipped**, 474.66 seconds. Tests cover deterministic ranking, polygon/full/partial eligibility, native end-to-end acquisition/processing, changed evidence/intent/AOI rejection, incomplete search, byte caps, transient-link redaction, network failures and contradictory native identity.
- Actual installed source CLI draft creation and rejection of an unreviewed acquisition digest passed without extra downloads. Visual QA covered source alternatives, recovered map and the human review page.

The processing approval explicitly records implementation-agent engineering review with user scientific review pending. Product `verified` is source-relative numerical/support verification; `physical_accuracy_validated` remains false.

## Review packet and reproduction

```text
D:\AgentLayer-acl-recovery\scientific-workflow-source-recovery-2026-11-03
```

Start with **`REVIEW.html`**. It links the full alternatives/rejections, selected native source package and plan, generated map/report/statistics, unchanged independent check, machine outcome and candidate identity. A presentation-only wording clarification changed “date” to “acquisition-window” to distinguish the changed observation from the unchanged request; original `REVIEW-initial.html` and both hashes are retained. It did not change source selection, processing or measurements.

The evidence directory also retains the preregistered protocol, frozen request/AOI/script/candidate identities, metadata snapshots/report digest, explicit selection recorded before pixels, original native downloads and checksums, native scientific plan, disclosed engineering approval, analytic artifacts, regression logs and final audited inventory. Original earlier experiments and the active Phase 11 trial were not modified. Existing destination directories are refused; reproduce processing into new directories using the documented CLI and new review, not by overwriting evidence.

## What the user should review

1. Whether **July 8** is a suitable observation for the intended study within July; it is not interchangeable with a fixed-day requirement.
2. Whether the AOI and terrestrial water/snow/cloud exclusions are appropriate, and the remaining missing observations acceptable.
3. Whether the quantity, upstream uncertainty and retrieval caveats fit the study. Surface temperature is not air temperature, and source-relative verification cannot validate upstream atmosphere/emissivity/QA truth.

No model calls, push, PR, merge or release. No automatic multi-date compositing or QA relaxation. This one development example supports usefulness of the source-recovery route, not broad scientific accuracy or comparative agent benefit. Dataset attribution and access references are in [sources/SOURCES.md](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature).
