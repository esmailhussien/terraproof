# Terraproof — Phase 9 Plan: Cover real deliverables, make declaring the default

> Status: **in progress (2026-11-01)**. Q0 is sealed; no product code yet. It follows [Phase 8](Terraproof_Phase8_PLAN.md) and release 0.10.0.

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
