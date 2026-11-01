# Terraproof — Phase 8 Plan: Easy declarations, real data, real agents

> Status: **in progress (2026-11-01)**. P0 sealed; P1 and P2 implemented; P3 measured (acceptance met when declared, not when proposed); P4 run (false assurance found through the `s2-l2a` preset). It follows [Phase 7](Terraproof_Phase7_PLAN.md) and release 0.9.0.

## 1. Why this phase

Phase 7 showed that Terraproof catches silent geospatial mistakes without false assurance, **when the user declares what they know**. On 48 sealed cases (V4b):

- 17 of 20 wrong outputs failed a required check.
- No wrong output was graded `decision-grade`, and 13 correct outputs were.
- No correct output raised a confirmed false alarm.

Three limits remain, and they decide whether this helps anyone in practice.

1. **Declaring is hard.** Every V4b miss came from an undeclared vertical unit. A user or an agent will rarely type `--qa-keep-code`, `--decode-scale` and `--dem-vertical-unit` unprompted. Yet most of those facts already sit in the data's own metadata: STAC `raster:bands` (scale, offset, nodata), band unit labels, QA asset roles, the CRS.
2. **The evidence is synthetic.** Both sealed sets were generated arrays. Real products have real metadata quirks:
   - fill values that are also valid codes;
   - scale and offset only in STAC;
   - QA layers on another grid;
   - missing or wrong unit labels.
3. **Agents were never measured on verification.** Phase 6 measured whether agents get better answers, and stopped at E5 because the models already did well. It never measured whether an agent that has Terraproof uses it to tell a good output from a bad one.

The aim is narrow: make the declared path the easy path, without guessing, and test it on real data and with a real agent.

## 2. Principles (unchanged from Phase 7)

- **Nothing is inferred from task text or file names.**
  - A proposal may only copy a fact that metadata states explicitly. It never infers one from value ranges or names.
  - The goal (which profile) is always the user's.
- **A proposal is not coverage.** A proposed binding counts only after the caller declares it, by passing the contract.
- **Cases first.** Held-out cases are sealed before any product code, measured once, then spent.
- **Mapping first.** Each measurement's mapping is committed before any result.

## 3. Workstreams

### P0. Seal a real-data held-out set (first)

- **What.** An independent agent authors at least 32 cases from small windows of public products:
  - Sentinel-2 L2A with SCL;
  - Landsat Collection 2 L2 with QA_PIXEL;
  - Copernicus or USGS DEMs, with metre and feet variants;
  - one NetCDF- or STAC-described packed product;
  - public vector boundaries.

  Wrong and correct outputs are derived from those real sources by scripts.
- **Data rules.**
  - No raster binaries are committed. The cases ship a fetch script with fixed URLs, byte ranges or windows, and the SHA-256 of every downloaded file, plus a deterministic derivation script and an independent oracle.
  - The data is cached locally. Tests skip without network or cache.
  - Licences and attribution go into [`sources/SOURCES.md`](../../sources/SOURCES.md), as AGENTS.md rule 10 requires.
- **Metadata as found.** Each case keeps the real metadata, including STAC items, so proposals can be measured on what products actually carry.
- **Sealing.** As in Phase 7: hashes of the committed files, plus a seal test. The content is not read for product work.
- **Seal record (2026-11-01).** An independent agent authored 34 cases from the brief, in a fresh clone of `main` (`b6aca7e`), on branch `geova/verification-heldout-real`, commit `3dfaedf`.
  - Counts: QA masking 4 wrong and 4 correct; scale, offset and fill 3 and 3; elevation units and slope 3 and 3; nodata 2 and 2; delivered metric values 3 and 3; plus 4 `plain` correct outputs. That is 15 wrong and 19 correct.
  - Sources: one Sentinel-2 L2A scene through Earth Search, Copernicus DEM GLO-30 and USGS 3DEP windows, and Natural Earth admin-0 at v5.1.2. Licences and attribution are in [`sources/SOURCES.md`](../../sources/SOURCES.md).
  - The agent reported that 112 of 162 `facts` entries (69.1%) are stated by the real metadata, two byte-identical cold fetches, two byte-identical derivations, and the oracle agreeing with all 34 cases. Not used: the requester-pays Sentinel-2 granule bucket.
  - The maintainer side verified the committed LF hashes, the import lines (no `terraproof` import) and the fetch hosts. It then ran a fresh fetch; the manifest hash matched, and the cases' own test passed 5 of 5. The case content was not read.
  - The commit adds `eol=lf` rules for these files to `.gitattributes`. A later commit makes the cases' test skip in CI without a cache unless `TERRAPROOF_HELDOUT_REAL_FETCH=1` is set, so routine CI runs download nothing.

  | File | SHA-256 |
  | --- | --- |
  | `evals/verification-heldout-real/cases.json` | `cd0c87d4456e53eab4c494604d6e197445a0584c0fc81da07650229e6812036f` |
  | `evals/verification-heldout-real/fetch.py` | `bfb015154cce813e9e975e69f10c3ed6e16f9c3e26e915b396980354f50619df` |
  | `evals/verification-heldout-real/derive.py` | `5141dd2794eddacde23968cec860d112effe9234c5847b31e3aecc37f04ac386` |
  | `evals/verification-heldout-real/oracle.py` | `2dce2f5cabeecec4b4fe4678e0cff7c714cf9d9324e3b7e600806078af54a2e1` |
  | `evals/verification-heldout-real/README.md` | `4765c19a71d063265b3c5b461ad72bd83618c3375fb19af3a93efbfc18597d62` |
  | Fetched-file manifest (`manifest.json` in the cache) | `6aaf6aeb15f3370bc9e27f6a99c699905dc0ab514b9e8f2124f45cecf503e486` |

