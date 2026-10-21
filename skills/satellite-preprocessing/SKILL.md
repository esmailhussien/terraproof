---
name: satellite-preprocessing
description: Prepare Sentinel-2 Level-2A and Landsat Collection 2 Level-2 surface reflectance with sensor-specific QA masks, exactly-once scale and offset decoding, grid harmonization, and temporal compositing; use before quantitative indices, cross-sensor comparison, or optical satellite time-series analysis.
---

# Satellite preprocessing

## Establish the product and encoding

Use product metadata to identify sensor, processing level, collection/baseline,
acquisition time, band identity, nodata, scale/offset and previous processing.
Sentinel-2 L2A provides surface (formerly BOA) reflectance; L1C provides TOA
reflectance. Landsat Collection 2 Level-2 SR is not Level-1 imagery, temperature,
or a display composite. QA arrays are categorical/bit-packed, not reflectance.

A provider may already decode or harmonize the original DN encoding. Inspect
both raster scale metadata and product XML/MTL/STAC metadata, plus the reader's
behavior. Rasterio `read()` returns stored values; rioxarray
`mask_and_scale=True` decodes scale/offset exposed by its raster reader.
Do not infer encoding from a plausible-looking histogram alone.

Use [raster processing](../raster-processing/SKILL.md) for masks, grids and output
I/O; [spectral indices](../spectral-indices/SKILL.md) for index computation; and
[geomaster](../geomaster/SKILL.md) for broader remote-sensing workflows.
Shared rules: [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Decode Sentinel-2 L2A reflectance

For original L2A DN, ESA defines [S1]:

```text
surface_reflectance_i = (DN_i + BOA_ADD_OFFSET_i) / BOA_QUANTIFICATION_VALUE
```

Starting with processing baseline **04.00**, radiometric offsets were introduced.
The operational `BOA_ADD_OFFSET` is **-1000 DN** for all spectral bands [S2]; the
reflectance quantification value is **10000** [S3]. Read the actual band-specific
offset and quantification value from the product metadata rather than hardcoding
based on acquisition date. Reprocessed older acquisitions can use newer baselines.
For pre-offset original products, follow their documented metadata/encoding;
do not subtract the newer offset from every historical product.

**DN 0 is nodata**, not a dark valid pixel [S1]. Mask it before decoding. Cast to
float before adding a negative offset, or unsigned arithmetic can wrap. A negative
retrieved reflectance is not automatically fill; ESA introduced the offset to
retain such values. Keep quality flags and investigate unexpected values instead
of clipping all outputs to a cosmetic range.

This function expects original, undecoded DN and an SCL already aligned by
nearest-neighbor to the band grid. Pass metadata values, not provider-adjusted DN:

```python
import numpy as np

def decode_s2_l2a(dn, scl, boa_add_offset, quantification_value):
    if dn.shape != scl.shape or quantification_value <= 0:
        raise ValueError("Aligned arrays and positive quantification required")
    invalid = np.ma.getmaskarray(dn) | np.ma.getmaskarray(scl)
    raw = np.ma.getdata(dn)
    classes = np.ma.getdata(scl)
    # Conservative example: also exclude unclassified, cast shadow and snow.
    invalid |= (raw == 0) | np.isin(classes, [0, 1, 2, 3, 7, 8, 9, 10, 11])
    sr = (raw.astype("float32") + boa_add_offset) / quantification_value
    return np.where(invalid | ~np.isfinite(sr), np.nan, sr).astype("float32")
```

## Mask Sentinel-2 SCL cloud and shadow classes

SCL is a classification, not a probability band. ESA's class values are [S4]:

| SCL | Meaning | Example policy |
|---|---|---|
| 0 | No data | Exclude |
| 1 | Saturated or defective | Exclude |
| 2 | Cast shadows; historically dark features/shadows | Review baseline; exclude in the conservative example |
| 3 | Cloud shadows | Exclude |
| 4 | Vegetation | Retain if task-relevant |
| 5 | Not vegetated | Retain if task-relevant |
| 6 | Water | Retain for water tasks; not automatically bad |
| 7 | Unclassified | Exclude or review explicitly |
| 8 | Cloud medium probability | Exclude |
| 9 | Cloud high probability | Exclude |
| 10 | Thin cirrus | Exclude |
| 11 | Snow or ice | Exclude for snow-free analysis; retain for snow studies |

The cloud/shadow rejection core is 3, 8, 9, 10 plus nodata/defective pixels; other
exclusions depend on the scientific question. Native SCL is supplied on coarser
grids than some reflectance bands [S1]. Reproject/resample it with nearest, never
bilinear. Retain the intersection of QA and validity for **all required bands**.

SCL can miss cloud edges, fog, or classify bright terrain incorrectly. Inspect
residual cloud/shadow contamination and document any additional spatial mask
expansion; no universal dilation distance is prescribed here.

## Decode Landsat Collection 2 Level-2 SR

For Landsat 8/9 Collection 2 Level-2 surface reflectance [S5, table 6-1]:

```text
surface_reflectance = DN * 0.0000275 - 0.2
```

Fill is **0**. Mask fill and quality flags before decoding; do not apply this
formula to QA bands or thermal bands. Read the MTL band multipliers/addends and
confirm that they describe the input encoding. Do not reuse Collection 1 scaling.
USGS notes that atmospheric correction can yield negative or above-unity values;
range checks alone cannot establish calibration correctness.

For Landsat **8/9** `QA_PIXEL`, bit positions are zero-based [S5, table 6-2; S6]:

| Bit | Flag when set |
|---|---|
| 0 | Fill |
| 1 | Dilated cloud |
| 2 | High-confidence cirrus |
| 3 | High-confidence cloud |
| 4 | High-confidence cloud shadow |
| 5 | High-confidence snow |
| 6 | Clear: cloud and dilated-cloud bits are not set |
| 7 | Water |

Bit 6 alone does not establish absence of cirrus, shadow, snow or saturation.
The confidence fields require separate decoding if used; they are not single
Boolean flags. Do not copy this sensor-specific table to older Landsat sensors.

```python
import numpy as np

def decode_landsat89_c2_sr(dn, qa_pixel, qa_radsat):
    if not (dn.shape == qa_pixel.shape == qa_radsat.shape):
        raise ValueError("QA and SR arrays must share a grid")
    invalid = (np.ma.getmaskarray(dn) | np.ma.getmaskarray(qa_pixel)
               | np.ma.getmaskarray(qa_radsat))
    raw = np.ma.getdata(dn)
    qa = np.ma.getdata(qa_pixel).astype("uint16")
    # Snow-free policy: reject fill, dilation, cirrus, cloud, shadow and snow.
    reject_bits = sum(1 << bit for bit in (0, 1, 2, 3, 4, 5))
    invalid |= (raw == 0) | ((qa & reject_bits) != 0)
    # Conservative: reject any QA_RADSAT flag; a band-specific policy is possible.
    invalid |= np.ma.getdata(qa_radsat) != 0
    sr = raw.astype("float32") * 0.0000275 - 0.2
    return np.where(invalid | ~np.isfinite(sr), np.nan, sr).astype("float32")
```

This does not filter every aerosol problem. Review `SR_QA_AEROSOL` and the guide's
caveats for the task; do not treat a clear QA_PIXEL flag as scientific certification.

## Apply scale and offset exactly once

Declare one of two states at every boundary: encoded DN with calibration metadata,
or decoded physical reflectance. Apply the source calibration only when crossing
from the first to the second. If a loader already decoded the values, skip manual
decoding. If a provider shifted the original DN, use that provider's encoding.

For a decoded single-band array, save physical values with identity metadata:

```python
import numpy as np
import rasterio

def write_reflectance(path, sr, crs, transform):
    with rasterio.open(
        path, "w", driver="GTiff", width=sr.shape[1], height=sr.shape[0],
        count=1, dtype="float32", crs=crs, transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(sr.astype("float32"), 1)
        dst.scales = (1.0,)
        dst.offsets = (0.0,)
```

Keep original calibration and mask policy in provenance, not active decoding
metadata on already decoded pixels. Reopen a known valid pixel and independently
compute its physical value from original DN; test nodata and dark pixels too.
A plausible range can still result from a missing offset or double scaling.

## Harmonize sensors before comparing them

Common CRS and resolution are necessary but not sufficient. Match band meaning,
spatial grid and effective resolution, atmospheric processing, QA policy, angular
conditions, acquisition season and temporal sampling. Sentinel-2 broad NIR and
narrow NIR are not interchangeable without analysis. Resampling a coarse band to
a finer grid does not create finer information.

Do not invent a universal regression to turn Sentinel-2 into Landsat. For work
requiring consistent multi-sensor time series, consider NASA Harmonized Landsat
Sentinel-2 (HLS), and follow its own band, QA, scaling and processing documentation
[S7]. HLS is a derived product, not original ESA/USGS DN with the same decoding
contract. Validate remaining bias over stable targets for the AOI.

## Build temporal composites from masked observations

Select acquisition dates and season first. Decode and mask each observation,
align required bands to a common grid, and retain acquisition IDs. De-duplicate
overlapping tiles from the same acquisition before counting temporal observations.
Choose a
composite statistic suited to the question: a masked median suppresses some
outliers but is not cloud detection and may combine different acquisition dates
across bands. A medoid/selected-observation composite can retain a real spectral
observation. Document tie-breaking and quality ranking.

Store valid-observation count and acquisition/date support alongside the
composite. All-invalid pixels remain nodata, not zero. Report coverage gaps,
seasonal bias and scenes rejected by QA. An index of a reflectance composite is
not generally the same as a composite of per-date indices.

## Verify with Terraproof

Use an installed Python core and real local outputs/STAC Items:

```bash
python -m terraproof check sr_red.tif sr_nir.tif --expect reflectance --format md --lang en --out sr-report.md
python -m terraproof check scl_aligned.tif --categorical --resampling nearest
python -m terraproof check source-item.json
```

`rs.reflectance_range` checks sampled statistics after raster scale/offset
metadata is applied. It is only a coarse plausibility test, not proof of the
correct processing level or calibration. `raster.nodata_declared` checks nodata
metadata. `raster.grid_alignment` compares CRS/pixel sizes/grid origin for
multiple rasters, not equal extents or actual image co-registration.
`raster.resampling` checks a declared categorical method, not historical usage.
`stac.provenance` checks Item time and a projection code, not full processing
lineage, licenses or calibration metadata. `crs.defined`/`crs.consistent` apply
to raster CRS metadata; `raster.cog_layout` may also run on GeoTIFFs.

Cloud/shadow-mask application, correct SCL/QA decoding, scale/offset applied
exactly once, sensor harmonization, valid-observation support and compositing
correctness are **not checked automatically yet**. Preserve independent pixel
arithmetic and QA tests; see [verification](../verification/SKILL.md).

## Sources

- [S1 — ESA Sentinel-2 products](https://sentiwiki.copernicus.eu/web/s2-products): L2A formula, baseline 04.00, DN 0 nodata, band grids and metadata authority.
- [S2 — ESA L2A Data Quality Report, October 2026](https://sentiwiki.copernicus.eu/__attachments/a_05551f216ff3e0ff859cd12fcc162978f08d70b32eaace391ba2ee5423bdc86b/S2-OMPC.CS.DQR.002.09-2026-i102r0-MSI-L2A-DQR-October-2026.pdf): radiometric offset section specifies -1000 DN for all spectral bands.
- [S3 — ESA Sen2Cor Input Output Data Definition](https://step.esa.int/thirdparties/sen2cor/2.13.0/docs/OMPC.TPZG.IOD.004%20-%20i1r0%20-%20Sen2Cor%202.13.02%20Input%20Output%20Data%20Definition.pdf): PDF page 12 specifies reflectance quantification 10000 and Reflectance = (DN - 1000) / 10000.
- [S4 — ESA Sentinel-2 processing](https://sentiwiki.copernicus.eu/web/s2-processing): scene-classification table 3 (classes 0–11), class-label evolution and algorithm limitations.
- [S5 — USGS Landsat 8–9 Collection 2 Level-2 Science Product Guide](https://www.usgs.gov/media/files/landsat-8-9-collection-2-level-2-science-product-guide): table 6-1 scale 0.0000275, offset -0.2, fill 0; table 6-2 QA_PIXEL bits; QA_RADSAT and aerosol caveats.
- [S6 — USGS Collection 2 QA bands](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands): zero-based QA_PIXEL positions 0–7 and clear-bit meaning for Landsat 8/9.
- [S7 — NASA HLS algorithms](https://hls.gsfc.nasa.gov/algorithms/): atmospheric, geometric, angular and spectral harmonization components.
- [Rasterio masks](https://rasterio.readthedocs.io/en/stable/topics/masks.html) and [rioxarray API](https://vylor.github.io/rioxarray/stable/rioxarray.html): masked reads, scale decoding and writing interfaces.
