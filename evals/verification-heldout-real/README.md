# verification-heldout-real — real-data held-out cases (Phase 8)

This bundle contains **34 held-out verification cases built entirely from real,
publicly accessible data and the metadata those products actually ship**. The
cases measure whoever runs the checks "cold": correct cases are correct for a
good reason and wrong cases state an independent reason and one number.
Nothing here imports `terraproof`, and no case was tuned against any check.

## Layout

| File | Purpose |
| --- | --- |
| `fetch.py` | Fixed-URL downloader. Writes every fetched source into a cache directory given on the command line, extracts small COG windows (a few hundred pixels per side) and records the SHA-256 of every fetched file in `manifest.json`. |
| `derive.py` | Deterministic builder: creates each case's delivered outputs from the cache under `<out-dir>/outputs/<case-id>/` and prints the numbers each builder produced. Records the trap exactly as a practitioner would have delivered it. |
| `oracle.py` | Independent recomputation of the truth for every case from the fetched sources plus the `facts` in `cases.json`. Reads the delivered artifacts, checks each case's committed `oracle` number and its `kind`, prints a summary and exits non-zero on any disagreement. |
| `cases.json` | The held-out cases themselves (see below). |

Run order (network needed at least once; afterwards a cache directory suffices):

```
python fetch.py <cache-dir>
python derive.py <cache-dir> <out-dir>
python oracle.py <cache-dir> <out-dir>
```

Two `derive.py` runs against the same cache are byte-identical (verified by
`tests/python/test_verification_heldout_real.py`).

## Sources and licences

Full statements live in [`../../sources/SOURCES.md`](../../sources/SOURCES.md).
Summary:

