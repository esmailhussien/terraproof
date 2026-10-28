"""Terrain derivative check: terrain.slope_consistent.

A slope raster is compared with a central-difference slope recomputed from the DEM it was
derived from, using the DEM's declared vertical unit and its real (possibly non-square)
pixel spacing. The check fails only when the delivered slope instead matches a named
mistake: vertical units ignored, or square pixels assumed. A slope that matches neither
(another stencil such as Horn's, a different edge policy) is a warning, not a failure.

A DEM in a geographic CRS is supported when its vertical unit is declared: each row's pixel
spacing is converted from degrees to metres on the CRS ellipsoid at that row's latitude. Its named
mistakes are degrees used as lengths and longitude spacing not scaled by latitude.

Nothing here checks the slope's nodata mask or edge policy beyond the cells compared.
"""

from __future__ import annotations

import numpy as np
import rasterio

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "terrain.slope_consistent"

# Metres per declared vertical unit. An empty unit is assumed to match the horizontal unit.
VERTICAL_UNITS = {
    "m": 1.0, "metre": 1.0, "meter": 1.0, "metres": 1.0, "meters": 1.0,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "international foot": 0.3048,
    "us-ft": 1200 / 3937, "ftus": 1200 / 3937, "us survey foot": 1200 / 3937,
}

# A compared cell agrees with a hypothesis when |delivered - expected| <= RTOL * expected + ATOL
# (degrees). Wide enough for float32 storage, narrow enough that a 0.3048 vertical factor or a
# 2:1 pixel aspect falls well outside it on any sloping cell.
RTOL = 1e-3
ATOL = 0.01
MIN_MATCH_FRACTION = 0.95
# Cells flatter than this are skipped: every hypothesis predicts about zero there.
MIN_SLOPE_DEGREES = 0.5


def _slope_degrees(z: np.ndarray, valid: np.ndarray, factor: float, dx, dy):
    """Central-difference slope at interior cells whose centre and four direct neighbours are valid.

    dx and dy are one spacing, or one spacing per row (a geographic grid)."""
    values = z * factor
    dx = np.broadcast_to(np.reshape(np.asarray(dx, float), (-1, 1)), (z.shape[0], 1))[1:-1]
    dy = np.broadcast_to(np.reshape(np.asarray(dy, float), (-1, 1)), (z.shape[0], 1))[1:-1]
    gx = (values[1:-1, 2:] - values[1:-1, :-2]) / (2 * dx)
    gy = (values[2:, 1:-1] - values[:-2, 1:-1]) / (2 * dy)
    out = np.full(z.shape, np.nan)
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(gx, gy)))
    support = np.zeros(z.shape, bool)
    support[1:-1, 1:-1] = (valid[1:-1, 1:-1] & valid[:-2, 1:-1] & valid[2:, 1:-1]
                           & valid[1:-1, :-2] & valid[1:-1, 2:])
    return out, support


def _fraction(observed: np.ndarray, expected: np.ndarray) -> float:
    return float(np.count_nonzero(np.abs(observed - expected) <= RTOL * np.abs(expected) + ATOL) / observed.size)


def _geographic_spacing(crs, transform, rows: int):
    """Metres per pixel along x and y for each row centre, on the CRS ellipsoid."""
    from pyproj import CRS
    datum = CRS.from_user_input(crs.to_wkt()).ellipsoid
    a, inverse = datum.semi_major_metre, datum.inverse_flattening
    e2 = 0.0 if not inverse else (2 - 1 / inverse) / inverse
    latitude = np.radians(transform[5] + (np.arange(rows) + 0.5) * transform[4])
    w = 1 - e2 * np.sin(latitude) ** 2
    meridional = a * (1 - e2) / w ** 1.5
    normal = a / np.sqrt(w)
    return (abs(transform[0]) * np.radians(1.0) * normal * np.cos(latitude),
            abs(transform[4]) * np.radians(1.0) * meridional)