### P1. Contract proposals from metadata

- **Command and tool.** `python -m terraproof propose OUTPUT... --profile NAME [--source PATH|--stac ITEM]...` and an MCP tool `propose_contract`.
  - The caller names the goal profile or profiles and the sources.
  - Terraproof fills each binding the profile needs **only from explicit metadata**, such as STAC `raster:bands` `scale`/`offset`/`nodata`, a band's unit label, a QA asset's declared role and classes, or the dataset CRS.
  - Each binding records its evidence: file, field and value.
  - Bindings that no metadata states are listed as **still undeclared**, with the argument that would supply them.
- **Output.** A draft contract marked `"status": "proposed"`, which the caller saves or edits and then passes as `--contract`.
  - A proposed contract is never applied automatically.
  - `run_checks` without a contract may return the proposal beside `checks-passed`, labelled as a proposal.
- **Tests.** Every binding source gets a fixture where the metadata states it, and one where it does not; the latter must leave the binding undeclared, never filled. Fixtures with conflicting metadata, such as a file label against STAC, must report the conflict instead of choosing.

#### P1 record (2026-11-01): implemented

- **Interface.** `propose` takes the same flags as `check` for what the caller knows; the separate `--source` flag was not needed. `--stac FILE=ITEM.json#ASSET` ties a file to a STAC asset explicitly; nothing is matched by name. The MCP tool `propose_contract` takes `paths`, `profiles`, `arguments` (named as for `run_checks`) and `stac`.
- **What metadata can fill.** Only facts about sources:
  - `dem_vertical_unit` and `vertical_source_units`, from a band unit label or STAC `unit`;
  - `decode_scale` and `decode_offset`, from STAC `scale`/`offset` or a file scale other than 1 or offset other than 0 (rasterio reports 1 and 0 when a file states none);
  - `support_source_nodata`, declared only where STAC states a fill the file lacks; a file's own fill keeps its mask.
  - `scaled-reflectance` binds `expect=reflectance` from the profile itself, recorded as `from: profile`.
- **Left to the caller.** The goal and verification choices: operations, the output's unit, the support rule, the QA kind and keep codes, and `processing_full_scan`. Each is listed in `undeclared` with its flag. A QA asset's roles and classes name what codes mean, not which ones a quality rule keeps, so `qa-masked` gets nothing from metadata. CRS needs no binding, since the checks read it themselves.
- **Output.** `status: proposed`, the contract (absolute paths), each binding with `from` (caller, metadata or profile) and evidence, then `undeclared`, `not_stated`, `conflicts` and `unusable`, plus `check_arguments` and `check_command`. `--contract-out` writes the contract alone. A caller's binding is never replaced.
- **Not done.** `run_checks` does not attach a proposal beside `checks-passed`. The plan left it optional, and an unrequested proposal next to every report would add noise without coverage.
- **Tests.** [`tests/python/test_propose.py`](../../tests/python/test_propose.py) has 15 tests: stated and unstated for each binding source, file-against-STAC conflicts for unit and scale, unusable labels, caller precedence, determinism, relocatable contracts, refused input, and a CLI proposal run to a verified contract. CLI/MCP parity is in `tests/python/test_mcp.py`.

