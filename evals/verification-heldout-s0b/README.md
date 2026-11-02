# verification-heldout-s0b — real-data held-out cases (Phase 10, second set)

This bundle contains **45 held-out verification cases built entirely from real,
publicly accessible data and the metadata those products actually ship**, in
the three deliverable forms of the brief: 1/0 validity masks made from a QA
layer (`validity-mask`), slope rasters delivered on another grid than their DEM
or on its own grid (`dataset`), and JSON reports holding three or more numbers
(`summary`). All places are new relative to the repository's earlier held-out
sets, and the set includes areas above 65° N (Sentinel-2 tile 33WXT ~69–70° N
and GLO-30 tile N69 E019 ~69.3° N, both Lyngen, Norway). Nothing here imports
`terraproof`, and no case was tuned against any check or against the `propose`
command.

## Layout

| File | Purpose |
| --- | --- |
| `fetch.py` | Fixed-URL downloader. Writes every fetched source into a cache directory given on the command line, extracts small COG windows (a few hundred pixels per side at most) and records the SHA-256 of every fetched file in `manifest.json`. |
| `derive.py` | Deterministic builder: creates each case's delivered artifact(s) under `<out-dir>/outputs/<case-id>/` and prints a JSON map of the numbers each builder produced. For wrong cases the mistake lives only in the delivered output; the facts describe the deliverable as claimed. |
| `oracle.py` | Independent recomputation of the truth for every case from the fetched sources and the case's own `facts` (never imports `terraproof` nor `derive`). Reads the delivered artifacts, checks each case's committed `oracle` number and its `kind`, prints a summary, exits non-zero on any disagreement. |
| `cases.json` | The held-out cases themselves. |

Run order (network needed at least once; afterwards a cache directory
suffices):

```
python fetch.py <cache-dir>
python derive.py <cache-dir> <out-dir>
python oracle.py <cache-dir> <out-dir>
```

Two `derive.py` runs against the same cache are byte-identical (verified by
`tests/python/test_verification_heldout_s0b.py`).

## Sources and licences

Full statements live in [`../../sources/SOURCES.md`](../../sources/SOURCES.md).

- **Sentinel-2 L2A**, scene `S2C_33WXT_20250915_0_L2A` (Earth Search
  `sentinel-2-l2a`, COGs on the public `sentinel-cogs` bucket; MGRS tile
  33WXT, Tromso area, lat ~69–70° N) with the SCL classification layer.
  ESA Copernicus Sentinel data; attribution: *"Contains modified Copernicus
  Sentinel data 2025"*.
- **Copernicus DEM GLO-30**, tiles N69 E019 (Lyngen, Norway) and
  N46 E007 (Matterhorn/Zermatt region), public AWS Open Data bucket. © DLR,
  free use with attribution (*"Contains Copernicus DEM data"*).
- **USGS 3DEP 1/3 arc-second**, tile `n33w118` (Los Angeles coast) plus its
  FGDC sidecar; public domain (the sidecar says so).
- **Natural Earth 110m admin-0 countries**, GeoJSON pinned at tag v5.1.2;
  public domain.

No account, API key, requester-pays bucket or expiring signed URL is used.
The `sentinel-2-l2a` item for the Tromso scene states
`earthsearch:boa_offset_applied = true`, so the stored S2 COG values already
include the −0.1 BOA offset and the scale-only decode (`value * 0.0001`) is
the honest one; one wrong report decodes a band with the declared offset
applied again and falls short by ≈0.1 reflectance.

## How reprojected slopes are judged, and the margin found

Every slope case states its full chain in `facts`: source DEM, vertical unit,
slope unit, method, computation order (`slope_then_warp` /
`warp_then_slope`), resampling, target CRS, target resolution and the
spacing interpretation (plain ground metres, or Web-Mercator grid metres
reduced by cos(latitude) to ground metres where that projection is the
target). `oracle.py` recomputes exactly that chain from the cache and
compares delivered means within a tolerance set by float32 storage
round-off (≤ ~3e-5 relative, observed).

