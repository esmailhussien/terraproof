# Terraproof Domain Routing Map

> **Status:** Static architectural routing guide for Terraproof skills.

This document describes the recommended skill composition and execution pipelines for complex user tasks spanning GIS, remote sensing, spatial data analysis, and process work.

---

## Routing Principles

1. **Instructions First:** Universal engineering rules (`instructions/`) are always loaded and persistent.
2. **Process & Planning:** Non-trivial tasks begin with `brainstorming` or `writing-plans`.
3. **Domain Wayfinding:** High-level domain skills (e.g. `geomaster`) provide conceptual grounding.
4. **Focused Execution:** Dedicated tool skills (e.g. `gdal`, `geopandas`, `design-postgis-tables`) provide precise implementation rules.
5. **Quality & Verification:** Every task concludes with `verification`.

---

## Canonical Task Compositions

### 1. Statistical Inference & Publication Figures
```text
User Task: "Test whether two patient cohorts differ significantly and publish the comparison figure"

1. instructions/engineering.md
2. skills/statistical-analysis
   → Hypothesis selection, assumption verification, effect size calculation
3. skills/scientific-visualization
   → Generate publication-quality figures with colorblind-safe palettes
4. skills/verification
   → Review findings against raw data and truthfulness standards
```

### 2. Vector GIS Analysis & Proximity Queries
```text
User Task: "Find all schools located within 1 km of primary highways"

1. skills/geospatial-data-discovery (if datasets need sourcing)
2. skills/geomaster (spatial reasoning, CRS selection)
3. skills/geopandas (GeoDataFrame loading, buffer, spatial join, geometry intersection)
4. skills/verification (confirm metric CRS was used for distance calculations)
```

### 3. Raster Processing & Cloud-Optimized GeoTIFF Conversion
```text
User Task: "Convert satellite tiles to Cloud-Optimized GeoTIFFs (COG) and reproject to Web Mercator"

1. skills/gdal
   → `gdalwarp` for reprojection, `gdal_translate` with `-co TILED=YES -co COPY_SRC_OVERVIEWS=YES`
2. skills/verification
   → Verify headers with `gdalinfo -json`
```

### 4. Spatial Database Design
```text
User Task: "Design a multi-tenant location tracking schema in PostgreSQL"

1. skills/brainstorming
   → Clarify scale, write throughput, and geographic scope
2. skills/design-postgis-tables
   → Geometry vs Geography selection, GiST indexing, bounding-box operators
3. skills/verification
```

### 5. Geospatial Web Map Application
```text
User Task: "Build an interactive map dashboard displaying live delivery fleets"

1. skills/brainstorming & skills/writing-plans
2. skills/geospatial-frontend
   → MapLibre GL map instance, layer styling, deck.gl data overlay
3. skills/verification
```

### 6. Spatial Network Analysis
```text
User Task: "Compute shortest emergency evacuation routes across a city road network"

1. skills/geomaster
   → Network topology extraction and edge weight assignment
2. skills/networkx
   → Graph construction, Dijkstra/A* path algorithms, centrality metrics
3. skills/geopandas
   → Re-project route geometries and export GeoJSON/GeoPackage
4. skills/verification
```

---

## Phase 4 Remote-Sensing Compositions

These four domain skills (Phase 4) cover multi-date work, SAR, map accuracy, and cloud-native data access. They compose rather than overlap: each owns one decision, and the companions supply the inputs.

### 7. Multi-Date Compositing & Change Detection
```text
User Task: "Build a monthly composite from Sentinel-2 and map forest loss 2020–2024"

1. skills/time-series-and-change
   → per-observation decode/mask, composite method, valid-observation counts,
     temporal alignment, change definition, thresholded differences or BFAST/CCDC/
     LandTrendr, and reference-validated change area
2. skills/satellite-preprocessing  (when decoding/QA signals are also present in the prompt)
3. skills/accuracy-assessment      (when change area or accuracy will be reported)
4. skills/verification
```

### 8. Sentinel-1 SAR Analysis
```text
User Task: "Map flood extent from a Sentinel-1 GRD scene"

1. skills/sar-basics
   → GRD vs SLC, calibration LUTs to σ⁰/γ⁰/β⁰, linear power vs dB, speckle filtering,
     terrain correction and geocoding, polarisation and incidence angle
2. skills/raster-processing  (for grids and resampling of the corrected product)
3. skills/verification
```