- **Sentinel-2 L2A** (Earth Search `sentinel-2-l2a`, item
  `S2B_32TMS_20250831_0_L2A`, tile 32TMS, 2025-08-31; COG assets served by
  element84's Earth Search). ESA Copernicus Sentinel data — attribution:
  *"Contains modified Copernicus Sentinel data 2025"*.
- **Copernicus DEM GLO-30** (tiles N28 E084 and N78 E016, public S3 bucket on
  AWS Open Data). Copernicus DEM — © DLR, free of use with attribution.
- **USGS 3DEP 1/3 arc-second** tiles `n31w091` and `n22w159` with their FGDC
  metadata sidecars, from the public `prd-tnm` bucket. The sidecar itself
  states: *"All 3DEP products are public domain."*
- **Natural Earth 110m admin-0 countries** (GeoJSON, pinned at tag v5.1.2 of
  `nvkelso/natural-earth-vector`). Natural Earth — public domain.

No account, API key, requester-pays bucket or expiring signed URL is used.

## Window definitions

| Cache path | Source | Window (col, row, w, h) |
| --- | --- | --- |
| `s2/wa_SCL.tif` | tile 32TMS `SCL.tif` (20 m) | 4200, 0, 512, 512 |
| `s2/wa_B02/B03/B08.tif` | 10 m band COGs | 8400, 0, 1024, 1024 |
| `s2/wa_B11.tif` | 20 m SWIR16 COG | 4200, 0, 512, 512 |
| `s2/wb_SCL.tif` / `s2/wb_B11.tif` | 20 m COGs | 4830, 4426, 512, 512 (swath-edge fill wedge) |
| `s2/wb_B03.tif` | 10 m COG | 9660, 8852, 1024, 1024 |
| `copdem/n28e084_win.tif` | GLO-30 Nepal tile | 1000, 1000, 400, 400 |
| `copdem/n78e016_win.tif` | GLO-30 Svalbard tile | 300, 1400, 400, 400 |
| `usgs3dep/USGS_13_n31w091_win.tif` | 1/3 arc-second tile | 6000, 7000, 604, 604 |
| `usgs3dep/USGS_13_n22w159_win.tif` | 1/3 arc-second tile | 9060, 6860, 512, 512 |

## Case schema

Each `cases.json` entry has: `id`, `family`, `kind` (`wrong` / `correct`), a
one-paragraph practitioner `scenario`, a plain-word `goal`, `sources` (paths
and roles), `facts`, `facts_in_metadata`, `output` and `oracle`.

### `sources`

Paths are prefixed `cache/` and resolve inside the cache directory handed to
`fetch.py`/`derive.py`/`oracle.py`. Roles say what each file is, including the
STAC item JSON and tile/granule metadata kept **as found** (never added, fixed
or removed). Output paths resolve inside the `derive.py` output directory
(`outputs/<case-id>/...`).

### `facts` — key vocabulary

The same key always means the same fact:

- `pixel_qa_layer_title` — title the product gives the classification layer.
- `pixel_qa_valid_classes` / `pixel_qa_invalid_classes` — class-code lists of
  the documented Sentinel-2 L2A scene-classification rule that the analysis
  treats as valid / rejected.
- `pixel_qa_class_meanings` — the documented meaning of each class code.
- `pixel_qa_scenario` — which documented variant the analysis uses
  (e.g. snow/ice counts as a valid class).
- `classified_window_role` — what the delivered classification window is
  (here: a swath-edge window that is entirely no data).
- `band_common_name` — the band referenced by a scale/offset case.
- `reflectance_scale` — the band's scale factor as the product states it.
- `reflectance_offset_declared` — the offset the product declares (whether or
  not applying it is right for the stored data is the trap under test).
- `reflectance_offset_applied_in_stored_values` — whether the stored values
  already include the BOA offset (the item states it explicitly).
- `fill_value` — the value the product declares as fill/no-data.
- `value_kind` — what a delivered value represents (surface reflectance).
- `window_role` — what the delivered reflectance window is (here: a swath-edge
  window that is entirely declared fill).
- `measured_quantity` / `measured_property` — the quantity a case measures
  (NDVI, terrain slope between neighbouring pixels).
- `measured_quantity_units` — the unit in which a delivered metric must make
  sense (km).
- `elevation_unit` — the vertical unit of an elevation raster.
- `elevation_vertical_datum` — the vertical datum of an elevation raster.
- `horizontal_crs` — the coordinate reference of the window.
- `pixel_spacing_deg_east_west` / `pixel_spacing_deg_north_south` — the pixel
  sizes, exactly as the source geotransform states them.
- `boundary_source` — which public dataset a vector geometry comes from.
- `deliverable_crs` — the CRS the source states for its geometry.
- `buffer_radius_km` — buffer distance a case uses, in kilometres.
- `elevation_unit` in scale/nodata/3DEP contexts: metres per NAVD 88 for 3DEP
  windows (stated by the product's sidecar XML), metre values in the
  Copernicus DEM (unit not stated by that product — recorded as such).

`facts_in_metadata` records, per fact key, `false` when the source's real
metadata does not state that exact fact, or `{"stated": true, "where": ...}`
with the file and field where it is stated.

### `oracle`

For **wrong** cases: an independent `reason` (never a Terraproof term), a
`value_metric` naming the single number, and `value` (that number, rounded to
6 decimals). For **correct** cases: `evidence` (why the delivered output is
right), plus `value_metric` and `value` of the honest recomputed quantity.
`oracle.py` recomputes each of these number from the cached sources and agrees
with every case's `kind` (wrong cases must be demonstrably wrong, correct
cases must match within rounding).

## Honest derivatives

All derived *outputs* (masks, decoded reflectances, slope grids, NDVI, buffers,
summaries) are generated by `derive.py` and carry exactly the labels the
scenario's character would have shipped. The one slightly mislabelled variant
(`elevation_wrong_unit_ignored_kauai/elevation_delivered.tif`) is the trap
itself: the derived raster carries **no unit tag** (label "none"), and the case
records that in its facts (the vertical unit and datum are stated by the
product metadata, and the deliverable claims feet).

## Counts

`qa_masking` 4 wrong + 4 correct, `scale_offset_fill` 3 + 3,
`elevation_units_slope` 3 + 3, `nodata` 2 + 2, `delivered_metrics` 3 + 3,
`plain` 4 correct — 34 cases in total.

## Test

`tests/python/test_verification_heldout_real.py` runs fetch (network), derive
and oracle when the cache or network is available and skips otherwise; it also
verifies that two `derive.py` runs are byte-identical and that neither fetch,
derive, oracle nor the test imports `terraproof.checks`, `terraproof.evidence`
or `terraproof.evals`.

## Determinism

- All fetch URLs are fixed and pinned (Natural Earth at tag v5.1.2).
- Every builder reads only cache content plus constants; JSON output is written
  with `sort_keys=True` and floats rounded to 6 decimals.
- Raster outputs are tiled GeoTIFFs (512 x 512 blocks, deflate, predictor 2)
  with two overview levels; no timestamps are embedded.
- The oracle draws the same numbers from the same cache under the facts' own
  definitions; it never imports `derive`.
