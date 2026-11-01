# Terraproof — Phase 9 Plan: Cover real deliverables, make declaring the default

> Status: **complete (2026-11-02)**. Q0 sealed; Q1–Q4 implemented; Q5.1 measured (acceptance met in all three configurations); Q5.2 run (zero false assurance; 8 of 10 agent runs declared their goal). It follows [Phase 8](Terraproof_Phase8_PLAN.md) and release 0.10.0.

## 1. Why this phase

Phase 8 measured Terraproof on real data and with a real agent. When the user declared, the checks caught every covered mistake, with no false assurance and no false alarm. Three limits now decide whether it helps in practice.

1. **Coverage of real deliverables.** 20 of 34 real deliverables were forms no check verifies:
   - 12 validity masks (1 = usable, 0 = not), which checks read as data, not as nodata;
   - 3 slopes in percent, where `terrain.slope_consistent` takes degrees only;
   - 5 JSON summaries (a mean, a count), which are not datasets at all.
2. **Agents rarely declare.** In P4 the agent checked 9 of 10 deliverables but declared a goal in 3. Without a goal, the best grade is `checks-passed`, and the agent's own arguments are never required.
3. **Two fixes are unmeasured.** The `s2-l2a` offset rule and the STAC offset conflict in `propose` were fixed after the cases that found them were spent.

## 2. Principles (unchanged)

- **Nothing is inferred.** No binding is inferred from task text, file names or value ranges. The goal is always the caller's.
- **Not-run, never guessed.** A check that cannot tell is `not-run`; it never picks.
- **Cases first.** Held-out cases are sealed before product code, measured once, then spent.
- **Mapping first.** Each measurement's mapping is committed before its results.
- **Approved runs only.** Model runs need an approved exact count.
- **One branch, one PR.** Release 0.11.0 only if behaviour changes.

## 3. Workstreams

### Q0. Seal a fresh real-data set (first)

- **Authoring.** An independent agent authors at least 36 cases from public data, with the Phase 8 P0 rules: no credentials, licences recorded, `fetch.py` with SHA-256, no committed rasters, and metadata as found.
- **Families.**
  - Validity masks: QA masks and fill masks, wrong and correct.
  - Slopes in percent and in degrees, on projected and geographic DEMs.
  - JSON summaries of a raster or vector: a mean, a count, an area.
  - Sentinel-2 decodes from at least two distributors, so that one applies the offset and one does not, each with its STAC item as found.
  - Plain correct outputs.
- **Two case fields.** Each case keeps `facts_in_metadata` from Phase 8, and adds `deliverable_form`: dataset, validity mask, or summary.
- **Brief.** It is kept outside the repository, as for Phase 8.

#### Q0 seal record (2026-11-01)

- **Authoring.** An independent agent authored 36 cases (15 wrong, 21 correct) in a fresh clone of `main` (`a2205a2`), on branch `geova/verification-heldout-q0`, commit `d90fd15`.
- **Counts by family.**
  - validity masks: 4 wrong, 4 correct;
  - slope: 3 and 3;
  - summary reports: 3 and 4;
  - Sentinel-2 decodes from two distributions: 3 and 4;
  - fill and vertical units: 2 and 2;
  - plain: 4 correct.
- **Counts by form.** 16 datasets, 12 summaries and 8 validity masks.
- **Sentinel-2 distributions.**
  - Earth Search `sentinel-2-l2a`: 1 wrong, 2 correct. Its item states `earthsearch:boa_offset_applied`, and pixels confirm the offset is already in the stored values.
  - Earth Search `sentinel-2-c1-l2a`: 2 wrong, 2 correct. The item has no such flag, and pixels show raw DNs, so the offset must still be applied. Its `raster:bands` declare the same −0.1, so the declaration alone does not tell the two distributions apart.
- **Other sources.** The Copernicus DEM and 3DEP tiles are the same tiles P0 used.
- **The agent's report.**
  - 147 of 238 `facts` entries (61.8%) are stated by real metadata.
  - Two cold fetches gave byte-identical manifests, and two derivations gave byte-identical outputs.
  - The oracle agreed with all 36 cases.
- **Maintainer checks.**
  - The committed LF hashes match the hand-off.
  - Imports were checked: no `terraproof`. Fetch hosts are public: Earth Search, both Sentinel-2 buckets, the Copernicus DEM bucket, `prd-tnm`, and GitHub raw.
  - A fresh fetch reproduced the manifest hash, and the cases' own test passed 5 of 5.
  - The case content was not read.