### 9. Map Accuracy & Area Estimation
```text
User Task: "Report the accuracy and forest area of my land-cover map"

1. skills/accuracy-assessment
   → stratified probability sampling by map class, response design, area-proportion
     confusion matrix, overall/user's/producer's accuracy with CIs, area-adjusted areas
2. skills/statistical-analysis  (for general inference on the sample)
3. skills/crs-and-units         (stratum areas need true metric areas first)
4. skills/verification
```

### 10. STAC Search & Cloud-Native Access
```text
User Task: "Search a STAC catalog and read only the window of a COG I need"

1. skills/stac-and-cloud-access
   → reproducible search parameters, pinned item ids, signed URLs / requester-pays,
     /vsicurl/ windowed reads, loader scale/offset behaviour, run manifest
2. skills/satellite-preprocessing  (decode the DN the loader did not decode)
3. skills/verification
```

---

## Recommended and Required Links

AGENTS.md rule 15 requires a documented reason for every `recommended` and `requires` link in a skill manifest. The resolver applies them differently. A `requires` skill is always selected. A `recommended` skill is added only if it also scores at or above the selection threshold (4), or if it is `verification`, which is always selected. A recommendation therefore never adds a skill on its own; the prompt must also contain a direct signal for that skill. No skill declares `requires` or `conflicts`. A recommended companion (for example, `satellite-preprocessing` alongside `spectral-indices`) is acceptable in any scenario and must not be listed in `mustExclude`.

| From | Type | To | Rationale |
|---|---|---|---|
| `spectral-indices` | recommended | `satellite-preprocessing` | Indices are defined on decoded, masked, calibrated surface reflectance, with scale and offset applied exactly once. `satellite-preprocessing` produces that input. |
| `satellite-preprocessing` | recommended | `raster-processing` | Mask application, grid harmonization, and COG delivery use the rules in `raster-processing`. |
| `vector-quality` | recommended | `crs-and-units` | Snapping tolerances, precision grids, and area checks are in coordinate units, so they need a reviewed metric CRS first. |
| `gdal`, `geomaster`, `geopandas`, `geoparquet-validation`, `geospatial-data-discovery`, `geozarr`, `networkx`, `scientific-visualization`, `statistical-analysis`, `systematic-debugging`, `writing-plans` | recommended | `verification` | Pre-existing link. `verification` is the completion audit for the skill's output, and it is always selected, so this link adds no skill. |
| `brainstorming` | recommended | `writing-plans` | Pre-existing link. Design options that are chosen become an execution plan. |
| `time-series-and-change` | recommended | `satellite-preprocessing` | A series is only analysis-ready once each observation is decoded (scale/offset exactly once) and QA-masked; `satellite-preprocessing` defines both, and the compositing rules assume them. |
| `time-series-and-change` | recommended | `accuracy-assessment` | Change is rare, so reported change area and accuracy need a probability sample stratified by the change classes with area-adjusted estimates; `accuracy-assessment` defines that design and estimator. |
| `sar-basics` | recommended | `raster-processing` | Terrain correction and geocoding produce a new grid, and multi-date stacks must share one CRS, pixel size and origin; the grid and resampling rules are in `raster-processing`. |
| `sar-basics` | recommended | `accuracy-assessment` | Water, flood and change thresholds derived from SAR are validated against reference data, so the same sample design and area-adjusted estimator apply. |
| `accuracy-assessment` | recommended | `statistical-analysis` | Confidence intervals for accuracy and area come from stratified variance estimation on the sample; general inference and effect-size tooling is in `statistical-analysis`. |
| `accuracy-assessment` | recommended | `crs-and-units` | Stratum areas `A_m,i` must be true areas, and `--operation area` fails on geographic/geocentric CRSs, so a reviewed metric CRS is a precondition for every area number. |
| `stac-and-cloud-access` | recommended | `satellite-preprocessing` | Loaders disagree on decoding: `odc.stac` returns raw DN while `stackstac` rescale-applies `raster:bands` scale/offset, so the decode-exactly-once rules must be applied after loading. |
| `stac-and-cloud-access` | recommended | `geospatial-data-discovery` | Catalog search answers "what imagery exists and may I use it"; `stac-and-cloud-access` then covers reproducible retrieval and provenance of the chosen items. |
