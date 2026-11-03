# Native Landsat workflow: real-scene engineering experiment

Date: 2026-11-03. Local branch: `Geova/scientific-workflow-core`. No publication or model calls. This experiment is separate from the frozen Phase 11 agent trial and uses none of its outputs.

## Outcome

The first real-scene run exposed a genuine AOI boundary bug that the workflow's own verifier had missed. After a source-coordinate membership correction, the **same scene, intent, QA policy and unchanged independent checker** agreed on all delivered pixel support, values, uncertainty and summary statistics. A separate explicitly injected unit error was detected and repaired in one regeneration, retaining the wrong copy.

This demonstrates one complete native-product processing route on one real scene. It does not establish general accuracy, independently validate the upstream thermal retrieval, or demonstrate an organic agent save.

## Protocol and provenance

The selection and policy were recorded before downloading pixels in the external `PROTOCOL.md`:

- WGS84 rectangle: longitude 32.55–32.75, latitude 25.65–25.85, near Luxor, Egypt; supplied as KMZ.
- July 2023; latest eligible Landsat 8/9 L2SP acquisition intersecting the AOI, reported scene cloud below 10%, with native temperature, QA, uncertainty and metadata assets. Selection did not use the workflow's success.
- Planetary Computer catalog item: `LC09_L2SP_175042_20230731_02_T1`; USGS product: `LC09_L2SP_175042_20230731_20230802_02_T1`.
- Acquisition: `2023-07-31T08:18:33.968715Z`. Scene cloud metadata was 0%; that is not proof of AOI cloud freedom.
- Native assets: 7801 columns × 7651 rows, EPSG:32636. Temperature and QA_PIXEL are uint16; ST_QA is int16. No metadata rewriting, raster reprojection, analytical resampling or gap filling.
- Temperature: native DN × 0.00341802 + 149 K, then subtract 273.15. Uncertainty magnitude: ST_QA × 0.01 K; never subtract a Celsius offset.
- Reject QA_PIXEL bits 0, 1, 2, 3, 4, 5, 7. Snow/water exclusion is an explicit terrestrial demonstration choice. Minimum usable fraction: 0.60 of AOI-selected centres within the scene.
- Review was disclosed as engineering review by the implementation agent. Independent human scientific review remains pending.

The catalogued JSON MTL returned 404; the original TXT MTL for the **same scene** was available and supported. This format fallback was recorded before pixels. Downloads used public anonymous, expiring Planetary Computer access; signed tokens were not retained or printed. Four complete original assets totalled **100,206,029 bytes**, below the 512 MiB cap.

All filenames have prefix `LC09_L2SP_175042_20230731_20230802_02_T1_`:

| Suffix | Bytes | SHA-256 |
| --- | ---: | --- |
| MTL.txt | 15,257 | `e3f32bd24a3b177aa011d869623ffca03ac382afa34b13c45ecc29899f76c456` |
| ST_B10.TIF | 83,441,225 | `45ec8ae7cfb69fe2345a2f9db38a131051c448ca2f302d983b0de239c0405ff1` |
| QA_PIXEL.TIF | 399,525 | `a33010d0df796e69f4c4180e973ce48fc92bb9378aab149d1861a2ca630afd73` |
| ST_QA.TIF | 16,350,022 | `9c1e68d2a4bdaf351b99e3bb1e479a0d4d6b63b99592da53870659a8f4d44663` |

Unsigned asset URLs and original STAC metadata are retained in the external evidence. Sources and scientific references: [attribution](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature).

## Baseline failure: retain it as a failure

Baseline source commit: `ca235406048ea5d40748b9c8179467d715deadbd`; installed candidate wheel SHA-256: `ffab59e1fb2264a7ef90b55290f0ed01efab84a10ac27c3217b2b80420d83846`.

The workflow returned `verified` / `decision-grade`. The independent checker rejected it:

- **102 incorrect AOI membership cells**, also affecting usable and uncertainty support.
- Selected cells: 493,543 instead of 493,549; usable cells: 480,619 instead of 480,625.
- Mean: 45.83108041708678 °C instead of 45.8302683476551 °C.
- Temperature decoding itself agreed on jointly selected valid cells.

Only polygon vertices had been projected into UTM. Straight edges in the geographic input became incorrect straight chords in UTM, changing boundary membership. Producer and verifier shared the same geometry assumption, so their agreement was false assurance. The effect on this scene's mean was small; the semantic error is still real. The baseline directory, wheel, interpreter, outputs and failing independent result are preserved, not relabelled as passing.

Correction commit: **`753dc42`**. Pixel centres are now transformed into the original AOI CRS and tested against its polygon, including boundary centres. A densified projected outline is used for crop/display only, with a one-pixel cross-CRS crop margin. Regression tests independently compute whole-scene membership and cover native-CRS centres exactly on a boundary.

