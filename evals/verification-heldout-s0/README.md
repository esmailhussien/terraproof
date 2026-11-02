# verification-heldout-s0 — real-data held-out cases (Phase 10)

This bundle contains **42 held-out verification cases built entirely from real,
publicly accessible data and the metadata those products actually ship**, in
the three deliverable forms of the brief: 1/0 validity masks made from a QA
layer (`validity-mask`), slope rasters delivered on another grid than their
DEM or on its own geographic grid (`dataset`), and JSON reports holding three
or more numbers (`summary`). They measure the checks cold — correct cases are
correct for a good reason, wrong cases state an independent reason and one
number. Nothing here imports `terraproof`, and no case was tuned against any
check or against the `propose` command.

## Layout

| File | Purpose |
| --- | --- |
| `fetch.py` | Fixed-URL downloader. Writes every fetched source into a cache directory given on the command line, extracts small COG windows (a few hundred pixels per side at most) and records the SHA-256 of every fetched file in `manifest.json`. |
| `derive.py` | Deterministic builder: creates each case's delivered artifact(s) under `<out-dir>/outputs/<case-id>/` and prints a JSON map of the numbers each builder produced. |
| `oracle.py` | Independent recomputation of the truth for every case from the fetched sources plus the `facts` in `cases.json` (never imports `terraproof` nor `derive`). Reads the delivered artifacts, checks each case's committed `oracle` number and its `kind`, prints a summary, exits non-zero on any disagreement. |
| `cases.json` | The held-out cases themselves. |

Run order (network needed at least once; afterwards a cache directory
suffices):

```
python fetch.py <cache-dir>
python derive.py <cache-dir> <out-dir>
python oracle.py <cache-dir> <out-dir>
```

Two `derive.py` runs against the same cache are byte-identical (verified by
`tests/python/test_verification_heldout_s0.py`).

## Sources and licences

Full statements live in [`../../sources/SOURCES.md`](../../sources/SOURCES.md).

- **Sentinel-2 L2A**, scene `S2B_32TMS_20250831_0_L2A` (Earth Search
  `sentinel-2-l2a`, COGs on the public `sentinel-cogs` bucket), with the SCL
  classification layer. ESA Copernicus Sentinel data; attribution:
  *"Contains modified Copernicus Sentinel data 2025"*.
- **Copernicus DEM GLO-30**, tiles N28 E084 (Nepal), N46 E008 (Bernese
  Oberland) and N78 E016 (Svalbard), public AWS Open Data bucket. © DLR, free
  use with attribution (*"Contains Copernicus DEM data"*).
- **USGS 3DEP 1/3 arc-second**, tiles `n31w091` (Mississippi delta) and
  `n22w159` (Kauai) plus their FGDC sidecars; public domain (the sidecar says
  so).
- **Natural Earth 110m admin-0 countries**, GeoJSON pinned at tag v5.1.2;
  public domain.

No account, API key, requester-pays bucket or expiring signed URL is used.
Landsat Collection 2 Level-2 `QA_PIXEL` could **not** be fetched this way
(its COGs live in the requester-pays `usgs-landsat` bucket; 403 without
credentials), so no Landsat source is included, as the brief allows; the
masks family uses Sentinel-2 SCL throughout.

## How reprojected slopes are judged, and the margin found

Every slope case states its full chain in `facts`: source DEM, vertical unit,
slope unit, method ("central-difference gradient of neighbouring pixels"),
computation order (`slope_then_warp` or `warp_then_slope`), resampling,
target CRS and target resolution. `oracle.py` recomputes exactly that chain
from the cache and compares delivered means within rounding tolerance
(2e-6 relative).

A careful practitioner's choice of resampling method moves the mean of the
same chain only slightly: on these windows the measured method spread (max
minus min over bilinear/cubic/average/nearest, as a share of the mean) is
**0.12%** (Nepal percent chain) and **1.03%** (Svalbard degrees chain) — so
any of those delivered values passes a verifier that recomputes the declared
method and also survives a swap of methods. The wrong cases in this bundle
deviate by factors **0.198–105,058** — orders of magnitude outside the method
margin. The oracle therefore does not need to know which resampling a
practitioner chose: recomputing the declared one pins the delivered artifact
to rounding, and every trap in this family misses by many times the spread of
a legitimate method choice.

## Window definitions

| Cache path | Source | Window (col, row, w, h) |
| --- | --- | --- |
| `s2/wa_SCL.tif` | SCL (20 m) | 4200, 0, 512, 512 — window A, all QA classes |
| `s2/wa_B02/B03/B08.tif` | 10 m bands | 8400, 0, 1024, 1024 |
| `s2/wb_SCL.tif` | SCL (20 m) | 4830, 4426, 512, 512 — swath-edge wedge, class 0 everywhere |
| `s2/wc_SCL.tif` | SCL (20 m) | 4352, 4096, 512, 512 — swath edge: wedge fill, land, water and cloud mixed |
| `copdem/nepal_win.tif` | GLO-30 N28 E084 | 1000, 1000, 400, 400 (lat ~28.67) |
| `copdem/alps_win.tif` | GLO-30 N46 E008 | 300, 1300, 400, 400 (lat ~46.64) |
| `copdem/svalbard_win.tif` | GLO-30 N78 E016 | 300, 1400, 400, 400 (lat ~78.56; X spacing 3x the Y spacing) |
| `usgs3dep/USGS_13_n31w091_win.tif` | 1/3 arc-second | 6000, 7000, 604, 604 (real zeros on the coast) |
| `usgs3dep/USGS_13_n22w159_win.tif` | 1/3 arc-second | 9060, 6860, 512, 512 (declared fill + real zeros) |