A careful practitioner's choice of resampling method moves the mean of the
same chain only slightly: on these windows the measured method spread (max
minus min over bilinear/cubic/average/nearest, as a share of the mean) is
**0.10%** (Norway percent chain) and **0.63%** (Matterhorn degrees chain).
The wrong cases deviate by factors 0.30–93,000 — orders of magnitude outside
any legitimate method choice; a label swap (degrees delivered as percent or
percent as degrees) deviates by ~2x or more at these latitudes and slopes.
The oracle therefore does not need to know which resampling a practitioner
chose: recomputing the declared one pins the delivered artifact to rounding,
and every trap in this family misses by many times the spread a legitimate
method choice produces. Projections used as targets: UTM 32N/33N
(scale ≈ 1.0), NSIDC polar stereographic EPSG:3413 (scale ≈ 1.0008 at 69.3° N
— ground metres within the method margin), and Web Mercator EPSG:3857
(scale = 1/cos(latitude) ≈ 2.83 at 69.3° N — far from one; the correct case
reduces its grid metres by cos(latitude) to measure ground distance, the
wrong case ships grid metres as ground metres).

Public credential-free DEM products (GLO-30, 3DEP) ship only on geographic
grids, so "a projected DEM" in this bundle means a slope delivered on a
projected target grid through the chain the facts declare.

## Window definitions

| Cache path | Source | Window (col, row, w, h) |
| --- | --- | --- |
| `s2/wa_SCL.tif` | SCL (20 m) | 5184, 1872, 256, 256 — window A: fjord, land, clouds 8/9, snow, shadow |
| `s2/wa_B02/B03/B08.tif` | 10 m bands | 10368, 3744, 512, 512 (aligned to A) |
| `s2/wb_SCL.tif` | SCL (20 m) | 0, 0, 512, 512 — swath-edge wedge, class 0 everywhere |
| `s2/wb_B03.tif` | 10 m B03 | 0, 0, 1024, 1024 (all declared fill) |
| `s2/wc_SCL.tif` | SCL (20 m) | 4224, 192, 512, 512 — swath edge: wedge fill, land, water mixed |
| `copdem/norway_win.tif` | GLO-30 N69 E019 | 1200, 2400, 400, 400 (lat ~69.28; X spacing 2x the Y spacing) |
| `copdem/matterhorn_win.tif` | GLO-30 N46 E007 | 2400, 3100, 400, 400 (lat ~46.08, elev up to ~4430 m) |
| `usgs3dep/USGS_13_n33w118_win.tif` | 1/3 arc-second | 8650, 4830, 604, 604 (LA coast: ~60% declared fill and ~142k genuine 0 m cells) |

## Case schema

Each `cases.json` entry has: `id`, `family`, `kind` (`wrong` / `correct`),
`deliverable_form` (`dataset` / `validity-mask` / `summary`), a one-paragraph
practitioner `scenario`, a plain-word `goal`, `sources` (paths and roles,
including STAC items and sidecars), `facts`, `facts_in_metadata`, `output`
and `oracle`.

**Facts state the intended computation and never the mistake.** In every
wrong case the `facts` are exactly the facts the correct deliverable of the
same chain would carry; the mistake lives only in the output and in
`oracle.reason`.

### `facts` — key vocabulary

- `pixel_qa_layer` — the QA layer (cache path plus 20 m resolution).
- `pixel_qa_classes_usable` / `pixel_qa_invalid_classes` /
  `pixel_qa_class_meanings` — the documented rule (usable classes, rejected
  classes, meanings).
- `mask_usable_value` — the value that means usable in the delivered 1/0
  mask (1).
- `source_dem` — the DEM a slope came from (path, product).
- `elevation_unit`, `elevation_vertical_datum` — vertical unit and datum
  (metres; NAVD 88 for 3DEP as its sidecar states; the Copernicus DEM states
  neither, recorded as missing).
