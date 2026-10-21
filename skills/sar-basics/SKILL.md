---
name: sar-basics
description: Work correctly with Sentinel-1 C-band SAR backscatter, covering GRD versus SLC products, calibration to sigma0/gamma0/beta0 from the product LUTs, linear power versus decibels, speckle and filtering trade-offs, terrain correction and geocoding, VV/VH polarisations and incidence-angle effects; use before SAR water, flood or change mapping or any statistics on Sentinel-1 backscatter.
license: MIT
---

# SAR basics (Sentinel-1)

## Identify the product before using pixel values

Sentinel-1 is a C-band SAR (centre frequency 5.405 GHz, wavelength ~5.55 cm) with
four exclusive modes: Stripmap (SM), Interferometric Wide swath (IW), Extra Wide
swath (EW) and Wave (WV). IW (250 km swath, incidence 29.1°–46.0°, VV+VH over
land) is the primary mode over land [S1]. Level-1 products are [S2, S3]:

| Product | Geometry | Pixel values | Use |
|---|---|---|---|
| SLC (Single Look Complex) | slant range, zero-Doppler; IW/EW per sub-swath, bursts separated by black-fill | complex I/Q, phase preserved, single look | interferometry, polarimetry, custom multilooking |
| GRD (Ground Range Detected) | detected, multi-looked, projected to ground range on the WGS84 ellipsoid | detected amplitude; phase lost | backscatter mapping and change |

The GRD ellipsoid projection uses a terrain height that varies in azimuth but is
constant in range [S3]: a GRD is **not terrain corrected**. IW GRD High resolution
has ~20 × 22 m resolution, 10 × 10 m pixel spacing and ENL 4.4 [S2]. Product
names encode mission, mode, type, resolution class, polarisation (`SV`, `SH`,
`DV` = VV/VH, `DH` = HH/HV), start/stop time, absolute orbit and datatake [S2].