### P2. Remaining check gaps

- **Categorical resampling.** Output values must be a subset of the source's class codes. This catches the invented classes `bilinear` and `cubic` produce.
- **Domain of a SAR filter.** A declared filter (boxcar, mean) is recomputed in linear power, not dB.
- **Temporal labels.** A declared accumulation window is checked against the per-layer dates.
- **`geometry.winding` severity.** Decide whether ring orientation on otherwise correct deliverables stays `fail` or becomes `warn`. The decision is recorded before P3 and does not use P3 results.

Each new or changed check follows the Phase 4 rules: a fail fixture, a pass fixture, zero false passes on all regression sets, and CLI and MCP parity.

#### P2 record (2026-11-01): implemented; winding decided before P3

- **`raster.categorical_codes`** (`--categorical-source`). Every valid output code must occur among the source's valid codes, on any grid. A subset is necessary, not sufficient: a nearest-neighbour shift or a dropped class is not detected.
- **`sar.filter_domain`** (`--sar-filter boxcar`, `--sar-filter-size`, `--sar-filter-source`, plus `--sar-expect` for both rasters). The boxcar is recomputed in linear power on the shared grid. Only cells whose whole window is valid are compared. A failure counts the cells that match the dB-domain average, which names the mistake. "Mean" is the same filter as boxcar, so it has no separate name.
- **`rs.stack_window`** (`--stack-window START END`, one `--stack-time START/END` per `--stack` layer). Layers must lie inside the labelled window without overlap. For `weighted-sum` they must also cover it without gaps, and each weight must equal its layer's hours. The per-layer intervals are declared; no metadata standard states them, so `propose` cannot fill them.
- **No new goal profiles.** The P0 families do not cover these checks, and contracts can name them as `checks`.
- **`geometry.winding`: `warn` (decided 2026-11-01, before any P3 run).** RFC 7946 §3.1.6 binds writers to the right-hand rule but tells parsers not to reject polygons that break it, and orientation changes no coordinate, area or topology. Phase 7 V4 recorded it failing a correct buffer (geom-06) as review burden. A warning still keeps a contract from `decision-grade`, so a non-conforming file is never certified, but it is no longer graded as wrong. User-visible: a clockwise GeoJSON with no other finding now exits 2 instead of 3.
- **Tests.** [`tests/python/test_phase8_checks.py`](../../tests/python/test_phase8_checks.py) has 14 tests:
  - for each check, pass and fail fixtures and refused or missing declarations;
  - SAR in both domains, across window boundaries;
  - a contract naming the missing window bindings;
  - CLI/MCP parity.

  The winding tests in `test_false_passes.py` and `test_mcp.py` now expect `warn`. The new checks are opt-in, so they never run on the regression sets unless declared.

### P3. Measure once on the real-data set (offline)

Three configurations, each with its mapping committed first.

1. **Declared by hand.** As V4b, from each case's declaration.
2. **Proposed.** Only the profile and the source paths are given; every other binding comes from `propose`. This measures whether metadata alone gets users to verified coverage.
3. **Undeclared.**

Reported measures are Phase 7's five, plus:

- the share of required bindings that a proposal filled from metadata;
- the bindings it left undeclared;
- the conflicts it reported.

**Acceptance, fixed now.**

- In every configuration, zero false assurance: no wrong output graded `decision-grade`.
- Zero confirmed false alarms within declared coverage.
- In the proposed configuration, no binding filled from metadata that contradicts the case's ground truth.

Detection and the proposal fill rate are reported, not thresholded.

#### P3 record (2026-11-01): measured once; acceptance met when declared, not when proposed

**Run.**

- The 34 sealed cases were fetched and derived with their own scripts, and their oracle agreed with all 34.
- [`tests/phase8_p3.py`](../../tests/phase8_p3.py) maps each case to three configurations. It uses one rule per deliverable form, never reads `kind`, and gives each wrong/correct pair the same rule. It was committed (`122c35c`) before any result existed.
- It ran once on the product at `4d9f360` (P1 and P2 included).
- Result: `.terracache/phase8-p3.json`, SHA-256 `138b73d4023e3a1477b92c9b70f818ba73e219c0b2d7fd64eff8e9483a04a06c`.
- These cases are now spent.

**Coverage first.** 20 of the 34 real deliverables fall outside what any check verifies, so they get no requirement in any configuration:

