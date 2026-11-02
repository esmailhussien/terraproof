# Terraproof — Phase 10 Plan: Masks, reprojected slopes and multi-value reports

> Status: **S4.1 measured (2026-11-02): acceptance not met, one false assurance; no release from this measurement.** It follows [Phase 9](Terraproof_Phase9_PLAN.md) and release 0.11.0.

## 1. Why this phase

Phase 9 closed most of the coverage gap: 33 of 36 real deliverables got a requirement, and with declarations 12 of 15 real mistakes were caught, with no false assurance. Three gaps remain. This phase works on these three only.

1. **Masks.**
   - In Q5.1, a wrong mask kept a swath edge, where the QA layer holds no data, as valid. The check returned `not-run`.
   - In Q5.2, both mask runs declared the form but never passed the QA layer, so the mask was never verified.
   - Two later fixes are unmeasured: the dropped `processing_full_scan` requirement and the `next_step.missing` hint.
2. **Reprojected slopes.** A slope delivered on another grid than its DEM is `not-run`, for example warped to UTM. In Q0, 2 of 6 slopes were delivered that way. The geographic tolerance fix is also unmeasured.
3. **Multi-value reports.** `report.summary_value` checks one number per call. Real reports hold several (a mean, a min, a max, a valid share), and nested keys or lists are common.

**Release rule.** 0.12.0 ships only if at least two of the three directions meet their acceptance on fresh cases (S4), with zero false assurance everywhere. A direction that misses is reported as missed, and the release notes claim nothing for it.

## 2. Principles (unchanged)

- **Nothing is inferred.** No binding is inferred from task text, file names or value ranges. The goal is always the caller's.
- **Not-run, never guessed.** A check that cannot tell is `not-run`; it never picks.
- **Cases first.** Held-out cases are sealed before product code, measured once, then spent.
- **Mapping first.** Each measurement's mapping is committed before its results.
- **Tolerances from first principles.** Every new tolerance is derived from synthetic data or published specifications before a fresh case is read, never from spent cases.
- **Approved runs only.** Model runs need an approved exact count.
- **One branch, one PR.** It also carries the v0.11.0 release ticks (`794e33e`).

## 3. Workstreams

### S0. Seal a fresh real-data set (first)

- **Authoring.** An independent agent authors at least 40 cases from public data, with the Phase 9 Q0 rules: no credentials, licences recorded, `fetch.py` with SHA-256, no committed rasters, and metadata as found. The brief is kept outside the repository.
- **Families, one per direction plus regression.**

  | Family | Wrong | Correct | Traps |
  | --- | --- | --- | --- |
  | QA validity masks | ≥ 5 | ≥ 5 | Sentinel-2 SCL and Landsat QA_PIXEL. Wrong cases include swath-edge or fill kept as valid, a rejected class kept, and a valid class rejected. |
  | Reprojected slopes | ≥ 5 | ≥ 5 | Slopes warped to another CRS or resolution, both "slope then warp" and "warp then slope", several resampling methods, degrees and percent, projected and geographic DEMs. Wrong cases include vertical units ignored, latitude ignored, degrees used as lengths, and the unit confused. |
  | Multi-value reports | ≥ 5 | ≥ 5 | JSON with 3 or more numbers, including nested keys and lists, raster statistics, vector area, length and count, and a valid share. Each wrong report has one wrong number among right ones. |
  | Same-grid geographic slopes | ≥ 2 | ≥ 2 | To measure the Phase 9 tolerance fix. |
  | Plain | — | ≥ 4 | Real outputs with no trap. |

- **Complete facts.** Three Q0 summaries could not be declared because their facts named no key or statistic. Every S0 case must state every fact a declaration needs: for each number in a report, its key, statistic, source, and unit; for a mask, its QA layer and rule.

#### S0 seal record (2026-11-02)

