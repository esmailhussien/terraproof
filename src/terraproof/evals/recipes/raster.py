"""Fixtures and oracles for the `raster-processing` task specs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from terraproof.evals.fixtures import UTM, read_raster, write_cog, write_raster
from terraproof.evals.oracles import Oracle
from terraproof.evals.recipes._util import check_step, correct, recipe, results_for, wrong

CLASS_CODES = (1, 2, 3, 4)
HALF_PIXEL_REF_ORIGIN = (500005.0, 5000000.0)  # 500005 / 10 = 50000.5: not on the zero-based tap lattice
RESOLUTION = 10.0
SHAPE = (32, 32)


def _categorical_array() -> np.ndarray:
    rows, cols = np.indices(SHAPE)
    values = np.full(SHAPE, 3, dtype="uint8")
    values[rows < 8] = 1
    values[(rows >= 8) & (rows < 16)] = 2
    values[(rows >= 16) & (rows < 24)] = 4
    values[(rows == 5) & (cols > 20)] = 2
    return values


def _warp(source_path: str, dst_transform, shape, resampling, src_nodata=255, dst_nodata=255) -> np.ndarray:
    with rasterio.open(source_path) as src:
        data = src.read(1)
        source_transform, source_crs = src.transform, src.crs
    output = np.full(shape, dst_nodata, dtype="float32")
    reproject(
        source=data,
        destination=output,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=src_nodata,
        dst_transform=dst_transform,
        dst_crs=source_crs,
        dst_nodata=dst_nodata,
        resampling=resampling,
    )
    return output


def raster_categorical_half_pixel(root: Path):
    """Task 1: equal resolution and shape with a half-pixel origin shift, aligned by bilinear."""
    reference = write_raster(
        root / "reference.tif",
        _categorical_array(),
        crs=UTM,
        origin=HALF_PIXEL_REF_ORIGIN,
        resolution=RESOLUTION,
        nodata=255,
        dtype="uint8",
    )
    shifted = write_raster(
        root / "shifted.tif",
        _categorical_array(),
        crs=UTM,
        origin=(HALF_PIXEL_REF_ORIGIN[0] - 0.5 * RESOLUTION, HALF_PIXEL_REF_ORIGIN[1]),
        resolution=RESOLUTION,
        nodata=255,
        dtype="uint8",
    )
    steps = [
        check_step(
            "check reference.tif shifted.tif --categorical --resampling bilinear",
            [reference, shifted],
            categorical=True,
            resampling="bilinear",
        )
    ]
    reference_array = read_raster(reference)
    with rasterio.open(reference) as src:
        destination_transform = src.transform
    bilinear = _warp(shifted, destination_transform, SHAPE, Resampling.bilinear)
    nearest = _warp(shifted, destination_transform, SHAPE, Resampling.nearest)

    oracle = Oracle("categorical alignment: codes must stay in the class set")
    blended = [
        float(value)
        for value in np.unique(bilinear)
        if value != 255 and abs(float(value) - float(round(float(value)))) > 1e-6
    ]
    oracle.require(
        "bilinear alignment invents non-class values",
        len(blended) > 0,
        sorted(round(value, 3) for value in blended[:10]),
        "values outside the integer class set",
    )
    oracle.require(
        "nearest alignment keeps every value in the permitted class set",
        set(np.unique(nearest)).issubset({float(code) for code in CLASS_CODES} | {255.0}),
        sorted(float(value) for value in np.unique(nearest)),
        sorted(float(code) for code in CLASS_CODES),
    )
    oracle.require(
        "the reference origin is not on the zero-based tap lattice",
        abs((HALF_PIXEL_REF_ORIGIN[0] / RESOLUTION) % 1.0) > 0.1,
        round(HALF_PIXEL_REF_ORIGIN[0] / RESOLUTION, 3),
        "fractional pixel offset, so -tap would move the grid",
    )
    oracle.require(
        "nodata stays outside the class set",
        255 not in CLASS_CODES,
        list(CLASS_CODES),
        "255 not a class code",
    )
    grid = results_for(steps, "raster.grid_alignment")
    resampling = results_for(steps, "raster.resampling")
    nodata = results_for(steps, "raster.nodata_declared")
    oracle.require(
        "raster.grid_alignment fails on the half-pixel shift",
        bool(grid) and grid[0].status == "fail",
        grid[0].status if grid else None,
        "fail",
    )
    oracle.require(
        "raster.resampling fails on bilinear for categorical data",
        bool(resampling) and resampling[0].status == "fail",
        resampling[0].status if resampling else None,
        "fail",
    )
    oracle.require(
        "raster.nodata_declared passes on both categorical rasters",
        bool(nodata) and all(result.status == "pass" for result in nodata),
        [result.status for result in nodata],
        "pass",
    )
    correct_control = correct(
        "half-pixel-bilinear-preflight",
        "Two north-up categorical GeoTIFFs with equal resolution and shape but a half-pixel origin "
        "shift, checked with --categorical --resampling bilinear.",
        steps,
        oracle,
    )

    aligned = write_raster(
        root / "reference_bilinear.tif",
        bilinear,
        crs=UTM,
        origin=HALF_PIXEL_REF_ORIGIN,
        resolution=RESOLUTION,
        nodata=255,
        dtype="float32",
    )
    wrong_steps = [
        check_step(
            "check reference.tif reference_bilinear.tif --categorical --resampling nearest",
            [reference, aligned],
            categorical=True,
            resampling="nearest",
        )
    ]
    wrong_oracle = Oracle("a blended categorical output is not a valid aligned class raster")
    wrong_values = read_raster(aligned)
    unique = sorted(float(value) for value in np.unique(wrong_values.compressed()))
    wrong_oracle.require(
        "aligned values stay in the permitted class set",
        set(unique).issubset({float(code) for code in CLASS_CODES} | {255.0}),
        unique,
        sorted(float(code) for code in CLASS_CODES),
    )
    wrong_oracle.require(
        "the class histogram matches the reference",
        _histogram(wrong_values) == _histogram(reference_array),
        _histogram(wrong_values),
        _histogram(reference_array),
    )
    wrong_control = wrong(
        "bilinear-blended-categories",
        "The categorical raster is aligned to the reference grid with bilinear interpolation and the "
        "result is relabelled as an aligned class raster.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "raster-categorical-half-pixel",
        correct_control,
        [wrong_control],
        automated_scope=[
            "raster.grid_alignment, raster.resampling and raster.nodata_declared on the seeded preflight",
            "independent bilinear/nearest alignment showing invented class values and histogram change",
        ],
        remaining=[
            "The answer must explain origin misalignment, category blending and why -tap does not match an arbitrary reference origin; prose is not graded.",
            "Review of the chosen categorical aggregation method on the real class lookup.",
        ],
    )


def _histogram(values) -> dict:
    array = values.compressed() if isinstance(values, np.ma.MaskedArray) else np.asarray(values)
    counts = np.unique(np.rint(array).astype("int64"), return_counts=True)
    return {int(code): int(count) for code, count in zip(*counts)}


def raster_nodata_dtype_windowing(root: Path):
    """Task 2: unsigned subtraction without overflow, with both masks intersected."""
    rows, cols = np.indices((16, 16))
    first = (300 + rows * 2 + cols).astype("uint16")
    second = (400 + rows + cols * 2).astype("uint16")
    second[10, 10] = first[10, 10]  # a legitimate zero difference
    first[3, 3] = 65535
    second[3, 3] = 400
    second[7, 7] = 65535
    first_path = write_raster(root / "first_u16.tif", first, crs=UTM, nodata=65535, dtype="uint16")
    second_path = write_raster(root / "second_u16.tif", second, crs=UTM, nodata=65535, dtype="uint16")
    valid = (first != 65535) & (second != 65535)
    expected = first.astype("int64") - second.astype("int64")
    difference = np.full((16, 16), -9999.0, dtype="float32")
    difference[valid] = expected[valid]
    difference_path = write_raster(root / "difference.tif", difference, crs=UTM, nodata=-9999.0, dtype="float32")

    steps = [check_step("check difference.tif", [difference_path])]
    oracle = Oracle("float difference: negative values, valid zeros and the intersected mask")
    oracle.equal("output dtype is floating point", read_raster(difference_path).dtype.kind, "f")
    oracle.equal("valid pixels equal the intersection of both input masks", int(np.count_nonzero(valid)), 254)
    oracle.close("minimum difference", float(np.min(expected[valid])), float(np.min(expected[valid])), 0.0)
    oracle.require(
        "negative differences are preserved",
        float(np.min(expected[valid])) < 0,
        float(np.min(expected[valid])),
        "< 0",
    )
    oracle.close("the legitimate zero difference stays valid", float(difference[10, 10]), 0.0, 1e-9)
    oracle.equal("input nodata is nodata in the output", float(np.ma.getdata(read_raster(difference_path))[3, 3]), -9999.0)
    oracle.close(
        "control pixel difference",
        float(difference[1, 1]),
        float(expected[1, 1]),
        1e-9,
    )
    windows = [(row, col) for row in (0, 8) for col in (0, 8)]
    covered = {
        (row + offset_row, col + offset_col)
        for row, col in windows
        for offset_row in range(8)
        for offset_col in range(8)
    }
    oracle.equal("four 8x8 windows tile the 16x16 array without overlap", len(covered), 16 * 16)
    crs = results_for(steps, "crs.defined")
    nodata = results_for(steps, "raster.nodata_declared")
    oracle.require(
        "crs.defined passes on the difference",
        bool(crs) and crs[0].status == "pass",
        crs[0].status if crs else None,
        "pass",
    )
    oracle.require(
        "raster.nodata_declared passes on the difference",
        bool(nodata) and nodata[0].status == "pass",
        nodata[0].status if nodata else None,
        "pass",
    )
    correct_control = correct(
        "float-difference-windowed",
        "Aligned unsigned rasters with nodata, legitimate zeros and negative differences; the "
        "difference is computed in float with both masks intersected.",
        steps,
        oracle,
    )

    wrapped = (first.astype("uint16") - second.astype("uint16")).astype("uint16")
    wrapped_path = write_raster(root / "difference_wrapped_u16.tif", wrapped, crs=UTM, nodata=65535, dtype="uint16")
    wrong_steps = [check_step("check difference_wrapped_u16.tif", [wrapped_path])]
    wrong_oracle = Oracle("unsigned wraparound must not be accepted as a difference")
    wrong_oracle.require(
        "negative differences survive as negative values in a floating output",
        bool(np.any(np.ma.getdata(read_raster(wrapped_path)) < 0)),
        "no negative values",
        "negative differences preserved",
    )
    wrong_oracle.close(
        "minimum difference",
        float(np.ma.getdata(read_raster(wrapped_path))[valid].min()),
        float(np.min(difference[valid])),
        1e-9,
    )
    wrong_control = wrong(
        "unsigned-wraparound",
        "The subtraction is done in uint16, so negative differences wrap to large positive values; the "
        "output still declares nodata and passes the raster checks.",
        wrong_steps,
        wrong_oracle,
        notes="The raster checks cannot see numeric wraparound, so only the oracle rejects this output.",
    )
    return recipe(
        "raster-nodata-dtype-windowing",
        correct_control,
        [wrong_control],
        automated_scope=[
            "crs.defined and raster.nodata_declared on the difference output",
            "independent expected-difference sample, finite extrema, intersected mask and window tiling",
        ],
        remaining=[
            "The answer must explain why the check cannot prove overflow avoidance, mask correctness or bounded memory; prose is not graded.",
            "Memory-budget conformance on the full dataset needs a production run, not a 16x16 fixture.",
        ],
    )


def raster_cog_delivery(root: Path):
    """Task 3: a lossless COG delivery of a continuous analysis raster."""
    rows, cols = np.indices((256, 256))
    source_values = (40 + (rows // 8 + cols // 8) % 90).astype("uint8")
    source_values = np.where((rows > 250) & (cols > 250), 0, source_values).astype("uint8")
    analysis = write_raster(
        root / "analysis.tif",
        source_values,
        crs=UTM,
        nodata=0,
        dtype="uint8",
        tiled=True,
        overviews=(2, 4),
    )
    delivery = write_cog(root / "delivery.tif", source_values, crs=UTM, nodata=0)
    steps = [check_step("check delivery.tif", [delivery])]
    oracle = Oracle("COG delivery: layout plus pixel identity with the analysis raster")
    delivered = read_raster(delivery)
    original = read_raster(analysis)
    oracle.equal("full-resolution pixel arrays are identical (lossless)", bool(np.array_equal(np.ma.getdata(delivered), np.ma.getdata(original))), True)
    oracle.equal("valid-pixel masks are identical", bool(np.array_equal(np.ma.getmaskarray(delivered), np.ma.getmaskarray(original))), True)
    with rasterio.open(delivery) as src, rasterio.open(analysis) as source:
        block_width, block_height = src.block_shapes[0]
        overviews = src.overviews(1)
        compression = str(src.compression).lower()
        delivered_shape = (src.height, src.width)
        delivered_dtype = src.dtypes[0]
        nodata = src.nodata
        same_crs = src.crs.to_string() == source.crs.to_string()
        same_transform = tuple(src.transform) == tuple(source.transform)
    oracle.require("the delivery is tiled", block_width > 1 and block_height > 1, [block_width, block_height], "block sizes > 1")
    oracle.require("the delivery has internal overviews", len(overviews) > 0, overviews, "non-empty overview list")
    oracle.require(
        "compression is lossless",
        any(name in compression for name in ("deflate", "lzw", "zstd", "lerc")),
        compression,
        "a lossless codec",
    )
    oracle.equal("dimensions match the analysis raster", delivered_shape, (256, 256))
    oracle.equal("dtype matches the analysis raster", delivered_dtype, "uint8")
    oracle.equal("nodata is declared", nodata, 0.0)
    oracle.equal("CRS matches the analysis raster", same_crs, True)
    oracle.equal("transform matches the analysis raster", same_transform, True)
    for check_id, expected in (
        ("raster.cog_layout", "pass"),
        ("raster.nodata_declared", "pass"),
        ("crs.defined", "pass"),
    ):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} passes on the delivered COG",
            bool(observed) and all(result.status == expected for result in observed),
            [result.status for result in observed],
            expected,
        )
    correct_control = correct(
        "lossless-cog-delivery",
        "A 256x256 continuous raster delivered as a deflate-compressed COG with overviews and declared nodata.",
        steps,
        oracle,
    )

    lossy = write_cog(root / "delivery_lossy.tif", source_values, crs=UTM, nodata=0, compress="JPEG", blocksize=128)
    wrong_steps = [check_step("check delivery_lossy.tif", [lossy])]
    wrong_oracle = Oracle("a lossy COG changes the analysis values")
    lossy_values = read_raster(lossy)
    changed = int(np.count_nonzero(np.ma.getdata(lossy_values) != np.ma.getdata(original)))
    wrong_oracle.equal("full-resolution pixel arrays are identical (lossless)", changed == 0, True)
    wrong_oracle.close(
        "maximum absolute pixel change",
        float(np.max(np.abs(lossy_values.astype("float64") - original.astype("float64")))),
        0.0,
        1e-9,
    )
    wrong_control = wrong(
        "lossy-jpeg-cog",
        "A COG with the same layout and nodata is written with lossy JPEG compression that changes the "
        "analysis values.",
        wrong_steps,
        wrong_oracle,
        notes="raster.cog_layout passes; it cannot see lossy compression.",
    )

    striped = write_raster(
        root / "delivery_striped.tif",
        source_values,
        crs=UTM,
        nodata=0,
        dtype="uint8",
        tiled=False,
        overviews=None,
    )
    striped_steps = [check_step("check delivery_striped.tif", [striped])]
    striped_oracle = Oracle("a striped GeoTIFF without overviews is not a COG delivery")
    with rasterio.open(striped) as src:
        block_width, block_height = src.block_shapes[0]
        overviews = src.overviews(1)
    striped_oracle.require("the delivery is tiled", block_width > 1 and block_height > 1, [block_width, block_height], "block sizes > 1")
    striped_oracle.require("the delivery has internal overviews", len(overviews) > 0, overviews, "non-empty overview list")
    wrong_controls = [
        wrong_control,
        wrong(
            "striped-no-overviews",
            "A striped GeoTIFF with no overviews; the heuristic layout screen warns, and the oracle also "
            "rejects it.",
            striped_steps,
            striped_oracle,
        ),
    ]
    return recipe(
        "raster-cog-delivery",
        correct_control,
        wrong_controls,
        automated_scope=[
            "raster.cog_layout, raster.nodata_declared and crs.defined on the delivered COG",
            "independent pixel/mask identity, tiling, overview presence and lossless-compression checks",
        ],
        remaining=[
            "A full COG validator and a range-request read over HTTP are external tools not available offline; the answer must inspect validator warnings.",
            "Review that regenerated overviews suit continuous data rather than inheriting unsuitable source overviews.",
        ],
    )


RECIPES = {
    "raster-categorical-half-pixel": raster_categorical_half_pixel,
    "raster-nodata-dtype-windowing": raster_nodata_dtype_windowing,
    "raster-cog-delivery": raster_cog_delivery,
}
