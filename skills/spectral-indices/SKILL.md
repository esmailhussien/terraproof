---
name: spectral-indices
description: Compute and interpret vegetation, water, and burn indices with explicit formulas, sensor band mappings, calibrated reflectance, masks, and numeric safeguards; use for NDVI, McFeeters NDWI, MNDWI, NBR or dNBR, EVI, and SAVI from Sentinel-2 or Landsat 8/9 imagery.
---

# Spectral indices

## Require calibrated, aligned inputs

For this skill's quantitative comparison workflows, use cloud/shadow-screened,
physical **surface reflectance**, not raw DN, RGB display values, QA codes, or a
mixture of TOA and surface reflectance. Decode scale and additive offset exactly
once using [satellite preprocessing](../satellite-preprocessing/SKILL.md). A
common multiplicative scale cancels in a normalized difference, but an additive
offset does not. EVI/SAVI constants also require physical reflectance units.

Verify CRS, complete affine transform, dimensions, extent and validity masks
before pairing pixels. Use the intersection of masks for all bands in the
formula. Resampling a coarse SWIR band to a finer grid does not create finer
information; document the chosen analysis grid and resampling. Resampling
reflectance before a nonlinear index is generally not equivalent to resampling the
computed index. Use
[raster processing](../raster-processing/SKILL.md) for I/O, masks and alignment,
[GDAL](../gdal/SKILL.md) for CLI workflows, and
[geomaster](../geomaster/SKILL.md) for broader interpretation context.
Shared rules: [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Map spectral roles to the sensor

Use product band identifiers, not positions in an arbitrary raster stack.
The following mapping is for Sentinel-2 MSI and Landsat **8/9 OLI**, not older
Landsat sensors [S1, S2]:

| Spectral role | Sentinel-2 | Landsat 8/9 surface reflectance |
|---|---|---|
| Blue (`B`) | B02 | SR_B2 |
| Green (`G`) | B03 | SR_B3 |
| Red (`R`) | B04 | SR_B4 |
| Broad NIR (`N`) | B08 | SR_B5 (OLI NIR) |
| Narrow NIR alternative | B8A | No interchangeable extra NIR band |
| SWIR1 (`S1`) | B11 | SR_B6 |
| SWIR2 (`S2`) | B12 | SR_B7 |

Sentinel-2 B02/B03/B04/B08 have native **10 m** resolution; B8A/B11/B12 have
native **20 m** resolution [S1]. B08 and B8A have different spectral responses.
For Sentinel-2 formulas below, `N` defaults to B08; if using B8A to match a
coarser grid or a harmonized workflow, name that choice and do not mix it across
dates as if unchanged. Landsat 8/9 reflective bands here have **30 m** resolution
[S2]. Do not read `src.read(8)` to obtain B08 from a single-band B08 file:
Rasterio indices address file bands, not sensor band names.

## NDVI: vegetation contrast

Use physical, masked red and NIR reflectance on the same grid [S3]:

```text
NDVI = (N - R) / (N + R)
Sentinel-2: (B08 - B04) / (B08 + B04)
Landsat 8/9: (SR_B5 - SR_B4) / (SR_B5 + SR_B4)
```

For nonnegative inputs with nonzero sum, NDVI lies in **[-1, 1]**. High values
indicate stronger NIR/red contrast, not a universal biomass or plant-health
measurement. NDVI can saturate in dense vegetation and responds to soil,
phenology, water, shadow and atmosphere. Do not apply universal vegetation-class
thresholds without local calibration. Negative corrected reflectances can yield
ratios outside the nominal interval; investigate rather than silently clipping.

## NDWI (McFeeters) versus MNDWI: specify the water index

For open-water contrast, use one named definition and physical reflectance [S4]:

```text
NDWI_McFeeters = (G - N) / (G + N)
MNDWI_Xu      = (G - S1) / (G + S1)
```

McFeeters NDWI uses Sentinel-2 B03/B08 or Landsat 8/9 SR_B3/SR_B5. MNDWI uses
Sentinel-2 B03/B11 or Landsat 8/9 SR_B3/SR_B6. These are **not** the NIR/SWIR
vegetation-moisture index also called NDWI (Gao). ESA SNAP names the McFeeters
operator `NDWI2`; always state the formula rather than trusting an operator name.

Both normalized differences lie in **[-1, 1]** for nonnegative inputs and nonzero
sum. MNDWI substitutes SWIR1 to reduce some built-up-land confusion, not to create
an infallible water mask. Turbid/shallow water, shadows, snow, mixed shore pixels
and urban surfaces still require validation. Select a local threshold using
reference data; do not present either continuous index as measured water depth.

## NBR and dNBR: burn-sensitive contrast and change

Use masked, aligned NIR and **SWIR2**, not SWIR1 [S5]:

```text
NBR  = (N - S2) / (N + S2)
dNBR = NBR_prefire - NBR_postfire
Sentinel-2 NBR: (B08 - B12) / (B08 + B12)
Landsat 8/9 NBR: (SR_B5 - SR_B7) / (SR_B5 + SR_B7)
```

For nonnegative reflectances with nonzero sum, NBR lies in **[-1, 1]**. The
unscaled dNBR difference can consequently span **[-2, 2]** (derived from the two
NBR bounds), so it must not be tested as though it were a single normalized index.
Record whether a delivered product is scaled; do not compare encoded integer
thresholds with unscaled floats.

Positive dNBR commonly indicates decreased NBR after fire, but seasonality,
moisture, harvest, land-cover change and cloud remnants also alter NBR. Match
prefire/postfire season and processing, retain both-date validity, and validate
burn severity with suitable reference observations [S6]. Do not invent universal
severity class breaks or treat an index change as causal proof of fire.

## EVI and SAVI: additive constants require physical reflectance

Use blue/red/NIR surface reflectance for EVI; use red/NIR for SAVI. The standard
USGS coefficients and the USGS SAVI soil adjustment choice are [S7, S8]:

```text
EVI  = 2.5 * (N - R) / (N + 6 * R - 7.5 * B + 1)
SAVI = (1 + L) * (N - R) / (N + R + L), with L = 0.5
```

Map `B`, `R`, `N` using the sensor table. Do not put raw DN or reflectance scaled
to integer storage into these formulas: the additive constants would be in the
wrong units. EVI mitigates some canopy-background/atmospheric effects but is not
a substitute for atmospheric correction and QA. Its blue term is sensitive to
residual atmospheric problems; USGS warns that Landsat 8/9 SR blue-band retrieval
can be unreliable for analysis [S9]. Make that caveat visible when using EVI.

EVI has no universal algebraic **[-1, 1]** bound: even nonnegative inputs can
produce a near-zero denominator and extreme values. USGS delivered EVI products
have a specified valid range, but that product contract is not a theorem about
every raw formula result [S7]. SAVI with `L = 0.5` is bounded by **[-1, 1]** when
both input reflectances are within **[0, 1]** (derived from its formula); negative
or above-unity corrected values invalidate that assumption. Keep exceptions
visible. Do not clip EVI/SAVI simply to pass an index-range checker.

## Divide safely and write explicit nodata

Cast before arithmetic. A zero denominator is invalid, not index zero. Mask
nonfinite inputs and outputs. If near-zero denominators are excluded, select a
tolerance from measurement/precision requirements and report it; a universal
machine epsilon is not a scientific quality threshold.

```python
import numpy as np

def safe_ratio(numerator, denominator, min_abs_denominator=0.0):
    if min_abs_denominator < 0:
        raise ValueError("Denominator tolerance must be nonnegative")
    num = np.ma.asarray(numerator, dtype="float32").filled(np.nan)
    den = np.ma.asarray(denominator, dtype="float32").filled(np.nan)
    valid = np.isfinite(num) & np.isfinite(den)
    valid &= np.abs(den) > min_abs_denominator
    out = np.full(np.broadcast_shapes(num.shape, den.shape), np.nan, dtype="float32")
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        np.divide(num, den, out=out, where=valid)
    out[~np.isfinite(out)] = np.nan
    return out
```

Standalone NDVI read/write example for **already decoded** single-band
reflectance files with identity scale/offset (small rasters; use windows for
large scenes). The helper above can be used for other formulas:

```python
import numpy as np
import rasterio

with rasterio.open("sr_red.tif") as red_src, rasterio.open("sr_nir.tif") as nir_src:
    if red_src.crs is None or red_src.crs != nir_src.crs:
        raise ValueError("Known, matching CRS required")
    if red_src.transform != nir_src.transform or red_src.shape != nir_src.shape:
        raise ValueError("Bands must share the complete grid")
    for src in (red_src, nir_src):
        if src.count != 1 or src.scales != (1.0,) or src.offsets != (0.0,):
            raise ValueError("Expected decoded single-band reflectance")
    r = red_src.read(1, masked=True).astype("float32").filled(np.nan)
    n = nir_src.read(1, masked=True).astype("float32").filled(np.nan)
    den = n + r
    valid = np.isfinite(n) & np.isfinite(r) & (den != 0)
    ndvi = np.full(r.shape, np.nan, dtype="float32")
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        np.divide(n - r, den, out=ndvi, where=valid)
    ndvi[~np.isfinite(ndvi)] = np.nan
    with rasterio.open(
        "ndvi.tif", "w", driver="GTiff", width=red_src.width,
        height=red_src.height, count=1, dtype="float32", nodata=np.nan,
        crs=red_src.crs, transform=red_src.transform,
    ) as dst:
        dst.write(ndvi, 1)
```

Metadata identity alone cannot prove physical encoding; that is a prerequisite
from the preprocessing record. Preserve valid zero indices and keep masked
pixels nodata. Independently check known input pixels and formula values.

## Verify with Terraproof

Use an installed Python core and real local data:

```bash
python -m terraproof check sr_red.tif sr_nir.tif --expect reflectance
python -m terraproof check ndvi.tif --expect index --format md --lang en --out ndvi-report.md
python -m terraproof check nbr_prefire.tif nbr_postfire.tif --expect index
python -m terraproof check dnbr.tif
```

`rs.reflectance_range` is sampled plausibility, not proof of decoded SR.
`rs.index_range` tests a nominal normalized-index interval; it is useful for
NDVI/NDWI/MNDWI/NBR under the stated assumptions, **not a general validator for
dNBR or EVI**. The last command intentionally omits `--expect index` for dNBR.
Inspect out-of-range results rather than altering data to satisfy a checker.

`raster.nodata_declared`, `raster.grid_alignment`, `crs.defined` and
`crs.consistent` provide metadata checks. Grid alignment does not establish
identical shape/extent or actual co-registration. GeoTIFF inputs may also receive
the heuristic `raster.cog_layout` check.

Formula choice, correct band roles, exact-once calibration, cloud masking,
denominator policy, scientific interpretation, and burn/water/vegetation
threshold validity are **not checked automatically yet**. A plausible wrong-band
index can pass. See [verification](../verification/SKILL.md).

## Sources

- [S1 — ESA Sentinel-2 mission](https://sentiwiki.copernicus.eu/web/s2-mission): spectral-band identities and native 10 m/20 m resolutions.
- [S2 — USGS Landsat band designations](https://www.usgs.gov/landsat-missions/landsat-8): OLI blue 2, green 3, red 4, NIR 5, SWIR1 6, SWIR2 7 and 30 m reflective resolution; [Landsat 9](https://www.usgs.gov/landsat-missions/landsat-9) has the corresponding OLI bands.
- [S3 — USGS NDVI](https://www.usgs.gov/landsat-missions/landsat-normalized-difference-vegetation-index): formula, Landsat 8/9 bands and delivered range. Normalized-difference bounds here follow algebraically for nonnegative inputs.
- [S4 — ESA SNAP McFeeters NDWI2 specification](https://raw.githubusercontent.com/senbox-org/optical-toolbox/master/opttbx-radiometric-indices-ui/src/main/resources/eu/esa/opt/radiometry/docs/ndwi2/Ndwi2AlgorithmSpecification.html) and [MNDWI specification](https://raw.githubusercontent.com/senbox-org/optical-toolbox/master/opttbx-radiometric-indices-ui/src/main/resources/eu/esa/opt/radiometry/docs/mndwi/MndwiAlgorithmSpecification.html): green/NIR versus green/middle-IR formulas with unit factors. No upstream text or code is vendored.
- [S5 — USGS NBR](https://www.usgs.gov/landsat-missions/landsat-normalized-burn-ratio): formula and Landsat 8/9 bands 5 and 7 (SWIR2).
- [S6 — USGS Burn Severity glossary](https://burnseverity.cr.usgs.gov/glossary): dNBR prefire-minus-postfire definition; [MTBS product descriptions](https://www.mtbs.gov/product-descriptions): seasonal/phenological scene matching.
- [S7 — USGS EVI](https://www.usgs.gov/landsat-missions/landsat-enhanced-vegetation-index): gain 2.5, red coefficient 6, blue coefficient 7.5, background constant 1 and delivered-product specifications.
- [S8 — USGS SAVI](https://www.usgs.gov/landsat-missions/landsat-soil-adjusted-vegetation-index): formula and L = 0.5; conditional bounds here are algebraic consequences, not universal physical limits.
- [S9 — USGS Collection 2 surface reflectance](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-reflectance): OLI coastal/blue-band aerosol-inversion caveat and potentially unreliable corrections.
