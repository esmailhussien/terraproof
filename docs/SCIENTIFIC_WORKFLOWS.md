# Scientific workflows: from approved intent to corrected outputs

Status: experimental local implementation, not published. Current intent schema: **`terraproof.workflow/3`**. Full QA-declared acquisition support is the default; partial support requires explicit `scene_coverage: "allow-partial"`. Native raster bounds are only the grid extent, not the acquired footprint. See the [coverage correction and uncertainty contract](SCIENTIFIC_ACQUISITION_UNCERTAINTY.md). The route consumes native USGS Landsat 8/9 Collection 2 L2SP Surface Temperature and delivers Celsius rasters, uncertainty, statistics, a map and evidence without a model or GUI.

## What the core now does

1. **Plan:** validate the native product, then scan bounded windows of QA/ST/uncertainty over the AOI before approval. Expose acquired support, quality/uncertainty distributions and optional-cutoff sufficiency; create no analysis outputs.
2. **Review:** bind a named review to the exact intent digest and input bytes, including recognized sidecars. This is an unsigned approval record, not an authentication system.
3. **Execute:** decode source-valid temperatures once, apply reviewed QA flags, select pixel centres inside the AOI, crop on the native grid, preserve product uncertainty and compute statistics.
4. **Verify:** re-read the originals and compare every output pixel, masks, crop transform, unit labels and statistics. Reuse the existing calibration check and explicit verification contract for the uncropped decoded intermediate.
5. **Repair:** after a failed output verification, regenerate once from the unchanged approved originals into a **new** directory. Preserve the previous output and the before/after findings. Insufficient coverage cannot be repaired by weakening QA or changing the requested quantity.
6. **Deliver:** analytical files, a self-contained SVG map, an HTML report, scoped verification and hashes. The API has no UI dependency.

The quantity is acquisition-time **land surface temperature**, not air temperature, a daily maximum or a heat-risk index. The first route does not redo the atmospheric/emissivity retrieval already present in the Level-2 product. It cannot independently establish absolute temperature accuracy from those same inputs.

## Local inputs

- Original USGS MTL JSON, grouped TXT or XML, with the product metadata and temperature calibration. MTL declares the local ST_B10, QA_PIXEL and ST_QA filenames. Assets must reside beside it. Arbitrary URLs, VRTs and alternative suppliers are not accepted by this adapter.
- Temperature: native one-band uint16; QA_PIXEL: uint16; ST_QA: int16. Grids must agree exactly. Tagged calibration may agree with the documented encoding, but raster samples are read as stored values and decoded exactly once.
- A single-layer polygon AOI: GeoJSON, Shapefile (with its companions), GeoPackage, KML or KMZ. KML/KMZ use longitude/latitude; network links and external XML entities are refused. Multipart polygons and holes are retained, altitude is ignored. An unknown CRS, invalid geometry, multiple layers or an antimeridian-spanning region is unresolved, not silently repaired.
- A native north-up grid, at most 100 million scene pixels. All analytical pixel processing uses 256-cell windows; vector AOI loading is not a streaming operation. Inputs are hashed in full, so this is not a zero-IO claim.

The metadata filenames establish the declared association; matching grids and hashes do not authenticate that a package genuinely came from USGS. Reviewers remain responsible for trusted provenance. Source metadata and QA can themselves contain errors.

## Command-line walkthrough

Write an **unapproved** template; the policy choices below are examples, not universal defaults:

```powershell
python -m terraproof workflow init workflow.json --metadata data/scene_MTL.json --aoi study_area.kmz --start 2025-06-01 --end 2025-08-31 --reject-qa-bits 0 1 2 3 4 5 7 --min-valid-fraction 0.6
python -m terraproof workflow plan workflow.json
```

The example excludes fill, dilated cloud, high-confidence cirrus/cloud/shadow/snow and water for a terrestrial study. Snow and water exclusion are scientific choices. This adapter supports individually declared QA_PIXEL flags 0–7, not arbitrary confidence-field expressions. It does not infer a policy from scene appearance or the user's prose.

Review the plan. Copy its **actual** `spec_digest`, not the literal placeholder below:

```powershell
python -m terraproof workflow approve workflow.json --reviewer "Engineering reviewer" --review-kind engineering-self-review --expect-digest DIGEST_FROM_PLAN --out approval.json
python -m terraproof workflow run approval.json --out runs/scene-001
python -m terraproof workflow verify approval.json runs/scene-001
```

`approve` refuses a changed digest or an existing approval destination. `run` refuses an existing output directory. Changed intent, metadata, assets or known companions invalidate the approval. A reviewer must hold a trusted approval copy: an actor allowed to rewrite both intent and approval can defeat this unsigned boundary. No ACL/ownership change or signing service is introduced.

If any requested native-grid AOI centre lacks QA-declared acquisition support, the default plan is `unresolved` before approval. Grid containment is also required. QA bit-0 fill or unavailable QA counts as unacquired/unknown, even inside the grid rectangle. Missing ST retrieval inside otherwise available QA is a separate quality issue. `--allow-partial` explicitly permits partial acquisition but never relaxes QA or the post-filter valid/acquired threshold.

To repair a corrupted/wrong derived output while preserving its history:

```powershell
python -m terraproof workflow repair approval.json runs/scene-001 --out runs/scene-001-repaired
```

This command verifies first, performs at most one regeneration, verifies the result and writes `repair.json`. It never edits original sources or silently chooses new parameters. It refuses a run already verified, and refuses to repeat a run whose only problem is insufficient coverage. Another scientific method, scene, quality policy or quantity needs a new reviewed intent. It does not rewrite arbitrary user scripts or implement a general AI repair agent.

If a processing step raises an exception, the `.partial-*` directory and its failure record remain available for diagnosis. The original output is not replaced. Artifacts and verification reports should be reviewed together; a static HTML report records a point-in-time run, not live monitoring of later file modifications.

## Intent format

```json
{
  "schema": "terraproof.workflow/3",
  "id": "Summer surface temperature",
  "intent": {
    "quantity": "land-surface-temperature",
    "unit": "degree_Celsius",
    "aoi": "study_area.geojson",
    "acquired_between": ["2025-06-01", "2025-08-31"],
    "reject_qa_bits": [0, 1, 2, 3, 4, 5, 7],
    "min_valid_fraction": 0.6,
    "scene_coverage": "full-aoi"
  },
  "source": {
    "metadata": "data/scene_MTL.json",
    "representation": "usgs-native-dn"
  }
}
```

Relative paths resolve against this file. Duplicate/unknown fields and nonfinite numbers are errors. The interval selects an inclusive UTC **single-acquisition** date; it does not define a monthly/period estimate. `scene_coverage` is `full-aoi` by default or explicitly `allow-partial`. Full acquisition requires grid containment, at least one requested centre, and available nonfill QA for every requested centre. The virtual-grid AOI audit includes centres outside the file and is capped at 110 million bounding cells. Fractions count centres, not geodesic area.

`min_valid_fraction` is **post-filter valid / QA-acquired AOI centres**. With no uncertainty cutoff, use `base_valid_count`; with a cutoff, use the retained count. Enforce sufficiency before approval in both cases, including zero usable observations. A nonbinding cutoff must not change admission timing. The grid-selected denominator is separately reported. Optional `max_uncertainty_kelvin` is omitted by default; exceeding and missing-uncertainty exclusions are counted separately when active. No automatic threshold/QA relaxation occurs.

Workflow `/1` and `/2` records are refused rather than reinterpreted. Copy the intent to a new `/3` file, review acquisition/cutoff semantics, get a fresh plan/digest/approval and use a new output directory. Plan, approval and run records use `/3`; source requests/search/package records use `/2`. Earlier frozen artifacts and candidate wheels remain unchanged.

Native source fill is removed before scaling. `0 degrees Celsius` and valid QA value `0` are not fill. Missing ST remains missing; no spatial or temporal gap fill is performed.

AOI membership is tested by transforming each native pixel centre into the AOI's original CRS and testing the original polygon, including boundary centres. Reprojecting only polygon vertices changes edge semantics and is not used for membership. A densified projected outline supplies crop/display bounds; cross-CRS crops include a one-pixel margin, so an outer row or column can be entirely excluded. Holes remain excluded. No analytical raster is reprojected.

## Outputs and meaning