def check_slope_consistent(output: dict, dem: dict) -> list:
    """Compare a slope-in-degrees raster with the slope its DEM's units and spacing imply."""
    evidence = {"output": output.get("path"), "dem": dem.get("path")}
    if dem.get("kind") != "raster" or output.get("kind") != "raster":
        return [result(CHECK_ID, NOT_RUN, "Slope consistency needs a raster output and a raster DEM.", **evidence)]
    problems = _grid_problems(dem, output)
    if problems:
        return [result(CHECK_ID, NOT_RUN,
                       f"Output {output['path']} and DEM {dem['path']} are not on the same grid "
                       f"({'; '.join(problems)}), so no cell-wise comparison is possible.",
                       problems=problems, **evidence)]
    try:
        with rasterio.open(dem["path"]) as src:
            crs = src.crs
            unit = (src.units[0] or "").strip()
            z = src.read(1, masked=True)
        with rasterio.open(output["path"]) as dst:
            slope = dst.read(1, masked=True)
    except rasterio.errors.RasterioIOError as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot read pixel values: {error}", **evidence)]
    if crs is None or not (crs.is_projected or crs.is_geographic):
        return [result(CHECK_ID, NOT_RUN,
                       f"DEM {dem['path']} has no projected or geographic CRS; its pixel spacing is not a length.",
                       **evidence)]
    if unit and unit.lower() not in VERTICAL_UNITS:
        return [result(CHECK_ID, NOT_RUN, f"DEM vertical unit '{unit}' is not a known length unit.",
                       vertical_unit=unit, **evidence)]
    geographic = not crs.is_projected
    if geographic and not unit:
        return [result(CHECK_ID, NOT_RUN, f"DEM {dem['path']} is geographic and declares no vertical unit, so "
                       "heights cannot be related to metres on the ground.", **evidence)]
    if geographic:
        factor = VERTICAL_UNITS[unit.lower()]  # DEM values -> metres
        dx, dy = _geographic_spacing(crs, dem["transform"], z.shape[0])
        evidence.update(vertical_unit=unit, vertical_factor=factor, geographic=True,
                        pixel_size_degrees=[abs(dem["transform"][0]), abs(dem["transform"][4])],
                        pixel_size_metres_range={"x": [float(dx.min()), float(dx.max())],
                                                 "y": [float(dy.min()), float(dy.max())]},
                        tolerance={"rtol": RTOL, "atol_degrees": ATOL}, min_match_fraction=MIN_MATCH_FRACTION)
    else:
        horizontal = crs.linear_units_factor[1]
        vertical = VERTICAL_UNITS[unit.lower()] if unit else horizontal
        factor = vertical / horizontal  # DEM values -> horizontal CRS units
        dx, dy = abs(dem["transform"][0]), abs(dem["transform"][4])
        evidence.update(vertical_unit=unit or None, vertical_factor=factor, pixel_size=[dx, dy],
                        tolerance={"rtol": RTOL, "atol_degrees": ATOL}, min_match_fraction=MIN_MATCH_FRACTION)

    values = np.ma.getdata(z).astype(np.float64)
    valid = ~np.ma.getmaskarray(z) & np.isfinite(values)
    delivered = np.ma.getdata(slope).astype(np.float64)
    delivered_valid = ~np.ma.getmaskarray(slope) & np.isfinite(delivered)
    expected, support = _slope_degrees(values, valid, factor, dx, dy)
    keep = support & delivered_valid & (expected >= MIN_SLOPE_DEGREES)
    compared = int(np.count_nonzero(keep))
    evidence["compared_cells"] = compared
    if compared == 0:
        return [result(CHECK_ID, NOT_RUN,
                       "No sloping cell has a full central-difference stencil in the DEM and a valid "
                       "delivered value, so nothing could be compared.", **evidence)]

    observed = delivered[keep]
    declared = _fraction(observed, expected[keep])
    evidence["declared_match_fraction"] = declared
    if declared >= MIN_MATCH_FRACTION:
        spacing = "ellipsoidal pixel spacing" if geographic else f"{dx:g} x {dy:g} pixel spacing"
        return [result(CHECK_ID, PASS,
                       f"Slope in {output['path']} matches central differences on {dem['path']} with its "
                       f"declared vertical unit and {spacing}.", **evidence)]

    mistakes = {}
    if geographic:
        degrees_x, degrees_y = abs(dem["transform"][0]), abs(dem["transform"][4])
        mistakes["degrees used as lengths"] = (factor, degrees_x, degrees_y)
        mistakes["longitude spacing not scaled by latitude"] = (factor, dy * degrees_x / degrees_y, dy)
    elif not np.isclose(factor, 1.0):
        mistakes["vertical units ignored"] = (1.0, dx, dy)
    if not geographic and not np.isclose(dx, dy):
        mistakes["square pixels assumed (x spacing)"] = (factor, dx, dx)
        mistakes["square pixels assumed (y spacing)"] = (factor, dy, dy)
    matches = {}
    for name, (f, sx, sy) in mistakes.items():
        alternative, _ = _slope_degrees(values, valid, f, sx, sy)
        matches[name] = _fraction(observed, alternative[keep])
    evidence["mistake_match_fractions"] = matches
    found = [name for name, fraction in matches.items() if fraction >= MIN_MATCH_FRACTION]
    if found:
        return [result(CHECK_ID, FAIL,
                       f"Slope in {output['path']} matches the DEM with {found[0]}, not its declared "
                       f"vertical unit ({unit or 'none'}) and its real pixel spacing.", **evidence)]
    return [result(CHECK_ID, WARN,
                   f"Slope in {output['path']} matches central differences on {dem['path']} at only "
                   f"{declared:.0%} of compared cells and no known unit or spacing mistake; another "
                   "stencil (e.g. Horn) or units other than degrees may explain it.", **evidence)]