- **Authoring.** An independent agent authored 42 cases (19 wrong, 23 correct) in a fresh clone of `main` (`9e69f54`), on branch `geova/verification-heldout-s0`, commit `09036d0`. Here it is cherry-picked as `b05dddd`.
- **Counts by family.**
  - QA validity masks: 5 wrong, 5 correct;
  - reprojected slopes: 6 and 6;
  - multi-value reports: 5 and 5;
  - same-grid geographic slopes: 3 and 3, at about 28.7°, 46.6° and 78.6°N;
  - plain: 4 correct.
- **Counts by form.** 19 datasets, 13 summaries and 10 validity masks.
- **Reprojected slopes.**
  - By order: 6 slope then warp, 6 warp then slope.
  - By resampling: bilinear 5, average 3, cubic 2, nearest 2.
- **Reports.** Every report holds 3 or more numbers; 2 hold lists. Each wrong report has exactly one wrong number.
- **Sources.** One Sentinel-2 L2A scene from Earth Search with its SCL layer, Copernicus DEM GLO-30, USGS 3DEP and Natural Earth.
  - **No Landsat.** Landsat Collection 2 QA_PIXEL was not used: it is requester-pays, so masks use Sentinel-2 SCL only, as the brief allows.
  - **Projected grids.** Public DEMs are geographic, so projected slopes come from each case's declared warp.
- **The agent's report.**
  - 104 of 298 `facts` entries (34.4%) are stated by real metadata. The set states complete facts on purpose, and most of them are the practitioner's.
  - Two cold fetches gave byte-identical manifests, and two derivations gave byte-identical outputs.
  - The oracle agreed with all 42 cases.
  - For reprojected slopes, a different resampling choice moves the mean slope by at most 1.03%; the wrong cases differ by factors of 0.198 to 105 058.
- **Maintainer checks.**
  - The committed LF hashes match the hand-off, including the test file (`fd559b52…98f08`).
  - Imports were checked: no `terraproof`. Fetch hosts are public: Earth Search, `sentinel-cogs`, the Copernicus DEM bucket, `prd-tnm`, and GitHub raw.
  - A cold fetch into a new cache reproduced the manifest hash, and the cases' own test passed 5 of 5. With `CI` set and no cache, it skips.
  - The case content was not read.

  | File | SHA-256 |
  | --- | --- |
  | `evals/verification-heldout-s0/cases.json` | `4549f04db22382930b65ad779c85f6dc44cb2575b738378fd111191688e9d724` |
  | `evals/verification-heldout-s0/fetch.py` | `88b904965cc7cf428a4310bc5f5495bd8324bdf73a91d9afb79f6022e247e1b6` |
  | `evals/verification-heldout-s0/derive.py` | `78218c9131205bfa5029b28f685ff46de219dec2fd5a53353213d73324d29906` |
  | `evals/verification-heldout-s0/oracle.py` | `82d0a153985457dd0a11d9f196a898dab4359f6b4c357137f1bd2935b41643a3` |
  | `evals/verification-heldout-s0/README.md` | `3b4d8cefefe8224ac7cb935a9454d31fee4b0a3c1afac3b4a741ede97a9f5fce` |
  | Fetched-file manifest (`manifest.json` in the cache) | `be0986e067f942c8b9a9b0eaccd93d34c9f22985ebca4d1682a4d3f1558aa1ad` |

### S1. Masks: verify the QA layer's own no-data, and measure the hint

- **Rule.** For a declared validity mask (`output_form = validity-mask`) with `qa_kind` `s2-scl` or `landsat-qa-pixel`, a cell marked valid where the QA layer records no observation fails `rs.cloud_mask_applied`.
  - **Basis.** The QA specifications themselves: SCL class 0 is "no data", and QA_PIXEL bit 0 is "fill". This is not inferred from values.
  - **Scope.**
    - `keep-codes` rules are unchanged, since there the caller declares which codes are kept.
    - Data outputs (not masks) are unchanged: missing QA there stays unverifiable.
- **Hint.** The `next_step.missing` hint, already shipped, names `qa_path` and `qa_kind` when a mask is declared without a QA layer. It is measured in S4.2, not changed.
- **Progress measure.** In Phase 9:
  - 3 of 4 wrong masks failed;
  - 0 of 8 masks were `decision-grade`;
  - 0 of 2 agent mask runs reached a QA verdict.