| File | Meaning |
| --- | --- |
| `decoded_celsius.tif` | Uncropped, source-valid native-grid intermediate; Celsius, identity scale/offset |
| `temperature_celsius.tif` | QA/AOI-masked clipped temperature, float32 with nodata |
| `validity.tif` | 1 usable, 0 excluded; native clipped grid |
| `aoi.tif` | 1 AOI pixel centre, 0 outside; preserves the coverage denominator |
| `acquired.tif` | QA-declared acquired support, separate from the raster extent and post-quality validity |
| `uncertainty_kelvin.tif` | ST_QA decoded as a difference magnitude; no subtraction of 273.15; missing uncertainty stays missing |
| `summary.json` | Requested/grid-selected/acquired/valid counts and explicit fractions; pre/post uncertainty distributions and separate exclusions; single-acquisition facts |
| `calibration-evidence.json` | Existing Terraproof check and contract, explicitly scoped to the decoded intermediate |
| `map.svg` | Self-contained continuous temperature display, AOI outline, legend, date and source; not heat-risk classification |
| `report.html` | English result/method report linking evidence and artifacts |
| `workflow.json` | Intent snapshot, approval, product facts, initial verification and artifact/sidecar hashes |

The map is a display thumbnail; it does not create higher-resolution thermal information. No resampling changes analytical values. The summary uses equal valid pixels, not an area-weighted mean. Product uncertainty is not uncertainty of that mean and is not divided by sqrt(n).

Verification returns `verified`, `failed` or defensively `incomplete`. A verified workflow is graded `checks-passed`; scientific suitability and identity are not certified. Known acquisition or usable-support insufficiency, with or without a cutoff, is unresolved before approval. An incomplete verification result remains a safety fallback rather than the intended path for a known-bad plan. `physical_accuracy_validated` remains false.

HTML/SVG show numerical status, grid/request and acquired/request centre fractions, valid/acquired fraction, and self-declared review kind. `engineering-self-review` is the default; `declared-scientific-review` remains an unauthenticated claim and cannot upgrade the grade. Percentiles, above-2/3/4-K proportions, missing uncertainty and minimum are shown. Finer absolute comparisons/accuracy are not established by this workflow; the minimum ST_QA is not a guaranteed accuracy floor. No uncertainty of the mean is inferred from sqrt(n). Reports remain point-in-time evidence.

CLI exit codes: 0 successful command/verified run, 3 unresolved/failed/incomplete, 1 invalid/unreadable input. Non-workflow commands/grades are unchanged. Verification does not rewrite saved evidence.

## Python API and future interfaces

```python
from terraproof.workflows import plan, approve, execute, verify, repair

review = plan("workflow.json")
# A human reviews the scientific choices and actual digest before approve().
```

The same functions can be used by a future MCP/QGIS/web adapter. The [source-selection extension](SCIENTIFIC_SOURCE_RECOVERY.md) adds one bounded public Landsat catalog/discovery/acquisition route and an unapproved native workflow; it adds no GUI, server, new routing trigger or MCP tool. Approval is an explicit caller responsibility, never an inferred user decision.

## Validation and scientific boundaries

Development fixtures and hand-computed expectations cover the complete route, changed pixels/masks/units, summaries/layout identities, source/sidecar drift, invalid policies, native metadata formats, AOI formats, no usable observations and bounded repair. These are engineering checks, not a new held-out measurement. No live model or active T3 artifacts are used.

One [real native-scene experiment](SCIENTIFIC_WORKFLOW_REAL_SCENE_2026-11-03.md) exposed and corrected an AOI false-assurance bug, then passed independent arithmetic/support validation and an explicitly injected repair. The [additional boundary review](SCIENTIFIC_WORKFLOW_BOUNDARY_REVIEW_2026-11-03.md) disclosed a coverage-oracle correction. The [schema-2 validation](SCIENTIFIC_WORKFLOW_COVERAGE_V2_2026-11-03.md) implements the user's full-coverage default and explicit partial choice, with installed real-data and visual checks. Independent scientific review and broader predeclared scene coverage remain release gates before describing this as production-ready. Additional products need dedicated admission rules; additional analyses need their own scientific requirements. Reuse current contracts/checks rather than adding a generic workflow framework before a second concrete route exists.

Primary scientific references are recorded in [sources/SOURCES.md](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature).
