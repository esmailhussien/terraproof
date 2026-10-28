# Terraproof — Phase 7 Plan: Say what was verified

> Status: **in progress (2026-10-28)**. V1 (grade and coverage) is implemented and V0 is sealed; V2–V4 have not started. It follows the [Phase 6 stop](Terraproof_Phase6_PLAN.md#e4-and-e5-record-2026-10-28-stop) and its [verification audit](../PHASE6_VERIFICATION_AUDIT.md). No model calls are planned.

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

## 4. Order

V0 is sealed first. V1 and V2 come next, together, because the grade needs the coverage block. V3 follows, then V4. V0 can be authored in parallel with the V1 design, but V2 and V3 code waits for the seal.

## 5. Out of scope

- New lift measurements with a model. Any later lift study needs a fresh task cohort, because the Phase 6 confirmation set was used to find these gaps.
- A whole-process evaluator boundary (Phase 6 R2). It remains a prerequisite for "evaluator-blind" claims.
- C group 3, large-data performance, spatial previews, automatic patches, signing and a public leaderboard, as deferred in Phase 6.

## 6. Decisions needed

1. **Decided (2026-10-28): `checks-passed`, exit 0.** CI pipelines keep running. The report, the MCP response and the Markdown summary state that coverage was not assessed and list what was not checked. `decision-grade` keeps exit 0 and is reserved for fully verified declared coverage.
2. **Decided (2026-10-28): an independent agent authors V0.** It works from a brief without check sources, and the result is sealed by hash before V2.
