# Skill-router evaluation sets

This directory holds prompt-to-skill evaluation data for the Terraproof skill
router. [`heldout.jsonl`](heldout.jsonl) is an **independent, held-out** set: it
measures the router, it does not tune it.

## Held-out policy

- `heldout.jsonl` must never be used to choose triggers, weights, thresholds,
  registry metadata or any other router parameter. Use a separate development
  set (for example `dev.jsonl`) for tuning and regression work.
- Do not look at per-item held-out results while iterating on the router; run it
  for a final score, then report the number.
- Any change to `heldout.jsonl` (adding, removing or re-labelling items) must be
  reviewed separately from router changes, in its own change, by someone other
  than the router author. Never edit a label to match router output.
- Do not copy held-out prompts into router tests, skill texts, or the dev set.

## Schema

One JSON object per line (UTF-8, no comments):

```json
{"id": "ho-en-001", "prompt": "...", "lang": "en", "datasets": [{"kind": "vector", "crs": {"is_geographic": true, "is_projected": false, "horizontal_kind": "geographic", "epsg": 4326}, "geometry_types": ["Polygon"], "feature_count": 12840}], "expected": ["crs-and-units"], "must_not": ["satellite-preprocessing"]}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable unique id: `ho-<lang>-<nnn>`. |
| `prompt` | yes | A realistic user request, written fresh for this set. |
| `lang` | yes | `en` or `ar`. |
| `datasets` | no | Dataset profiles available to the router alongside the prompt. |
| `expected` | yes | Minimal set of skills a geospatial expert would call clearly required (1–3). |
| `must_not` | no | Plausible but wrong skills; ranking one in the top 5 is a violation. |

`datasets` entries are a subset of the output of the
[Terraproof inspectors](../../src/terraproof/inspect/) and contain only the
keys relevant to their kind:

- `vector`: `crs`, `geometry_types`, `feature_count`
- `raster`: `crs`, `band_count`, `bands` (each `dtype`, `scale`, `offset`, `nodata`)
- `stac`: `collection`, `crs`, `bands` (each `scale`, `offset`)

`crs` is `null` when the source has no CRS, otherwise
`{"is_geographic", "is_projected", "horizontal_kind", "epsg"}`.

`expected` and `must_not` use only these 16 non-process skill names from
[the registry](../../routing/registry.json): `crs-and-units`,
`vector-quality`, `raster-processing`, `satellite-preprocessing`,
`spectral-indices`, `gdal`, `geopandas`, `geomaster`, `design-postgis-tables`,
`geoparquet-validation`, `geozarr`, `geospatial-frontend`,
`geospatial-data-discovery`, `scientific-visualization`,
`statistical-analysis`, `networkx`. Process and verification skills
(`brainstorming`, `writing-plans`, `systematic-debugging`, `verification`) are
never labelled. A skill never appears in both lists of one item.

## Metric

For each item, take the router's ranked skill list for `prompt` (plus
`datasets` when present), drop the four process/verification skills above
(they are never labelled, so they would only consume slots), and keep the first
five as `top5`.

- **recall@5** per item = `|expected ∩ top5| / |expected|`.
- **Mean recall@5** = the average of per-item recall@5 over all 80 items.
- **Violation**: any `must_not` skill in `top5`. Report the number of items with
  at least one violation (and the rate over the items that have `must_not`).

Report mean recall@5 overall and split by `lang`, and by items with and
without `datasets`, together with the violation count. Precision is not scored:
`expected` is deliberately minimal, so additional reasonable skills in the top
five are not penalised unless they are listed in `must_not`.

## Contents

- 80 items: 40 English, 40 Arabic. The Arabic prompts mix Modern Standard
  Arabic and Egyptian dialect and often embed English technical tokens
  (`GeoTIFF`, `EPSG:4326`, `Sentinel-2`, `STAC`, `ST_Intersects`) as real users
  write them.
- Each of the 16 skills appears in `expected` at least four times, across both
  languages.
- 24 items carry `datasets` where the prompt alone is ambiguous and the profile
  decides the answer: a geographic or Web Mercator CRS under an area or buffer
  request, a missing CRS, two misaligned rasters, a categorical `uint8` raster
  under a resampling request, scaled `uint16` reflectance or a
  `sentinel-2-l2a`/`landsat-c2-l2` STAC item under an index or comparison
  request, mixed geometry types before GeoJSON export, and undeclared nodata.
  Some pairs differ mainly in the profile (for example a buffer task with a
  projected CRS expects only `geopandas`, while one with EPSG:4326 also expects
  `crs-and-units`).
- 56 items carry `must_not`, including 8 hard or off-topic items (non-geospatial
  charts, statistics and social networks; a conceptual COG question; a data
  source question that names a file format) whose single expected skill sits
  next to tempting distractors.

## How it was built

The set was written by hand by a worker independent of the router author. The
author of this set read only the skill registry, the skill frontmatter
descriptions and the inspector source to learn the skill boundaries and the
profile fields. It did not read the router implementation, its development set,
or the router test scenarios, and no prompt was taken from those or from skill
texts. Labels reflect what a geospatial expert would consider clearly required,
not what any router currently returns; the set has not been run against a router
by its author.

Structural checks (item and language counts, unique ids, allowed skill names,
no process skills, per-skill coverage, `datasets` and `must_not` counts, and no
overlap between `expected` and `must_not`) are run with the bundled Python
before any change to the file is merged.

## heldout_v2

[`heldout_v2.jsonl`](heldout_v2.jsonl) is a second, fresh held-out set. It
exists because `heldout.jsonl` has been used for per-category feedback and so
no longer gives an unbiased estimate. v2 gives a new, independent one.

- Same schema and metric as above (ids are `h2-<lang>-<nnn>`; means are over its
  100 items).
- 100 items: 50 English, 50 Arabic (MSA and Egyptian dialect, with embedded
  English technical tokens and informal spelling). Each of the 16 skills appears
  in `expected` at least five times; `expected` has 1 skill in 92 items and 2
  in 8.
- 29 items carry `datasets` that decide the answer: geographic, Web Mercator or
  missing CRS under area, distance and buffer tasks (with projected-CRS
  counterparts that expect only `geopandas`), categorical `uint8` rasters,
  rasters on different grids, scaled or undeclared-scale `uint16` reflectance,
  undeclared nodata, mixed geometry types before GeoJSON export, and
  `sentinel-2-l2a`/`landsat-c2-l2` STAC items that are already held versus a
  request to search for more.
- 98 items carry `must_not`. About 20 are deliberately hard: indirect symptoms
  with no skill keywords, near-misses between neighbouring skills, and
  off-domain distractor words (for example `h2-en-003`, `h2-en-024`,
  `h2-en-027`, `h2-en-028`, `h2-en-037`, `h2-en-042`, `h2-ar-003`, `h2-ar-010`,
  `h2-ar-044`, `h2-ar-050`).
- It was written by a worker who read only the registry, the skill frontmatter
  descriptions, the inspector source and this README. That worker did not read
  the router code, `dev.jsonl`, `heldout.jsonl` or the router test scenarios.

**Policy:** `heldout_v2.jsonl` is never used for tuning, debugging or feedback of
any kind (not even per-category or per-item results) until a release decision.
Run it once, for the release decision, and report only the aggregate numbers
defined under Metric. The held-out policy above applies to it in full.
