# Terraproof Phase 7 Held-Out Verification Cases (V0)

This directory contains the independent, held-out verification benchmark designed for Terraproof Phase 7. These 40 held-out cases serve as an independent test harness across five subtle remote-sensing and geospatial trap families.

None of the generator, oracle, or case definitions import or depend upon `terraproof.checks`, `terraproof.evidence`, or `terraproof.evals`.

---

## 1. Structure

- `cases.json`: Specification of all 40 verification cases (8 cases per family: 4 wrong, 4 correct).
- `generate.py`: Deterministic synthetic dataset generator producing rasters (GeoTIFF) and vector features (GeoJSON) alongside a SHA-256 hash manifest.
- `oracle.py`: Independent validator that recomputes expected ground truth from declared facts and sources, testing whether deliverables match declared `kind` (`wrong` vs `correct`).
- `README.md`: Declared vocabulary, scenario spread, and execution instructions.

---

## 2. Scenario Spread per Family

All 5 trap families contain **4 wrong cases** and **4 correct cases** (40 cases total), spanning diverse geographic regions, sensors, coordinate systems, grid resolutions, and physical value ranges.

### Family 1: Vertical Units (`vertical_units`)
Measures elevation units (metres, international feet, US survey feet, fathoms) and datum transformations (ellipsoidal vs orthometric NAVD88).
- `heldout-vert-01-wrong`: Washington coast storm erosion; UAV post-storm DTM in metres subtracted from USGS 3DEP LiDAR in feet without conversion (reported mean -104.5 m instead of -0.22 m).
- `heldout-vert-02-wrong`: Cascade Range avalanche DTM; county source in feet multiplied by 3.28084 instead of 0.3048, yielding mountains >21,000 m.
- `heldout-vert-03-wrong`: North Carolina coastal flooding; GNSS ellipsoidal heights $h$ delivered raw without NGS GEOID18 undulation correction ($N = -31.5$ m), leaving 31.5 m vertical datum bias.
- `heldout-vert-04-wrong`: Oregon timber canopy height; drone DSM in metres subtracted from bare-earth DTM in feet, generating negative canopy heights (~ -485 m).
- `heldout-vert-05-correct`: Puget Sound channel dredging; baseline feet converted ($ft \times 0.3048$) before differencing with post-dredge metres; exact metric agreement.
- `heldout-vert-06-correct`: Swiss Alps tunnel portal; alpine terrain converted to SI metres with exact factor 0.3048; summit elevations preserved up to 4,419.6 m.
- `heldout-vert-07-correct`: Chesapeake Bay marshland; ellipsoidal LiDAR converted to NAVD88 orthometric heights ($H = h - N$), accurately preserving 0.2 m tidal marsh boundary.
- `heldout-vert-08-correct`: Gulf of Maine bathymetry; legacy soundings in fathoms converted to negative elevations in metres ($fathoms \times 1.8288$).

### Family 2: QA Masking (`qa_masking`)
Measures surface classification quality flags (Sentinel-2 SCL, Landsat 8/9 QA_PIXEL, MODIS Mandatory QC, PlanetScope UDM2, VIIRS DNB).
- `heldout-qa-01-wrong`: Kansas wheat NDVI; completely omitted SCL QA masking; bright cumulus clouds and cloud shadows left unmasked (23.9% of scene).
- `heldout-qa-02-wrong`: British Columbia wildfire burn scar; inverted QA_PIXEL bitmask, masking 76% valid forest while retaining clouds and shadows.
- `heldout-qa-03-wrong`: Iberian Peninsula MODIS LST; omitted Mandatory QA check, keeping 230 K cloud-top temperatures in summer ground fields.
- `heldout-qa-04-wrong`: Everglades wetland survey; over-masked PlanetScope UDM2 by retaining only clear land (class 1), dropping all clear open water (class 2).
- `heldout-qa-05-correct`: Nile Delta Sentinel-2 NDVI; clouds/shadows masked while retaining clear water (class 6) with legitimate negative NDVI (-0.28).
- `heldout-qa-06-correct`: Death Valley Landsat 8 thermal; hot desert playa temperatures (>335 K) preserved without false cloud triggers.
- `heldout-qa-07-correct`: Greenland glacier monitoring; SCL correctly separates snow/ice (class 11) from atmospheric clouds (classes 8, 9, 3).
- `heldout-qa-08-correct`: Midwest US nighttime lights; cloud and stray-light pixels masked while preserving genuine 0.0 nW/cm2/sr dark rural pastures.