## Corrected result

Corrected candidate wheel SHA-256: `70a6d83c8cff75bf4025f3d7b8ea6dd1a02777bc23dc1d089e80265c53634f97`. It was installed in a new product-only interpreter; evaluators are absent and workflow/CLI bytes match the source after CRLF normalization. Both candidate wheels carry the internal 0.12.0 label; **neither is the published v0.12.0 artifact**.

The checker imports no Terraproof code. It derives every cropped pixel's longitude/latitude from the original native grid, uses direct rectangle comparisons, the fixed bitmask `0xBF`, and independent arithmetic `DN × 0.00341802 − 124.15`. It compares masks, uncertainties, labels and summaries and tests a neighbouring ring outside the delivered crop. Its SHA-256 remained `eb8ed86993238b6ffb8a962a1f87fcb02d4f71fed6b10a42ac636a21a3ff85d5` through baseline, corrected, corrupted and repaired runs. This is a separate implementation by the same agent, **not independent expert review**.

| Measurement | Corrected result |
| --- | ---: |
| AOI-selected centres | 493,549 |
| Usable temperature / uncertainty cells | 480,625 |
| Usable fraction within scene | 97.381415% |
| Outside-scene fraction (native plane) | 0 |
| Mean surface temperature | 45.83026835 °C |
| Range | 27.24094184–59.36691182 °C |
| Mean product uncertainty magnitude | 2.20029576 K |
| AOI / support / uncertainty mismatches | 0 / 0 / 0 |
| Maximum temperature arithmetic difference | 0.0000019073 °C |
| Independent requirements passed | 9 / 9 |

The arithmetic difference is within float32 storage precision. These are acquisition-time **surface**, not air, temperatures. The uncertainty magnitude is an upstream product measure, not uncertainty of the spatial mean. The PNG thumbnail was visually inspected; visual plausibility was not used as an acceptance oracle. The complete SVG includes the AOI, legend, source/date and limitations.

## Injected repair, separately labelled

A copy of the corrected run had **273.15 added to all 480,625 valid temperature pixels**. No source, policy, approval or other output was changed. The product rejected it with 480,625 numerical mismatches, including when manifest checking was disabled. The independent checker also rejected the temperature values (maximum error about 273.150016 °C).

One regeneration into a new directory returned `verified` and independently passed all 9 requirements with zero support errors. The original good run and native assets remained unchanged; the corrupted copy was retained and still failed. This tests deterministic detection/regeneration, not arbitrary script repair or a naturally observed agent mistake.

## Reproduction and evidence

Local evidence root:

```text
D:\AgentLayer-acl-recovery\scientific-workflow-real-scene-2026-11-03
```

It retains `PROTOCOL.md`, `fetch.py`, `catalog-item.json`, `fetch-manifest.json`, original inputs, unchanged `workflow.json`/KMZ, both approvals and candidate records, `run_original.py`, `run_v2.py`, the unchanged `independent_check.py`, all four run directories, per-run independent JSON, logs and `injected-repair.json`. Source hashes are checked again before/after rerun and repair. The installed candidate environments reuse existing dependency directories read-only; this is not a clean network dependency-resolution claim.

To replay the independent arithmetic on a retained directory, from that evidence root:

```powershell
.\installed-v2\Scripts\python.exe -I .\independent_check.py .\run-v2
.\installed-v2\Scripts\python.exe -I .\independent_check.py .\corrupted-copy
.\installed-v2\Scripts\python.exe -I .\independent_check.py .\repaired
```

Read the JSON `passed` field: the observational checker prints a failure receipt without a nonzero exit code. Rerunning it replaces that directory's independent receipt, not analytical outputs. Processing commands deliberately refuse existing destinations.

Targeted workflow regression: **38 passed**. Complete regression at correction commit `753dc42`: **2016 passed, 13 skipped**, in 502.89 seconds (`full-suite-v2.log`). Router: **87/87**, deterministic; repository integrity/link validation passed. No existing assertion was weakened. Subsequent changes only record these results and attribution.

## Remaining gates

- Independent scientific review of source identity, QA choice, quantity, coverage and uncertainty meaning.
- Additional predeclared scenes/regions and unsupported-boundary cases before generalizing beyond this one scene. The finite crop-outline densification/margin is not a proof for arbitrary projection singularities; antimeridian AOIs remain unsupported.
- No claim of validated atmospheric correction, emissivity, QA truth, absolute physical accuracy, comparative model benefit or autonomous scientific approval.
- No push, PR, merge, release, active-trial edits or permission/security-label changes were performed. Integration with the Phase 11 branch waits for its frozen trial to close.