### S2. Slopes delivered on another grid

- **Today.** `terrain.slope_consistent` returns `not-run` when the slope and DEM grids differ.
- **New path.**
  1. The check computes the reference slope on the DEM's own grid, as today.
  2. It maps each output cell centre into the DEM's CRS, and reads the reference there by bilinear interpolation. A cell is used only where all four neighbours have full stencils.
  3. Per-cell agreement is replaced by a distribution test: the median absolute difference and the share of cells within a per-cell bound.
  4. The named mistakes use the same test. The check fails only when a mistake fits and the declared reading does not; otherwise it warns.
- **Tolerances.** Both bounds are set from synthetic terrain (planes, cones, sinusoids, and fractal surfaces of several roughnesses), warped by nearest, bilinear and cubic resampling, in both orders. This is done before S0 cases are read, and recorded with the margins to every named mistake.
  - A bound that cannot separate correct from wrong on synthetic terrain stops the work. In that case the direction is reported as missed.
- **Unchanged.**
  - Same-grid slopes keep the per-cell test.
  - `terrain.slope_formula` stays same-grid only.
  - The evidence says `comparison: resampled`, so a resampled pass is never read as a cell-exact one.
- **Progress measure.** In Phase 9, 0 of 2 reprojected slopes got a verdict.

### S3. Multi-value reports

- **Several summaries in one check.** A `summaries` binding lists entries of `{key, statistic, source, unit?, feature?, mask?}`.
  - `report.summary_value` returns one result per entry.
  - A contract requires every entry.
  - The single `summary_*` bindings stay as shorthand for one entry.
  - CLI: repeatable `--summary key=…,statistic=…,source=…`. MCP: a `summaries` list.
- **Paths into lists.** Keys may index lists, as in `bands.0.mean`.
- **One new statistic: `fraction`.**
  - With `summary_mask`, it is the share of the source's valid cells that the mask marks valid.
  - Without a mask, it is the share of all cells that are valid.
  - `summary_unit` is `fraction` or `percent`.
- **Unchecked numbers are listed, never judged.**
  - The evidence lists every numeric leaf of the report that no entry declared.
  - The report adds a `next_step.missing` line naming them.
  - The grade covers the declared numbers only, as for any other output.
- **Progress measure.** In Phase 9, a report was checked one number at a time, and lists and shares were not checkable.

#### S1–S3 record (2026-11-02): implemented, not yet measured

No S0 case content was read. The resampled-slope rule was calibrated on synthetic terrain only.

- **S1, as planned.**
  - The rule applies to masks declared with `s2-scl` or `landsat-qa-pixel`. They fail where they mark valid a cell the QA records as no observation: the QA file's nodata, SCL 0, or QA_PIXEL bit 0. The evidence counts these as `valid_without_qa_observation`.
  - Data outputs and `keep-codes` rules are unchanged.