| Deliverable form | Cases | Why no check applies |
| --- | --- | --- |
| 1/0 validity mask | 12 (all of QA masking, 3 nodata, 1 scale) | Checks read nodata, not a 0 value |
| JSON report | 5 | Not a dataset |
| Slope in percent | 3 | `terrain.slope_consistent` takes degrees only |

That leaves 7 wrong and 7 correct cases with a declared requirement.

**Results.**

| Measure | Declared | Proposed | Undeclared |
| --- | --- | --- | --- |
| Wrong outputs failing a required check | 7 of 7 covered (7 of 15 overall) | 3 | 0 |
| Wrong outputs graded `decision-grade` (false assurance) | **0** | **0** | **0** |
| Correct outputs with a failing check (false alarms) | **0** | **2** | 0 |
| Correct outputs graded `decision-grade` | 1 | 0 | 0 |
| Correct covered outputs graded `review-required` | 5 | 0 | — |
| Requirements left incomplete | 1 | 13 | — |

- **Declared.** All 7 covered wrong outputs failed a required check:
  - raw DN, a sign-flipped offset, and fill decoded as data;
  - metres labelled as feet, where fill kept as data also failed;
  - area, perimeter and buffer computed in degrees.

  Of the 7 correct covered outputs:
  - 1 is `decision-grade` (the NDVI range).
  - 5 are `review-required`, from genuine findings that are not errors: two reflectance outputs declare no nodata, and the three Natural Earth geometries break the RFC 7946 ring order.
  - 1 is `incomplete`: the Svalbard slope was reprojected, so the DEM and the slope no longer share a grid and `terrain.slope_consistent` is not-run.
  - Under the old `fail` severity for `geometry.winding`, the three correct metric outputs would have been false alarms. That severity was decided before this run (P2 record).
