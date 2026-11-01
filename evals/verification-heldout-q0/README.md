# verification-heldout-q0 — real-data held-out cases (Phase 9)

This bundle contains **36 held-out verification cases built entirely from real,
publicly accessible data and the metadata those products actually ship**. The
cases arrive in the forms people actually deliver: data rasters
(`deliverable_form: dataset`), 1/0 validity masks (`validity-mask`) and small
summary reports (`summary`). They measure the checks cold — correct cases are
correct for a good reason and wrong cases state an independent reason and one
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
`tests/python/test_verification_heldout_q0.py`).

## Sources and licences

Full statements live in [`../../sources/SOURCES.md`](../../sources/SOURCES.md).
Summary:

- **Sentinel-2 L2A, two Earth Search distributions**
  - distribution `sentinel-2-l2a` (v0): scene `S2B_32TMS_20250831_0_L2A`
    (MGRS tile 32TMS, 2025-08-31, Bernese Oberland), COG assets on
    `sentinel-cogs`; ESA Copernicus Sentinel data, attribution:
    *"Contains modified Copernicus Sentinel data 2025"*.
  - distribution `sentinel-2-c1-l2a` (Collection 1): scene
    `S2B_T32TMS_20230928T102123_L2A` (same MGRS tile, 2023-09-28), COG assets
    on element84's `e84-earth-search-sentinel-data` bucket, with `tileInfo.json`
    and `product_metadata.xml` sidecars; same ESA licence and attribution.
- **Copernicus DEM GLO-30** (tiles N28 E084 and N78 E016, public AWS Open Data
  bucket) — © DLR, free use with attribution.
- **USGS 3DEP 1/3 arc-second** tiles `n31w091` and `n22w159` plus their FGDC
  metadata sidecars (public `prd-tnm` bucket); the sidecar states: *"All 3DEP
  products are public domain."*
- **Natural Earth 110m admin-0 countries** (GeoJSON, pinned at tag v5.1.2 of
  `nvkelso/natural-earth-vector`) — public domain.

No account, API key, requester-pays bucket or expiring signed URL is used.

## How each distribution's offset status was established

- **`sentinel-2-l2a` (v0):** the STAC item states
  `properties.earthsearch:boa_offset_applied = true`, and the pixel data
  confirms it: over open water the stored green values sit near DN 244, which
  decodes to a physical ~0.024 reflectance with the scale-only rule
  (`value * 0.0001`); applying the declared −0.1 offset again would make open
  water negative (≈ −0.076), which is unphysical.
- **`sentinel-2-c1-l2a` (c1):** the STAC item declares the same
  `raster:bands` scale 0.0001 and offset −0.1 but carries **no**
  `earthsearch:boa_offset_applied` property — an absence, not a statement.
  The status is therefore established from the data: over the same alpine
  window the stored green values sit near DN 1272 over open water, which only
  decodes to a physical ≈ 0.027 after subtracting the declared offset
  (`(DN − 1000) * 0.0001`); the scale-only read would claim an unphysical 0.127
  over water. This is recorded per case in the `facts` key
  `reflectance_offset_status_evidence`.

## Window definitions

| Cache path | Source | Window (col, row, w, h) |
| --- | --- | --- |
| `s2-v0/wa_SCL.tif` | v0 `SCL.tif` (20 m) | 4200, 0, 512, 512 |
| `s2-v0/wa_B02/B03/B08.tif` | v0 10 m band COGs | 8400, 0, 1024, 1024 |
| `s2-v0/wa_B11.tif` | v0 20 m SWIR16 COG | 4200, 0, 512, 512 |
| `s2-v0/wb_SCL.tif` | v0 `SCL.tif` | 4830, 4426, 512, 512 (swath-edge fill wedge) |
| `s2-v0/wb_B03.tif` | v0 10 m B03 | 9660, 8852, 1024, 1024 |
| `s2-c1/wa_SCL.tif` / `s2-c1/wa_B11.tif` | c1 20 m COGs | 4200, 0, 512, 512 |
| `s2-c1/wa_B02/B03/B08.tif` | c1 10 m band COGs | 8400, 0, 1024, 1024 |
| `copdem/n28e084_win.tif` | GLO-30 Nepal tile | 1000, 1000, 400, 400 |
| `copdem/n78e016_win.tif` | GLO-30 Svalbard tile | 300, 1400, 400, 400 |
| `usgs3dep/USGS_13_n31w091_win.tif` | 1/3 arc-second tile | 6000, 7000, 604, 604 |
| `usgs3dep/USGS_13_n22w159_win.tif` | 1/3 arc-second tile | 9060, 6860, 512, 512 |

## Case schema

Each `cases.json` entry has: `id`, `family`, `kind` (`wrong` / `correct`),
`deliverable_form` (`dataset` / `validity-mask` / `summary`), a one-paragraph
practitioner `scenario`, a plain-word `goal`, `sources` (paths and roles,
including STAC items and sidecars), `facts`, `facts_in_metadata`, `output` and
`oracle`.

