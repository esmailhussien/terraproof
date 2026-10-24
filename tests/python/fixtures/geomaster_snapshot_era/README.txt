Snapshot-era copies of two geomaster files, used only by
tests/python/test_router.py::head_snapshot_index to keep the router's BM25 corpus
identical to the one tests/python/fixtures/router_head_snapshot.json was recorded
against.

- SKILL.md.txt          = skills/geomaster/SKILL.md before the 2026-10-24 terrain fix
- code-examples.md.txt  = skills/geomaster/references/code-examples.md before that fix

Both are unmodified upstream text from K-Dense-AI/scientific-agent-skills
(skills/geomaster/, commit 390f5146bf3c1877cf15636a3dd7b775e4f0f185), MIT licensed:
see third_party/kdense-scientific-agent-skills/LICENSE. They contain the incorrect
terrain snippet on purpose and must not be used as guidance.
