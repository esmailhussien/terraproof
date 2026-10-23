# Terraproof routing heldout_v3 protocol

## Freeze and purpose

This is a freshly agent-authored EN/AR routing evaluation corpus, written after the router checkpoint was frozen. It measures retrieval of minimal task-relevant skills, not completion of the tasks themselves.

- Router checkpoint supplied and verified at initial inspection: `f9181801f57ce43f23cee19608bd7d3a1d7ce5f8` (short form `f918180`). This is a Git object ID, not the corpus SHA256.
- Frozen corpus: [heldout_v3.jsonl](heldout_v3.jsonl).
- Exact corpus byte SHA256: `9cafbb7b1d378f281fd643e0a61869980b11ce2aa17b765461d350d14fba3ae9`.
- Encoding: UTF-8 without BOM; one JSON object per line. The hash covers the actual bytes, including line endings and the final newline. Verify bytes rather than assuming a checkout preserves them.
- Scope: only this protocol and the new corpus. No production code, existing datasets, other workers' tests, provenance/optical recipes, evaluation README, host validation, CI or release checklist were changed by this author. No commit, push, publication, model installation or download was performed.

The coordinator must verify the checkpoint and corpus hash before a downstream run. If router changes occur before that run, results must not be attributed to the frozen checkpoint. Subsequent router development against this corpus makes it a regression set, not an unseen heldout set. Do not silently edit labels after seeing outputs; any correction requires a documented new version/hash and disclosure of exposure.

## Independent authorship and its limits

Permitted authoring evidence was limited to project instructions, real skill SKILL.md domain documentation, registered skill IDs from [registry.json](../../routing/registry.json), and the evaluator input/metric contract in [evaluate.py](../../src/terraproof/router/evaluate.py). Registry access extracted IDs only; no trigger, signal, dependency or scoring metadata informed the tasks. Read-only assistants summarized the permitted skill documents. Git status and checkpoint checks established worktree context, not routing behavior.

No router implementation, signals, lexicon, dev corpus, older heldout content, previous routing outputs, metrics or failing-item reports were inspected. No routing or evaluator execution occurred before or after authoring. This protocol and its gate were fixed before any such output was available. Input validation used Python standard-library JSON and filesystem operations only, without importing the router.

The corpus is agent-authored, not authored or adjudicated by human domain experts. Domain labels are reasoned judgments grounded in skill documentation, not observed router selections. There has been no empirical inter-annotator agreement study, expert validation, or task execution. Familiar public domain concepts may overlap other corpora by coincidence; global novelty cannot be certified without inspecting prohibited material, which was deliberately not done. Languages share a coverage plan and some boundary concepts, so they are not independent statistical samples. Prompts were written as distinct tasks, not literal translated duplicate pairs; Arabic includes formal and colloquial Egyptian/Gulf-style intent expressions, not comprehensive dialect coverage.

## Item design and labeling

There are 120 items: IDs `v3-en-001` through `v3-en-060` and `v3-ar-001` through `v3-ar-060`. Each item contains exactly `id`, `prompt`, `lang`, `expected`, and `must_not`. No dataset profiles are necessary: input state is specified in the prompt, so `datasets` is omitted rather than inventing profile fields.

Each language has 48 positive items and 12 empty-expected items (20% negatives). Across the corpus, 80 items expect one skill, 16 expect two, and 24 expect none. No item expects more than two. The four process skills `brainstorming`, `writing-plans`, `systematic-debugging`, and `verification` never appear in either label array.

Labeling criteria:

- `expected` is a minimal set of high-confidence skills for the requested operation, not every useful supporting tool and not a full workflow dependency closure. Incidental file formats, project names and tool availability do not establish an expectation.
- Broad geospatial science expectations use substantive terrain, hydrology, point-cloud or EO classification objectives. They are not automatically added to every specialist task.
- `must_not` is used only when the skill is genuinely outside the stated scope: optical preparation versus SAR, database-only versus Python rewriting, presentation-only versus new inference, or explicitly out-of-scope domain work in narrow host edits. Legitimate supporting skills are not excluded merely because a more specialized skill is expected.
- Empty expected means no domain skill is required by the request. It does not establish a global abstention rule or mark every unlisted skill as forbidden. Forbidden annotations are intentionally selective, not an exhaustive precision oracle.
- Natural professional requests take priority over registry-like phrasing. Technology names occur when they are genuine constraints of the work, not manufactured lists of triggers.

### Boundary and negative coverage

Positive tasks distinguish data acquisition from processing data already in hand, source suitability from STAC access mechanics, optical QA/decoding from index formulas, SAR backscatter from optical reflectance, single-period preparation from temporal inference, and map validation from general statistical inference.

Correctness traps include datum and feet/metre confusion, antimeridian distances, grid alignment, categorical resampling, count-versus-density aggregation, valid zeros versus nodata, exactly-once optical scale/offset handling, additive constants in EVI/SAVI, QA masks, linear versus dB averaging, seasonal comparability, uneven observations and area-weighted accuracy estimates. Expectations do not require processing fictional supplied files; prompts request plans or code appropriate to their stated input state.

