# Terraproof Phase 7 Held-Out Verification Cases (V0b)

This directory contains the second independent, held-out verification benchmark (V0b) authored for Terraproof Phase 7. These 48 held-out cases independently measure checker accuracy and false-alarm resistance across 6 trap and regression families.

None of the generator, oracle, or case definitions import or depend upon `terraproof.checks`, `terraproof.evidence`, or `terraproof.evals`.

---

## 1. Directory Contents

- `cases.json`: Declarations, scenario narratives, deliverables, and oracle specifications for all 48 verification cases.
- `generate.py`: Deterministic synthetic generator producing tiled GeoTIFF rasters with overviews and GeoJSON vector features alongside a SHA-256 hash manifest.
- `oracle.py`: Independent validator that recomputes expected ground truth from declared facts and sources, testing whether deliverables match declared `kind` (`wrong` vs `correct`).
- `README.md`: Declared vocabulary, scenario spread, and execution instructions.

---

## 2. Scenario Spread per Family

All 6 families contain 8 cases each (48 cases in total). Families 1–5 feature 4 wrong cases and 4 correct cases; Family 6 features 8 plain correct cases measuring false-alarm rates.

### Family 1: Metric values delivered in geographic coordinates (`geographic_metric_work`)
Vector outputs stored in EPSG:4326 that carry measured values (area, length) as properties, or that are buffers of a stated ground distance.
- `heldout-v0b-geom-01-wrong`: Scottish Highlands estate; computed planar area in square degrees ($0.00025\text{ deg}^2$) and stored as $m^2$ (off by $6.8 \times 10^9$).
- `heldout-v0b-geom-02-wrong`: Northern Norway Arctic char river; 500m buffer generated with isotropic degree radius at $68^\circ$N, expanding east-west ground width to $1,334\text{ m}$ (167% distortion).
- `heldout-v0b-geom-03-wrong`: Germany transport corridor; road length computed as Euclidean degree distance $\times 111,319.5$, ignoring $\cos(50^\circ)$ (+55.5% error).
- `heldout-v0b-geom-04-wrong`: New Zealand transmission powerline; executed naive degree buffer `buffer(100.0)`, spanning 100 degrees of latitude/longitude.
- `heldout-v0b-geom-05-correct`: Alberta forest compartment; parcel area in $m^2$ computed geodesically on WGS84 ellipsoid ($3,450,200\text{ m}^2$) while delivered geometry remains in EPSG:4326.
- `heldout-v0b-geom-06-correct`: Iceland marine bird skerry; 250m sanctuary buffer constructed in conformal metric space with verified uniform 250m ground width, delivered in EPSG:4326.
- `heldout-v0b-geom-07-correct`: Northern Chile mining railway; route length in metres evaluated via WGS84 ellipsoidal geodesics, delivered in EPSG:4326.
- `heldout-v0b-geom-08-correct`: Alaska pipeline corridor; 1,000m safety buffer evaluated in Alaska Albers (EPSG:3338) with verified uniform 1,000m ground width, delivered in EPSG:4326.

### Family 2: QA masking, both directions (`qa_masking`)
Surface classification quality flags (Sentinel-2 SCL, Landsat 8/9 QA_PIXEL, MODIS QC), including under-masking, over-masking, and source nodata gaps.
- `heldout-v0b-qa-01-wrong`: Ukraine wheat NDVI; completely omitted SCL QA masking, retaining clouds and shadows across 22% of scene.
- `heldout-v0b-qa-02-wrong`: Minnesota lake quality; over-masked by keeping only clear land (class 4), dropping all valid clear water (class 6).
- `heldout-v0b-qa-03-wrong`: Pyrenees snow monitoring; over-masked by rejecting valid snow/ice (class 11) as cloud.
- `heldout-v0b-qa-04-wrong`: Rocky Mountains MODIS snow fraction; failed to filter cloud bit 0, keeping cloudy pixels in snow fraction.
- `heldout-v0b-qa-05-correct`: Thessaly Greece NDVI; masks clouds (classes 3, 8, 9) and preserves source sensor swath edge nodata (-9999.0) as nodata.
- `heldout-v0b-qa-06-correct`: Everglades Landsat 9 NDVI; masks clouds while preserving clear water (class 6) with legitimate negative NDVI (-0.28).
- `heldout-v0b-qa-07-correct`: Swiss Alps NDSI; correctly distinguishes atmospheric clouds (3, 8, 9) from alpine snow (class 11) and rock (class 5).
- `heldout-v0b-qa-08-correct`: Death Valley TIRS; masks clouds while preserving instrument scan border nodata and hot desert surfaces (>335 K).

