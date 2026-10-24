# Upstream Attribution

This skill is derived from the `geomaster` skill in `K-Dense-AI/scientific-agent-skills`.

- **Upstream repository:** https://github.com/K-Dense-AI/scientific-agent-skills
- **Upstream path:** `skills/geomaster/`
- **License:** MIT (see [third_party/kdense-scientific-agent-skills/LICENSE](../../third_party/kdense-scientific-agent-skills/LICENSE))
- **Imported commit:** `390f5146bf3c1877cf15636a3dd7b775e4f0f185`
- **Import date:** 2026-08-25
- **Local path:** `skills/geomaster/`

## Imported Files

- `SKILL.md`

## Local modifications

Initial import:
- Local behavioral modifications: none (faithful vendoring, byte-for-byte identical to upstream).

2026-10-24, terrain slope correctness fix (Terraproof):
- `SKILL.md`, section "Terrain Analysis": `terrain_metrics()` is rewritten. The upstream version called
  `np.gradient(dem)` with no spacing, so it assumed 1-unit square pixels and equal vertical and horizontal
  units, and its hillshade swapped the sine and cosine of the slope. The local version uses the signed pixel
  size from the transform, converts the band's vertical unit to metres (or a given `z_factor`), refuses
  geographic, non-metre, rotated or sheared grids, masks nodata as NaN, leaves flat cells without aspect, and
  uses the standard hillshade formula. A short checklist follows the code.
- `references/code-examples.md`, example 68: the same `np.gradient(dem)` example is replaced by a pointer to
  `terrain_metrics()` and the reason.
- Found by an independent review (Codex, 2026-10-24) while authoring the `terrain-slope-map` eval task.
  Covered by `tests/python/test_skill_snippets.py`, which runs the snippet on synthetic DEMs.
- All other content is unchanged from upstream.

Any future modifications must be documented here.
