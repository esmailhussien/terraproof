"""Terrain derivative check: terrain.slope_consistent.

A slope raster is compared with a central-difference slope recomputed from the DEM it was
derived from, using the DEM's declared vertical unit and its real (possibly non-square)
pixel spacing. The check fails only when the delivered slope instead matches a named
mistake: vertical units ignored, or square pixels assumed. A slope that matches neither
(another stencil such as Horn's, a different edge policy) is a warning, not a failure.

A DEM in a geographic CRS is supported when its vertical unit is declared: each row's pixel
spacing is converted from degrees to metres on the CRS ellipsoid at that row's latitude. Its named
mistakes are degrees used as lengths and longitude spacing not scaled by latitude.

A slope delivered on another grid (another CRS, resolution or origin) is compared after resampling
(`comparison: resampled`). The reference is made each common way: slope then warp, or warp then slope;
nearest, bilinear, cubic or average resampling; central differences or Horn; warped in the delivered
unit. It passes only when one way reproduces it cell by cell, and fails when one way reproduces a named
mistake instead. Otherwise the area-mean gradient decides only gross mistakes: it fails when the declared
reading lies outside the envelope any correct resampling stays inside, and a mistake lies within it with
the DEM's pattern (correlation). The rest warns.

Nothing here checks the slope's nodata mask or edge policy beyond the cells compared.
"""

from __future__ import annotations

import math

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result
from terraproof.checks.rs_processing import _grid_problems

CHECK_ID = "terrain.slope_consistent"
SLOPE_UNITS = (None, "degrees", "percent")

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
# Geographic DEMs: spacing from the WGS84 ellipsoid, a mean-radius sphere or 111 320 m per degree differs
# by at most 0.674% from 0 to 88 degrees (Phase 9), so 1% accepts any of them. The mistakes differ by far
# more: longitude not scaled by latitude is 13% at 28 degrees and 380% at 78; degrees as lengths ~1e5.
GEOGRAPHIC_RTOL = 0.01
MIN_MATCH_FRACTION = 0.95
# Cells flatter than this are skipped: every hypothesis predicts about zero there.
MIN_SLOPE_DEGREES = 0.5
# Slopes on another grid (Phase 10 S2), set from synthetic terrain before any held-out case was read (see
# tests/phase10_s2_calibration.py and the Phase 10 plan). A way reproduces a slope when MIN_MATCH_FRACTION of
# cells agree within RESAMPLED_RTOL (spacing models differ by 0.674%). The envelope bounds
# |ln(mean delivered tan / mean reference tan)| for correct slopes made any way, including ways not emulated.
RESAMPLED_RTOL = GEOGRAPHIC_RTOL
RESAMPLED_LOG_ENVELOPE = 0.25
# A gross mistake must also keep the DEM's pattern: the Pearson correlation of tan(slope) with that reading.
RESAMPLED_MIN_CORRELATION = 0.5
# The common ways a slope reaches another grid, each tried for every reading (declared and mistakes).
RESAMPLING = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear, "cubic": Resampling.cubic,
              "average": Resampling.average}
STENCILS = ("central", "horn")


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


def _fraction(observed: np.ndarray, expected: np.ndarray, rtol: float = RTOL) -> float:
    return float(np.count_nonzero(np.abs(observed - expected) <= rtol * np.abs(expected) + ATOL) / observed.size)


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


def _grid_model(crs, transform, rows: int, vertical_metres: float):
    """(factor, dx, dy, geographic): DEM values times factor are in the grid's horizontal length unit."""
    if crs.is_projected:
        return vertical_metres / crs.linear_units_factor[1], abs(transform[0]), abs(transform[4]), False
    dx, dy = _geographic_spacing(crs, transform, rows)
    return vertical_metres, dx, dy, True


