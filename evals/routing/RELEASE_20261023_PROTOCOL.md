# Phase4 release routing audit — 2026-10-23

This is a fresh **same-agent internal** audit after the scope/Arabic fixes. The
user requested one agent and accepted internal review instead of additional
reviewers. There is no claim of independent authorship or expert adjudication.
The historical independent v3/v4 failures remain unchanged. The exposed first
internal audit was explicitly promoted to development regressions, not reused
as fresh acceptance.

## Freeze and measurement

- [Corpus](release_20261023.jsonl) SHA-256:
  `02b445bd9c4816eec3bded3b88d7e3ef9a2f12a040af22c2ccc51d53fe609fd5`.
- 100 questions, 50 per language: two positive tasks for each of 20 domain
  skills, plus ten negative tasks that exclude every domain skill.
- Labels and corpus bytes were authored and saved before one call to
  `terraproof.router.evaluate.evaluate_file`, ranked top 5, `semantic=False`.
- Original numeric thresholds were retained: recall at least 0.90 and at most
  5 forbidden selections per 100, separately for each language. With 50 items,
  at most two forbidden selections are allowed.
- Negatives have recall 1 by evaluator convention; positive-only recall is
  reported separately. Cross-language counterparts are paired task families,
  not independent samples. Most cases name a capability/technology; adversarial
  paraphrase and broad real-world generalisation are not established.
- No old independent heldout prompts/failures were read. The author has seen
  router code and development data. This contamination risk and small sample
  size are material limits even when the numerical thresholds pass.

## One recorded result

Windows / Python 3.14.4, working tree based on `f918180` with uncommitted Phase4
changes. Local record: `.terracache/phase4-release-routing-acceptance.json`.

| Language | Items | Recall | Positive-only recall | Forbidden selections | Per 100 | Thresholds |
| --- | --- | --- | --- | --- | --- | --- |
| EN | 50 | 1.0 | 1.0 | 2 | 4 | Pass |
| AR | 50 | 0.98 | 0.975 | 1 | 2 | Pass |

Both languages meet the original numerical targets on this scoped internal
set. There were three forbidden selections and one missing positive skill; this
is not perfect routing. The corpus and labels were not changed after scoring,
and no routing fix was made from these release-audit failures. No independent
heldout pass is claimed. Real-host tool use and hosted CI have separate gates.

Post-measurement integrity note: while preparing the recovery checkout, a Git
whitespace check unexpectedly printed frozen v4 rows because that corpus uses
CRLF bytes. This occurred after the release audit and all routing edits; the
rows were not used for code/label changes or a new measurement. This author
must not be treated as an independent future v4 evaluator. Corpus hashes remain
unchanged; `.gitattributes` preserves v4 bytes and recognises its CR line ends.