- **S2, changed from the plan after a first rule failed calibration.**
  - **The planned rule failed.** It used an area-mean distribution test with a correlation floor. On synthetic terrain it was unsafe at every setting: 6 to 101 wrong slopes passed, and 20 to 32 correct ones failed. On rough terrain, the resampling choice alone moves the mean gradient by up to 13%, as much as latitude ignored or a confused unit.
  - **The rule as built** (`terrain.resampled_fits`, `resampled_outcome`):
    1. The reference is made every common way: slope then warp (in the delivered unit), or warp then slope; nearest, bilinear, cubic or average resampling; central differences or Horn.
    2. A slope passes only when one way reproduces it cell by cell, with 95% of cells within 1% (the geographic tolerance).
    3. It fails when one way reproduces a named mistake instead. "Degrees and percent confused" is a new named mistake.
    4. Otherwise it fails only for a gross mistake: the declared reading lies outside the area-mean envelope (|ln ratio| ≤ 0.25), and a mistake lies inside it with correlation ≥ 0.5.
    5. The rest warns.
  - **Disclosure.** The four emulated methods are GDAL's common ones. They were fixed after the S0 hand-off, whose counts name the same four methods (bilinear 5, average 3, cubic 2, nearest 2). The case content was not read.
  - **Calibration.** [`tests/phase10_s2_calibration.py`](../../tests/phase10_s2_calibration.py) covers:
    - 8 terrains: a plane, a cone, a sinusoid and fractals with β 2 to 4;
    - 16 grids: geographic at 28.7°, 46.6°, 60° and 78.6° to UTM at 1×, 1.25× and 2×; UTM at 1.5× to 3×; and UTM 33 to UTM 32;
    - correct slopes made with six methods, two of them never emulated (cubic spline, Lanczos), WGS84 or spherical spacing, float32 or float64, in degrees or percent;
    - each named mistake, made the same ways.
  - **Calibration results** at the chosen setting: 1,536 correct and 3,456 wrong slopes.

    | Outcome | Pass | Warn | Fail |
    | --- | --- | --- | --- |
    | Correct slopes | 1,124 | 412 | **0** |
    | Wrong slopes | **0** | 265 | 3,191 |

    - **Correct, by method.** All 1,024 made with an emulated method were reproduced. Of those made with cubic spline or Lanczos, 100 of 512 were reproduced, and the rest warn.
    - **The envelope.** The largest correct |ln ratio| was 0.189 (the roughest fractal), so 0.25 leaves a margin. Across every envelope from 0.15 to 0.4 and correlation from 0.3 to 0.7, no correct slope failed and no wrong one passed.
    - **Wrong, by mistake.**
      - Degrees as lengths: 576 of 576 failed.
      - Unit confused: 729 of 768 and 712 of 768.
      - Vertical units ignored: 687 of 768.
      - Latitude ignored: 487 of 576, from 111 of 144 at 28.7° to 138 of 144 at 78.6°.
      - The rest warn.
  - **Unchanged.** Same-grid slopes keep the per-cell test. A slope merely relabelled half a pixel off now warns, where before it was `not-run`; its test was updated.
- **S3, as planned, with one addition.**
  - **As planned.**
    - `summaries` is in `run_checks`, the CLI (`--summary`, repeatable), MCP and contracts. Each entry's missing fields are named, as in `summaries[0].unit`.
    - Keys may index lists, and `fraction` is a new statistic.
    - Undeclared numbers are listed per result and in `coverage.unchecked_numbers`, with one Markdown line in English and Arabic. They are listed in coverage rather than `next_step`, because `next_step` is absent under a contract.
  - **Addition: rounding.** A number also matches within half a unit of its last written decimal. This is read from the JSON text, so a mean written as `12.3` is not a false alarm.
- **Tests.** [`tests/python/test_phase10.py`](../../tests/python/test_phase10.py) has 11 tests:
  - S1: swath edge with and without QA nodata, Landsat fill, and data and keep-codes outputs unchanged;
  - S2: bilinear and average warps, percent, vertical units ignored, unit confused, and an unrelated slope that warns;
  - S3: all numbers checked and the undeclared one listed; one wrong number among right ones; a share over all cells; contract coverage and missing fields; CLI/MCP parity and the proposed command.
- **Open until S4.** Whether these meet the per-direction acceptance on real cases.

#### Before S4.1 (2026-11-02): two design gaps fixed, disclosed

The S4.1 mapping was written from the bundle README and a pooled view of the facts. The pooled view
showed keys, types and the distinct values of each vocabulary field across all cases. It showed no
ids, `kind`, scenarios, goals, outputs or oracle fields. It still showed two things:

