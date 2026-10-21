# Change-detection approaches compared

Reference for [time series and change](../SKILL.md). Descriptions are limited to
what the cited method papers, package descriptions and implementation docs state;
check each implementation's own documentation for parameters.

| Approach | Input series | What it models | Typical output | Main failure modes |
|---|---|---|---|---|
| Thresholded difference / ratio (ΔNDVI, dNBR, SAR log ratio) | Two dates (or two composites) | Nothing; direct difference | Continuous change magnitude, thresholded to classes | Phenology mismatch, residual cloud, uncalibrated threshold, mask mismatch |
| Post-classification comparison | Two classified maps | Independent classifications | From–to change classes | Errors in either map become false change; single-date accuracy does not describe change accuracy [S5] |
| BFAST [S1] | Seasonal series; the package notes its BFAST Lite variant handles missing data without interpolation | Trend + seasonal + remainder; breaks in trend and seasonal components | Break dates, magnitudes, fitted piecewise models | Gaps/undetected clouds, irregular sampling, short series |
| CCDC [S2, S4] | All available clear observations | Harmonic functions fitted iteratively; temporal breakpoints | Segments with fit coefficients, break dates; breakpoint bands selectable | Undetected cloud/shadow, sparse observations, sensor/baseline shifts |
| LandTrendr [S3, S4] | One observation per year (e.g. annual composites) | Temporal segmentation of spectral trajectories into linear segments | Vertices (breakpoints), fitted values, disturbance/recovery segments | Inconsistent annual compositing, phenology in composites, one index drives breakpoints |

## Choosing

- **Question:** abrupt events (fire, clearing, flood) suit differences or
  breakpoint methods; gradual trends need models with trend terms over long
  records; from–to classes need a classification step that maps change directly.
- **Data density:** dense methods need many clear observations; persistent cloud
  or short records favour seasonal composites or SAR.
- **Consistency:** a single processing baseline, sensor harmonisation and stable
  masks matter more than the algorithm; method reviews organise the choices by
  frequency, preprocessing, algorithm and application [S6].
- **Validation:** every approach needs a reference sample stratified by the
  change classes it produces and area-adjusted estimates [S5, S7].

## Record for every run

Input ids and dates, masks, composite rule and valid counts, index or band,
method and version, parameters, thresholds with their derivation, and the
validation sample design.

## Sources

- [S1 — Verbesselt et al. (2010), Remote Sensing of Environment 114(1):106–115](https://doi.org/10.1016/j.rse.2009.08.014); [bfast package description](https://github.com/cran/bfast/blob/master/DESCRIPTION).
- [S2 — Zhu & Woodcock (2014), Remote Sensing of Environment 144:152–171](https://doi.org/10.1016/j.rse.2014.01.011).
- [S3 — Kennedy, Yang & Cohen (2010), Remote Sensing of Environment 114(12):2897–2910](https://doi.org/10.1016/j.rse.2010.07.008).
- [S4 — Google Earth Engine CCDC](https://developers.google.com/earth-engine/apidocs/ee-algorithms-temporalsegmentation-ccdc) and [LandTrendr](https://developers.google.com/earth-engine/apidocs/ee-algorithms-temporalsegmentation-landtrendr) API documentation.
- [S5 — FAO (2016), Map accuracy assessment and area estimation: a practical guide](https://www.fao.org/3/i5601e/i5601e.pdf).
- [S6 — Zhu (2017), ISPRS J. Photogramm. Remote Sens. 130:370–384](https://doi.org/10.1016/j.isprsjprs.2017.06.013).
- [S7 — Olofsson et al. (2014), Remote Sensing of Environment 148:42–57](https://doi.org/10.1016/j.rse.2014.02.015).
