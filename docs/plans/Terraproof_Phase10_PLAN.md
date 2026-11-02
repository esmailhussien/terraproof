# Terraproof — Phase 10 Plan: Masks, reprojected slopes and multi-value reports

> Status: **S0 sealed (2026-11-02)**; S1–S3 next. It follows [Phase 9](Terraproof_Phase9_PLAN.md) and release 0.11.0.

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