Raw GRD/SLC digital numbers are **not backscatter**. Analysis-ready collections
may already be calibrated, terrain corrected and/or in dB; for example Google Earth
Engine `COPERNICUS/S1_GRD` is thermal-noise removed, calibrated, terrain corrected
and converted with `10*log10(x)`, while `COPERNICUS/S1_GRD_FLOAT` keeps power
values [S4]. Read the provider's processing description before any arithmetic.
Find and load products with [STAC and cloud access](../stac-and-cloud-access/SKILL.md).
Shared rules: [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Calibrate to β⁰, σ⁰ or γ⁰ with the product LUTs

Every Level-1 product carries calibration LUTs (`betaNought`, `sigmaNought`,
`gamma`, `dn`) in `annotation/calibration/`. For distributed targets [S5]:

```text
σ⁰ = DN² / Aσ²      β⁰ = DN² / Aβ²      γ⁰ = DN² / Aγ²
DN = GRD amplitude, or sqrt(I² + Q²) for SLC
```

LUT values are bilinearly interpolated between their sub-sampled pixel/line
positions [S3]. β⁰ is normalised in slant range, σ⁰ in the ground-range plane,
γ⁰ in the plane perpendicular to slant range [S5]. On the annotation's ellipsoid
model, `σ⁰ = β⁰·sin α`, `γ⁰ = β⁰·tan α`, so `γ⁰ = σ⁰ / cos α` [S5]. A noise LUT
(linear power) can be scaled by the same LUT and subtracted [S3].

GDAL ≥ 3.4 applies calibration for the `SIGMA0`, `BETA0` and `GAMMA` calibration
subdatasets of the SAFE driver; list them with `gdalinfo` on the `.SAFE`
directory [S6]. Interpolation code, the noise step and ESA's numerical check
(`<DN²> = 22142.71`, `Aσ = 319.946` → −6.65 dB) are in
[references/calibration-lut.md](references/calibration-lut.md).

## Keep linear power for arithmetic, dB for display and thresholds

The LUTs give natural (linear power) values; decibels are [S5]:

```text
σ⁰_dB = 10 * log10(σ⁰_lin)        σ⁰_lin = 10 ** (σ⁰_dB / 10)
amplitude = sqrt(power)
```

**Average in linear power, not in dB.** ESA averages intensity (`DN²`) before
calibrating an area [S5]; ASF notes power scale is appropriate for statistical
analysis while dB values are not appropriate for some statistics [S7]. Averaging
dB values computes a geometric mean: −5 dB and −15 dB average to −10 dB in dB but
to −7.6 dB when averaged in linear power.

```python
import numpy as np

def to_db(power):
    power = np.asarray(power, dtype="float64")
    out = np.full(power.shape, np.nan)
    np.log10(power, out=out, where=power > 0)
    return 10.0 * out                     # non-positive power stays NaN

def mean_db(db_values, axis=None):
    lin = 10.0 ** (np.asarray(db_values, dtype="float64") / 10.0)
    return to_db(np.nanmean(lin, axis=axis))
```

Label every raster with its quantity and scale (σ⁰ or γ⁰; linear, amplitude or
dB) in metadata and filenames. Typical confusions: dB data averaged or resampled
as if linear; dB thresholds applied to linear data; DN treated as σ⁰. Power values
are generally close to zero (ASF suggests a 0–0.3 display stretch) [S7], so a
"σ⁰" raster dominated by negative values is in dB and one with values in the
hundreds or thousands is likely uncalibrated DN. The noise-equivalent σ⁰ is
specified at −22 dB or better [S1]: values near that level are noise-dominated.

## Speckle: filtering is a trade-off

Speckle arises from interference of returns from many scatterers in a resolution
cell [S7]. Multi-looking reduces speckle at the cost of resolution: IW SLC has
ENL 1, IW GRDH ENL 4.4 [S2, S3]. Spatial filters (e.g. the local-statistics Lee
filter [S8]; ASF's optional Enhanced Lee, 7 × 7) smooth speckle but reduce
resolution [S7]. Temporal averaging (mean or median over dates) also mitigates
speckle, in which case a spatial filter may be unnecessary [S7].

- Choose and record filter type, window and order (before/after terrain
  correction); compare outputs with and without filtering for the task [S7].
- Filters that average pixel values should run on linear power for the same
  reason dates are averaged in linear power.
- Filtering blurs edges and small features; it can hide small floods or narrow
  rivers that a change map must report.

## Terrain correction and geocoding

GRD/SLC geolocation is provided as a grid of geolocation points; GDAL's SAFE
driver exposes them as **GCPs** with an empty coordinate system and no
geotransform [S6]. Warping on GCPs (`gdalwarp` polynomial or thin-plate-spline
transformers [S9]) is not DEM-based terrain correction. Two different
corrections exist:

- **Geometric terrain correction** (range-Doppler geocoding with a DEM) places
  pixels at the correct map position despite relief [S7].
- **Radiometric terrain correction (RTC)** normalises backscatter by the
  DEM-derived illuminated area, yielding terrain-flattened γ⁰ [S10, S7].

Side-looking geometry causes foreshortening, layover and shadow; in RTC products
layover/shadow areas carry no valid data and are flagged in a layover-shadow mask
[S7]. Record the DEM and its vertical datum, output CRS and pixel spacing (a
resampled DEM does not have finer information) [S7]. Coregistration to the DEM
can improve RTC but may introduce inconsistent offsets through time; orbit-based
geocoding gives more consistent alignment for time series [S7]. Use
[raster processing](../raster-processing/SKILL.md) for grids and resampling.

## Polarisation, water, flood and change

Sentinel-1 transmits H or V and receives both (dual pol HH+HV or VV+VH; single
HH or VV) [S1]. Rough surfaces and complex structures (forest) scatter more
energy back; flat surfaces reflect it away and appear dark [S1]. Cross-pol (VH)
is high for volume scatterers such as vegetation [S7, S1].

- **Water:** calm open water has very low backscatter and can often be separated
  with a threshold, frequently in dB; there is **no universal threshold** — derive
  it per scene, e.g. from the valley of a bimodal histogram, then refine [S7].
  Wind-roughened water is brighter (roughness raises backscatter [S1]); radar
  shadow and smooth surfaces such as dry sand are also dark [S7]. Validate.
- **Change/flood:** the log ratio `log10(date2 / date1)` of calibrated,
  co-registered images shows the direction of change (negative = decrease)
  [S7]. Compute ratios on linear values (equivalently, dB differences).
  Validate change maps with [accuracy assessment](../accuracy-assessment/SKILL.md);
  temporal design is in [time series and change](../time-series-and-change/SKILL.md).

## Incidence angle and acquisition geometry

Backscatter depends on incidence angle; ESA's processor applies range-dependent
gains partly to compensate for its variation [S3], and IW spans 29.1°–46.0° [S1].
σ⁰ and γ⁰ differ by `cos α`, so their sensitivity to geometry differs [S5, S7].

- Build time series from the **same relative orbit** (and orbit direction) when
  comparing dates, or normalise for incidence angle and document how. Relative
  orbit is in the manifest, not in the product name; ESA gives
  `relative = mod(absolute − 73, 175) + 1` for S1A (175 orbits per 12-day cycle;
  other units have their own offsets) [S2]. STAC fields `sat:relative_orbit` and
  `sat:orbit_state` carry it when present [S11].
- Revisit depends on the constellation: S1B ended in 2022; S1C (launched December
  2024) and S1D (November 2025) continue the mission [S1]. Expect irregular
  temporal sampling across these periods.

## Verify with Terraproof

Existing checks: `crs.defined` and `raster.grid_alignment` (multi-date stacks on
one grid), `raster.nodata_declared`, `raster.resampling`, `raster.cog_layout`, and
`stac.provenance` for source Items. The optical `rs.*` range checks do not apply
to SAR backscatter.

```bash
python -m terraproof check s1_vv_20240101_db.tif s1_vv_20240113_db.tif
python -m terraproof check s1-item.json
```

Being added in Phase 4: `sar.value_domain` (sampled values plausible for the
declared scale, sigma0 in dB or linear; flags dB/linear confusion) and
`sar.geocoded` (a real CRS/geotransform rather than GCP-only slant/ground-range
geometry before spatial analysis). CLI options are not final.

**Not checked automatically:** that the right LUT was used, noise removal,
terrain-correction quality and DEM choice, speckle-filter suitability, orbit
consistency in a time series, and water/change thresholds. Calibration-chain
verification against annotation metadata is not in scope.

## Sources

- [S1 — ESA SentiWiki, S1 Mission](https://sentiwiki.copernicus.eu/web/s1-mission): frequency, modes, IW swath/incidence 29.1°–46.0°, polarisations, primary IW VV+VH over land, NESZ −22 dB, roughness/dielectric behaviour, polarimetry, launch timeline, 12-day/175-orbit cycle.
- [S2 — ESA SentiWiki, S1 Products](https://sentiwiki.copernicus.eu/web/s1-products): GRD resolution classes and Table 6 (IW GRDH 20×22 m, 10 m spacing, ENL 4.4; SLC ENL 1), naming convention, relative-orbit formulas.
- [S3 — ESA SentiWiki, S1 Processing](https://sentiwiki.copernicus.eu/web/s1-processing): SLC/GRD definitions, ellipsoid projection with azimuth-varying terrain height, bilinear LUT interpolation, noise LUT, incidence-angle compensating application LUT.
- [S4 — Google Earth Engine, COPERNICUS/S1_GRD](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD): preprocessing steps, `10*log10(x)`, S1_GRD_FLOAT.
- [S5 — ESA-EOPG-CSCOP-TN-0002, Radiometric Calibration of S-1 Level-1 Products (Miranda & Meadows 2015)](https://sentiwiki.copernicus.eu/__attachments/a_362015d79d4b31d2ec7bfc41d6edf57727461ab4812ae4fbc7d634df98d3db58/ESA-EOPG-CSCOP-TN-0002%20-%20Sentienl-1%20Radiometric%20Calibration%20of%20Products%202015%20-%201.0.pdf): LUTs, `DN²/A²`, dB, intensity averaging, sin/tan normalisation, `cos α = Aγ²/Aσ²`.
- [S6 — GDAL SAFE driver](https://gdal.org/en/stable/drivers/raster/safe.html): geolocation grid as GCPs, calibration subdatasets since GDAL 3.4.
- [S7 — ASF HyP3 Sentinel-1 RTC Product Guide](https://hyp3-docs.asf.alaska.edu/guides/rtc_product_guide/): σ⁰/γ⁰ normalisation, power/amplitude/dB scales and statistics, speckle and Enhanced Lee filter, DEM matching, layover/shadow, log-difference change, water thresholding.
- [S8 — Lee, J.-S. (1980). Digital image enhancement and noise filtering by use of local statistics. IEEE TPAMI PAMI-2(2):165–168](https://doi.org/10.1109/TPAMI.1980.4766994).
- [S9 — GDAL gdalwarp](https://gdal.org/en/stable/programs/gdalwarp.html): GCP polynomial order and thin-plate-spline transformer.
- [S10 — Small, D. (2011). Flattening Gamma: Radiometric Terrain Correction for SAR Imagery. IEEE TGRS 49(8):3081–3093](https://doi.org/10.1109/TGRS.2011.2120616).
- [S11 — STAC sat extension](https://github.com/stac-extensions/sat): `sat:orbit_state`, `sat:relative_orbit`, `sat:absolute_orbit`.