### Family 3: Scale and Offset (`scale_and_offset`)
Measures integer packing conventions ($physical = raw \times scale + offset$).
- `heldout-scale-01-wrong`: Landsat 9 Collection 2 Red band; raw uint16 integers delivered unscaled (mean 16,840 instead of physical reflectance 0.2631).
- `heldout-scale-02-wrong`: MODIS Terra LST; scale factor 0.02 applied twice, producing mean surface temperature of 5.96 K instead of 298.15 K (50x too small).
- `heldout-scale-03-wrong`: Sentinel-3 SLSTR SST; offset sign inverted ($raw \times 0.01 - 273.15$ instead of $+ 273.15$), yielding negative temperatures (-253.8 K).
- `heldout-scale-04-wrong`: SMAP soil moisture; divided by scale factor instead of multiplying, giving values $>28,000,000\text{ m}^3/\text{m}^3$.
- `heldout-scale-05-correct`: Landsat 8 NIR band; correctly unpacked with $raw \times 0.0000275 - 0.2$, matching terrestrial reflectance range [0.05, 0.65].
- `heldout-scale-06-correct`: ERA5-Land air temperature; correctly unpacked ($raw \times 0.002 + 260.0$), retaining sub-zero winter temperatures down to 244.5 K.
- `heldout-scale-07-correct`: GPCC precipitation anomaly; correctly unpacked ($raw \times 0.1 - 50.0$), representing drought anomalies (-42.5 mm) and surplus (+75.0 mm).
- `heldout-scale-08-correct`: GEDI L3 canopy height; unpacked uint8 ($raw \times 0.25$), preserving 0.0 m river clearings and 58.5 m emergent canopy.

### Family 4: Nodata Stored as Zero (`nodata_stored_as_zero`)
Measures discrimination between fill/nodata zeros and legitimate physical zero measurements.
- `heldout-nodata-01-wrong`: Harbor bathymetry; unmeasured terrestrial fill zeros included in navigation channel depth, pulling mean depth from -18.25 m to -5.12 m.
- `heldout-nodata-02-wrong`: Salton Sea / Pacific coast DEM; analyst assumed zero is nodata and evicted genuine 0.0 m shoreline pixels, punching holes in the coast.
- `heldout-nodata-03-wrong`: Sentinel-1 InSAR coherence; unmasked zero-padded border included in scene mean, dropping coherence from 0.684 to 0.221.
- `heldout-nodata-04-wrong`: Iowa hail damage; unsurveyed county zero-fill treated as 0% damage, diluting disaster aid severity index from 54.2% down to 12.1%.
- `heldout-nodata-05-correct`: St. Helena island DEM; ocean fill zeros (fill_value: 0.0) masked to NaN, preserving true island elevations.
- `heldout-nodata-06-correct`: Flevoland polder DEM; -9999.0 nodata masked to NaN while genuine 0.0 m sea-level dikes and negative polders are preserved.
- `heldout-nodata-07-correct`: Congo forest change; persistent cloud (class 255) masked while stable forest (class 0) is preserved to compute deforestation rates.
- `heldout-nodata-08-correct`: Atacama Desert precipitation; unmonitored cells (-999.0) masked while legitimate 0.0 mm dry weather days are retained.

### Family 5: Geographic Metric Work (`geographic_metric_work`)
Measures distinction between geographic angular units (degrees) and metric projected units (metres), including latitude convergence $\cos(\phi)$.
- `heldout-geom-01-wrong`: Scottish Highlands cadastral parcel; computed planar area in square degrees ($0.00015\text{ deg}^2$) and stored as $m^2$ (off by $6.8 \times 10^9$).
- `heldout-geom-02-wrong`: Alaska salmon stream 500 m buffer; buffered using isotropic degree radius at $60^\circ$N, creating a buffer $1,000\text{ m}$ wide north-south (100% distortion).
- `heldout-geom-03-wrong`: French highway length at $45^\circ$N; multiplied degree length by equatorial constant $111,319.5\text{ m/deg}$, ignoring $\cos(45^\circ)$ (+41.4% error).
- `heldout-geom-04-wrong`: Andes SRTM slope; computed gradient using degree cell spacing $0.001^\circ$ as metres, yielding average slopes of $89.92^\circ$ instead of $22.45^\circ$.
- `heldout-geom-05-correct`: Swedish nature reserve; reprojected to SWEREF99 TM (EPSG:3006), matching WGS84 geodesic area within 0.02%.
- `heldout-geom-06-correct`: California pipeline safety buffer; reprojected to UTM Zone 11N (EPSG:32611), buffered by exactly 250.0 m, verified uniform ground radius.
- `heldout-geom-07-correct`: Baltic Sea fiber cable; true ellipsoidal route length calculated with WGS84 Geod, matching geodesic ground distance.
- `heldout-geom-08-correct`: Colorado Rockies slope; grid steps scaled by local ground metres ($dx = d\lambda R \cos\phi, dy = d\phi R$), matching true mountain slope angles ($0^\circ$ to $38^\circ$).