- **Trap wording in the facts.** Some report-number `mask` texts describe a mistake ("genuine 0 m
  heights wrongly evicted", "denominator all pixels"). The mapping therefore never reads `mask` text to
  build a declaration. A number is declared only when its mask text is empty or one of a fixed list of
  fill-exclusion phrases, since the check always honours the source's own nodata.
- **Inexpressible numbers.** Several report numbers cannot be expressed by the check: NDVI, a mean
  restricted to a QA class, a share of a class. They stay undeclared.

Writing the mapping exposed two gaps in S1 and S3, fixed before any result:

1. **S1 scope.** As built, S1 would not have caught the Q5.1 miss it was meant to fix. That mask was
   declared with `keep-codes`, and S1 excluded `keep-codes`. The QA file's nodata is "no observation"
   under any rule, so a declared mask now fails there for every QA kind. SCL 0 and the QA_PIXEL fill
   bit still apply only to their own kinds.
2. **S3 grade.** Undeclared report numbers used to be listed only. A wrong number left undeclared
   could then let the report reach `decision-grade`, which is false assurance. Now a warning names the
   undeclared numbers, so such a report is at best `review-required`.

### S4. Measure once (offline, then agent)

1. **Offline on S0's sealed set.** Three configurations, as in Q5.1: declared, proposed and undeclared. The mapping is committed before any result.
   - **Overall acceptance:** zero false assurance in every configuration; zero confirmed false alarms within declared coverage; no metadata-filled binding that contradicts the truth.
   - **Per-direction acceptance (declared configuration):**

     | Direction | Met when |
     | --- | --- |
     | S1 masks | Every wrong QA mask fails, and at least half of the correct masks reach `decision-grade` |
     | S2 reprojected slopes | At least 4 of 5 wrong reprojected slopes fail, and no correct one fails |
     | S3 multi-value reports | Every declared number is checked, every wrong report fails, and at least half of the correct reports reach `decision-grade` |

   - **Reported, not thresholded:** same-grid geographic slopes, coverage by form, and the comparison with Q5.1.
2. **Agent run on fresh tasks** (not S0's cases), with the same host, model and protocol as Q5.2.
   - **Tasks.** Two per direction: a QA mask, a reprojected slope and a multi-value report. At two runs per task, that is **12 invocations**, to be approved before any run.
   - **Requirement.** Zero false assurance.
   - **Reported:** whether mask runs reached a QA verdict (0 of 2 in Q5.2), the declared share, `next_step` offered and followed, and correctness.

#### S4.1 record (2026-11-02): measured once; acceptance not met, one false assurance

**Run.**

- The 42 sealed S0 cases were derived with their own scripts, and their oracle agreed with all 42.
- The mapping, [`tests/phase10_s4.py`](../../tests/phase10_s4.py), was committed (`b134244`) before any result.
  - It ran once on the product at that commit.
  - A declaration-only dry run before the commit printed pooled counts only, with no check results.
- Result: `.terracache/phase10-s4.json`, SHA-256 `ee7c9385255d57af449c94525a1b80dbaa1ab3ab8bcc92ae3fae81e25571165d`.
- These cases are now spent.

**Coverage.** 36 of 42 deliverables got a requirement: all 10 masks, all 18 slopes, and 8 of 13 reports. The other 5 reports hold no number the check can express, and one dataset had no rule.

**Overall acceptance: not met.**

| Measure | Declared | Proposed | Undeclared |
| --- | --- | --- | --- |
| Wrong outputs failing a check (of 19) | 13 | 0 | 0 |
| **False assurance** (wrong graded `decision-grade`) | **1** | 0 | 0 |
| False alarms within declared coverage | 0 | 0 | 0 |
| Correct outputs graded `decision-grade` (of 23) | 9 | 0 | 0 |
| Metadata bindings contradicting the truth | — | 0 | — |

**Per direction (declared): none met.**

| Direction | Acceptance | Result | Met |
| --- | --- | --- | --- |
| S1 masks | every wrong fails; at least half the correct `decision-grade` | 5 of 5 wrong failed; 0 of 5 correct `decision-grade` | no |
| S2 reprojected slopes | at least 5 of 6 wrong fail; no correct fails | 4 of 6 failed, 1 certified, 1 warned; 0 correct failed, 6 of 6 `decision-grade` | no |
| S3 multi-value reports | no declared number not-run; every wrong fails; at least half the correct `decision-grade` | 0 not-run; 2 of 5 wrong failed; 1 of 5 correct `decision-grade` | no |

**What happened, by direction.**

- **S1 masks.**
  - **Wrong masks: all caught.** All 5 wrong masks failed, against 3 of 4 in Q5.1. That includes the swath-edge mask (fill kept valid), the case the S1 fix targets.
  - **Correct masks: none reached `decision-grade`.** Each correct mask has a failing check count of zero and passed `rs.cloud_mask_applied`. But every one is `review-required`, because of two format screens: `raster.cog_layout` (the masks are not COGs) and `raster.nodata_declared` (a 1/0 mask declares no nodata). The Phase 9 grading policy is unchanged, so these screens still cap the grade.
- **S2 reprojected slopes.**
  - **Correct slopes: all verified.** All 6 correct slopes were reproduced cell by cell, across nearest, bilinear, cubic and average and both orders, and reached `decision-grade`.
  - **The false assurance is a design flaw.** The Web Mercator slope (EPSG:3857, warp then slope, 78.6°N) was certified. On the warp-then-slope path, the check took projected units as ground lengths. Mercator overstates ground distance by 1/cos(latitude), about 5 times here, so the check's own reference repeated the mistake, at 100% of cells. The same flaw affects same-grid slopes in any projection whose scale factor is far from 1. UTM's (0.9996–1.001) is negligible.
  - **The second miss is a missing named mistake.** "Feet over metres" (heights converted to feet over metre spacing) warned, as did its same-grid twin. "Vertical units ignored" exists only for a DEM labelled in feet.
- **S3 multi-value reports.**
  - **Declared numbers.** Every declared number ran, and the wrong ones failed: fill averaged in, and area in degrees.
  - **Most wrong numbers were not expressible:**
    - zeros evicted: the trap number's selection text describes the mistake, so the mapping left it undeclared, and the report only warned;
    - a share over all cells, a class share: a share restricted to QA classes cannot be expressed;
    - a band taken from the wrong band: the source COGs state no scale in the file, so reflectance means cannot be decoded.
  - **No false assurance from those.** The undeclared-number warning held two correct reports at `review-required` and left reports with nothing declared `advisory-only`. That cap, added before the run, is what kept them from being certified.
- **Same-grid geographic slopes.**
  - **Wrong:** 2 of 3 failed; the third is the feet-over-metres mistake, which warned.
  - **Correct:** all 3 passed the slope check, and were held at `review-required` by `raster.nodata_declared`.
- **Proposed.** Metadata filled none of the 62 required bindings, as in Q5.1, and contradicted nothing.
- **Undeclared.** No `next_step` was offered.

**What this shows.**

1. **Release rule not met.** No direction met its acceptance, and there was one false assurance. By the rule in §1, there is no 0.12.0 from this measurement.
2. **Real progress, but not to the bar.**
   - Every wrong mask was caught.
   - Off-grid slopes went from 0 verdicts to 6 of 6 correct verified and 4 of 6 wrong caught.
   - Multi-value reports are checked number by number.
3. **One must-fix flaw.** The Mercator false assurance is a defect in S2's design: projected spacing is taken as ground spacing.
4. **Measured gaps to close before another measurement:**
   - scale factor in projected spacing;
   - "metres read as feet" as a named mistake;
   - the format screens holding correct declared masks and slopes at `review-required`;
   - class-restricted and declared-scale report statistics.

## 4. Order and delivery

1. S0 is sealed first.
2. Then S1, S2 and S3, each with its tests.
3. Then S4.1, and S4.2 if it is approved.
4. Then 0.12.0, if the release rule is met.
5. One branch (`geova/post-0.11.0`) and one PR.

## 5. Out of scope

- New check families or output forms beyond these three directions.
- Lift studies, an evaluator boundary, large-data performance, and automatic repair.
- Any rule that infers a goal, a QA layer or a report key from task text or file names.

## 6. Decisions needed

1. **S0 authoring.** Who authors S0: an independent agent from a brief, as before (`S0_REAL_DATA_CASES_BRIEF.md`).
2. **S4.2.** Whether to run the agent measurement at 12 invocations; decided after S4.1.