def _mistakes(factor: float, dx, dy, geographic: bool, transform) -> dict:
    """Named mistakes on one grid, as (factor, x spacing, y spacing)."""
    mistakes = {}
    if geographic:
        degrees_x, degrees_y = abs(transform[0]), abs(transform[4])
        mistakes["degrees used as lengths"] = (factor, degrees_x, degrees_y)
        mistakes["longitude spacing not scaled by latitude"] = (factor, dy * degrees_x / degrees_y, dy)
    elif not np.isclose(factor, 1.0):
        mistakes["vertical units ignored"] = (1.0, dx, dy)
    if not geographic and not np.isclose(dx, dy):
        mistakes["square pixels assumed (x spacing)"] = (factor, dx, dx)
        mistakes["square pixels assumed (y spacing)"] = (factor, dy, dy)
    return mistakes


def _horn_degrees(z: np.ndarray, valid: np.ndarray, factor: float, dx, dy):
    """Horn's 3x3 slope (the GDAL default) at interior cells whose 3x3 window is valid."""
    v = np.where(valid, z * factor, np.nan)
    dx = np.broadcast_to(np.reshape(np.asarray(dx, float), (-1, 1)), (z.shape[0], 1))[1:-1]
    dy = np.broadcast_to(np.reshape(np.asarray(dy, float), (-1, 1)), (z.shape[0], 1))[1:-1]
    gx = ((v[:-2, 2:] + 2 * v[1:-1, 2:] + v[2:, 2:]) - (v[:-2, :-2] + 2 * v[1:-1, :-2] + v[2:, :-2])) / (8 * dx)
    gy = ((v[2:, :-2] + 2 * v[2:, 1:-1] + v[2:, 2:]) - (v[:-2, :-2] + 2 * v[:-2, 1:-1] + v[:-2, 2:])) / (8 * dy)
    out = np.full(z.shape, np.nan)
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(gx, gy)))
    return out, np.isfinite(out)


def _slope(values, valid, hypothesis, stencil):
    """Slope in degrees of one hypothesis, NaN where the stencil is incomplete."""
    degrees, support = (_horn_degrees if stencil == "horn" else _slope_degrees)(values, valid, *hypothesis)
    return np.where(support, degrees, np.nan)


def _warp(array, src_crs, src_transform, shape, dst_crs, dst_transform, method):
    out = np.full(shape, np.nan)
    reproject(np.ascontiguousarray(array, dtype="float64"), out, src_transform=Affine(*src_transform[:6]),
              src_crs=src_crs, dst_transform=Affine(*dst_transform[:6]), dst_crs=dst_crs,
              resampling=RESAMPLING[method], src_nodata=np.nan, dst_nodata=np.nan)
    return out


def _tan(degrees):
    inside = np.isfinite(degrees) & (degrees >= 0) & (degrees < 90)
    return np.where(inside, np.tan(np.radians(np.where(inside, degrees, 0.0))), np.nan)


def _fit(observed, expected, keep):
    """Cell-wise agreement (in degrees, as the same-grid test) and |ln| of the area-mean gradient ratio."""
    o, e = observed[keep], expected[keep]
    total = float(e.sum())
    ratio = float(o.sum()) / total if total > 0 else math.inf
    match = _fraction(np.degrees(np.arctan(o)), np.degrees(np.arctan(e)), RESAMPLED_RTOL) if o.size else 0.0
    correlation = float(np.corrcoef(o, e)[0, 1]) if o.size > 1 and o.std() > 0 and e.std() > 0 else 0.0
    return {"match_fraction": match, "abs_log_mean_ratio": abs(math.log(ratio)) if 0 < ratio < math.inf else math.inf,
            "correlation": correlation, "cells": int(o.size)}


def _in_unit(degrees, unit):
    return np.tan(np.radians(degrees)) * 100 if unit == "percent" else degrees


def _from_unit(values, unit):
    return values / 100 if unit == "percent" else _tan(values)


CONFUSED = "degrees and percent confused"


