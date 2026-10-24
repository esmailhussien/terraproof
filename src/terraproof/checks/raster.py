"""Raster checks: raster.nodata_declared, raster.resampling, raster.grid_alignment, raster.cog_layout."""

from __future__ import annotations

from pyproj import CRS

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result

# Grid origin and pixel size must agree within this fraction of one pixel.
GRID_TOLERANCE = 1e-6
SAFE_CATEGORICAL_METHODS = frozenset({"nearest", "mode"})


def check_nodata(dataset: dict) -> list:
    path = dataset["path"]
    missing = [band["index"] for band in dataset["bands"] if band["nodata"] is None]
    if missing:
        return [
            result(
                "raster.nodata_declared",
                WARN,
                f"No nodata value declared for band(s) {missing} of {path}.",
                input=path,
                bands_without_nodata=missing,
            )
        ]
    return [
        result(
            "raster.nodata_declared",
            PASS,
            f"Nodata declared for all {len(dataset['bands'])} bands of {path}.",
            input=path,
        )
    ]


def check_cog_layout(dataset: dict) -> list:
    """Heuristic layout screen for GeoTIFFs: tiling, internal overviews when needed, and lossy JPEG compression.

    Overviews are expected only when the raster is larger than one block in some dimension
    (in any band); a raster that fits in one block gets none from GDAL and is not warned about.
    JPEG in a GeoTIFF is always lossy, so it changes stored pixel values; it suits visual
    products, not analysis values. Lossy LERC or WebP settings are not detected.
    This is not Cloud Optimized GeoTIFF validation.
    """
    if dataset["driver"] != "GTiff":
        return []
    path = dataset["path"]
    tiled = dataset["tiled"]
    overview_counts = [band["overview_count"] for band in dataset["bands"]]
    has_overviews = all(count > 0 for count in overview_counts)
    one_block = all(
        dataset["width"] <= band["block_size"]["width"] and dataset["height"] <= band["block_size"]["height"]
        for band in dataset["bands"]
    )
    evidence = {
        "input": path,
        "tiled": tiled,
        "overview_counts": overview_counts,
        "fits_one_block": one_block,
        "block_sizes": [band["block_size"] for band in dataset["bands"]],
        "compression": dataset.get("compression"),
    }
    problems = []
    if not tiled:
        problems.append("not tiled (striped layout)")
    if not one_block and not has_overviews:
        problems.append("no internal overviews")
    if (dataset.get("compression") or "").lower() == "jpeg":
        problems.append("lossy JPEG compression changes pixel values (acceptable for visual products, not analysis values)")
    if problems:
        return [
            result(
                "raster.cog_layout",
                WARN,
                f"{path} layout: {'; '.join(problems)}. This is a heuristic layout screen, not Cloud Optimized "
                "GeoTIFF validation; full conformance needs a COG validator.",
                **evidence,
            )
        ]
    if one_block and not has_overviews:
        message = (
            f"{path} is tiled and fits in one block, so no internal overviews are expected. "
            "Layout screen only; not Cloud Optimized GeoTIFF validation."
        )
    else:
        message = f"{path} is tiled and has internal overviews. Layout screen only; not Cloud Optimized GeoTIFF validation."
    return [result("raster.cog_layout", PASS, message, **evidence)]


def _same_crs(first: dict, second: dict) -> bool:
    if first["crs"] is None or second["crs"] is None:
        return first["crs"] is None and second["crs"] is None
    return CRS.from_user_input(first["crs"]["wkt"]).equals(CRS.from_user_input(second["crs"]["wkt"]))


def check_grid_alignment(rasters: list[dict]) -> list:
    """Compare every raster with the first one: CRS, pixel size, and pixel-grid origin."""
    reference = rasters[0]
    ref_transform = reference["transform"]
    pixel_x, pixel_y = ref_transform[0], ref_transform[4]
    tolerance_x = GRID_TOLERANCE * abs(pixel_x)
    tolerance_y = GRID_TOLERANCE * abs(pixel_y)
    inputs = [r["path"] for r in rasters]

    problems = []
    for other in rasters[1:]:
        other_transform = other["transform"]
        if not _same_crs(reference, other):
            problems.append(f"CRS of {other['path']} differs from {reference['path']}")
        if abs(other_transform[0] - pixel_x) > tolerance_x or abs(other_transform[4] - pixel_y) > tolerance_y:
            problems.append(f"pixel size of {other['path']} differs from {reference['path']}")
        offset_x = (other_transform[2] - ref_transform[2]) / pixel_x
        offset_y = (other_transform[5] - ref_transform[5]) / pixel_y
        if abs(offset_x - round(offset_x)) > GRID_TOLERANCE or abs(offset_y - round(offset_y)) > GRID_TOLERANCE:
            problems.append(f"pixel-grid origin of {other['path']} is offset from {reference['path']}")

    if problems:
        return [
            result(
                "raster.grid_alignment",
                FAIL,
                "Raster grids are not aligned: " + "; ".join(problems) + ".",
                inputs=inputs,
                problems=problems,
            )
        ]
    return [
        result(
            "raster.grid_alignment",
            PASS,
            f"All {len(rasters)} rasters share CRS, pixel size, and pixel-grid origin.",
            inputs=inputs,
            problems=[],
        )
    ]


def check_resampling(rasters: list[dict], method: str) -> list:
    """Categorical rasters need nearest or mode resampling so category codes are not blended."""
    if not rasters:
        return [
            result(
                "raster.resampling",
                NOT_RUN,
                f"Resampling '{method}' declared for categorical data, but no raster input was given.",
                method=method,
            )
        ]
    inputs = [r["path"] for r in rasters]
    if method.lower() in SAFE_CATEGORICAL_METHODS:
        return [
            result(
                "raster.resampling",
                PASS,
                f"Resampling '{method}' is suitable for categorical rasters.",
                method=method,
                categorical=True,
                inputs=inputs,
            )
        ]
    return [
        result(
            "raster.resampling",
            FAIL,
            f"Resampling '{method}' blends category codes. Use 'nearest' or 'mode' for categorical rasters.",
            method=method,
            categorical=True,
            inputs=inputs,
        )
    ]
