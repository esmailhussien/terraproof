# Heldout v5 routing evaluation protocol

## Frozen corpus

The corpus is [heldout_v5.jsonl](heldout_v5.jsonl). It is frozen with SHA-256 (computed over the exact file bytes: UTF-8 without BOM, LF line endings, one JSON object per line):

```text
5cc76cffc955ee03dc85f99cf7dccee419dd319ac2cbaf6416f36765ea891889
```

It contains 160 JSONL items: 80 English (`en`, ids `h5-en-001`…`h5-en-080`) and 80 Arabic (`ar`, ids `h5-ar-001`…`h5-ar-080`). Each language has 60 positive geospatial/remote-sensing work requests and 20 negative requests with `expected: []`. Positives list one to three skills in `expected`; English has 14 and Arabic has 15 compositional multi-skill positives (one English item lists three skills), each stating separable pieces of work. Every one of the 20 registered non-process skills in [routing/registry.json](../../routing/registry.json) appears at least three times in positive `expected` lists per language (the gate set during authoring was at least two). Eleven positives per language carry a `datasets` array (vector, raster, or STAC profiles following the [README schema](README.md#schema)) where the profile is part of the request context. Every negative forbids all 20 non-process skills in `must_not`. Positive `must_not` lists name plausible-but-wrong neighbouring skills and never overlap `expected`. Process skills (`brainstorming`, `writing-plans`, `systematic-debugging`, `verification`) are absent from `expected` and `must_not`.

The label vocabulary is the 20 non-process skills currently registered (the README schema text lists an older 16-skill subset; the evaluator accepts every registered non-process skill).

Item order was randomized once after corpus assembly by a Fisher–Yates shuffle (Python `random.Random(20261024)`, descending index loop with `randint(0, i)`), using deterministic seed `20261024`. Ids were assigned per language in the shuffled order, so id order does not reveal authoring groups. The seed was fixed before assembly (the authoring date) and was not chosen from router scores, ranks, candidates, or evaluation results.

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

The evaluator assigns recall 1 to an empty `expected` list. Therefore report the evaluator's per-language mean recall and also report positive-only recall for the 60 positive items in each language; positive-only recall prevents negative-item inflation from obscuring positive routing performance. Forbidden occurrences on negatives and on positives are both counted toward the per-language limit and should be reported separately as well.

A candidates-mode run is diagnostic only. It is not a gate, a substitute for ranked-mode results, or a basis for changing this corpus.

## Freeze and failure handling

Failures remain failures. After this freeze, do not alter prompts, labels, `must_not` lists, datasets, ordering, ids, or this protocol in response to results; there is no relabelling after measurement. Do not rerun or tune against this corpus after seeing failures, and do not cherry-pick alternate gates, subsets, modes, `top_k` values, or candidate lists. A later evaluation must identify the fixed SHA-256 above, confirm the file bytes still match it, and retain all failures in its report. If a label is later believed wrong, record that belief alongside the unchanged result; a corrected corpus must be a new, separately frozen version.

This protocol makes no release-gate pass claim. Router execution and evaluation were intentionally outside this authoring task; no result for this corpus exists at freeze time.

## Authoring method and independence boundaries

This is agent-authored heldout material, not expert-adjudicated material, and it provides no blindness guarantee beyond the boundaries listed here. All prompts were written fresh for this set as realistic operational requests. English prompts use varied geographies, sensors, and constraints. Arabic prompts were written separately (not as literal translations of the English items) in MSA and Egyptian/Gulf/Levantine professional phrasing with varied morphology (prefixes such as ال، و، ب، ل، ف; plurals; varied verb forms) and embedded English technical tokens (for example GeoTIFF, EPSG codes, Sentinel-1, STAC, PostGIS) as practitioners write them. Positives use the smallest clearly necessary capability set; multi-skill items state separable work rather than a kitchen-sink request. Negatives cover ordinary writing, email, translation, cooking, travel, budget spreadsheets, general programming and web/app maintenance, mathematics concepts, and HR, including deliberate incidental spatial or technical vocabulary (for example map out a week, layer cake, network with colleagues, project plan, new year's resolution, a band's tour, satellite office, data scientist interview, neural-network layers, monitor pixel density) without any geospatial operation.

Authoring read only:

- [AGENTS.md](../../AGENTS.md)
- [routing/registry.json](../../routing/registry.json) (skill names, layers, descriptions, capabilities, metadata)
- the `SKILL.md` documents under [skills](../../skills) (front-matter descriptions and when-to-use / do-not-use sections)
- [src/terraproof/router/evaluate.py](../../src/terraproof/router/evaluate.py), for the JSONL schema and validation rules only
- [HELDOUT_V4_PROTOCOL.md](HELDOUT_V4_PROTOCOL.md), as a structural template for this document only (it contains no items)
- the "Schema" section of [README.md](README.md)

Authoring did not open or search any other router implementation file (`src/terraproof/router/` modules other than `evaluate.py`, the TypeScript `router/`), router tests or scenarios, any development, heldout, internal, or release JSONL corpus, the release checklist, the changelog, shared notes, or git history/diffs. A directory listing of `evals/routing` showed existing file names only; no other corpus contents were read. The router, `find_guidance`, the evaluator, and the test suites were not run, and `terraproof.router` was not imported. Labels are the author's own judgement and were not informed by any router output. Structural validation (counts, unique ids, JSON validity, allowed skill names, no process skills, no `expected`/`must_not` overlap, per-skill per-language coverage, complete negative `must_not`, dataset key sets) was performed with a standalone script outside the repository.

## Declared limits

- Labels are author judgments of the smallest clearly necessary registered capability set, not an external gold-standard adjudication; some neighbouring skills (for example `gdal` versus `raster-processing`, or `geomaster` for general Earth-observation work) are left unlabelled rather than forbidden where either could reasonably help.
- The same author wrote both languages; Arabic items cover overlapping task families with independent wording, so the two languages are not statistically independent samples.
- The corpus measures the stated bilingual routing conditions only; it does not establish general production quality, safety, latency, or release readiness.
- Forbidden occurrences are counted as defined by the evaluator against `must_not`; they are not a complete taxonomy of all possible over-selection.
- Candidate diagnostics are retained for analysis but cannot override primary ranked-mode failures.