def _references(output, dem, values, valid, shape, dem_crs, out_crs, vertical_metres, unit):
    """tan(slope) on the output grid per reading, for every common way of making it: slope then warp (in the
    delivered unit), or warp then slope; each RESAMPLING method; central differences or Horn. Besides the
    unit and spacing mistakes, one reading is the declared slope written in the other unit."""
    other = None if unit == "percent" else "percent"
    dem_model = _grid_model(dem_crs, dem["transform"], values.shape[0], vertical_metres)
    out_model = _grid_model(out_crs, output["transform"], shape[0], vertical_metres)
    dem_readings = {"declared": dem_model[:3], **_mistakes(*dem_model, dem["transform"])}
    out_readings = {"declared": out_model[:3], **_mistakes(*out_model, output["transform"])}
    for stencil in STENCILS:
        native = {name: _slope(values, valid, h, stencil) for name, h in dem_readings.items()}
        written = {name: (_in_unit(slope, unit), unit) for name, slope in native.items()}
        written[CONFUSED] = (_in_unit(native["declared"], other), unit)
        for method in RESAMPLING:
            yield f"slope then warp, {method}, {stencil}", {
                name: _from_unit(_warp(slope, dem_crs, dem["transform"], shape, out_crs, output["transform"], method),
                                 read_as)
                for name, (slope, read_as) in written.items()}
    for method in RESAMPLING:
        warped = _warp(np.where(valid, values, np.nan), dem_crs, dem["transform"], shape, out_crs,
                       output["transform"], method)
        for stencil in STENCILS:
            slopes = {name: _slope(warped, np.isfinite(warped), h, stencil) for name, h in out_readings.items()}
            yield f"warp then slope, {method}, {stencil}", {
                **{name: _tan(slope) for name, slope in slopes.items()},
                CONFUSED: _from_unit(_in_unit(slopes["declared"], other), unit)}


def resampled_fits(output, dem, values, valid, delivered_tan, dem_crs, out_crs, vertical_metres, unit=None):
    """Each reading's best cell-wise match and best area-mean ratio over the common ways of making a slope on
    another grid, each with the way that gave it."""
    fits = {}
    minimum = math.tan(math.radians(MIN_SLOPE_DEGREES))
    for way, expected in _references(output, dem, values, valid, delivered_tan.shape, dem_crs, out_crs,
                                     vertical_metres, unit):
        keep = np.isfinite(delivered_tan) & np.isfinite(expected["declared"]) & (expected["declared"] >= minimum)
        if np.count_nonzero(keep) < 2:
            continue
        for name, gradient in expected.items():
            fit = _fit(delivered_tan, gradient, keep & np.isfinite(gradient))
            best = fits.setdefault(name, {"match_fraction": -1.0, "abs_log_mean_ratio": math.inf})
            if fit["match_fraction"] > best["match_fraction"]:
                best.update(match_fraction=fit["match_fraction"], match_way=way, cells=fit["cells"])
            if fit["abs_log_mean_ratio"] < best["abs_log_mean_ratio"]:
                best.update(abs_log_mean_ratio=fit["abs_log_mean_ratio"], mean_way=way,
                            mean_correlation=fit["correlation"])
    return fits


def resampled_outcome(fits) -> tuple[str, str | None]:
    """(status, mistake) from resampled_fits: a cell-wise reproduction decides; otherwise only a gross
    mistake fails: the declared reading outside the correct envelope, the mistake inside it and correlated."""
    declared = fits["declared"]
    if declared["match_fraction"] >= MIN_MATCH_FRACTION:
        return PASS, None
    mistakes = {name: fit for name, fit in fits.items() if name != "declared"}
    reproduced = sorted((-fit["match_fraction"], name) for name, fit in mistakes.items()
                        if fit["match_fraction"] >= MIN_MATCH_FRACTION)
    if reproduced:
        return FAIL, reproduced[0][1]
    gross = sorted((fit["abs_log_mean_ratio"], name) for name, fit in mistakes.items()
                   if fit["abs_log_mean_ratio"] <= RESAMPLED_LOG_ENVELOPE
                   and fit["mean_correlation"] >= RESAMPLED_MIN_CORRELATION)
    if gross and declared["abs_log_mean_ratio"] > RESAMPLED_LOG_ENVELOPE:
        return FAIL, gross[0][1]
    return WARN, None