### Family 3: Terrain slope from DEMs without unit labels (`terrain_slope_unlabeled`)
DEMs in geographic or projected CRSs whose files carry no vertical unit label (unit is specified only in declaration).
- `heldout-v0b-slope-01-wrong`: Japanese Alps DEM in EPSG:4326 (cell step $0.001^\circ$); computed slope using degree step as 0.001 metres, generating slopes $>89.9^\circ$.
- `heldout-v0b-slope-02-wrong`: Colorado Rockies DEM in UTM (10m grid); declared unit is foot; analyst computed slope treating feet as metres, inflating gradients by $3.28\times$.
- `heldout-v0b-slope-03-wrong`: Western Norway fjord DEM in EPSG:4326 ($62^\circ$N); used uniform equatorial $111,320\text{ m/deg}$, ignoring $\cos(62^\circ) = 0.4695$ (53% gradient error).
- `heldout-v0b-slope-04-wrong`: Appalachian DEM in EPSG:4326 ($38^\circ$N); declared unit is foot; analyst treated feet as metres AND degrees as metres ($>89.9^\circ$ slope).
- `heldout-v0b-slope-05-correct`: Italian Apennines DEM in EPSG:4326 ($42^\circ$N); correctly scaled metric grid spacing ($dx=82.72\text{ m}, dy=111.32\text{ m}$), yielding true slopes $[0^\circ, 36^\circ]$.
- `heldout-v0b-slope-06-correct`: Sierra Nevada DEM in UTM (30m grid); declared vertical unit foot converted ($ft \times 0.3048$) before gradient calculation.
- `heldout-v0b-slope-07-correct`: Kenai Peninsula DEM in EPSG:4326 ($60^\circ$N); properly scaled by $\cos(60^\circ) = 0.5000$.
- `heldout-v0b-slope-08-correct`: Mt. Rainier DEM in Washington State Plane (horizontal 100 ft = 30.48 m); harmonized horizontal feet with declared vertical metres.

### Family 4: Vertical datums and unusual units (`vertical_datums_and_units`)
Datum transformations, geoid undulation grids, fathoms, US survey feet, and soundings sign conventions.
- `heldout-v0b-datum-01-wrong`: Everglades survey; inverted geoid correction ($h + N$ instead of $h - N$), placing land 53 metres below sea level.
- `heldout-v0b-datum-02-wrong`: Boston Harbor soundings; positive-down soundings (+8m to +24m) delivered as positive elevations without sign inversion.
- `heldout-v0b-datum-03-wrong`: Bering Sea bathymetry in fathoms; converted using foot factor 0.3048 instead of fathom factor 1.8288 ($6\times$ too shallow).
- `heldout-v0b-datum-04-wrong`: Houston subsidence LiDAR; omitted declared 2D GEOID18 undulation grid, leaving 27.2 m datum bias.
- `heldout-v0b-datum-05-correct`: San Francisco Bay soundings; correctly applied $z = -depth$, delivering valid negative elevations (-4m to -38m).
- `heldout-v0b-datum-06-correct`: Mississippi Delta levee survey; correctly applied 2D GEOID18 undulation grid ($H = h - N$), yielding +1.5m to +22.0m NAVD88.
- `heldout-v0b-datum-07-correct`: North Sea sounding chart in fathoms; converted with exact factor 1.8288, preserving negative signs (-27.4m to -146.3m).
- `heldout-v0b-datum-08-correct`: Puerto Rico highway survey in US survey feet; converted using exact factor $1200 / 3937 = 0.3048006096$, preserving sub-millimeter precision.