## Case schema

Each `cases.json` entry has: `id`, `family`, `kind`, `deliverable_form`
(`dataset` / `validity-mask` / `summary`), one-paragraph practitioner
`scenario`, plain-word `goal`, `sources` (paths and roles), `facts`,
`facts_in_metadata`, `output` and `oracle`. `facts` are complete: a reader
can re-derive the deliverable from them alone.

### `facts` — key vocabulary

- `pixel_qa_layer_title`, `pixel_qa_valid_classes`, `pixel_qa_invalid_classes`,
  `pixel_qa_class_meanings` — the QA layer, its class codes and their
  documented meanings.
- `pixel_qa_window` — where the delivered mask came from (cache path,
  resolution and role).
- `mask_usable_value` — the value that means usable in the delivered mask
  (always 1 here).
- `source_dem` — the DEM the slope came from (path, product).
- `elevation_unit`, `elevation_vertical_datum` — vertical unit and datum
  (metres, NAVD 88 for 3DEP as its sidecar states; the Copernicus DEM states
  neither, recorded as missing).
- `horizontal_crs`, `pixel_spacing_deg_east_west`, `pixel_spacing_deg_north_south`
  — the source grid, exactly as its geotransform states.
- `slope_unit` — what the delivered slope values mean (`percent` / `degrees`).
- `slope_method` — the differencing used.
- `computation_order` — `slope_then_warp` or `warp_then_slope`.
- `resampling`, `target_crs`, `target_resolution_m` — the warp step of a
  reprojected chain.
- `report_numbers` — for every number in a summary report: its key path (list
  positions written as `per_class[*].share_of_valid`), its statistic, the data
  it summarises, the mask/selection applied, and its unit.
- `fill_value`, `reflectance_scale`, `reflectance_offset_applied_in_stored_values`
  — where decoding or masking matters.
- `boundary_source`, `deliverable_crs` — the vector dataset and the CRS it
  states.

`facts_in_metadata` records, per key, `false` or `{"stated": true, "where":
...}` naming the exact file and field. The `earthsearch:boa_offset_applied`
item property is the statement that the Sentinel-2 COG values already include
the BOA offset; the scale-only decode is therefore the honest one (the
declared offset must not be applied again).

### `oracle`

Wrong cases: an independent `reason`, a `value_metric` and one `value` (6-decimal
rounded). Correct cases: `evidence`, `value_metric` and `value` of the honest
recomputation. `oracle.py` recomputes each and agrees with every `kind`.

## Honest derivatives

Derived outputs carry exactly the labels the scenario's practitioner would
have shipped, including the mislabelled ones the traps consist of (a slope
grid holding degrees values under a `percent` label, or metres relabelled as
feet — the case facts record the truth the source metadata states).

## Counts

`qa_validity_masks` 5 wrong + 5 correct; `reprojected_slopes` 6 + 6
(slope_then_warp 6, warp_then_slope 6; bilinear 5, cubic 2, average 3,
nearest 2); `multi_value_reports` 5 + 5; `same_grid_geographic_slopes`
3 + 3 (latitudes ~28.7, ~46.6, ~78.6); `plain` 4 correct — 42 cases.
By `deliverable_form`: dataset 19, summary 13, validity-mask 10. Every
report holds at least three numbers; `report_c_scl_class_list_wc` and
`report_w_one_share_over_all_cells_scl_wc` are list reports, and several
reports nest objects (e.g. `extremes`, `bands`, `iceland`).

## Test

`tests/python/test_verification_heldout_s0.py` runs fetch, derive and oracle
when a cache or the network is available and skips otherwise; on CI (`CI`
set) it skips without a cache unless `TERRAPROOF_HELDOUT_S0_FETCH=1`; it
verifies byte-identical derive runs and that no bundle source imports
`terraproof.checks`, `terraproof.evidence` or `terraproof.evals`.

## Determinism

- All fetch URLs are fixed and pinned (Natural Earth at tag v5.1.2).
- Every builder reads only cache content plus constants; JSON output uses
  `sort_keys=True` and floats rounded to 6 decimals.
- Raster outputs are tiled GeoTIFFs (512x512 blocks, deflate, predictor 2)
  with two overview levels; no timestamps are embedded.
- The oracle re-derives the declared chains and report numbers from the same
  cache; it imports neither `terraproof` nor `derive`.
