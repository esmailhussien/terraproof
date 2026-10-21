---
name: time-series-and-change
description: Build analysis-ready satellite time series and detect change defensibly, covering per-observation masking and decoding, compositing, gap handling, temporal alignment, per-date index versus index of a composite, seasonality and phenology confounds, thresholded differences, trend and breakpoint methods, post-classification comparison and validation of change with reference data; use for multi-date optical or SAR monitoring, composites and change maps.
license: MIT
---

# Time series and change detection

## Define the change question first

State what change means (land-cover conversion, disturbance, flooding, gradual
trend), the minimum detectable size and magnitude, the period and the
observation frequency needed. Different change-detection procedures produce
different change maps even in the same environment [S1]; the question decides the
method, not the other way round. Reviews organise Landsat time-series change
detection by temporal frequency, preprocessing, algorithm and application [S2].

Related skills: [satellite preprocessing](../satellite-preprocessing/SKILL.md)
(decoding, QA masks, single-period composites),
[spectral indices](../spectral-indices/SKILL.md) (formulas, dNBR),
[SAR basics](../sar-basics/SKILL.md) (backscatter scales, orbit consistency),
[STAC and cloud access](../stac-and-cloud-access/SKILL.md) (search, loading,
provenance), [raster processing](../raster-processing/SKILL.md) (grids,
resampling), [accuracy assessment](../accuracy-assessment/SKILL.md) (validation).
Shared rules: [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Build an analysis-ready time series

Process each observation **before** stacking or compositing:

1. Decode scale/offset exactly once and mask fill, cloud, shadow and other QA
   classes per sensor ([satellite preprocessing](../satellite-preprocessing/SKILL.md)).
   Check whether your loader already decoded the data
   ([STAC and cloud access](../stac-and-cloud-access/SKILL.md#know-what-your-loader-decodes)).
2. Put all dates on **one grid** (CRS, transform, shape); categorical QA layers
   with nearest neighbour.
3. Merge tiles of the same acquisition into one observation (e.g. odc-stac
   `groupby="solar_day"`) so overlaps are not counted as extra dates [S3].
4. Keep one consistent product definition: processing level and baseline,
   sensor, band (B08 vs B8A) and, for SAR, quantity/scale and relative orbit.
5. Keep per-observation provenance: item id, acquisition time (UTC), processing
   version and mask policy.

Store a **valid-observation count** per pixel and period beside every composite
or statistic. A median of two valid observations is not comparable with a median
of twenty.

## Handle gaps without inventing data

- Invalid pixels stay nodata (NaN or a declared nodata), never 0 — zero is a
  valid reflectance or index value.
- Set a minimum valid count per period and mask results below it; report the
  masked fraction.
- Interpolation or gap filling is a model: label filled values, keep the
  original count, and never treat filled values as observations in validation.
- Irregular sampling (orbit changes, constellation gaps, seasonal cloud) biases
  composites towards the clearer part of a period; report the dates that
  actually contributed.

## Align observations in time

STAC `datetime` is UTC [S4]. Define periods (calendar months, 16-day windows,
seasons) explicitly, and whether an observation belongs to a period by its UTC
timestamp or local solar day. For bi-temporal change use comparable dates
(anniversary dates or the same phenological window), the same sensor geometry
(SAR: same relative orbit) and the same processing baseline where possible.

## Composite of indices is not index of composite

For a nonlinear index such as NDVI, the median (or mean) of per-date indices
differs in general from the index of per-band composites, and per-band medians can
come from **different dates**. Three valid dates (red, NIR):
(0.05, 0.40), (0.10, 0.20), (0.04, 0.30):

```text
per-date NDVI          = 0.778, 0.333, 0.765     → median of NDVI = 0.765
median red, median NIR = 0.05 (date 1), 0.30 (date 3) → NDVI of medians = 0.714
```

Pick one, name it in metadata and outputs, and use it consistently across
periods. A medoid or best-observation composite keeps real spectra from a single
date ([satellite preprocessing](../satellite-preprocessing/SKILL.md)). The code below computes both, with counts:

```python
import xarray as xr

def ndvi(red, nir):
    den = nir + red
    return ((nir - red) / den).where(den != 0)

def monthly_products(red, nir, min_obs=3):
    """red, nir: decoded, masked reflectance (NaN = invalid), dims (time, y, x)."""
    valid = red.notnull() & nir.notnull()
    red, nir = red.where(valid), nir.where(valid)
    count = valid.resample(time="1MS").sum()
    median_of_ndvi = ndvi(red, nir).resample(time="1MS").median()
    ndvi_of_median = ndvi(red.resample(time="1MS").median(),
                          nir.resample(time="1MS").median())
    enough = count >= min_obs
    return xr.Dataset({
        "valid_count": count,
        "median_of_ndvi": median_of_ndvi.where(enough),
        "ndvi_of_median": ndvi_of_median.where(enough),
    })
```

On the three dates above this returns 0.765 and 0.714 with `valid_count` 3. For
Dask-backed arrays, test chunking along `time` before relying on median
reductions; write outputs with explicit nodata
([raster processing](../raster-processing/SKILL.md)).

## Separate seasonality and phenology from change

Vegetation indices, soil moisture, snow and water levels vary within the year.
A difference between a spring and a summer image is mostly phenology. Options:

- compare the same season or phenological stage across years;
- use a multi-year baseline per period (e.g. same month in prior years) and
  express change as a departure from it;
- use models that represent seasonality explicitly (harmonic or seasonal terms),
  as BFAST and CCDC do [S5, S6].

Also check for non-land-change causes: residual cloud/shadow, sensor or baseline
changes, illumination and view geometry, and (SAR) moisture and incidence angle.

## Thresholded differences

Bi-temporal differencing (e.g. ΔNDVI, dNBR) or SAR log ratios
(`log10(date2/date1)` on linear power) is simple and transparent
([spectral indices](../spectral-indices/SKILL.md), [SAR basics](../sar-basics/SKILL.md)).

- Use the intersection of both dates' valid masks.
- No universal threshold exists; derive and document it for the study area
  (reference data, histogram analysis) and report sensitivity to it.
- A difference measures signal change, not cause; interpret with the change
  definition and validate.

## Trend and breakpoint methods

Dense time-series methods model each pixel's trajectory and flag departures:

- **BFAST** decomposes a series into trend, seasonal and remainder components and
  detects abrupt changes in the trend and seasonal components [S5].
- **CCDC** uses all available observations, iteratively fitting harmonic
  functions and finding temporal breakpoints [S6, S7].
- **LandTrendr** temporally segments yearly Landsat trajectories into linear
  segments to characterise disturbance and recovery [S8, S7].

Their parameters, input requirements and outputs are compared in
[references/change-methods.md](references/change-methods.md). Each needs a
consistent, well-masked series; gaps, undetected clouds and baseline changes
create false breaks. Treat their parameters as model choices to document and
test, not universal defaults.

## Post-classification comparison

Comparing two independently classified maps labels every classification error
in either date as change, and the accuracies of the two single-date maps say
nothing about the accuracy of the change classes [S9]. Prefer mapping change
directly (time-series or multi-date classification). If maps must be compared,
assess the resulting change map itself.

## Validate change with reference data

Change is usually rare, so assessment needs a probability sample **stratified by
the change map's classes** (e.g. loss, gain, stable) with enough units in the
change strata, reference labels that cover both dates, and area-adjusted
estimates with confidence intervals [S9, S10]. Follow
[accuracy assessment](../accuracy-assessment/SKILL.md); do not report change area
as a pixel count of the change map.

## Verify with Terraproof

```bash
python -m terraproof check ndvi_2023-06.tif ndvi_2024-06.tif --expect index
python -m terraproof check composite_count_2024-06.tif
python -m terraproof check source-item.json
```

`raster.grid_alignment` (dates on one grid), `raster.nodata_declared`,
`crs.defined`/`crs.consistent`, `rs.index_range` (normalised indices, not dNBR or
differences), `rs.reflectance_range` (decoded reflectance composites) and
`stac.provenance` apply today.

Being added in Phase 4: `rs.temporal_scope` (item/input datetimes inside the
declared time range), `rs.cloud_mask_applied` (pixels flagged cloud/shadow in an
aligned SCL/QA raster are nodata in the output), `rs.scale_applied_once`,
`provenance.reproducible`, and for change validation `accuracy.sample_design`
and `accuracy.estimates`. CLI options are not final.

**Not checked automatically:** composite method and its consistency across
periods, valid-count thresholds, phenological comparability, change thresholds,
breakpoint-model parameters, and whether a detected change is real.

## Sources

- [S1 — Singh, A. (1989). Digital change detection techniques using remotely-sensed data. International Journal of Remote Sensing 10(6):989–1003](https://doi.org/10.1080/01431168908903939): different procedures give different change maps.
- [S2 — Zhu, Z. (2017). Change detection using Landsat time series: a review of frequencies, preprocessing, algorithms, and applications. ISPRS J. Photogramm. Remote Sens. 130:370–384](https://doi.org/10.1016/j.isprsjprs.2017.06.013).
- [S3 — odc-stac `load`](https://odc-stac.readthedocs.io/en/latest/_api/odc.stac.load.html): `groupby="solar_day"` and fusing of overlapping items.
- [S4 — STAC Item specification](https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md): `datetime` in UTC.
- [S5 — Verbesselt, J., Hyndman, R., Newnham, G., Culvenor, D. (2010). Detecting trend and seasonal changes in satellite image time series. Remote Sensing of Environment 114(1):106–115](https://doi.org/10.1016/j.rse.2009.08.014); [bfast package description](https://github.com/cran/bfast/blob/master/DESCRIPTION): trend/seasonal/remainder decomposition and break detection.
- [S6 — Zhu, Z., Woodcock, C.E. (2014). Continuous change detection and classification of land cover using all available Landsat data. Remote Sensing of Environment 144:152–171](https://doi.org/10.1016/j.rse.2014.01.011).
- [S7 — Google Earth Engine `ee.Algorithms.TemporalSegmentation.Ccdc`](https://developers.google.com/earth-engine/apidocs/ee-algorithms-temporalsegmentation-ccdc) and [`LandTrendr`](https://developers.google.com/earth-engine/apidocs/ee-algorithms-temporalsegmentation-landtrendr): harmonic-function breakpoints; temporal segmentation of spectral trajectories.
- [S8 — Kennedy, R.E., Yang, Z., Cohen, W.B. (2010). Detecting trends in forest disturbance and recovery using yearly Landsat time series: 1. LandTrendr. Remote Sensing of Environment 114(12):2897–2910](https://doi.org/10.1016/j.rse.2010.07.008).
- [S9 — FAO (2016). Map accuracy assessment and area estimation: a practical guide](https://www.fao.org/3/i5601e/i5601e.pdf): accuracy of change must be assessed on change, not on two single-date maps; stratification for change classes.
- [S10 — Olofsson, P. et al. (2014). Good practices for estimating area and assessing accuracy of land change. Remote Sensing of Environment 148:42–57](https://doi.org/10.1016/j.rse.2014.02.015).