### Family 5: Nodata stored as zero, and scale and offset (`nodata_and_scale_regression`)
Regression checks covering nodata fill zeros vs legitimate zero measurements, and scale & offset integer unpacking.
- `heldout-v0b-reg-01-wrong`: Rhode Island wind farm bathymetry; rocky island fill 0.0 kept in depth statistics, pulling mean depth from -32.4m to -8.8m.
- `heldout-v0b-reg-02-wrong`: Death Valley sea-level base level (0.0 m); analyst treated 0 as nodata and evicted valid coastal pixels to NaN.
- `heldout-v0b-reg-03-wrong`: MODIS Band 1 Red uint16; delivered unscaled raw integers (500 to 6,000) instead of surface reflectance [0.05, 0.60].
- `heldout-v0b-reg-04-wrong`: Sentinel-3 SLSTR LST int16; inverted offset sign ($DN \times 0.01 - 273.15 = -245\text{ K}$).
- `heldout-v0b-reg-05-correct`: Belize coral reef bathymetry; caye fill 0.0 correctly masked to nodata before calculating channel depths.
- `heldout-v0b-reg-06-correct`: Namib Desert precipitation; legitimate 0.0 mm dry observations preserved while true nodata (-999.0) is masked.
- `heldout-v0b-reg-07-correct`: Landsat 9 Band 3 Green uint16; unpacked with $DN \times 0.0000275 - 0.2$, matching terrestrial reflectance range [0.02, 0.45].
- `heldout-v0b-reg-08-correct`: ERA5-Land Siberian winter temperature int16; unpacked with $DN \times 0.002 + 250.0$, preserving sub-freezing conditions down to 232.5 K.

### Family 6: Plain correct outputs (`plain`)
Standard deliverables with no trap that measure false alarms on ordinary GIS and remote-sensing deliverables.
- `heldout-v0b-plain-01-correct`: Standard DEM in UTM Zone 32N (EPSG:32632) in metres [220m, 850m], tiled with overviews.
- `heldout-v0b-plain-02-correct`: Standard NDVI in UTM Zone 18N (EPSG:32618) [-0.10, +0.82], tiled with overviews.
- `heldout-v0b-plain-03-correct`: Standard Land Surface Temperature in Kelvin in UTM Zone 31N (EPSG:32631) [285K, 312K].
- `heldout-v0b-plain-04-correct`: Standard Canopy Height Model in metres in British National Grid (EPSG:27700) [0m, 32.5m].
- `heldout-v0b-plain-05-correct`: Standard building footprints GeoJSON in UTM Zone 10N (EPSG:32610).
- `heldout-v0b-plain-06-correct`: Standard river reaches LineString GeoJSON in UTM Zone 33N (EPSG:32633).
- `heldout-v0b-plain-07-correct`: Standard air quality monitoring stations Point GeoJSON in EPSG:4326.
- `heldout-v0b-plain-08-correct`: Standard Land Cover categorical uint8 GeoTIFF in UTM Zone 16N (EPSG:32616) [classes 1-5, nodata 255].

---

## 3. Declared-Key Vocabulary

The `declared` block in `cases.json` uses plain GIS domain terms without referencing internal Terraproof check IDs:

| Key | Type | Description |
|---|---|---|
| `primary_source` | string | Relative path to primary raster or vector source. |
| `secondary_source` | string (optional) | Relative path to secondary source (e.g. 2D geoid undulation grid). |
| `source_crs` | string | Native coordinate system of source data (`"EPSG:4326"`, `"EPSG:32613"`). |
| `delivery_crs` | string (optional) | Declared coordinate system of deliverable product. |
| `declared_vertical_unit` | string (optional) | Vertical unit stated in declaration when missing from file (`"metre"`, `"foot"`). |
| `source_vertical_unit` | string (optional) | Source vertical measurement unit (`"fathom"`, `"us_survey_foot"`). |
| `target_vertical_unit` | string (optional) | Expected vertical unit of delivered output (`"metre"`). |
| `conversion_factor` | float (optional) | Scalar factor used to convert units (e.g. 1.8288 for fathoms, 0.3048006096 for US ft). |
| `source_datum` | string (optional) | Vertical datum of source (`"WGS84_ellipsoidal"`). |
| `target_datum` | string (optional) | Vertical datum of target (`"NAVD88_orthometric"`). |
| `geoid_undulation_m` | float (optional) | Constant geoid undulation $N$ in metres ($H = h - N$). |
| `source_convention` | string (optional) | Directional sounding convention (`"positive_down_depth"`). |
| `target_convention` | string (optional) | Directional elevation convention (`"positive_up_elevation"`). |
| `qa_layer` | string (optional) | Relative path to pixel quality or classification raster. |
| `valid_qa_classes` | list[int] | List of integer classification codes to preserve. |
| `invalid_qa_classes` | list[int] | List of integer classification codes to mask to nodata. |
| `invalid_bit_indices` | list[int] | Bit indices where 1 indicates cloud or invalid observation. |
| `raw_data_type` | string (optional) | Storage type of packed integers (`"uint16"`, `"int16"`). |
| `scale_factor` | float (optional) | Multiplicative scale factor ($physical = raw \times scale + offset$). |
| `add_offset` | float (optional) | Additive offset. |
| `physical_quantity` | string (optional) | Physical quantity name (`"surface_reflectance"`, `"air_temperature_k"`). |
| `physical_unit` | string (optional) | Unit of unpacked measurement (`"ratio"`, `"kelvin"`). |
| `fill_value` | float (optional) | Value used as fill or nodata in source dataset. |
| `zero_is_valid` | bool (optional) | `true` if 0.0 is a legitimate physical measurement; `false` if fill. |
| `declared_nodata_value` | float/int | Declared nodata value in file metadata. |
| `metric_property_name` | string (optional) | Feature attribute name storing measured metric quantity (`"area_m2"`, `"length_m"`). |
| `metric_unit` | string (optional) | Target metric measurement unit (`"square_metre"`, `"metre"`, `"degrees_slope"`). |
| `buffer_distance_m` | float (optional) | Mandated buffer distance in ground metres. |
| `operation` | string | Processing operation descriptor (`"polygon_area_calculation"`, `"line_buffer_generation"`, `"geodesic_length_calculation"`, `"qa_class_masking"`, `"qa_bitmask_filtering"`, `"terrain_slope_calculation"`, `"geoid_height_correction"`, `"sounding_to_elevation"`, `"unit_conversion"`, `"nodata_handling"`, `"scale_and_offset_unpacking"`, `"pass_through_verification"`). |

---

## 4. Tiled GeoTIFF Layout & Determinism

All raster deliverables and sources are generated with:
- `tiled=True, blockxsize=64, blockysize=64`
- Nearest-neighbor overviews (`[2, 4]`)
- Declared nodata in metadata where applicable
- Fixed random seed (`seed=42`) ensuring byte-identical reproduction across runs.

---

## 5. How to Run

### 5.1 Run the Deterministic Generator
```bash
python evals/verification-heldout-v0b/generate.py /path/to/target_dir
```
Outputs 48 case directories and `/path/to/target_dir/manifest.json` recording SHA-256 hashes of all 106 generated files.

### 5.2 Run the Independent Oracle
```bash
python evals/verification-heldout-v0b/oracle.py /path/to/target_dir
```
Evaluates all 48 deliverables against ground truth, prints the verification table, and exits with code 0 on complete agreement.

### 5.3 Run the Automated Regression Test
```bash
pytest tests/python/test_verification_heldout_v0b.py -v
```
