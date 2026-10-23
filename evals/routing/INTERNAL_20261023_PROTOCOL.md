# Internal routing audit — 2026-10-23

The user declined additional agents/reviewers and requested that the implementing
agent continue alone. This is a new **internal audit**, authored by the same
agent that inspected and modified the implementation. It is not an independent
heldout set or an expert-adjudicated acceptance measurement. It does not replace
the historical failed v3/v4 results or establish independent generalisation.

## Freeze before measurement

- Corpus: [internal_20261023.jsonl](internal_20261023.jsonl).
- SHA-256: `743909b10d02110287aa715c682b6e4d643735a0c5445640044fbb1b8f501221`.
- 160 items, 80 in each of English and Arabic. Each language has three positive
  cases for each of the 20 domain skills (60 total), plus 20 negatives that forbid
  every domain skill. Process skills are not scored.
- Language counterparts cover the same task families; they are not independent
  samples. Labels use the current documented skill scopes. Most cases name the
  capability or technology and are not adversarial paraphrase coverage.
- No previous heldout items or their per-item failures were consulted. The
  author has seen development data and router code, so contamination by that
  knowledge remains a material limitation.
- Labels and corpus bytes were saved before calling the router. Do not change
  labels or tune routing against these results and call a rerun fresh acceptance.

## Single measurement

Use `terraproof.router.evaluate.evaluate_file` once on the frozen corpus with
`mode="ranked"`, `top_k=5`, `semantic=False`. Derive per-language forbidden counts
from that same returned measurement, without additional router calls.

Retain the original numerical targets as audit thresholds: mean recall at least
0.90 for **each** language and at most 5 forbidden skill selections per 100
items for **each** language (at most 4 selections per 80). Negatives have recall
1 by evaluator convention; report positive-only recall as well.

Keep both passing and failing results. Report environment, corpus hash,
per-language recall, positive-only recall and forbidden counts, with explicit
internal authorship. A pass here is a scoped diagnostic and is not proof of the
unfulfilled independent release gate, real-agent tool use or hosted CI.

## Recorded result

One measurement on 2026-10-23, Windows / Python 3.14.4, source checkout at
`f9181801f57ce43f23cee19608bd7d3a1d7ce5f8` plus the uncommitted continuation
changes. Both languages missed an unchanged audit threshold:

| Language | Items | Recall | Positive-only recall | Forbidden selections | Per 100 | Result |
| --- | --- | --- | --- | --- | --- | --- |
| EN | 80 | 0.95 | 0.9333333333333333 | 10 | 12.5 | Forbidden-rate failure |
| AR | 80 | 0.8125 | 0.75 | 3 | 3.75 | Recall failure |

Local report: `.terracache/phase4-internal-routing-audit.json`. The corpus was
not relabelled, and the router was not tuned after this audit. These results
confirm an open performance problem on new questions despite a perfect score on
development data; they are not an independent comparison with v3/v4.

## Subsequent exposure and development use

The user subsequently requested completing and publishing Phase4. The agent
then inspected this internal audit's failures to fix the implementation. Its
160 unchanged items are now registered development regressions in
`tests/router/scenarios.json` and `dev.jsonl`. Any later score on this corpus is
an exposed regression score, never fresh acceptance. The original failed result
and SHA-256 above remain historical facts. The old independent v3/v4 items and
their failures were not inspected or used for this development work.
