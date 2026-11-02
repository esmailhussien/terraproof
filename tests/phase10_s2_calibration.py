"""Phase 10 S2: set the resampled-slope rule from synthetic terrain, before any held-out case is read.

Correct slopes are made the ways practitioners make them: slope then warp (in the delivered unit), or
warp then slope; central differences or Horn; WGS84 or spherical spacing; float64 or float32 storage;
degrees or percent; nearest, bilinear, cubic, average, cubic-spline or Lanczos resampling (the check
emulates only the first four); output pixels 1x to 3x the DEM's. Wrong slopes are the named mistakes made
the same ways, plus degrees and percent confused in both directions. The script applies the check's own
rule (terrain.resampled_outcome) for several area-mean envelopes and counts outcomes, so the envelope and
its margins can be recorded. Run: python tests/phase10_s2_calibration.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
from rasterio.crs import CRS
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject

from terraproof.checks import terrain

METHODS = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear, "cubic": Resampling.cubic,
           "average": Resampling.average, "cubic_spline": Resampling.cubic_spline, "lanczos": Resampling.lanczos}
SIZE = 96
SPHERE = 6371008.8
ENVELOPES = (0.1, 0.15, 0.2, 0.25, 0.3, 0.4)
CORRELATIONS = (0.3, 0.5, 0.7)


def terrains(rng):
    y, x = np.mgrid[0:SIZE, 0:SIZE].astype("float64")
    yield "plane", 0.35 * x + 0.2 * y
    yield "cone", 600 - 4.0 * np.hypot(x - SIZE / 2, y - SIZE / 2)
    yield "sinusoid", 120 * np.sin(x / 9) * np.cos(y / 13)
    for beta in (2.0, 2.5, 3.0, 3.5, 4.0):  # spectral synthesis: lower beta is rougher
        k = np.hypot(*np.meshgrid(np.fft.fftfreq(SIZE), np.fft.fftfreq(SIZE)))
        k[0, 0] = 1.0
        spectrum = (rng.normal(size=(SIZE, SIZE)) + 1j * rng.normal(size=(SIZE, SIZE))) * k ** (-beta / 2)
        surface = np.real(np.fft.ifft2(spectrum))
        gy, gx = np.gradient(surface)
        yield f"fractal-{beta}", surface * (0.45 / np.mean(np.hypot(gx, gy)))  # mean gradient ~0.45 per pixel


def slope(z, dx, dy, stencil):
    return terrain._slope(z, np.isfinite(z), (1.0, dx, dy), stencil)


def spacing(crs, transform, rows, model):
    if crs.is_projected:
        return abs(transform[0]), abs(transform[4])
    if model == "sphere":
        latitude = np.radians(transform[5] + (np.arange(rows) + 0.5) * transform[4])
        return (abs(transform[0]) * np.radians(1) * SPHERE * np.cos(latitude),
                np.full(rows, abs(transform[4]) * np.radians(1) * SPHERE))
    return terrain._geographic_spacing(crs, transform, rows)


def warp(array, src_crs, src_transform, dst_crs, dst_transform, shape, method):
    out = np.full(shape, np.nan)
    reproject(np.ascontiguousarray(array, dtype="float64"), out, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=dst_crs, resampling=METHODS[method],
              src_nodata=np.nan, dst_nodata=np.nan)
    return out


def grids():
    """(name, DEM CRS, DEM transform, output CRS, scale of output pixels)."""
    for latitude in (28.7, 46.6, 60.0, 78.6):
        for scale in (1.0, 1.25, 2.0):
            yield (f"geo{latitude}->utm x{scale}", CRS.from_epsg(4326),
                   from_origin(14.5, latitude + SIZE / 3600 / 2, 1 / 3600, 1 / 3600), CRS.from_epsg(32633), scale)
    for scale in (1.5, 2.0, 3.0):
        yield (f"utm30m x{scale}", CRS.from_epsg(32633), from_origin(500000, 5000000, 30, 30),
               CRS.from_epsg(32633), scale)
    yield ("utm33->utm32 x1", CRS.from_epsg(32633), from_origin(300000, 5200000, 30, 30), CRS.from_epsg(32632), 1.0)


def output_grid(dem_crs, dem_transform, out_crs, scale):
    left, top = dem_transform[2], dem_transform[5]
    right, bottom = left + SIZE * dem_transform[0], top + SIZE * dem_transform[4]
    transform, width, height = calculate_default_transform(dem_crs, out_crs, SIZE, SIZE, left, bottom, right, top)
    transform = Affine(transform.a * scale, 0, transform.c, 0, transform.e * scale, transform.f)
    return transform, (max(3, int(height / scale)), max(3, int(width / scale)))


def to_unit(degrees, unit):
    return np.tan(np.radians(degrees)) * 100 if unit == "percent" else degrees


def run():
    """One correct slope per order, method and unit, with a seeded stencil, spacing model and storage type;
    and each named mistake per method, in a seeded order where it can arise either way."""
    rng = np.random.default_rng(10)
    rows = []
    for terrain_name, z in terrains(rng):
        z = z - z.min() + 100.0
        for grid_name, dem_crs, dem_transform, out_crs, scale in grids():
            out_transform, shape = output_grid(dem_crs, dem_transform, out_crs, scale)
            dem = {"transform": list(dem_transform)[:6]}
            out = {"transform": list(out_transform)[:6]}
            geographic = dem_crs.is_geographic

            def made(values, dem_spacing, out_spacing, order, method, stencil, unit, float32=False):
                """A slope raster as delivered, in `unit`."""
                if order == "slope then warp":
                    delivered = warp(to_unit(slope(values, *dem_spacing, stencil), unit), dem_crs, dem_transform,
                                     out_crs, out_transform, shape, method)
                else:
                    warped = warp(values, dem_crs, dem_transform, out_crs, out_transform, shape, method)
                    delivered = to_unit(slope(warped, *out_spacing, stencil), unit)
                return delivered.astype("float32").astype("float64") if float32 else delivered

            def score(delivered, declared_unit, values, vertical_metres, label, truth):
                degrees = np.degrees(np.arctan(delivered / 100)) if declared_unit == "percent" else delivered
                fits = terrain.resampled_fits(out, dem, values, np.isfinite(values), terrain._tan(degrees),
                                              dem_crs, out_crs, vertical_metres, declared_unit)
                if "declared" not in fits:
                    return
                mistakes = {k: v for k, v in fits.items() if k != "declared"}
                rows.append({"terrain": terrain_name, "grid": grid_name, "variant": label, "truth": truth,
                             "fits": fits,
                             "declared_match": fits["declared"]["match_fraction"],
                             "declared_log": fits["declared"]["abs_log_mean_ratio"],
                             "best_mistake_match": max((v["match_fraction"] for v in mistakes.values()), default=None),
                             "best_mistake_log": min((v["abs_log_mean_ratio"] for v in mistakes.values()),
                                                     default=None)})

            for method in METHODS:
                for order in ("slope then warp", "warp then slope"):
                    stencil = ("central", "horn")[rng.integers(2)]
                    model = ("ellipsoid", "sphere")[rng.integers(2)] if geographic else "ellipsoid"
                    unit = ("degrees", "percent")[rng.integers(2)]
                    float32 = bool(rng.integers(2))
                    delivered = made(z, spacing(dem_crs, dem_transform, SIZE, model),
                                     spacing(out_crs, out_transform, shape[0], model), order, method, stencil, unit,
                                     float32)
                    score(delivered, None if unit == "degrees" else unit, z, 1.0,
                          f"{order}, {method}, {stencil}, {model}, {unit}, f32={float32} | correct", "correct")
                stencil = ("central", "horn")[rng.integers(2)]
                order = ("slope then warp", "warp then slope")[rng.integers(2)]
                dem_spacing = spacing(dem_crs, dem_transform, SIZE, "ellipsoid")
                out_spacing = spacing(out_crs, out_transform, shape[0], "ellipsoid")
                feet = z / 0.3048  # heights in feet, labelled feet, used as metres
                score(made(feet, dem_spacing, out_spacing, order, method, stencil, "degrees"), None, feet, 0.3048,
                      f"{order}, {method}, {stencil} | vertical units ignored", "wrong")
                if geographic:
                    degrees = (abs(dem_transform[0]), abs(dem_transform[4]))
                    score(made(z, degrees, out_spacing, "slope then warp", method, stencil, "degrees"), None, z, 1.0,
                          f"slope then warp, {method}, {stencil} | degrees as lengths", "wrong")
                    unscaled = (dem_spacing[1], dem_spacing[1])
                    score(made(z, unscaled, out_spacing, "slope then warp", method, stencil, "degrees"), None, z, 1.0,
                          f"slope then warp, {method}, {stencil} | latitude ignored", "wrong")
                score(made(z, dem_spacing, out_spacing, order, method, stencil, "percent"), None, z, 1.0,
                      f"{order}, {method}, {stencil} | percent delivered, degrees declared", "wrong")
                score(made(z, dem_spacing, out_spacing, order, method, stencil, "degrees"), "percent", z, 1.0,
                      f"{order}, {method}, {stencil} | degrees delivered, percent declared", "wrong")
    return rows


def outcome(row, envelope, correlation):
    saved = terrain.RESAMPLED_LOG_ENVELOPE, terrain.RESAMPLED_MIN_CORRELATION
    terrain.RESAMPLED_LOG_ENVELOPE, terrain.RESAMPLED_MIN_CORRELATION = envelope, correlation
    try:
        return terrain.resampled_outcome(row["fits"])[0]
    finally:
        terrain.RESAMPLED_LOG_ENVELOPE, terrain.RESAMPLED_MIN_CORRELATION = saved


def sweep(rows):
    table = []
    for envelope in ENVELOPES:
        for correlation in CORRELATIONS:
            counts = {}
            for row in rows:
                key = f"{row['truth']}->{outcome(row, envelope, correlation)}"
                counts[key] = counts.get(key, 0) + 1
            table.append({"envelope": envelope, "min_correlation": correlation, **counts})
    return table


def summarize(rows):
    correct = [r for r in rows if r["truth"] == "correct"]
    wrong = [r for r in rows if r["truth"] == "wrong"]
    summary = {"correct_variants": len(correct), "wrong_variants": len(wrong), "by_terrain": {}, "by_mistake": {},
               "by_method": {}}
    for name in sorted({r["terrain"] for r in correct}):
        group = [r for r in correct if r["terrain"] == name]
        logs = np.array([r["declared_log"] for r in group])
        summary["by_terrain"][name] = {"max_abs_log": float(logs.max()), "p95_abs_log": float(np.percentile(logs, 95)),
                                       "reproduced": sum(r["declared_match"] >= terrain.MIN_MATCH_FRACTION
                                                         for r in group), "variants": len(group)}
    for method in METHODS:
        group = [r for r in correct if f", {method}, " in r["variant"]]
        summary["by_method"][method] = {"reproduced": sum(r["declared_match"] >= terrain.MIN_MATCH_FRACTION
                                                          for r in group), "variants": len(group)}
    for name in sorted({r["variant"].split(" | ")[1] for r in wrong}):
        group = [r for r in wrong if r["variant"].split(" | ")[1] == name]
        low = min(group, key=lambda r: r["declared_log"])
        summary["by_mistake"][name] = {
            "variants": len(group), "min_declared_abs_log": low["declared_log"],
            "at": f"{low['terrain']} {low['grid']} {low['variant']}",
            "max_declared_match": max(r["declared_match"] for r in group),
            "reproduced": sum((r["best_mistake_match"] or 0) >= terrain.MIN_MATCH_FRACTION for r in group)}
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    rows = run()
    summary = summarize(rows)
    summary["sweep"] = sweep(rows)
    print(json.dumps(summary, indent=1, default=float))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"summary": summary, "rows": rows}, handle, indent=1,
                      default=lambda v: None if isinstance(v, float) and math.isinf(v) else float(v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