def _check_resampled(output, dem, values, valid, delivered_tan, dem_crs, out_crs, vertical_metres, unit, evidence):
    evidence.update(comparison="resampled", tolerance={"rtol": RESAMPLED_RTOL, "atol_degrees": ATOL,
                                                       "min_match_fraction": MIN_MATCH_FRACTION,
                                                       "abs_log_mean_ratio_envelope": RESAMPLED_LOG_ENVELOPE})
    fits = resampled_fits(output, dem, values, valid, delivered_tan, dem_crs, out_crs, vertical_metres, unit)
    if "declared" not in fits:
        return [result(CHECK_ID, NOT_RUN, "No sloping cell of the delivered grid has a full reference stencil, so "
                       "nothing could be compared.", **evidence)]
    status, mistake = resampled_outcome(fits)
    declared = fits.pop("declared")
    evidence.update(declared_fit=declared, mistake_fits=fits)
    if status == PASS:
        return [result(CHECK_ID, PASS,
                       f"Slope in {output['path']} is on another grid than {dem['path']}; made "
                       f"{declared['match_way']}, the DEM's slope reproduces it at "
                       f"{declared['match_fraction']:.0%} of compared cells.", **evidence)]
    if status == FAIL:
        return [result(CHECK_ID, FAIL,
                       f"Slope in {output['path']} matches the DEM resampled with {mistake}, not its declared "
                       "vertical unit and real pixel spacing.", **evidence)]
    return [result(CHECK_ID, WARN,
                   f"Slope in {output['path']} is on another grid than {dem['path']}; no common way of resampling "
                   "reproduces it from the DEM, and it shows no gross unit or spacing mistake.", **evidence)]