- **Proposed.** The configuration gave goal profiles, source paths, and for each band file the STAC asset it came from. Acceptance was **not met**:
  - **Wrong offset.** The scene's STAC item states `raster:bands` offset `-0.1` for every reflectance asset, and also `earthsearch:boa_offset_applied: true` in its properties. The stored values already include the offset: the lowest green DN is 35, which an offset would make negative reflectance. The case oracle anchors on that flag and physical plausibility. `propose` copied the `-0.1` (evidence: `assets.green.raster:bands[0].offset`). That contradicts the truth in all 5 scale cases and makes `rs.scale_applied_once` fail both correct decodes, which are the 2 false alarms.
  - **No coverage from metadata.** Metadata filled none of the 45 required coverage bindings. Its 10 fills were `decode_scale` (right, 5 cases) and `decode_offset` (wrong, 5 cases); neither is a coverage binding. The 5 `expect` bindings came from the profile. (The script's `required_filled_from_metadata: 5` counts those profile bindings; this table corrects it from the same result file.)
  - **Left undeclared.** The goal bindings: operations, the output unit, the support rule, and the metric quantity, property and unit.
  - **Not stated.** The vertical units. 3DEP states metres only in its FGDC XML sidecar, which `propose` does not read, and GLO-30 states no unit at all.
  - **Conflicts reported:** none. The flag that disagrees is a vendor property that `propose` does not read.
  - **No false assurance.** Every requirement was `incomplete` or `failed`, so no output reached `decision-grade`.
- **Undeclared.** No failures, and no false assurance. The two clean correct outputs were `checks-passed`.

**What this shows.**

1. **Declarations work.** With the declarations a careful user would make, Terraproof caught every covered real-data mistake, with no false assurance and no false alarm.
2. **Proposals are not yet safe.** Metadata alone does not get users to coverage here, and real STAC metadata can be self-contradictory. A proposal must treat a stated "offset already applied" as a conflict, not copy the offset.
3. **Coverage is the larger gap.** 59% of these real deliverables are forms no check verifies: validity masks, slope in percent, and summary reports.

These findings cannot be fixed and re-measured on these cases. Any fix needs fresh sealed cases.

#### After P3 (2026-11-01): the offset conflict fixed, not re-measured

- **Fix.** `propose` now reports a STAC `raster:bands` offset as a conflict, instead of filling it, when the same item states `earthsearch:boa_offset_applied: true`. The scale is still proposed.
- **Tests.** Fixtures cover the flag true (conflict) and false (offset filled).
- **Sanity run, not a measurement.** On the real cached item, `propose` now fills only `decode_scale` and lists the `decode_offset` conflict, citing both fields.
- **What it does not show.** The P3 cases are spent, so this does not show that P3's proposed-configuration acceptance would now be met. Only fresh sealed cases can.
- **Still unaddressed.** The coverage gaps (validity masks, slope in percent, reports) need their own work and their own fresh cases.

### P4. Agent verification behaviour (optional; separate approval)

- **Setup.** One OpenCode Go model, MiMo-V2.6-Flash as registered in Phase 6, with the Terraproof MCP server. It runs on a small set of real-data tasks drawn from P0's sources but not from its sealed cases.
- **Approval.** The exact invocation count is approved separately before any run.
- **What is measured.** Not lift, but:
  - whether the agent calls `propose_contract` or declares profiles;
  - the share of its outputs that reach assessed coverage;
  - false assurance on its outputs: wrong outputs it would hand over as `decision-grade`.
- **Trace handling.** Traces keep Phase 6's contamination labels, and results are labelled "contamination screened".

#### P4 design (2026-11-01): registered before any run

- **Driver.** [`tests/phase8_p4.py`](../../tests/phase8_p4.py) is committed before any P4 run. Its label extraction is tested in `tests/python/test_phase8_p4.py`. It reuses Phase 6's OpenCode adapter, trace sanitising, install, brief and preflight, and runs the "with" condition only.
- **Tasks.** Five, on windows of the P0 sources that are not its sealed cases. Each has one deliverable and an oracle that uses numpy, rasterio and pyproj, never Terraproof:
  - `p4-s2-blue-reflectance`: blue DN to reflectance, with the STAC item. The offset is already applied, so the truth is DN × 1e-4, with fill as nodata.
  - `p4-s2-swir-clear`: SWIR reflectance keeping SCL 4, 5, 6 and 11.
  - `p4-kauai-feet`: 3DEP metres to international feet, keeping fill as nodata.
  - `p4-svalbard-slope`: GLO-30 slope in degrees on a geographic grid. It passes if the median difference is at most 0.5° and the 95th percentile at most 3°.
  - `p4-iceland-area`: geodesic area in km², within 1%.

  Every oracle accepted a right deliverable and rejected a known mistake in calibration. The driver repeats that calibration before any run and stops if it fails.
- **Brief.** Neutral: it asks for the deliverable and never mentions verification. Terraproof is installed as a user would install it: routed skills, the MCP server with seven tools, and its instructions.
- **Host.** OpenCode 1.19.4 with `opencode-go/mimo-v2.6-flash`, 900 s per run, two runs per task: **10 invocations**, with no retries.
  - The "with" interpreter is `C:\Users\mrsom\.venvs\agent-with-p8`. It holds this branch's wheel at `56f3108` (SHA-256 `572106fe…ea50`), with `terraproof.evals` excluded and dependencies pinned to R1's `agent-with-r1c`.
  - The driver interpreter is `terraproof-py312` with this checkout's `src`. The 3.14 interpreter under `D:\AgentLayer\.venv` cannot host the run: its temp folder resolves to the checkout, and an `opencode` started from it cannot open its own log.
- **Preflight.** All 10 prepared projects passed every no-model check: inputs, outputs, skills, MCP registered and serving the seven tools, interpreter isolation, and global OpenCode config. No model was called.
- **What is reported.** Per run, from the trace, as names and enums only:
  - whether `propose_contract` was called;
  - whether `run_checks` targeted the deliverable, and with `profiles` or a `contract`;
  - the grade and verification status of the last such check.

  Also reported: the oracle verdict, the summary rates and false assurance (a wrong deliverable whose last check the agent saw as `decision-grade`). There is no acceptance threshold: P4 describes behaviour.

#### P4 record (2026-11-01): 10 approved invocations run; false assurance found

**Run.**

- The user approved exactly 10 invocations. All 10 started and completed, with no retries.
- No run carried a contamination label (contamination screened, not evaluator-blind).
- Oracle calibration passed again before the first run.
- Report: `.terracache/phase8-p4.json`, SHA-256 `5c1e6e3e07dde1cff0d6db2a3a2b0855bc17f7754a202e8955719ad663d5e3ff`.
- Two reporting bugs were fixed after the run, not affecting what ran or was recorded:
  - The final console print crashed on a `None` key after the report was written.
  - One run passed `profiles` as a string, and its label split it into characters. The run's own label shows the characters of `scaled-reflectance`.

**Results.**

| Task | Deliverable correct | Checked the deliverable | Declared (profiles or contract) | Last grade the agent saw |
| --- | --- | --- | --- | --- |
| Blue reflectance | 0 / 2 (offset −0.1 applied) | 2 | 2 (one through `propose_contract`) | **decision-grade, decision-grade** |
| SWIR clear | 0 / 2 (offset −0.1 applied) | 2 | 0 | review-required, review-required |
| Kauai feet | 2 / 2 | 2 | 0 (declared units without a profile) | review-required, review-required |
| Svalbard slope | 1 / 2 (one run delivered nothing) | 1 | 1 (through `propose_contract`) | none, decision-grade |
| Iceland area | 2 / 2 | 2 | 0 | advisory-only, advisory-only |

- The agent checked its deliverable in 9 of 10 runs, but declared a goal (profiles or a contract) in only 3. It called `propose_contract` in 2 runs; one first attempt named a profile that does not exist.
- Of 3 `decision-grade` results, **2 were wrong deliverables: false assurance.**
  - In both, the agent passed `encoding="s2-l2a"`. Terraproof's preset for it decodes DN × 1e-4 − 0.1. These Earth Search COGs already include the offset: 73% of the blue window's DNs are below 1000, and open water's SWIR median DN is 80. The preset therefore matched the wrong output exactly.
  - `rs.reflectance_range` did not catch it. It is a loose screen (p1 ≥ −0.5, p99 ≤ 1.5).
  - In one of the two runs, `propose_contract` had reported the offset conflict (the post-P3 fix), but the agent's own `encoding` argument reintroduced the offset.
- The Iceland area was correct in both runs but graded `advisory-only`. The agent also passed `operation="area"`, so `crs.metric_operation` failed on the geographic file: a misuse that turned into an alarm on a correct output.

**What this shows.**

1. **Agents check, but rarely declare.** Most checks ran without a goal, so they could never certify, and never falsely certify, either.
2. **A built-in preset is a binding no one can see.** `encoding="s2-l2a"` silently states an offset that is wrong for a major public distribution. This is the same fact P3 found in metadata, now coming from Terraproof itself.
3. **One required fix:** the `s2-l2a` preset must not certify a decode whose offset would make the source's own DNs implausible. It must also never override a STAC statement that the offset is already applied.

#### After P4 (2026-11-01): the `s2-l2a` preset fixed, not re-measured

- **Rule.** The fix uses a declaration rule, not a dark-pixel threshold. A threshold would be fragile: in the P4 windows only 3% of SWIR DNs and 1% of NIR DNs fall below 1000.
  - `--encoding s2-l2a` now uses a declared `--decode-offset`.
  - Without one, it tests both 0 and −0.1. An output matching either is `not-run`; it names the matching offset and lists `decode_offset` as missing. Only an output matching neither fails, so raw-DN and double decodes are still caught.
  - This holds in both sampled and full-scan modes.
- **Trade-off.** A decode that forgot the offset on pre-harmonised ESA data now gives `not-run` instead of `fail` unless `--decode-offset -0.1` is declared. It is never certified. The cost is one declaration: the offset was always a fact about the data's baseline and distributor, not about the product name.
- **Tests.**
  - Existing tests that relied on the preset's −0.1 now declare it.
  - New tests cover both offsets and the double decode, in both scan modes.
- **Not re-measured.** The P4 tasks are spent for measurement; any new agent run needs fresh tasks and a fresh approval.

## 4. Order and delivery

1. P0 is sealed first, by an independent agent, from a brief kept outside the repository.
2. P1 and P2 follow, then P3. P4 runs only if approved.
3. **One branch and one PR for the whole phase.**
   - Commits accumulate locally, and the full local suite runs before any push.
   - The branch is pushed as a draft only when a CI signal is needed, and marked ready at the end.
   - Seals, measurement records and checklist ticks ride on the same PR.
4. **One release, 0.10.0**, after the PR merges, and only if P1 or P2 changed user-visible behaviour. Docs, evals and measurement records alone never trigger a release.

## 5. Out of scope

- New lift studies; Phase 6's E5 stop stands.
- A whole-process evaluator boundary, which is still required before any "evaluator-blind" claim.
- Large-data performance, spatial previews, automatic patches, signing and a public leaderboard.

## 6. Decisions needed

1. **Who authors P0.** The proposal is an independent agent from a brief, as for V0 and V0b.
2. **Whether to run P4**, and its exact invocation count, decided after P3.