- **Repository changes.** The commit adds `eol=lf` rules; the seal commit removes a duplicated V0b block it introduced in `.gitattributes`. The cases' test skips on CI without a cache unless `TERRAPROOF_HELDOUT_Q0_FETCH=1`.

  | File | SHA-256 |
  | --- | --- |
  | `evals/verification-heldout-q0/cases.json` | `188f00537572e3f8a04f0d9a0a1e0bfdc247cec19623f1be375c3bfebce37130` |
  | `evals/verification-heldout-q0/fetch.py` | `6a58013132997cf885e429ad692c198c6ee523ad461e7d261068e8652cabb75c` |
  | `evals/verification-heldout-q0/derive.py` | `4c4df0a11d188ee3f66b5ad6cc250a65857d79172b0fd9ecce0f05d7ce7f76e2` |
  | `evals/verification-heldout-q0/oracle.py` | `6127b66edc7be2c3e74cca6b0529a533673371dbf0470087afbac41d11ea0060` |
  | `evals/verification-heldout-q0/README.md` | `86cfaa0f3f87a5482c331744b509ba2cbf9f52b3db30293127a1aad7a2e2c10d` |
  | Fetched-file manifest (`manifest.json` in the cache) | `90d2690490dbd47f4f5aaaf1cb12f1349cbce0b37f7e56a10ed7db93e1902503` |

### Q1. Validity masks as a declared output form

- **Binding.** A new binding, `output_form = validity-mask` (CLI `--output-form`), with the valid value (default 1).
- **How checks read it.** `rs.cloud_mask_applied` and `raster.nodata_support` then treat any other value as invalid, instead of reading the output's nodata.
- **Not inferred.** A 1/0 raster without the binding is still read as data. Nothing is inferred from the values.

### Q2. Slope units

- **Binding.** `slope_unit = degrees | percent` for `terrain.slope_consistent` and `terrain.slope_formula`.
- **Missing unit.** An undeclared unit keeps today's degrees, with a note in the evidence. A percent slope checked as degrees still fails, as today.

### Q3. Declared summaries (in scope, decided 2026-11-01)

- **Proposed check.** `report.summary_value` recomputes one declared statistic over a declared source and compares it with the delivered JSON number.
  - Statistics: `mean`, `count`, `sum`, `min`, `max` of valid raster cells, or `area` / `length` of vector features, geodesic.
  - Bindings: the JSON key and the source.
  - Nodata and any declared validity mask are honoured.
- **Decided in scope (2026-11-01).** It is the first check whose output is not a geospatial dataset. Its scope is narrow: one declared statistic, one declared key, one declared source. It never reads free text in a report.

### Q4. Make declaring the default for agents

- **Suggest, never apply.** `run_checks` without a contract returns a `next_step` when the caller passed bindings that enable opt-in checks. It names the goal profiles whose checks those bindings enabled, and the `propose_contract` call that would make them required.
  - It reads only the caller's own arguments, never task text.
  - It is advisory and never changes the grade.
- **Instructions.** The MCP instructions and `verify-with-terraproof` sections state the two-step pattern: propose, then check with the contract.
- **Proposal limits.** P3 showed metadata fills few coverage bindings. Q4 therefore does not promise coverage from metadata; it makes the declaration step visible and cheap.

#### Q1–Q4 record (2026-11-01): implemented, not yet measured

- **Q1.** `output_form = validity-mask`, with `output_valid_value` (default 1).
  - `rs.cloud_mask_applied` and `raster.nodata_support` count a cell as valid only where it holds that value. A declared mask always takes the exhaustive QA path.
  - An unknown form is refused. A 1/0 raster without the binding is still read as data.
- **Q2.** `slope_unit = degrees | percent` for `terrain.slope_consistent` and `terrain.slope_formula`. Percent is converted with arctan(p/100) before comparing, and an undeclared unit stays degrees.
- **Q3.** New check `report.summary_value` and profile `summary-value`.
  - Statistics: `mean`, `count`, `sum`, `min`, `max` of valid raster cells (file scale and offset applied, optional `summary_mask`), or `count`, `area`, `length` of vector features (geodesic, `summary_unit`, optional `summary_feature`).
  - Tolerances: rtol 1e-4 for raster statistics, 1% for geodesic sums; counts must be exact.
  - A plain `.json` object is now inspected as `kind: report`, listing only its top-level keys. STAC and GeoJSON are unchanged.
