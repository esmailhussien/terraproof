# Skill manifests

Each skill describes its own routing metadata in `skills/<name>/skill.json`. The router reads `routing/registry.json`, which `npm run registry:build` generates from these files. Do not edit `routing/registry.json` by hand.

`SKILL.md` frontmatter is not changed. Agent Skills tools reject unknown frontmatter fields, so metadata lives in this sidecar file.

## Schema

All fields are required. Arrays may be empty. Unknown fields are an error.

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Must equal the directory name. |
| `layer` | string | One of `process`, `domain`, `implementation`, `risk`, `verification`. |
| `domains` | string[] | Domain tags used for scoring. |
| `capabilities` | string[] | Capability tags used for scoring. |
| `triggers` | string[] | Phrases matched in the task prompt. |
| `recommended` | string[] | Skills added with this one. Each needs a documented rationale in the routing docs (AGENTS.md rule 15). |
| `requires` | string[] | Skills always added with this one. Same rationale rule. |
| `conflicts` | string[] | Skills that compete with this one; the router keeps one. |
| `explanation` | string | One sentence shown in routed output for this skill. Must be non-empty. |
| `sections` | object[] | Retrievable parts of the skill; see below. |
| `checks` | string[] | Check ids from `routing/checks.json` whose evidence this skill's guidance bears on. Empty is fine. |

`path` is not stored. It is derived as `skills/<name>`.

`recommended`, `requires`, and `conflicts` must name skills that have a `skill.json`.

## Sections

Each section is `{ "id", "title", "source" }`. There is one section per `##` heading in `SKILL.md`, and one per Markdown file directly under `references/`.

- Heading: `id` is the GitHub-style anchor of the heading (lowercase, punctuation removed, spaces become hyphens). Repeated headings get `-1`, `-2`. `source` is `SKILL.md#<id>`. Headings inside fenced code blocks are not sections.
- Reference: `id` is the file stem, and `source` is `references/<file>.md`. If a `SKILL.md` heading already uses that stem as its id, the reference id is `<stem>-reference`. This applies to `geospatial-frontend` (`design-system`).

Excerpt from `skills/gdal/skill.json` (the `sections` list is abridged here; the file lists all five):

```json
{
  "name": "gdal",
  "layer": "domain",
  "domains": ["geospatial"],
  "capabilities": ["raster-processing", "reprojection", "cog-conversion", "ogr2ogr", "raster-clipping"],
  "triggers": ["gdal", "ogr", "geotiff", "cog", "cloud-optimized geotiff", "reproject", "gdalwarp", "gdal_translate", "raster clip", "raster mosaic"],
  "recommended": ["verification"],
  "requires": [],
  "conflicts": [],
  "explanation": "Executes GDAL/OGR CLI operations for raster reprojection, clipping, and COG conversion.",
  "sections": [
    { "id": "quick-reference", "title": "Quick Reference", "source": "SKILL.md#quick-reference" },
    { "id": "gdal-recipes", "title": "GDAL Recipes", "source": "references/gdal-recipes.md" }
  ],
  "checks": ["crs.defined", "crs.consistent", "raster.nodata_declared", "raster.resampling", "raster.cog_layout"]
}
```

## Check catalog

`routing/checks.json` lists every check id with its `family` and a one-line `description`. The ids are the ones the Python package emits from `src/terraproof/checks/`. `tests/python/test_check_catalog.py` fails if the catalog and the source disagree.

## Generation and validation

`npm run registry:build` reads every `skills/*/skill.json`, validates it, and writes `routing/registry.json` (skills sorted by name, 2-space JSON, trailing newline). `$schema` and `version` are kept from the existing file.

`npm run registry:check` exits 1 if the committed `routing/registry.json` differs from what the manifests generate, and prints a summary of the differences. The router test suite runs the same check as step 9.

The generator rejects a manifest that:

- has a missing or unknown field, or a field of the wrong type;
- has a `name` that differs from its directory name, or a `layer` outside the list above;
- has an empty `explanation`;
- has a section whose `source` is neither `SKILL.md#<anchor>` nor `references/<file>.md`;
- has a `SKILL.md#<anchor>` source whose anchor is not a `##` heading in `SKILL.md`, or whose `id` differs from the anchor;
- has a reference source that does not exist on disk, or whose `id` is not the file stem (or `<stem>-reference`, see above);
- has a duplicate section id;
- lists a check id that is not in `routing/checks.json`;
- names a `recommended`, `requires`, or `conflicts` skill that has no `skill.json`.

A skill directory without `skill.json` is skipped with a warning and is not routed. This lets a skill be drafted before it is registered.

## Adding a skill

1. Write `skills/<name>/SKILL.md` and its references.
2. Add `skills/<name>/skill.json` with the fields above.
3. Add test scenarios in `tests/router/scenarios.json` for each new trigger (AGENTS.md rule 11).
4. Run `npm run registry:build`, then `npm run test:router`.