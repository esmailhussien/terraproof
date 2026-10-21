---
name: raster-processing
description: Read, transform, align, resample, and write rasters with explicit masks, dtypes, grids, and delivery validation; use for rasterio, rioxarray, or GDAL workflows involving nodata, large datasets, reprojection, categorical data, or Cloud Optimized GeoTIFF output.
---

# Raster processing

## Inspect the storage and analysis contract

Identify CRS, affine transform, dimensions, band meanings, dtype, nodata/masks,
scale/offset, block layout, and overviews before selecting an operation. A file
extension or band position does not establish scientific meaning.

```python
import rasterio

with rasterio.open("input.tif") as src:
    print(src.crs, src.transform, src.shape, src.count)
    print(src.dtypes, src.nodatavals, src.scales, src.offsets)
    print(src.descriptions, src.block_shapes, src.mask_flag_enums)
```

Rasterio band indices are one-based [S1]. `read()` returns stored values; do not
assume it applied scale/offset metadata. Choose raw or physical values explicitly.
For satellite calibration use [satellite preprocessing](../satellite-preprocessing/SKILL.md).
For general commands use [GDAL](../gdal/SKILL.md), not another full recipe catalog.
Shared rules: [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Distinguish nodata values, masks, and valid zero

Nodata means missing/invalid, not numerically zero. A valid zero can represent
no rainfall, sea-level elevation, or an index value. Inspect per-band masks,
alpha/internal masks, and nodata metadata; a mask can override nodata-derived
validity. Multi-band calculations normally require the intersection of validity
across required bands, not the union.

GDAL-style masks use zero for invalid and nonzero (usually 255) for valid pixels;
NumPy masked-array masks use `True` for invalid pixels [S2]. Do not invert twice.

```python
import numpy as np
import rasterio

with rasterio.open("input.tif") as src:
    band = src.read(1, masked=True).astype("float32")
    values = band.filled(np.nan)
    valid = ~np.ma.getmaskarray(band) & np.isfinite(values)
```

When writing, use a representable sentinel outside the valid domain, an explicit
mask, or floating NaN with declared nodata as appropriate for downstream readers.
Changing the nodata label does not replace existing pixels. Reopen and compare
valid-pixel counts and the spatial mask, not just the metadata. Never fill missing
pixels with zero merely to simplify arithmetic.

## Avoid dtype overflow and stale scale metadata

Cast integer operands to a sufficient signed/float type **before** subtraction,
multiplication, division, or calibration. Unsigned subtraction can wrap; integer
output can truncate continuous results. Check finite extrema before conversion
with `numpy.iinfo`/`numpy.finfo`; decide rounding and nodata representability.
Compression is not a substitute for preserving numeric precision.

When physical values have been materialized, write identity scale/offset metadata
rather than retaining the original calibration. If values remain encoded, keep
and test the encoding on a round trip. Build an output profile intentionally:
a copied profile can preserve inappropriate dtype, band count, dimensions, nodata,
photometric settings, or blocks after an operation.

## Match a complete grid, not just resolution

A pixelwise calculation requires matching CRS, transform, width and height, and
compatible pixel interpretation. Equal resolution alone does not rule out a
half-pixel shift. A grid-lattice match with different extents is not an array-shape
match; explicitly choose intersection, union, or a reference raster's extent.

For north-up rasters, GDAL `-tap` aligns extent boundaries to multiples of `-tr`
in target CRS units [S3]. It does **not** guarantee alignment to an arbitrary
reference raster with a different origin. For exact reference matching, use the
reference CRS, transform and shape rather than independently calculating a new
grid for every band. This small continuous-data example handles one band:

```python
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

with rasterio.open("reference.tif") as ref, rasterio.open("source.tif") as src:
    if ref.crs is None or src.crs is None:
        raise ValueError("Both grids need known CRSs")
    source = src.read(1, masked=True).astype("float32").filled(np.nan)
    target = np.full(ref.shape, np.nan, dtype="float32")
    reproject(
        source=source, destination=target,
        src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
        dst_transform=ref.transform, dst_crs=ref.crs, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    with rasterio.open(
        "aligned.tif", "w", driver="GTiff", count=1, dtype="float32",
        width=ref.width, height=ref.height, transform=ref.transform,
        crs=ref.crs, nodata=np.nan,
    ) as dst:
        dst.write(target, 1)
```

This uses stored source values and is an in-memory example, not a calibration or
large-scene recipe. For rotated grids, compare all affine coefficients yourself;
the current Terraproof alignment check is not a full rotated-grid validator.

## Select resampling from the data meaning

| Data | Suitable starting choice | What to verify |
|---|---|---|
| Categorical classes, SCL, bit-packed QA | Nearest; mode for majority-class aggregation | Codes stay in the permitted set; mode must not be used to decode/recombine QA bits |
| Continuous reflectance/elevation | Bilinear or cubic for interpolation | Cubic may overshoot; inspect range and nodata-edge behavior |
| Continuous data aggregated to coarser cells | Average when a weighted mean is appropriate | A mean is not a conserved sum or a new independent observation |

GDAL warp uses `-r near`; Rasterio and Terraproof call it `nearest` [S3, S4].
Mode selects a modal value; it does not preserve minority classes or class area.
Use the same semantic choice for overviews as for the main product. Never blend
land-cover codes with bilinear/cubic/average. QA flags are bit fields, not
continuous values. Reprojection and aggregation are scientific choices, not
just file-format changes.

## Process windows or lazy chunks

Rasterio reads whole underlying blocks even for small windows [S5]. Iterate
`src.block_windows(1)` and write each result to the same output window when grids
match. For a cropped output, update its transform with `src.window_transform()`.
Ensure the array shape equals the write-window shape to avoid unintended
resampling/decimation. Neighborhood filters need halos around chunks.

For a labelled, chunked array with rioxarray and Dask installed [S6]:

```python
import rioxarray

with rioxarray.open_rasterio(
    "input.tif", chunks="auto", mask_and_scale=True
) as data:
    subset = data.isel(band=slice(0, 1))
    subset.rio.to_raster("subset.tif", driver="GTiff", windowed=True)
```

`mask_and_scale=True` decodes **available raster metadata**, not an arbitrary
sidecar calibration that the driver did not expose. Do not apply those same
scale/offset values again. Chunked reads do not guarantee a lazy reprojection or
bounded-memory write: rioxarray documents that `windowed` has no effect with
Dask. Test the execution path and memory use; use windowed rasterio/GDAL warping
when a full-scene operation would otherwise materialize the array.

## Create and validate a COG with overviews

Finish analysis first, then create a COG as a delivery step. Choose lossless
compression for scientific values. Regenerate overviews if existing ones have
unknown or incorrect resampling [S7]. For a continuous raster:

```bash
gdal_translate -of COG -co COMPRESS=DEFLATE -co OVERVIEWS=IGNORE_EXISTING -co RESAMPLING=AVERAGE analysis.tif delivery.tif
gdalinfo delivery.tif
```

For categorical rasters change `RESAMPLING=AVERAGE` to `RESAMPLING=NEAREST`.
The COG driver generates appropriate overview levels; very small rasters may not
need any. Inspect overview presence and values for your delivery contract. For large
compressed COG output, plan `BIGTIFF` and temporary disk capacity before running:
set the BIGTIFF option explicitly where the output may exceed classic TIFF limits,
and confirm free space for both the output and intermediate files.
Do not add overviews or edit pixels in-place after COG creation; regenerate the
COG, since updates can break optimized byte ordering.

A complete layout validation is separate from `gdalinfo`. With GDAL 3.13 or newer
and its Python bindings available [S8]:

```bash
gdal driver cog validate --full-check yes delivery.tif
```

For earlier environments use the COG validation workflow in
[GDAL](../gdal/SKILL.md#workflow). Read validator warnings as well as exit status.
Reopen and compare CRS, transform, mask, dtype and representative pixel values
against the analysis output; layout validity alone proves no scientific result.

## Verify with Terraproof

Use an installed Python core and actual local paths:

```bash
python -m terraproof check classes.tif --categorical --resampling nearest
python -m terraproof check reference.tif aligned.tif --format md --lang en --out alignment-report.md
python -m terraproof check delivery.tif
```

`raster.nodata_declared` warns when a band lacks a nodata value, including cases
where a valid mask-only product may be intentional. `raster.resampling` checks
only the method you declared with `--categorical --resampling`; it does not
recover the processing history. `raster.grid_alignment` compares CRS, pixel
sizes and grid origins for multiple positional rasters, **not** equal dimensions,
extents, full affine rotation, or successful co-registration.

`raster.cog_layout` is only a tiling-plus-overviews heuristic on GeoTIFFs, not
full COG byte-layout validation. It warns on striped layout, and on missing overviews
only when the raster is larger than one block; a small tiled raster without
overviews passes.
`crs.defined` and `crs.consistent` cover CRS metadata. Mask correctness, dtype
overflow, conservation of quantities, overview resampling history, and peak
memory use are **not checked automatically yet**. See
[verification](../verification/SKILL.md).

## Sources

- [S1 — Rasterio reading](https://rasterio.readthedocs.io/en/stable/topics/reading.html): one-based band access; [GDAL raster data model](https://gdal.org/en/stable/user/raster_data_model.html): stored values, scale and offset.
- [S2 — Rasterio masks](https://rasterio.readthedocs.io/en/stable/topics/masks.html): zero/nonzero GDAL mask convention, typical 255 valid value, inverse NumPy masks and mask precedence.
- [S3 — GDAL gdalwarp](https://gdal.org/en/stable/programs/gdalwarp.html): target-aligned pixels, resolution, resampling and nodata behavior.
- [S4 — Rasterio resampling](https://rasterio.readthedocs.io/en/stable/topics/resampling.html): continuous-data interpolation and average resampling.
- [S5 — Rasterio windowed I/O](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html): block iteration, window transforms and implicit decimation.
- [S6 — rioxarray API](https://vylor.github.io/rioxarray/stable/rioxarray.html): chunks, mask_and_scale, rio.to_raster and Dask/windowed limitation.
- [S7 — GDAL COG driver](https://gdal.org/en/stable/drivers/raster/cog.html): overview generation, resampling options and update/layout limitations.
- [S8 — GDAL COG validator](https://gdal.org/en/stable/programs/gdal_driver_cog_validate.html): GDAL 3.13 introduction, Python-binding requirement and full-check option.
