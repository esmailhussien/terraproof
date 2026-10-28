# Terraproof — Phase 7 Plan: Say what was verified

> Status: **in progress (2026-10-28)**. V0 is sealed, and V1 (grade and coverage) and V2/V3 (goal profiles, `raster.vertical_units`, `raster.nodata_support`) are implemented; known gaps are listed in the V2/V3 record. V4 was measured once on the sealed cases (acceptance not met; see the V4 record). It follows the [Phase 6 stop](Terraproof_Phase6_PLAN.md#e4-and-e5-record-2026-10-28-stop) and its [verification audit](../PHASE6_VERIFICATION_AUDIT.md). No model calls are planned.

## 1. Why this phase

Phase 6 did not measure agent lift: on MiMo-V2.6-Flash the confirmation cohort kept 6 tasks, short of the 8 required. It did measure the product's verification on its own terms, and the result is the reason for this phase.

- **Development set.** The configured checking path detected 0/21 seeded mistakes and 0/2 live mistakes.
- **Confirmation set.** It detected 0/8 live mistakes.
- **What ran.** Every artifact got the same three generic checks: `crs.defined`, `raster.nodata_declared` and `raster.cog_layout`.
- **The grade.** All of those wrong artifacts were graded `decision-grade`, the strongest grade, with exit code 0.

Two causes are separable:

1. **The grade overclaims.** `grade_for` gives `decision-grade` whenever every check that ran passed, so it describes the checks that ran, not the output. Coverage is assessed only when a verification contract is supplied, and none was.
2. **Relevant checks were not invoked, or do not exist.**

   | Trap family (wrong artifacts) | Check status |
   | --- | --- |
   | QA masking (3) | `rs.cloud_mask_applied` exists, never invoked |
   | Scale and offset (1) | `rs.scale_applied_once` exists, never invoked |
   | Metric work in a geographic CRS (1) | `crs.metric_operation` and `terrain.slope_*` exist, never invoked |
   | Vertical units (2) | **no check exists** |
   | Nodata stored as zero (1) | `raster.nodata_declared` sees only the declaration, **not the delivered mask against the source support** |

The aim of this phase is narrow: a Terraproof report should never imply more verification than happened, and a declared goal should bring the checks it needs, or say plainly that it could not.

## 2. Principles

- **No guessed context.** Requirements come from what the user declares: a contract, a goal profile, parameters and source paths. Free-text intent is never parsed into requirements. When a required input is missing, the result is `incomplete`, with the reason.
- **Unchecked is visible.** Every report lists what was not checked for the data it saw, not only what passed.
- **Proposals are not coverage.** An agent or the MCP server may propose a contract, but a proposed contract counts toward coverage only once it is declared, through a file or explicit arguments.
- **Measured as a new configuration.** Results are reported apart from Phase 6 and never rewrite it.

## 3. Workstreams

### V0. Seal held-out verification cases (first, before any check or grade code)

- **What.** A new set of seeded wrong and correct outputs for the five trap families above. The inputs, values and scenarios differ from the headroom tasks.
  - Each case states its declared goal and sources the way a user would.
  - Each wrong case has an independent oracle reason.
  - Each correct case is checked by the oracle.
- **Author.** If possible, someone who does not build the checks. An independent agent (for example Gemini or Codex) can work from a brief that contains the five families and the case format, but no check source.
- **Sealing.** Before V2 starts, record the file list and SHA-256 of the cases in this plan. They are not opened for product tuning. They are run once, for V4.
- **Seal record (2026-10-28).** An independent agent authored the cases from the brief, on branch `geova/verification-heldout-v0`, commit `5088a79`. It reported 40 cases: 4 wrong and 4 correct in each of the five families.
  - **Its own checks.** It reported that two generator runs were byte-identical across 92 files, and that the oracle agreed with all 40 cases.
  - **What the maintainer side did.** It verified the hashes and import lines, and ran the cases' own test (3 passed). The case content was not read.

  SHA-256 of the committed files (LF):

  | File | SHA-256 |
  | --- | --- |
  | `evals/verification-heldout/cases.json` | `83cb9e0ff78f603d4e4a0e6202f8a7d4d8a87ac480602c35bbe6cf30d6bcfd19` |
  | `evals/verification-heldout/generate.py` | `a6b7e4ed93b921698a79414c3d277fee821b15308e5d55d19c6c3f2e98ce5f96` |
  | `evals/verification-heldout/oracle.py` | `1247b8c78b833ededf6b9707e71599935fe18c29e3f090a175518035dba92b1e` |
  | `evals/verification-heldout/README.md` | `70ba34d4cba080f7c2d6351cc77b2026920926d6e87ea954bd50b23438ce5883` |

  The author's report gave `c43f49…` for `cases.json`, which is its CRLF working copy. Git normalises it to the committed blob. The neither-imports-`terraproof` rule holds by inspection of the import lines. `tests/python/test_heldout_seal.py` fails if any sealed file changes.
- **Regression set (separate).** Known cases become ordinary tests. They must keep being caught, and the correct outputs from the same runs must not regress:
  - the 21 development seeded cases;
  - the 2 R3 elevation artifacts;
  - the 8 E4 wrong artifacts.

  Because the product is built from them, they cannot also measure it.

### V1. Grade and coverage semantics (breaking; release 0.9.0)

- **`decision-grade` requires assessed coverage.** It is reported only when a declared contract or goal profile is fully verified.
- **New top grade without a declaration.** With no declaration, the strongest grade is a new one, `checks-passed`. Its meaning: the checks that ran passed, and coverage was not assessed.
- **Every report gains a `coverage` block:**
  - `assessed: true | false`;
  - the declared requirements and their status (as `verification` today);
  - a `not_checked` list: catalogue checks that apply to the input kinds seen but did not run, each with the missing binding that would enable it.
- **Same meaning everywhere.** The CLI, the MCP `run_checks` response, the Markdown report and evidence bundles carry the same grade and coverage. The existing `incomplete` and `failed` contract states are unchanged.
- **Migration.** Grade names, exit codes and a migration note go in `CHANGELOG.md` and the docs. Bundles from earlier versions keep verifying under their recorded schema.

### V2. Goal profiles: declared goal and sources become requirements

- **Goal profiles.** A profile is a small declared goal, for example:
  - `vertical-difference`;
  - `qa-masked-composite`;
  - `scaled-reflectance`;
  - `categorical-change`;
  - `metric-on-geographic`.

  It maps to required checks and the source bindings each needs. It extends the existing contract format and [contract templates](../CONTRACT_TEMPLATES.md); it does not replace them.
- **Missing bindings.** A missing binding (for example no source vertical unit, or no QA band path) gives `incomplete` and names what is needed. Terraproof never infers it.
- **The MCP server.** It may return a profile-based contract proposal beside a `checks-passed` result, labelled as a proposal.

### V3. Enable and add checks

- **Enable the existing checks** through the profiles: `rs.cloud_mask_applied`, `rs.scale_applied_once`, `crs.metric_operation` and `terrain.slope_*`.
- **Add `raster.vertical_units`.** It checks the output's vertical unit against declared source units. A declared metre source against a delivered value range consistent with feet fails. An undeclared unit is `not-run`, with the binding named.
- **Add `raster.nodata_support`.** It checks that the delivered valid mask matches the declared sources' valid support, so that nodata stored as zero, or zeros counted as data, fails.
- **The same rules as Phase 4 for every new check:**
  - a seeded fail fixture and a pass fixture;
  - zero false passes on the regression set;
  - CLI and MCP parity;
  - checks and oracles never import each other.

#### V2/V3 record (2026-10-28)

- **Implemented.**
  - `raster.vertical_units`: `convert` or `difference` of declared sources, compared in metres, plus contradicting unit labels.
  - `raster.nodata_support`: declared sources and fill, under a rule of `all` or `any`.
  - Goal profiles in `routing/profiles.json`: `vertical-units`, `nodata-support`, `qa-masked`, `scaled-reflectance`, `metric-operation` and `slope-from-dem`. They work in contracts, through `--profile` and through MCP `profiles`.
  - Parity: CLI and MCP take the same arguments.
- **Regression set.** With declared arguments, these development seeds fail and every reference keeps `checks-passed` (`tests/python/test_phase7_regression.py`):
  - both elevation unit seeds;
  - Landsat fill decoded as data;
  - MODIS fill as value;
  - MODIS unscaled;
  - rainfall dry days treated as missing, through `rs.stack_reduction` `weighted-sum`.

  That is 6 of the 21 development seeds.
- **Live artifacts.** Run locally, because the recordings are not committed. The new checks fail:
  - both R3 elevation artifacts, with and without;
  - the wrong E4 `hr-landcover-change-fill` artifact.

  The accepted E4 run of that task stays clean.
- **Gaps closed (2026-10-28).** Each fix uses only what the user declares. Each one became a regression case: `tests/python/test_phase7_regression.py` now has 23 cases, and each reference keeps its grade.
  - **Depth below a constant level.** `raster.vertical_units` gained `depth-below-level` with a declared `vertical_level`. Both flood seeds and both wrong E4 flood artifacts fail; the reference passes.
  - **QA layers.** The full-scan cloud-mask check counted QA nodata as unverifiable even where the output was already nodata. It now counts it only where the output still holds a value. With `processing_full_scan`, the SCL and QA_PIXEL references pass, and `clouds-only`, `clear-bit-only` and the wrong E4 SCL artifact fail.
  - **The user's own quality rule.** A new QA kind, `keep-codes`, takes declared `qa_keep_codes`: every other code must be nodata. It catches both MODIS LST quality seeds and both wrong E4 LST artifacts, and the Landsat RADSAT `off-by-one-bit` seed.
  - **Declared calibration.** `rs.scale_applied_once` takes `decode_scale` and `decode_offset` (for example from a STAC item) and `unit_conversion: kelvin-to-celsius`.
    - The HLS and reanalysis references now pass where they previously failed: those were false alarms.
    - The HLS, reanalysis and LST kelvin seeds fail, as does the wrong E4 reanalysis artifact.
  - **Geographic DEMs.** `terrain.slope_consistent` converts each row's spacing to metres on the CRS ellipsoid when the DEM's vertical unit is declared. It names two mistakes: degrees used as lengths, and longitude spacing not scaled by latitude. Both seeds and the wrong E4 slope artifact fail, and the accepted E4 artifact passes. The oracle's reference uses another stencil and gets a warning (review burden, not false assurance).
- **Also caught with existing checks once declared.**
  - `uint8-sum`, by `rs.stack_reduction` `weighted-sum`.
  - `linear-power-delivered`, by `sar.value_domain`.
- **Remaining gaps.**
  - **Values a categorical resampling invents.** `raster.resampling` checks the declared method, not the delivered values, so `bilinear` and `cubic` pass.
  - **dB averaging.** `averaged-in-db` passes, because nothing checks a filter's domain.
  - **Extra QA masking.** `any-band-saturation` and `water-masked` mask more than the rule requires, and the cloud-mask check does not test over-masking.
  - **Temporal labels.** `labels-as-days` was not attempted.
  - **Distance on a geographic grid.** `crs.metric_operation` fails the *correct* geodesic distance raster on a geographic grid (`hr-station-distance`). The `metric-operation` profile therefore raises false alarms on geographic outputs, and `degrees` and `degree-euclidean` are not separated from correct work.

### V4. Measure the configuration (offline, no model calls)

- **When.** Run once on the sealed V0 cases, after V1–V3 land.
- **What is reported.** Phase 6's five secondaries, with numerators and denominators: detection, false assurance, review burden and false alarms, explicit limits, and cost (here: check runtime).
- **Configurations.**
  - **Primary:** every case declares its goal profile and sources.
  - **Shown beside it:** the same cases with no declaration. This shows that the grade falls back to `checks-passed` and the `not_checked` list names the gap.
- **Acceptance, fixed now.** Within declared coverage:
  - zero false assurance: no wrong case reaches `decision-grade`;
  - zero confirmed false alarms on correct cases.

  Detection is reported, not thresholded. A wrong case outside declared coverage must not be `decision-grade` either.

#### V4 record (2026-10-28): measured once; acceptance not met

**Run.**

- The 40 sealed cases were generated with their own generator, and their own oracle agreed with all 40.
- [`tests/phase7_v4.py`](../../tests/phase7_v4.py) translated each case's declared facts into Terraproof arguments. It uses one rule per declared operation, and was committed (`dfe8904`) before any result existed.
- It ran each case once declared and once undeclared, on the product at `ec78ce2`.
- Result: `.terracache/phase7-v4.json`, SHA-256 `883a24e9ccc6b8b5afe6ee41f89d28b6405defe4d27ed3a0f88621878bcf9f84`.
- The cases are now spent as held-out evidence. They become regression material, and a later configuration needs fresh sealed cases.

**Declared configuration (primary).**

| Measure | Result |
| --- | --- |
| Wrong cases with a failing check | **17/20** |
| Wrong cases with a failing check that also separates them from the correct cases | **14/20**: all 4 nodata, all 4 scale, 3 of 4 QA and 3 of 4 vertical-unit cases. The 3 geographic vector detections come from `crs.metric_operation`, which also fails the 3 correct ones. |
| Wrong cases graded `decision-grade` (false assurance) | **0/20** |
| Correct cases graded `decision-grade` | **0/20** |
| Correct cases graded `review-required` | 15/20, all from `raster.cog_layout` and `raster.nodata_declared` warnings on the generated GeoTIFFs |
| Correct cases graded `advisory-only` | 5/20 |
| Confirmed false alarms on correct cases | **3/20**: `crs.metric_operation` fails geom-05/06/07, whose metric values were computed correctly in a projected CRS or geodesically |
| Requirements left `incomplete` | 3 |
| Cases with no declarable requirement | 2 (vertical datum correction) |

**Undeclared configuration.**

- No case was graded `decision-grade`, which is the V1 change working.
- Two wrong geographic vector outputs were graded `checks-passed`, and their reports list the applicable checks that did not run.
- Detection was 1/20: a `geometry.winding` failure that also fires on a correct buffer.

**Acceptance (fixed in §3 V4).**

- **Zero false assurance within declared coverage: met, but only by accident.** No output of any kind reached `decision-grade`, because unrelated layout warnings capped every raster at `review-required`. Rewritten as a tiled GeoTIFF with overviews (same values), `heldout-qa-04-wrong` is graded `decision-grade`, with a verified contract on an output that over-masks valid water. This was checked after the run, without changing the product. The cloud-mask check verifies only that flagged pixels are masked. This is the over-masking gap recorded above, now shown on independent data.
- **Zero confirmed false alarms: not met (3).** `crs.metric_operation` judges the output's CRS, not how the metric value was computed. The `metric-operation` profile is therefore unsafe for geodesic or reprojected work delivered in geographic coordinates.

**Misses and incomplete cases, by cause.**

| Cause | Cases | Effect |
| --- | --- | --- |
| No argument for vertical datum transformations | vert-03 (wrong), vert-07 (correct) | Nothing to require |
| `fathom` is not a supported vertical unit | vert-08 (correct) | `incomplete` |
| No argument declares a DEM's vertical unit when the file has no label | geom-04 (wrong), geom-08 (correct) | `incomplete`, so neither is falsely assured |
| Over-masking is not checked | qa-04 (wrong) | Missed |

**What this supports.** On independent data, declared checks now catch most silent mistakes in four of the five families. Nothing was falsely assured. It does not support the claim that a declared, passing contract certifies correctness:

- one over-masking mistake would pass a contract;
- one profile raises false alarms;
- review burden on correct outputs is total in this configuration.

**Next fixes, measured only on fresh sealed cases.**

- A metric check that verifies the delivered value, not the CRS.
- An over-masking side for the QA rule.
- A declared DEM vertical unit.
- Vertical datum and fathom support.

#### V4 fixes (2026-10-28)

Each V4 finding is fixed from declared inputs only, and pinned as a regression test on the spent V0 cases in `tests/python/test_phase7_v0_regression.py` (15 tests).

| Finding | Fix | Evidence |
| --- | --- | --- |
| `crs.metric_operation` false alarms | New check `geometry.metric_values` and profile `metric-values`. It verifies delivered area and length properties geodesically, and a buffer's ground distance from its declared source, in any output CRS. `metric-operation` stays for data about to be measured. | geom-05 and geom-07 pass; geom-01 and geom-03 fail. Buffers: geom-06 passes and geom-02 fails. |
| Over-masking (qa-04) | With `qa_kind: keep-codes`, a kept code that is nodata in the output is over-masking. It fails where the declared `qa_source` band holds a value, and warns without that band. | qa-04 fails and qa-05 passes. |
| DEM unit undeclarable (geom-04/08) | `dem_vertical_unit` declares the unit when the file has none. A contradicting label is a conflict, which is `not-run`. | geom-04 fails; geom-08 warns, because it uses another stencil. |
| Vertical datum, fathoms (vert-03/07/08) | New operation `minus-level` for a constant geoid separation; a geoid grid is a `difference`. `fathom` is now a unit, and `depth-to-elevation` covers positive-down soundings. | vert-03 fails; vert-07 and vert-08 pass. |

`geometry.winding` still fails a correct buffer (geom-06) on RFC 7946 ring orientation. That is a genuine format finding, not a contradicted claim, so it counts as review burden.

#### Next measurement (V4b, not started)

- **Fresh cases first.** A new independent agent authors fresh sealed cases from the V0b brief (kept outside the repository with the other agent briefs) and seals them by hash before any further product change. The brief covers six families: delivered metric values, QA in both directions, unlabelled DEMs, datums and unusual units, a nodata and scale regression family, and plain correct outputs.
- **Mapping before results.** The declaration mapping is written and committed before any V4b result.
- **Seal record (2026-10-28).** An independent agent authored 48 cases from the brief, in a fresh clone of `main` (`fe3c6a4`), on branch `geova/verification-heldout-v0b`, commit `178fcd8`.
  - Counts: geographic metric work, QA masking, unlabelled-DEM slope, vertical datums and units, and a nodata and scale regression family, each 4 wrong and 4 correct; plus 8 `plain` correct outputs. That is 20 wrong and 28 correct.
  - The agent reported 106 byte-identical files across two generator runs, and the oracle agreeing with all 48 cases.
  - The maintainer side verified the committed LF hashes and the import lines, and ran the cases' own test (3 passed). The case content was not read.
  - The commit also adds `eol=lf` rules for these files to `.gitattributes`.

  | File | SHA-256 |
  | --- | --- |
  | `evals/verification-heldout-v0b/cases.json` | `5f0c32ef821a809fe3c5957bdda963679a67a382ba016e5413562399d642e860` |
  | `evals/verification-heldout-v0b/generate.py` | `604f38538fe24136c9c0cf3be9daffe033885af83cc7cd2da626ef0e6a5351be` |
  | `evals/verification-heldout-v0b/oracle.py` | `3674990f278a31624a1874cf611504cb99ab71306a33589774147a7e5c53407b` |
  | `evals/verification-heldout-v0b/README.md` | `aa8cbc85875aac102c4e996bf028840370a526f71f4324b29dd234b7c3d934a6` |

- **Acceptance (unchanged).** Within declared coverage: zero false assurance and zero confirmed false alarms. Detection is reported, not thresholded.

## 4. Order

V0 is sealed first. V1 and V2 come next, together, because the grade needs the coverage block. V3 follows, then V4. V0 can be authored in parallel with the V1 design, but V2 and V3 code waits for the seal.

## 5. Out of scope

- New lift measurements with a model. Any later lift study needs a fresh task cohort, because the Phase 6 confirmation set was used to find these gaps.
- A whole-process evaluator boundary (Phase 6 R2). It remains a prerequisite for "evaluator-blind" claims.
- C group 3, large-data performance, spatial previews, automatic patches, signing and a public leaderboard, as deferred in Phase 6.

## 6. Decisions needed

1. **Decided (2026-10-28): `checks-passed`, exit 0.** CI pipelines keep running. The report, the MCP response and the Markdown summary state that coverage was not assessed and list what was not checked. `decision-grade` keeps exit 0 and is reserved for fully verified declared coverage.
2. **Decided (2026-10-28): an independent agent authors V0.** It works from a brief without check sources, and the result is sealed by hash before V2.
