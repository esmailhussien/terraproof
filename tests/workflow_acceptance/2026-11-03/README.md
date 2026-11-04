# Archived scientific workflow acceptance

These are byte-identical copies of the 2026-11-03 reviewer records and selected execution records. They make the [acceptance report](../../../docs/SCIENTIFIC_WORKFLOW_INDEPENDENT_ACCEPTANCE_2026-11-03.md) reviewable from the repository. They are historical evidence, not new runs or production rules.

Start with [the assessment](reviewer/ASSESSMENT.md), [public cases](reviewer/PUBLIC_CASES.json), [prior criteria](reviewer/SEALED_CRITERIA.md), and [the final independent comparisons](reviewer/independent-evidence.json). The corrected [checker](reviewer/independent_checker.py), first checker/evidence and both original reviewer manifests are retained. Criteria were prior-written; the executable oracle was written after outcome freeze. Separate AI context does not establish human scientific expertise or cryptographic blinding. The original reviewer report describes all corrections and unexercised conditions.

The archive holds 26 original text files (1,223,019 bytes). Native imagery, analytical outputs, browser profiles and Python environments are **not** repository payload. Complete original evidence remains at `D:\AgentLayer-acl-recovery\scientific-workflow-independent-acceptance-2026-11-03`. `OUTCOMES_FROZEN.json` describes that larger tree; it is not a claim that all 119 original files are present in this archive. All 10 members of `reviewer/SHA256_MANIFEST.json` and all 7 members of `reviewer/ASSESSMENT_SHA256.json` are included.

The archived programs expect the original complete directory layout, and some retained intent/provenance records contain original absolute paths. Running a checker in this archive would overwrite a neighboring historical report; run only in a separate reconstruction, preserving the originals. CI verifies retained hashes without executing the archived programs, fetching imagery or calling a model. A new end-to-end run should use the public requests, the frozen product commit `77ce7aea9798f3622cec46d019a8267b52fb558a` and fresh destinations; it is a new evidence record, not a rewrite of the original byte/path identities.

Verify the archive without remote calls:

```sh
python -m pytest -q tests/python/test_workflow_acceptance_archive.py
```

Archive bytes are protected against line-ending conversion by the local attributes file. This directory is outside the Python product package, explicitly pruned from source distributions, and excluded from the npm package by its existing file allowlist. It does not install oracle code beside the product or change the ongoing Phase 11 treatment.

Dataset attribution and primary references are retained in [the original public brief](reviewer/PUBLIC_BRIEF.md). Files copied from the original execution/review were not edited to remove old paths or rewrite wording; new navigation and packaging decisions are recorded here.