def check_slope_consistent(output: dict, dem: dict, declared_unit: str | None = None,
                           slope_unit: str | None = None) -> list:
    """Compare a slope raster with the slope its DEM's units and spacing imply.

    `declared_unit` states the DEM's vertical unit when the file carries no label; a label that
    contradicts it is a conflict, not something to choose between. `slope_unit` declares the output
    in degrees (the default) or percent; a percent slope is converted to degrees before comparing.
    A slope on another grid than its DEM is compared after resampling."""
    evidence = {"output": output.get("path"), "dem": dem.get("path"), "declared_vertical_unit": declared_unit,
                "slope_unit": slope_unit}
    if slope_unit not in SLOPE_UNITS:
        return [result(CHECK_ID, NOT_RUN, "slope_unit must be degrees or percent.", **evidence)]
    if dem.get("kind") != "raster" or output.get("kind") != "raster":
        return [result(CHECK_ID, NOT_RUN, "Slope consistency needs a raster output and a raster DEM.", **evidence)]
    problems = _grid_problems(dem, output)
    if any(p in ("one raster has no CRS", "non-finite transform", "rotated or sheared grids are unsupported")
           for p in problems):
        return [result(CHECK_ID, NOT_RUN,
                       f"Output {output['path']} and DEM {dem['path']} are not on the same grid "
                       f"({'; '.join(problems)}), and cannot be resampled onto each other.",
                       problems=problems, **evidence)]
    try:
        with rasterio.open(dem["path"]) as src:
            crs = src.crs
            unit = (src.units[0] or "").strip()
            z = src.read(1, masked=True)
        with rasterio.open(output["path"]) as dst:
            out_crs = dst.crs
            slope = dst.read(1, masked=True)
        if slope_unit == "percent":
            slope = np.degrees(np.arctan(slope.astype("float64") / 100.0))  # ufuncs keep the mask
    except rasterio.errors.RasterioIOError as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot read pixel values: {error}", **evidence)]
    if crs is None or not (crs.is_projected or crs.is_geographic):
        return [result(CHECK_ID, NOT_RUN,
                       f"DEM {dem['path']} has no projected or geographic CRS; its pixel spacing is not a length.",
                       **evidence)]
    if declared_unit:
        declared = declared_unit.strip().lower()
        if declared not in VERTICAL_UNITS:
            return [result(CHECK_ID, NOT_RUN, f"Declared DEM vertical unit '{declared_unit}' is not a known "
                           "length unit.", **evidence)]
        if unit and unit.lower() in VERTICAL_UNITS and VERTICAL_UNITS[unit.lower()] != VERTICAL_UNITS[declared]:
            return [result(CHECK_ID, NOT_RUN, f"The DEM is labelled '{unit}' but declared '{declared_unit}'; "
                           "resolve the conflict before checking slope.", vertical_unit=unit, **evidence)]
        unit = declared
    if unit and unit.lower() not in VERTICAL_UNITS:
        return [result(CHECK_ID, NOT_RUN, f"DEM vertical unit '{unit}' is not a known length unit.",
                       vertical_unit=unit, **evidence)]
    geographic = not crs.is_projected
    if geographic and not unit:
        return [result(CHECK_ID, NOT_RUN, f"DEM {dem['path']} is geographic and declares no vertical unit, so "
                       "heights cannot be related to metres on the ground.", **evidence)]
    # Metres per DEM value; an empty unit on a projected DEM is its horizontal unit.
    vertical_metres = VERTICAL_UNITS[unit.lower()] if unit else crs.linear_units_factor[1]
    values = np.ma.getdata(z).astype(np.float64)
    valid = ~np.ma.getmaskarray(z) & np.isfinite(values)
    delivered = np.ma.getdata(slope).astype(np.float64)
    delivered_valid = ~np.ma.getmaskarray(slope) & np.isfinite(delivered)

    if problems:
        if out_crs is None or not (out_crs.is_projected or out_crs.is_geographic):
            return [result(CHECK_ID, NOT_RUN, f"Output {output['path']} is on another grid and has no projected "
                           "or geographic CRS to resample onto.", problems=problems, **evidence)]
        evidence.update(vertical_unit=unit or None, problems=problems)
        delivered_tan = _tan(np.where(delivered_valid, delivered, np.nan))
        try:
            return _check_resampled(output, dem, values, valid, delivered_tan, crs, out_crs, vertical_metres,
                                    slope_unit, evidence)
        except (ValueError, rasterio.errors.RasterioError) as error:
            return [result(CHECK_ID, NOT_RUN, f"Cannot resample the DEM onto the output grid: {error}", **evidence)]

    factor, dx, dy, _ = _grid_model(crs, dem["transform"], z.shape[0], vertical_metres)
    if geographic:
        evidence.update(vertical_unit=unit, vertical_factor=factor, geographic=True,
                        pixel_size_degrees=[abs(dem["transform"][0]), abs(dem["transform"][4])],
                        pixel_size_metres_range={"x": [float(dx.min()), float(dx.max())],
                                                 "y": [float(dy.min()), float(dy.max())]},
                        tolerance={"rtol": GEOGRAPHIC_RTOL, "atol_degrees": ATOL},
                        min_match_fraction=MIN_MATCH_FRACTION)
    else:
        evidence.update(vertical_unit=unit or None, vertical_factor=factor, pixel_size=[dx, dy],
                        tolerance={"rtol": RTOL, "atol_degrees": ATOL}, min_match_fraction=MIN_MATCH_FRACTION)

    expected, support = _slope_degrees(values, valid, factor, dx, dy)
    keep = support & delivered_valid & (expected >= MIN_SLOPE_DEGREES)
    compared = int(np.count_nonzero(keep))
    evidence["compared_cells"] = compared
    if compared == 0:
        return [result(CHECK_ID, NOT_RUN,
                       "No sloping cell has a full central-difference stencil in the DEM and a valid "
                       "delivered value, so nothing could be compared.", **evidence)]

    observed = delivered[keep]
    rtol = GEOGRAPHIC_RTOL if geographic else RTOL
    declared = _fraction(observed, expected[keep], rtol)
    evidence["declared_match_fraction"] = declared
    if declared >= MIN_MATCH_FRACTION:
        spacing = "ellipsoidal pixel spacing" if geographic else f"{dx:g} x {dy:g} pixel spacing"
        return [result(CHECK_ID, PASS,
                       f"Slope in {output['path']} matches central differences on {dem['path']} with its "
                       f"declared vertical unit and {spacing}.", **evidence)]

    matches = {}
    for name, hypothesis in _mistakes(factor, dx, dy, geographic, dem["transform"]).items():
        alternative, _ = _slope_degrees(values, valid, *hypothesis)
        matches[name] = _fraction(observed, alternative[keep], rtol)
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
