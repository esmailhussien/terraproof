"""Opt-in delivered-value check for vector measurements: geometry.metric_values.

`crs.metric_operation` judges whether a dataset's CRS is fit for a metric operation still to come.
This check judges a measurement already delivered, whatever CRS the output is stored in:

- ``area`` / ``length``   each feature's declared property (``metric_property``, in ``metric_unit``)
                          is compared with the feature's geodesic area or length on the CRS ellipsoid
- ``buffer``              the output's boundary vertices are compared with the declared ground
                          distance (``buffer_distance_m``) from the declared source geometry
                          (``buffer_source``), measured in a local azimuthal equidistant projection

A correct value computed geodesically or in a suitable projected CRS agrees well within the
tolerance; a value computed in degrees, or with longitude not scaled by latitude, does not.
Nothing is inferred: an undeclared property, unit, distance or source is not-run, naming it.
"""
from __future__ import annotations

import math

import numpy as np
import pyogrio.raw
from pyproj import CRS, Geod, Transformer
import shapely
from shapely.ops import transform as shapely_transform

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result

CHECK_ID = "geometry.metric_values"
QUANTITIES = ("area", "length", "buffer")
UNITS = {"area": {"square_metre": 1.0, "m2": 1.0, "hectare": 1e4, "ha": 1e4, "square_kilometre": 1e6, "km2": 1e6},
         "length": {"metre": 1.0, "m": 1.0, "kilometre": 1000.0, "km": 1000.0}}
RTOL = 0.01          # area and length: projected-CRS methods differ from geodesic far less than this
BUFFER_RTOL = 0.02   # buffer: polygonal arcs and projection scale stay well inside this
BUFFER_MIN_FRACTION = 0.95


def _read(path: str):
    meta, _fids, geometry, fields = pyogrio.raw.read(path)
    geoms = shapely.from_wkb(geometry)
    crs = CRS.from_user_input(meta["crs"]) if meta.get("crs") else None
    return crs, geoms, dict(zip(meta["fields"], fields))


def _to_geographic(crs: CRS):
    geographic = crs.geodetic_crs
    if crs.is_geographic:
        return geographic, None
    transformer = Transformer.from_crs(crs, geographic, always_xy=True)
    return geographic, lambda geom: shapely_transform(transformer.transform, geom)


def _geod(crs: CRS) -> Geod:
    ellipsoid = crs.ellipsoid
    return Geod(a=ellipsoid.semi_major_metre, rf=ellipsoid.inverse_flattening or 0)