---

## 3. Declared-Key Vocabulary

The `declared` block in `cases.json` describes what a careful practitioner specifies for the analysis. Keys avoid internal Terraproof check IDs and reflect plain domain terms:

| Key | Type | Description |
|---|---|---|
| `primary_source` | string | Relative path to primary input raster or vector. |
| `secondary_source` | string (optional) | Relative path to secondary raster (e.g. baseline DTM, geoid grid). |
| `source_vertical_unit` | string | Vertical measurement unit of primary raster (`"metre"`, `"foot"`, `"fathom"`). |
| `secondary_vertical_unit`| string | Vertical measurement unit of secondary raster. |
| `target_vertical_unit` | string | Expected vertical unit of output product (`"metre"`). |
| `conversion_factor` | float (optional) | Exact conversion scalar applied to convert source to target unit. |
| `source_datum` | string (optional) | Vertical/horizontal datum of source (`"WGS84_ellipsoidal"`). |
| `target_datum` | string (optional) | Target datum of output (`"NAVD88_orthometric"`). |
| `geoid_undulation_m` | float (optional) | Mean or local geoid separation $N$ in metres ($H = h - N$). |
| `qa_layer` | string (optional) | Relative path to pixel quality or classification raster. |
| `valid_qa_classes` | list[int] | Documented valid classification integer codes to preserve. |
| `invalid_qa_classes` | list[int] | Invalid classification integer codes to mask to nodata. |
| `invalid_bit_indices` | list[int] | Bit indices where a set bit (1) designates invalid/cloud data. |
| `valid_mandatory_qa_value`| int | Target integer value for mandatory QA subfields (e.g. bits 0-1 == 0). |
| `raw_data_type` | string | Integer storage type (`"uint16"`, `"int16"`, `"uint8"`). |
| `scale_factor` | float | Linear multiplier for unpacking raw integers to physical values. |
| `add_offset` | float | Additive offset for unpacking ($physical = raw \times scale + offset$). |
| `physical_quantity` | string | Domain quantity name (`"surface_reflectance"`, `"air_temperature_k"`, etc.). |
| `physical_unit` | string | Physical unit of unpacked measurement (`"ratio"`, `"kelvin"`, `"mm"`, `"m3/m3"`, `"metre"`). |
| `fill_value` | float | Numeric value used as fill or nodata in source dataset. |
| `zero_is_valid` | bool | `true` if 0.0 is a legitimate physical measurement; `false` if 0 is unmeasured fill. |
| `declared_nodata_value` | float | Declared nodata value in file metadata. |
| `physical_meaning_of_zero`| string | Explanation of what zero represents in the source domain. |
| `source_crs` | string | Native coordinate reference system of input geometry (`"EPSG:4326"`). |
| `intended_metric_crs` | string | Target metric projected CRS (`"EPSG:32611"`, `"EPSG:3006"`, `"EPSG:27700"`, etc.). |
| `metric_property_name` | string | Feature attribute field storing measured metric quantity (`"area_sqm"`, `"length_m"`). |
| `metric_unit` | string | Output metric unit (`"square_metre"`, `"metre"`, `"degrees_slope"`). |
| `buffer_distance_m` | float | Mandated buffer distance in ground metres. |
| `operation` | string | Expected processing operation (`"dem_elevation_difference"`, `"unit_conversion"`, `"qa_class_masking"`, `"scale_and_offset_unpacking"`, `"nodata_handling"`, `"polygon_area_calculation"`, etc.). |

---

## 4. How to Run

### 4.1 Running the Deterministic Generator
Generate all 40 verification cases into a target directory:
```bash
python evals/verification-heldout/generate.py /path/to/target_dir
```
Outputs:
- 40 case subdirectories containing sources and delivered outputs.
- `/path/to/target_dir/manifest.json` recording SHA-256 hashes of all 92 generated files.

### 4.2 Running the Independent Oracle
Evaluate generated deliverables against ground truth:
```bash
python evals/verification-heldout/oracle.py /path/to/target_dir
```
The oracle prints a structured verification table for all 40 cases, reporting agreement with declared `kind` (`wrong` vs `correct`), and exits with code 0 on complete agreement.

### 4.3 Running the Automated Regression Test
Run pytest suite to verify determinism and oracle agreement:
```bash
pytest tests/python/test_verification_heldout.py -v
```