- **Q4.**
  - Without a contract, `build_report` adds `next_step` when every check of a goal profile ran from the caller's arguments. It holds the profiles, the `propose_contract` arguments and the CLI command, plus one Markdown line in English and Arabic.
  - The MCP instructions now state the two-step pattern. The nine skill `Verify with Terraproof` sections were left unchanged: AGENTS.md rule 6 keeps a universal rule out of individual skills, and the MCP instructions reach every agent that has the tools.
- **Tests.** [`tests/python/test_phase9.py`](../../tests/python/test_phase9.py) has 11 tests covering pass and fail for each binding, refused or missing declarations, the inspect change, the next step in both languages, and CLI/MCP parity.
- **Open until Q5.** Whether the new forms close the coverage gap on real cases is for Q5.1 to measure, and whether agents follow `next_step` is for Q5.2.

### Q5. Measure once (offline, then agent)

1. **Offline on Q0's sealed set.** Three configurations, as in Phase 8 P3: declared, proposed, and undeclared.
   - **Acceptance, fixed now:**
     - zero false assurance in every configuration;
     - zero confirmed false alarms within declared coverage;
     - in the proposed configuration, no metadata-filled binding that contradicts the truth.
   - **Reported:** coverage by deliverable form.
2. **Agent run on fresh tasks** (not Q0's cases), with an approved exact count.
   - Same host and model as Phase 8 P4, with Terraproof installed.
   - **Reported:** the declared share, false assurance, and the grade the agent last saw.
   - **No acceptance threshold**, except that **zero false assurance** is required.

#### Q5.1 record (2026-11-02): measured once; acceptance met in all three configurations

**Run.**

- The 36 sealed Q0 cases were derived with their own scripts, and their oracle agreed with all 36.
- [`tests/phase9_q5.py`](../../tests/phase9_q5.py) maps each case by one rule per deliverable form. It never reads `kind`, and each wrong/correct pair gets the same rule. It was committed (`f6fd239`) before any result.
- It ran once on the product at `7c26d08` (Q1–Q4).
- Result: `.terracache/phase9-q5.json`, SHA-256 `b728c302e2c7f22a19eb2c1516fda31813b2446a256eaa8ccd1ece7109d55df6`.
- These cases are now spent.

**Coverage.** 33 of 36 deliverables got a requirement, against 14 of 34 in Phase 8 P3:
- all 8 validity masks;
- all 16 datasets;
- 9 of 12 summaries. The other 3 are summaries whose facts state no key or statistic, which the mapping does not guess.

**Results.**

| Measure | Declared | Proposed | Undeclared |
| --- | --- | --- | --- |
| Wrong outputs failing a required check | **12 of 15** | 4 | 0 |
| Wrong outputs graded `decision-grade` (false assurance) | **0** | **0** | **0** |
| Correct outputs with a failing check (false alarms) | **0** | **0** | 0 |
| Correct outputs graded `decision-grade` | 6 | 0 | 0 |
| Metadata bindings contradicting the truth | — | **0** | — |

**Acceptance (fixed in this plan): met.** There was no false assurance in any configuration and no false alarm within declared coverage. In the proposed configuration, no metadata binding contradicted the truth.

**By form (declared).**
- **Summaries.** 3 of 3 wrong were caught (fill averaged in, zeros evicted, degree area). 5 correct reached `decision-grade`. One correct case is `incomplete`: its facts name a key the report does not hold.
- **Sentinel-2 decodes, both distributions.** 4 of 4 wrong were caught, including the v0 double offset and the c1 missing offset and raw DN. The 4 correct decodes are `review-required`, only because the delivered rasters declare no nodata or are not COGs.
- **Fill and vertical units.** Both wrong were caught.
- **Validity masks.** 3 of 4 wrong failed `rs.cloud_mask_applied`, and no correct mask raised an alarm.
  - All 8 are `incomplete` because the mapping did not declare `processing_full_scan`, which the `qa-masked` profile requires. That omission is the mapping's, recorded as it ran.
  - A declared mask is always read in full, so the requirement adds nothing for masks.
  - The missed wrong mask keeps a swath-edge window whose QA is entirely nodata as valid. The QA check is then `not-run`: it is unverifiable, never certified.
- **Slopes.** 1 of 3 wrong was caught (degrees used as lengths).
  - **Geographic DEMs do not discriminate.** Correct geographic slopes match the check's own central differences in only 51% of cells at its 0.1% tolerance. The author's spacing approximation most likely differs from the check's ellipsoidal one. They therefore warn, and the latitude-ignored wrong slope also only warns: it matches its mistake in 34% of cells, under the 95% needed to fail.
  - The unit-confused slope and one correct slope were reprojected to UTM, off the DEM's grid, so both are `not-run`.

**Proposed.**
- **Offset handled correctly in both distributions.**
  - For the v0 distribution, `propose` reported the STAC offset as a conflict in 4 cases, citing `earthsearch:boa_offset_applied`, so it did not fill the wrong offset.
  - For c1, which has no such flag, it filled −0.1, which is right there.
  - This is the post-P3 fix, now measured on fresh cases.
- **No coverage from metadata.** Metadata again filled none of the 87 required coverage bindings, so every requirement stayed `incomplete`. Proposals remain a convenience, not a route to coverage.

**Undeclared.** No case offered `next_step`, as expected: the undeclared configuration passes no arguments that could run a goal's checks. Whether agents follow `next_step` is for Q5.2.

**What this shows.**

1. **The coverage gap is mostly closed.** Validity masks and summaries are now checkable, from 14 of 34 deliverables to 33 of 36. With declarations, 12 of 15 real mistakes were caught, with no false assurance or false alarm.
2. **The offset fixes work on real data.** Both distributions' decodes were judged correctly, and proposals no longer copy a self-contradicting offset.
3. **Two weaknesses remain, and need fresh cases to fix and measure:**
   - geographic slope tolerance, which makes the check warn on correct and wrong alike;
   - the `processing_full_scan` requirement for declared masks, which can be dropped because a mask is always read in full.

#### After Q5.1 (2026-11-02): both weaknesses fixed, not re-measured

- **Masks.** A `rs.cloud_mask_applied` requirement no longer lists `processing_full_scan` as missing when `output_form = validity-mask`, since the mask is always read in full. A test shows a declared mask contract verifying at full-grid scope.
- **Geographic slopes.**
  - **Rule.** `terrain.slope_consistent` now uses a 1% relative tolerance on geographic DEMs, and keeps 0.1% on projected ones.
  - **Derivation.** The tolerance was set from first principles, not from the spent cases. WGS84 ellipsoidal spacing, a mean-radius sphere and 111 320 m per degree differ by at most 0.674% from 0 to 88°N. The mistakes differ by far more: latitude ignored is off by 13% at 28°N and 380% at 78°N, and degrees as lengths by about 10⁵.
  - **Mistake hypotheses** use the same tolerance.
- **Test changes.**
  - Two Phase 7 regression references and one V0 regression case used to warn ("another stencil"). They now pass, and their seeded mistakes still fail.
  - New tests show a spherical-model slope passing and a latitude-ignored one failing at 78°N.
- **Sanity run on spent cases, not a measurement.** On the spent Q0 outputs, both correct geographic Nepal slopes now pass (100% match), and both geographic wrong slopes fail (100% match to their mistake).
- **Not re-measured.** Q0 is spent, so this does not show the fixes on fresh cases.

#### Q5.2 design (2026-11-02): registered before any run

- **Driver.** [`tests/phase9_q5_agent.py`](../../tests/phase9_q5_agent.py) is committed (`bd5af54`) before any run. It reuses the Phase 8 P4 adapter, labels, install, brief and preflight, and runs the "with" condition only. Its labels add whether `run_checks` offered `next_step` and whether the agent then called `propose_contract` (tested in `tests/python/test_phase9_q5_agent.py`).
- **Tasks.** Five, on Q0's cached sources but on bands and products no sealed Q0 case or P4 task delivered. One task per form:

  | Task | Form | Truth (oracle: numpy, rasterio, pyproj) |
  | --- | --- | --- |
  | `q5-c1-blue-reflectance` | dataset | c1 stores raw DNs (1st percentile 1079), so (DN − 1000) × 1e-4, with fill as nodata |
  | `q5-c1-clear-mask` | validity mask | 1 exactly where SCL is 4, 5, 6 or 11; the trap is class 2 (dark area), 34 561 cells |
  | `q5-nepal-slope-percent` | dataset | slope in percent on WGS84 ground spacing; either central differences or Horn, with median ≤ 0.2° and p95 ≤ 1° (latitude ignored is ≥ 1.1° off) |
  | `q5-kauai-summary` | summary | mean of non-fill cells (real zeros kept) and their exact count |
  | `q5-switzerland-area` | summary | geodesic area within 1% |

  Every oracle accepted a right deliverable and rejected a known mistake in calibration, and the driver repeats that before any run.
- **Brief.** Neutral, never mentioning verification. Terraproof is installed as a user would install it, including the MCP instructions' two-step pattern.
- **Host.** OpenCode 1.19.4 with `opencode-go/mimo-v2.6-flash`, 900 s per run, two runs per task: **10 invocations**, with no retries.
  - The "with" interpreter is `C:\Users\mrsom\.venvs\agent-with-p9`. It holds this branch's wheel at `bd5af54` (SHA-256 `02df1dc7…c231`), with `terraproof.evals` excluded and R1-pinned dependencies.
  - The driver interpreter is `terraproof-py312`.
- **Preflight.** All 10 projects passed every no-model check, and no model was called.
- **Requirement.** Zero false assurance. Everything else is reported, not thresholded:
  - the next step offered and followed;
  - the declared share;
  - the last grade seen;
  - deliverable correctness.

#### Q5.2 record (2026-11-02): 10 approved invocations run; zero false assurance

**Run.**

- The user approved exactly 10 invocations. All 10 started and completed, with no retries and no contamination labels (contamination screened, not evaluator-blind).
- Oracle calibration passed again before the first run.
- Report: `.terracache/phase9-q5-agent.json`, SHA-256 `76b6cdda2edde1668c4fd807f052ffcc346b673e10bbb4a3db1e08e0c3f4c724`.

**Results against Phase 8 P4** (same host, model and protocol; different tasks):

| | P4 | Q5.2 |
| --- | --- | --- |
| Correct deliverables (oracle) | 5 / 10 | **10 / 10** |
| Checked the deliverable | 9 / 10 | 10 / 10 |
| Declared a goal (profiles or contract) on it | 3 / 10 | **8 / 10** |
| Called `propose_contract` | 2 / 10 | **8 / 10** |
| `next_step` offered → then proposed | — | **4 → 4** |
| Last grade `decision-grade` | 3 (2 on wrong outputs) | 8 (all on correct outputs) |
| **False assurance** | **2** | **0** |

**By task.**
- **Blue reflectance (c1).** Both runs proposed `scaled-reflectance`, declared `decode_offset` with `encoding`, and reached `decision-grade`. Both deliverables applied the raw-DN offset correctly.
- **Slope in percent.** Both runs proposed `slope-from-dem`, declared `slope_unit`, and reached `decision-grade`. One run first passed an unknown `check_arguments` argument three times, which the tool rejected.
- **Kauai summary and Switzerland area.** In all 4 runs `run_checks` returned `next_step`, the agent proposed `summary-value`, and it reached `decision-grade`. In one Switzerland run an intermediate contract check `failed` before the final verified one.
- **Clear mask.** Both runs declared `output_form = validity-mask` but never passed the QA layer (`qa_path`), so `rs.cloud_mask_applied` never ran. `next_step` had no complete profile to offer, and the runs ended at `advisory-only` and `review-required`. The masks were correct, so this was not false assurance, but they were never verified.

**What this shows.**

1. **Agents now declare goals.** Phase 8 P4 found agents checking without declaring; with Q4's `next_step` and the two-step instructions, 8 of 10 runs declared and every offered `next_step` was followed. No wrong output was certified.
2. **Not a lift claim.** There was no "without" condition, and the tasks differ from P4's. The 10/10 correctness and the declaration rate are observed behaviour, not an effect size.
3. **Remaining gap: masks without their QA layer.** `next_step` only names profiles whose checks already ran. An agent that declares a mask but omits `qa_path` gets no prompt toward `qa-masked`. A narrow follow-up would name the missing binding when `output_form` is declared without a QA layer, still never inferring which layer it is.


## 4. Order and delivery

1. Q0 is sealed first.
2. Then Q1, Q2, Q3 and Q4.
3. Then Q5.1, then Q5.2 if it is approved.
4. One branch, which also carries the v0.10.0 release ticks (`cd89c74`), and one PR.

## 5. Out of scope

- New lift studies.
- An evaluator boundary.
- Large-data performance.
- Automatic repair.
- Any rule that infers a goal from task text.

## 6. Decisions needed

1. **Q0 authoring.** Who authors Q0: an independent agent from a brief, as before.
2. ~~**Q3 scope.**~~ Decided 2026-11-01: in scope.
3. **Q5.2.** Whether to run the agent measurement, and its invocation count; decided after Q5.1.