- `horizontal_crs`, `pixel_spacing_deg_east_west`,
  `pixel_spacing_deg_north_south`, `source_window_mid_latitude_deg` — the
  source grid and its middle latitude.
- `slope_unit`, `slope_method` — what the delivered slope values mean and how
  they were computed (metre steps from the geotransform, east-west reduced by
  cos(latitude)).
- `computation_order`, `resampling`, `target_crs`, `target_resolution_m`,
  `spacing_interpretation` — the reprojected chain (order, method, target
  grid and how its spacing is to be read; Web-Mercator targets declare
  `cos_reduced_ground_metres`).
- `report_numbers` — for every number of a summary report: its exact key path
  (list positions written explicitly, e.g. `per_class.0.pixel_count`,
  `bands.nir_B08.mean_reflectance`), its statistic or decode
  (`mean`, `maximum`, `minimum`, `count`, `share`, `ndvi_mean`,
  `feature_count`, `area_geodesic`, `length_geodesic`; decode = the scale and
  offset applied), the file it summarises (including a raster's exact
  selection rule: not-value / not-zero / equal / class-in / all / joint
  `all_not_zero` across bands; the QA layer used, with classes), any
  denominator (`all` or `valid` with its own mask), and its unit.
- `fill_value`, `reflectance_scale`,
  `reflectance_offset_applied_in_stored_values` — where masking or decoding
  matters.
- `boundary_source`, `deliverable_crs` — the vector dataset and the CRS it
  states.

`facts_in_metadata` records, per key, `false` or `{"stated": true, "where":
...}` naming the exact file and field.

### `oracle`

Wrong cases: an independent `reason` (no Terraproof terms), a `value_metric`
and one `value` (6-decimal rounded). Correct cases: `evidence`,
`value_metric` and `value` of the honest recomputation. `oracle.py`
recomputes each and agrees with every case's `kind`.

## Honest derivatives

Derived outputs carry exactly the labels the scenario's practitioner would
have shipped, including the mislabelled grids the traps consist of (slope
rasters holding one unit under another unit's label, metres relabelled as
feet — the case facts record the truth the source metadata states, and the
delivered summary's `labelled_unit` field records the claim as delivered).

## Counts

`qa_validity_masks` 5 wrong + 5 correct; `reprojected_slopes` 6 + 6
(slope_then_warp 4, warp_then_slope 8; bilinear 5, cubic 2, average 3,
nearest 2), `multi_value_reports` 6 + 7; `same_grid_geographic_slopes`
3 + 3 (a Web-Mercator-style spacing confusion at 69.3° N included);
`plain` 4 correct — 45 cases. By `deliverable_form`: dataset 19, summary 16,
validity-mask 10. Every report holds at least three numbers; list reports
include `per_class` entries; several reports nest objects (`extremes`,
`bands`, `by_qa`, `new_zealand`).

## Test

`tests/python/test_verification_heldout_s0b.py` runs fetch, derive and
oracle when a cache or the network is available and skips otherwise; on CI
(`CI` set) it skips without a cache unless `TERRAPROOF_HELDOUT_S0B_FETCH=1`;
it verifies byte-identical derive runs and that no bundle source imports
`terraproof.checks`, `terraproof.evidence` or `terraproof.evals`.

## Determinism

- All fetch URLs are fixed and pinned (Natural Earth at tag v5.1.2).
- Every builder reads only cache content plus constants; JSON output uses
  `sort_keys=True` and floats rounded to 6 decimals.
- Raster outputs are tiled GeoTIFFs (512x512 blocks, deflate, predictor 2)
  with two overview levels; no timestamps are embedded.
- The oracle re-derives the chains and report numbers from the same cache
  under the facts' own definitions; it imports neither `terraproof` nor
  `derive`.
