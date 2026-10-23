# Heldout v4 routing evaluation protocol

## Frozen corpus

The corpus is [heldout_v4.jsonl](heldout_v4.jsonl). It is frozen with SHA-256:

```text
5fcb9c236ad22d2bd4254dac3c212c57499b7ded9f075a5d317ecb0945022874
```

It contains 160 JSONL items: 80 English (`en`) and 80 Arabic (`ar`). Each language has 60 positive domain-work requests and 20 negative requests with `expected: []`. Each language has 10 compositional multi-skill positives. Every one of the 20 declared domain/implementation capability skills appears at least twice in positive `expected` lists per language (the constructed base coverage is three appearances each before additional positives). Every negative forbids all 20 declared domain/implementation skills. Process skills are absent from `expected` and `must_not`.

Item order was randomized once after corpus assembly by a Fisher–Yates shuffle using deterministic seed `24112026`. The seed was selected for corpus ordering, not from router scores, ranks, candidates, or evaluation results.

## Preregistered primary evaluation

Run the frozen corpus in ranked mode with `top_k=5` and `semantic=False`:

```text
mode=ranked
top_k=5
semantic=False
```

The primary gates are evaluated separately for each language (80 items each):

- Mean per-item recall must be at least `0.90`.
- Forbidden-skill occurrences must be no more than 5 per 100 items. For 80 items, this permits at most 4 occurrences per language.

The evaluator assigns recall 1 to an empty `expected` list. Therefore report the evaluator's per-language mean recall and also report positive-only recall for the 60 positive items in each language; positive-only recall prevents negative-item inflation from obscuring positive routing performance.

A candidates-mode run at `top_k=8` is diagnostic only. It is not a gate, a substitute for ranked-mode results, or a basis for changing this corpus.

## Freeze and failure handling

Failures remain failures. After this freeze, do not alter prompts, labels, `must_not` lists, ordering, or the protocol in response to results. Do not rerun or tune against this corpus after seeing failures, and do not cherry-pick alternate gates, subsets, modes, or candidate lists. A later evaluation must identify the fixed SHA-256 above and retain all failures in its report.

This protocol makes no release-gate pass claim. Router execution and evaluation are intentionally outside this authoring task.

## Authoring method and independence boundaries

This is agent-authored heldout material, not expert-adjudicated material, and it provides no blindness guarantee. Prompts were independently written as realistic operational requests in English and natural Arabic (MSA and Egyptian professional phrasing), including nonliteral cross-language variety, geographic context, constraints, and quoted technical operands where useful. Positives use minimal one-to-three capability expectations; multi-skill items state separable compositional work rather than a kitchen-sink request. Negatives cover ordinary language work, workplace/application maintenance, mathematics concepts, and incidental technical terminology without a domain operation request.

Authoring inspected only [AGENTS.md](../../AGENTS.md), registered real skill metadata in [routing/registry.json](../../routing/registry.json), real skill documents under [skills](../../skills), and the JSONL field schema in [evaluate.py](../../src/terraproof/router/evaluate.py). It did not inspect production router implementation, routing signals/lexicons/intents/evaluation outputs, development or prior heldout corpora, router tests/scenarios, release-checklist/results/cache material, prior worker reports, or any router output. No routing, guidance lookup, or evaluator execution informed the labels.

## Declared limits

- Labels are author judgments of the smallest clearly necessary registered capability set, not an external gold-standard adjudication.
- The corpus measures the stated bilingual routing conditions only; it does not establish general production quality, safety, latency, or release readiness.
- Forbidden occurrences are counted as defined by the evaluator against `must_not`; they are not a complete taxonomy of all possible over-selection.
- Candidate diagnostics are retained for analysis but cannot override primary ranked-mode failures.
