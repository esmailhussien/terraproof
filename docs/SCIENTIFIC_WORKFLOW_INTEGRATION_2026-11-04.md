# Closed-trial project/workflow integration

2026-11-04 (Africa/Cairo). The user confirmed that the Phase 11 frozen experiment had completed and closed, and requested completion of the reviewed batch. This integration combines fixed PR 45 head `49bbab6afe52b2396ec9d5b5482416b18aa40718` and scientific-core PR 46 head `4bacbe62f08a8cf1a38261431dbe86b7bc8f250b` in [one PR](https://github.com/esmailhussien/terraproof/pull/46), preserving both ancestries.

## Resolution and scope

Two additive conflicts occurred in `CHANGELOG.md` and `src/terraproof/cli.py`. Both changelog sections and both CLI registrations are retained. `terraproof verify`/MCP `verify_project` perform declared project verification; `terraproof workflow` plans and executes the native Landsat temperature route. The production project/report/proposal/MCP changes come from the reviewed Phase 11 head. All seven scientific workflow modules remain unchanged from accepted candidate `77ce7aea9798f3622cec46d019a8267b52fb558a` after newline normalization.

An isolated detached worktree and separate interpreter validated the combined configuration. No original trial checkout/result, frozen acceptance artifact or shared dependency was modified. No model experiment was rerun and no new imagery was downloaded. This is a new combined configuration; historical measurements remain attributed to their original source/configuration.

## Combined validation

- Full offline Python regression: **2114 passed, 16 skipped**, 712.24 seconds. These are the combined-tree counts; the earlier 2083/13 result remains attached to its original frozen product candidate.
- Repository/link validation and diff checks passed.
- Wheel and source distributions built successfully with project verification and scientific workflows. The archive, independent oracle files and private evaluators are excluded from both distributions. The seven native-workflow modules match the accepted candidate after newline normalization; expected production differences are CLI, proposal/report and MCP integration plus the project module.
- Existing installed-wheel smoke passed outside the checkout, including skill assets, bilingual routing, evaluator exclusion and raster contracts.
- Actual CLI/MCP stdio release validation passed **20 assertions**. This is a validation command, not a package publication.

The five retained native acceptance variants were rechecked read-only under the combined code:

| Variant | Admission | Delivered-output recheck |
| --- | --- | --- |
| Phoenix R1-full | ready-for-review | verified / checks-passed |
| Cape Town R2-corner-default | unresolved | no approval/output |
| Cape Town R2-corner-cutoff | unresolved | no approval/output |
| Brisbane R3-baseline | ready-for-review | verified / checks-passed |
| Brisbane R3-strict | unresolved | no approval/output |

All **119 original frozen evidence records** matched their retained byte lengths and SHA256 values after the replay. New recheck reports are separate files; original approvals, outputs, criteria and results are unchanged. This compatibility recheck does not replace the [prior separate-context acceptance](SCIENTIFIC_WORKFLOW_INDEPENDENT_ACCEPTANCE_2026-11-03.md), its limitations or its disclosed oracle corrections.

Local integration evidence: `D:\AgentLayer-acl-recovery\scientific-workflow-merge-readiness-2026-11-04\integration`. It holds the full regression, distribution inspection, wheel/transport validation, conflict-resolution record and real-output compatibility reports. Final GitHub checks and merge state are recorded on PR 46.

## Boundaries

The workflow still reports numerical `checks-passed`, unauthenticated review declarations and `physical_accuracy_validated: false`. Unknown-uncertainty exclusions and other unexercised acceptance branches remain qualified in the original assessment. No new agent-lift, physical-accuracy or human scientific-suitability result follows from combining the interfaces. The original Phase 11 and native-scene measurement records are not retroactively rewritten.

Package versions remain 0.12.0 during this integration. Creating a version tag and publishing packages are separate work. See the [scientific workflow plan](plans/SCIENTIFIC_WORKFLOW_CORE_PLAN.md).