Items 049–060 in each language are empty-expected negatives: narrow host labels/configuration/authentication edits, generic writing or Python requests, IT-network versus graph ambiguity, incidental remote-sensing terminology, confirmed receipt of already acquired files, figurative coordinate language and administrative requests about accuracy reports. Other near-neighbor distinctions occur inside positive tasks; not every difficult contrast is an empty-expected item. Arabic explicitly distinguishes polite administrative intent, negated work scope, and phrases such as requests for preparation rather than change detection.

There are 33 forbidden skill annotations in EN and 31 in AR, including positive-item boundaries. These counts describe annotation density, not measured forbidden selections.

## Per-skill and language coverage

Counts are positive expected-label occurrences, not item counts or retrieval results. Every non-process registered skill is expected at least twice in each language. Most have two standalone examples per language, with deliberate two-skill boundary tasks adding coverage.

| Skill ID | EN | AR |
| --- | ---: | ---: |
| accuracy-assessment | 3 | 3 |
| crs-and-units | 3 | 3 |
| design-postgis-tables | 2 | 2 |
| gdal | 3 | 3 |
| geomaster | 2 | 2 |
| geopandas | 4 | 4 |
| geoparquet-validation | 2 | 2 |
| geospatial-data-discovery | 2 | 2 |
| geospatial-frontend | 2 | 2 |
| geozarr | 2 | 2 |
| networkx | 2 | 2 |
| raster-processing | 3 | 3 |
| sar-basics | 3 | 3 |
| satellite-preprocessing | 4 | 4 |
| scientific-visualization | 3 | 3 |
| spectral-indices | 3 | 3 |
| stac-and-cloud-access | 3 | 3 |
| statistical-analysis | 3 | 3 |
| time-series-and-change | 4 | 4 |
| vector-quality | 3 | 3 |
| Total expected-label occurrences | 56 | 56 |

The four newer specialized domains are represented by `stac-and-cloud-access`, `sar-basics`, `accuracy-assessment`, and `time-series-and-change`. Optical preprocessing and indices have separate coverage rather than being folded into a broad remote-sensing label.

## Predeclared downstream evaluation gate

No routing scores have been measured by this author. The coordinator may evaluate only after verifying this freeze and without intervening router changes.

Primary gate: ranked recall@5 must be **at least 0.90 separately for EN and AR**, and forbidden picks must be **at most 5 per 100 items separately for EN and AR**. Both conditions must pass in both languages; pooled performance cannot compensate for a language failure. With 60 items per language, the forbidden threshold is at most 3 occurrences per language (and therefore at most 6 over all 120 items).

For item i, recall is `|expected_i intersect ranked_top5_i| / |expected_i|`; the evaluator assigns 1 when expected is empty. Average those item recalls within each language, matching the documented evaluator semantics. This means negatives contribute automatic recall credit; report positive-only recall as a supplementary diagnostic to expose that limitation, not as a newly imposed gate.

A forbidden pick is one distinct annotated `must_not` skill present in an item's returned top five. Two different forbidden skills on the same item count twice. The per-language rate is `100 * forbidden_occurrences / language_item_count`, not the percentage of items with any violation. A pick absent from both label arrays is unjudged, not automatically a violation. This is not exhaustive precision measurement. The evaluator's CLI exit policy rejects any forbidden occurrence; that stricter exit code is not identical to this predeclared rate gate, so the coordinator must apply the stated gate to the recorded counts.

Candidate@8 is diagnostic only: report candidate inclusion recall and misses separately from ranked@5 and never use it to substitute for a failed primary gate. Record checkpoint, corpus hash, actual evaluation configuration and semantic mode with results. Do not silently enable a download or new model dependency. Ranked output here refers to the documented router ranking interface; no host-injected, host-reranked or end-to-end host behavior has been measured or established by this corpus author. Those claims require separate host evidence.

## Offline artifact validation

The exact requested deciding command was executed successfully from the repository root:

```powershell
.venv\Scripts\python -c "import json,hashlib; from pathlib import Path; p=Path('evals/routing/heldout_v3.jsonl'); rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]; reg=json.loads(Path('routing/registry.json').read_text(encoding='utf-8')); assert len(rows)==120; assert len({r['id'] for r in rows})==120; assert sum(r['lang']=='en' for r in rows)==60; assert sum(r['lang']=='ar' for r in rows)==60; assert all(not(set(r['expected'])&set(r.get('must_not',[]))) for r in rows); print('120 unique items; 60 EN / 60 AR; sha256='+hashlib.sha256(p.read_bytes()).hexdigest())"
```

Observed output:

```text
120 unique items; 60 EN / 60 AR; sha256=9cafbb7b1d378f281fd643e0a61869980b11ce2aa17b765461d350d14fba3ae9
```

Additional standalone offline assertions passed for exact required keys, nonempty string prompts, language-to-ID agreement, complete ID ranges, unique prompts, string arrays with no duplicate labels, registered non-process membership, maximum expected cardinality of two and positive coverage of every skill in both languages. Coverage and negative counts above were computed from the frozen corpus. No optional dataset schema is exercised because no profiles are supplied.

`git diff --check` is the final whitespace check; its actual result is reported at handoff. Offline validity does not imply routing quality. The evaluator and all routing commands were intentionally not run; the coordinator owns the first frozen-set routing measurement.