def check_metric_values(output: dict, quantity: str | None, metric_property: str | None = None,
                        metric_unit: str | None = None, buffer_distance_m: float | None = None,
                        buffer_source: dict | None = None) -> list:
    evidence = {"output": output.get("path"), "quantity": quantity, "metric_property": metric_property,
                "metric_unit": metric_unit, "buffer_distance_m": buffer_distance_m,
                "buffer_source": buffer_source.get("path") if buffer_source else None}
    if quantity not in QUANTITIES:
        return [result(CHECK_ID, NOT_RUN, f"Declare metric_quantity ({', '.join(QUANTITIES)}).",
                       missing_bindings=["metric_quantity"], **evidence)]
    if quantity == "buffer":
        missing = [name for name, value in (("buffer_distance_m", buffer_distance_m), ("buffer_source", buffer_source))
                   if value is None]
    else:
        missing = [name for name, value in (("metric_property", metric_property), ("metric_unit", metric_unit))
                   if not value]
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to check delivered metric values.",
                       missing_bindings=missing, **evidence)]
    if output.get("kind") != "vector" or (buffer_source is not None and buffer_source.get("kind") != "vector"):
        return [result(CHECK_ID, NOT_RUN, "Metric values are checked on vector datasets.", **evidence)]
    try:
        crs, geoms, fields = _read(output["path"])
        if crs is None:
            return [result(CHECK_ID, NOT_RUN, "The output declares no CRS.", **evidence)]
        if quantity == "buffer":
            return _buffer(crs, geoms, buffer_source, buffer_distance_m, evidence)
        factor = UNITS[quantity].get(str(metric_unit).strip().lower())
        if factor is None:
            return [result(CHECK_ID, NOT_RUN, f"metric_unit must be one of {', '.join(UNITS[quantity])}.", **evidence)]
        if metric_property not in fields:
            return [result(CHECK_ID, NOT_RUN, f"The output has no property '{metric_property}'.", **evidence)]
        geographic, to_geographic = _to_geographic(crs)
        geod = _geod(geographic)
        values = fields[metric_property]
        compared = mismatched = 0
        worst = 0.0
        for geom, value in zip(geoms, values):
            if geom is None or geom.is_empty or value is None or not math.isfinite(float(value)):
                continue
            lonlat = to_geographic(geom) if to_geographic else geom
            if quantity == "area":
                expected = abs(geod.geometry_area_perimeter(lonlat)[0])
            else:
                expected = geod.geometry_length(lonlat)
            if expected <= 0:
                continue
            delivered = float(value) * factor
            error = abs(delivered - expected) / expected
            worst = max(worst, error)
            compared += 1
            mismatched += error > RTOL
        evidence.update(compared_features=compared, mismatched_features=mismatched,
                        worst_relative_error=round(worst, 6), tolerance={"rtol": RTOL})
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot read the vector output ({type(error).__name__}).", **evidence)]
    if not compared:
        return [result(CHECK_ID, NOT_RUN, "No feature has a finite value and a measurable geometry.", **evidence)]
    if mismatched:
        return [result(CHECK_ID, FAIL, f"{mismatched} of {compared} features' {metric_property} values differ from "
                       f"the geodesic {quantity} by more than {RTOL:.0%}.", **evidence)]
    return [result(CHECK_ID, PASS, f"Every feature's {metric_property} matches its geodesic {quantity} within "
                   f"{RTOL:.0%}.", **evidence)]


def _buffer(crs, geoms, source: dict, distance: float, evidence: dict) -> list:
    if not (isinstance(distance, (int, float)) and math.isfinite(distance) and distance > 0):
        return [result(CHECK_ID, NOT_RUN, "buffer_distance_m must be a positive number of metres.", **evidence)]
    source_crs, source_geoms, _ = _read(source["path"])
    if source_crs is None:
        return [result(CHECK_ID, NOT_RUN, "The buffer source declares no CRS.", **evidence)]
    output_union = shapely.union_all([g for g in geoms if g is not None and not g.is_empty])
    source_union = shapely.union_all([g for g in source_geoms if g is not None and not g.is_empty])
    if output_union.is_empty or source_union.is_empty:
        return [result(CHECK_ID, NOT_RUN, "The buffer or its source has no geometry.", **evidence)]
    to_lonlat = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    centre = shapely_transform(to_lonlat.transform, output_union).centroid
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={centre.y} +lon_0={centre.x} +datum=WGS84 +units=m")
    out_local = shapely_transform(Transformer.from_crs(crs, local, always_xy=True).transform, output_union)
    src_local = shapely_transform(Transformer.from_crs(source_crs, local, always_xy=True).transform, source_union)
    rings = [polygon.exterior for polygon in getattr(out_local, "geoms", [out_local])]
    points = [shapely.Point(xy) for ring in rings for xy in ring.coords]
    distances = np.array([src_local.distance(point) for point in points])
    within = np.abs(distances - distance) <= BUFFER_RTOL * distance
    fraction = float(np.count_nonzero(within) / len(distances)) if len(distances) else 0.0
    evidence.update(boundary_vertices=len(distances), within_tolerance_fraction=round(fraction, 4),
                    median_ground_distance_m=round(float(np.median(distances)), 3) if len(distances) else None,
                    tolerance={"rtol": BUFFER_RTOL, "min_fraction": BUFFER_MIN_FRACTION})
    if not len(distances):
        return [result(CHECK_ID, NOT_RUN, "The buffer has no boundary vertices.", **evidence)]
    if fraction < BUFFER_MIN_FRACTION:
        return [result(CHECK_ID, FAIL, f"Only {fraction:.0%} of buffer boundary vertices lie {distance:g} m from the "
                       "source on the ground; the buffer distance was not applied in metres.", **evidence)]
    return [result(CHECK_ID, PASS, f"The buffer boundary lies {distance:g} m from the source on the ground.",
                   **evidence)]