`sources` paths are prefixed `cache/` and resolve inside the directory handed
to `fetch.py`/`derive.py`/`oracle.py`; roles say what each file is, with real
metadata kept **as found** (never added, fixed or removed). `output` paths
resolve inside the derive output directory (`outputs/<case-id>/...`).

### `facts` — key vocabulary (same key, same meaning everywhere)

- `pixel_qa_layer_title` — title the product gives the classification layer.
- `pixel_qa_valid_classes` / `pixel_qa_invalid_classes` — class codes the
  documented Sentinel-2 L2A scene-classification rule treats as valid /
  rejected for the analysis at hand.
- `pixel_qa_class_meanings` — documented meaning of each class code.
- `pixel_qa_scenario` — which documented variant the analysis uses.
- `classified_window_role` — what the delivered classification window is.
- `mask_usable_value` — the value that means usable in a delivered 1/0 mask.
- `s2_distribution` — which Earth Search distribution a band window comes from.
- `band_common_name` — the band a case refers to.
- `reflectance_scale` / `reflectance_offset_declared` — the band's scale and
  offset exactly as the product states them.
- `reflectance_offset_applied_in_stored_values` — whether the stored values
  already include the BOA offset.
- `reflectance_offset_status_evidence` — how the offset status was established
  (property or pixel evidence; absence of the property is an absence, not a
  statement).
- `fill_value` — the value the product declares as fill/no-data.
- `value_kind` / `measured_quantity` / `measured_property` — what a delivered
  value or map represents.
- `window_role` — what a delivered reflectance window is (e.g. wholly
  declared fill).
- `elevation_unit` / `elevation_vertical_datum` — vertical unit and datum of
  an elevation raster (metres / NAVD 88 for 3DEP as its sidecar states; the
  Copernicus DEM COG states neither — recorded as missing).
- `horizontal_crs` — the CRS of the window.
- `pixel_spacing_deg_east_west` / `pixel_spacing_deg_north_south` — pixel
  sizes exactly as the source geotransform states them.
- `summary_statistic` — the statistic a summary report holds (mean, count,
  sum, max, an area or a length).
- `summary_key` — the JSON key in the delivered summary that holds the
  reported number (as the delivered file itself names it).
- `summary_data` — what data the summary summarises.
- `measured_quantity_units` — the unit a delivered metric must make sense in
  (`km`, `sq_km`).
- `boundary_source` / `deliverable_crs` — the public vector dataset and the
  CRS the source states for it.

`facts_in_metadata` records, per fact key, `false` when the source's real
metadata does not state that exact fact, or `{"stated": true, "where": ...}`
with the file and field where it is stated.

### `oracle`

For **wrong** cases: an independent `reason` (no Terraproof terms), a
`value_metric` naming the single number and `value` (that number, rounded to
6 decimals). For **correct** cases: `evidence` (why the delivered output is
right), plus `value_metric` and `value` of the honest recomputed quantity.
`oracle.py` recomputes each number from the cached sources under the facts'
own definitions and agrees with every case's `kind` (wrong cases must be
demonstrably wrong, correct cases must match within rounding).

## Honest derivatives

All derived *outputs* (masks, decoded reflectances, slope grids, NDVI,
summaries) are generated by `derive.py` and carry exactly the labels the
scenario's character would have shipped. The one mislabelled variant
(`fillunits_wrong_vertical_unit_ignored_kauai/elevation_delivered.tif`) is the
trap itself: the derived raster carries **no unit tag** (label "none"), and
the case records the claimed label in its `facts` (the product metadata states
metres and NAVD 88).

## Counts

`validity_masks` 4 wrong + 4 correct, `slope` 3 + 3, `summary_reports` 3 + 4,
`s2_decodes_two_distributions` 3 + 4 (v0: 1 wrong + 2 correct; c1: 2 wrong +
2 correct), `fill_and_vertical_units` 2 + 2, `plain` 4 correct — 36 cases in
total. By `deliverable_form`: dataset 16, summary 12, validity-mask 8.

## Test

`tests/python/test_verification_heldout_q0.py` runs fetch, derive and oracle
when a cache or the network is available and skips otherwise; on CI (`CI` set)
it skips without a cache unless `TERRAPROOF_HELDOUT_Q0_FETCH=1`; it verifies
that two `derive.py` runs are byte-identical and that neither fetch, derive,
oracle nor the test imports `terraproof.checks`, `terraproof.evidence` or
`terraproof.evals`.

## Determinism

- All fetch URLs are fixed and pinned (Natural Earth at tag v5.1.2).
- Every builder reads only cache content plus constants; JSON output is
  written with `sort_keys=True` and floats rounded to 6 decimals.
- Raster outputs are tiled GeoTIFFs (512 x 512 blocks, deflate, predictor 2)
  with two overview levels; no timestamps are embedded.
- The oracle draws the same numbers from the same cache under the facts' own
  definitions; it imports neither `terraproof` nor `derive`.
