"""Fixtures and oracles for the `crs-and-units` task specs."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pyproj
import shapely

from terraproof.evals.fixtures import (
    GEOGRAPHIC,
    UTM,
    write_geojson,
    write_vector,
)
from terraproof.evals.oracles import Oracle, relative_difference
from terraproof.evals.recipes._util import check_step, correct, recipe, results_for, wrong

# A compact AOI in one UTM zone, used by the metric-buffer task.
ROAD_POINTS_LONLAT = [
    (31.2000, 30.0500),
    (31.2060, 30.0512),
    (31.2125, 30.0540),
    (31.2190, 30.0555),
    (31.2250, 30.0580),
]
SURVEY_POINTS_LONLAT = [
    (31.2000, 30.0500),
    (31.2100, 30.0600),
    (31.2200, 30.0700),
    (31.2300, 30.0800),
    (31.2400, 30.0900),
]


def _transformer(source: str, target: str) -> pyproj.Transformer:
    return pyproj.Transformer.from_crs(source, target, always_xy=True)


def _project(points: list[tuple[float, float]], target: str = UTM) -> list[tuple[float, float]]:
    transformer = _transformer(GEOGRAPHIC, target)
    return [transformer.transform(lon, lat) for lon, lat in points]


def _aeqd_buffer_area(points: list[tuple[float, float]], radius: float = 500.0) -> float:
    """Independent reference: buffer in a local azimuthal equidistant projection centred on the AOI."""
    lon0 = sum(lon for lon, _ in points) / len(points)
    lat0 = sum(lat for _, lat in points) / len(points)
    crs = pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs"
    )
    transformer = pyproj.Transformer.from_crs(GEOGRAPHIC, crs, always_xy=True)
    local = [transformer.transform(lon, lat) for lon, lat in points]
    return shapely.LineString(local).buffer(radius, quad_segs=64).area


def _utm_buffer_area(points: list[tuple[float, float]], radius: float = 500.0, target: str = UTM) -> float:
    projected = _project(points, target)
    return shapely.LineString(projected).buffer(radius, quad_segs=64).area


def crs_local_metric_buffer(root: Path):
    """Task 1: a 500 m buffer measured in a justified local metre CRS."""
    roads_lonlat = shapely.LineString(ROAD_POINTS_LONLAT)
    roads_geographic = write_vector(
        root / "roads.gpkg",
        [roads_lonlat],
        crs=GEOGRAPHIC,
        geometry_type="LineString",
    )
    projected_points = _project(ROAD_POINTS_LONLAT)
    roads_projected = write_vector(
        root / "roads_projected.gpkg",
        [shapely.LineString(projected_points)],
        crs=UTM,
        geometry_type="LineString",
    )
    reference_area = _aeqd_buffer_area(ROAD_POINTS_LONLAT)
    utm_area = _utm_buffer_area(ROAD_POINTS_LONLAT)

    steps = [
        check_step("check roads_projected.gpkg --operation buffer", [roads_projected], operation="buffer"),
    ]
    oracle = Oracle("500 m access buffer measured in a local metre CRS")
    oracle.close(
        "buffer area in the chosen metre CRS equals the local-AEQD reference (m2)",
        utm_area,
        reference_area,
        reference_area * 0.005,
        note="tolerance 0.5% of the independent local azimuthal-equidistant calculation",
    )
    oracle.require(
        "the measurement CRS is projected with metre units",
        pyproj.CRS.from_user_input(UTM).axis_info[0].unit_name in ("metre", "meter"),
        pyproj.CRS.from_user_input(UTM).axis_info[0].unit_name,
        "metre",
    )
    oracle.require(
        "the geographic source is not used for the metric buffer",
        pyproj.CRS.from_user_input(GEOGRAPHIC).is_geographic,
        "EPSG:4326",
        "geographic (not a metric operation CRS)",
    )
    metric = results_for(steps, "crs.metric_operation")
    oracle.require(
        "crs.metric_operation passes on the projected roads",
        bool(metric) and all(result.status == "pass" for result in metric),
        [result.status for result in metric],
        "pass",
    )
    correct_control = correct(
        "local-metre-buffer",
        "Roads transformed into one suitable UTM zone, buffered at 500 metres, and checked with "
        "--operation buffer.",
        steps,
        oracle,
    )

    foot = pyproj.Transformer.from_crs(GEOGRAPHIC, "EPSG:2227", always_xy=True)
    foot_points = [foot.transform(lon, lat) for lon, lat in ROAD_POINTS_LONLAT]
    foot_area_m2 = shapely.LineString(foot_points).buffer(500.0, quad_segs=64).area * 0.09290304
    roads_feet = write_vector(
        root / "roads_projected_feet.gpkg",
        [shapely.LineString(foot_points)],
        crs="EPSG:2227",
        geometry_type="LineString",
    )
    wrong_oracle = Oracle("a 500-foot buffer, or an unsuitable projected CRS, changes the measured area")
    wrong_oracle.close(
        "buffer area (m2) matches the metric reference",
        foot_area_m2,
        reference_area,
        0.0,
        note="the foot-based candidate buffers 500 layer units, i.e. 500 US survey feet",
    )
    wrong_oracle.require(
        "the foot-based CRS uses foot units",
        any("foot" in axis.unit_name.lower() for axis in pyproj.CRS.from_epsg(2227).axis_info),
        [axis.unit_name for axis in pyproj.CRS.from_epsg(2227).axis_info],
        "foot",
        note="crs.metric_operation accepts foot units, so the radius unit is not checked automatically",
    )
    wrong_steps = [
        check_step("check roads_projected_feet.gpkg --operation buffer", [roads_feet], operation="buffer"),
    ]
    wrong_control = wrong(
        "foot-radius-unit-confusion",
        "The same road is buffered by 500 units in a foot-based projected CRS, which Terraproof's "
        "crs.metric_operation accepts because foot units are metric-adjacent.",
        wrong_steps,
        wrong_oracle,
        notes="Both checks pass, so the checker cannot distinguish a 500-foot buffer from a 500-metre one.",
    )
    return recipe(
        "crs-local-metric-buffer",
        correct_control,
        [wrong_control],
        automated_scope=[
            "crs.defined and crs.metric_operation on the projected pre-buffer roads",
            "independent local azimuthal-equidistant reference area for the 500 m buffer (0.5% tolerance)",
        ],
        remaining=[
            "The written answer must justify the chosen CRS after checking the full AOI and explain that crs.metric_operation accepts feet too; the harness does not grade prose.",
            "Independent field measurement of the buffer in the study area.",
        ],
    )


def crs_axis_datum(root: Path):
    """Task 2: axis convention and datum-grid availability control."""
    transformer = _transformer(GEOGRAPHIC, UTM)
    targets = [transformer.transform(lon, lat) for lon, lat in SURVEY_POINTS_LONLAT]
    observed = write_vector(
        root / "transformed.gpkg",
        [shapely.Point(x, y) for x, y in targets],
        crs=UTM,
        geometry_type="Point",
        fields=["feature_id"],
        field_data=[np.arange(len(targets))],
    )
    observations = write_vector(
        root / "observations.gpkg",
        [shapely.Point(x, y) for x, y in targets],
        crs=UTM,
        geometry_type="Point",
        fields=["feature_id"],
        field_data=[np.arange(len(targets))],
    )

    steps = [
        check_step("check transformed.gpkg --compare-to observations.gpkg", [observed], compare_to=observations),
    ]
    oracle = Oracle("axis convention and datum-grid availability are not evidenced by a defined CRS")
    measured = _read_points(observed)
    distances = [
        math.hypot(x - tx, y - ty) for (x, y), (tx, ty) in zip(measured, targets)
    ]
    oracle.require(
        "every transformed control point matches the independent target within 0.01 m",
        len(distances) == len(targets) and max(distances) <= 0.01,
        round(max(distances), 6) if distances else None,
        0.01,
    )
    swapped = [(lat, lon) for lon, lat in SURVEY_POINTS_LONLAT]
    swapped_targets = [transformer.transform(lon, lat) for lon, lat in swapped]
    swapped_distance = min(
        math.hypot(x - ox, y - oy)
        for (x, y), (ox, oy) in zip(swapped_targets, targets)
    )
    oracle.require(
        "swapping longitude and latitude moves the point by kilometres",
        swapped_distance > 10_000.0,
        round(swapped_distance, 1),
        "> 10000 m",
        note="this is what makes the axis convention a real risk rather than a cosmetic one",
    )
    grid = _grid_availability("EPSG:4267", "EPSG:32610")
    oracle.require(
        "the datum-grid report names the best operation and any missing grid",
        bool(grid["best_name"]),
        grid,
        "operation name and missing-grid list",
    )
    oracle.require(
        "a lower-accuracy fallback is identified when the best operation's grid is missing",
        grid["best_available"] or bool(grid["missing_grids"]),
        grid,
        "missing grid recorded or best operation available",
    )
    correct_control = correct(
        "lon-lat-axis-convention",
        "Survey points transformed with an explicit longitude/latitude convention and checked against "
        "independent target control points; the datum-grid availability is probed offline.",
        steps,
        oracle,
    )

    swapped_points = [transformer.transform(lat, lon) for lon, lat in SURVEY_POINTS_LONLAT]
    swapped_path = write_vector(
        root / "transformed_swapped.gpkg",
        [shapely.Point(x, y) for x, y in swapped_points],
        crs=UTM,
        geometry_type="Point",
        fields=["feature_id"],
        field_data=[np.arange(len(targets))],
    )
    wrong_steps = [
        check_step("check transformed_swapped.gpkg --compare-to observations.gpkg", [swapped_path], compare_to=observations),
    ]
    wrong_oracle = Oracle("a swapped axis convention must not be published as an accurate transform")
    swapped_measured = _read_points(swapped_path)
    swapped_gaps = [
        math.hypot(x - tx, y - ty) for (x, y), (tx, ty) in zip(swapped_measured, targets)
    ]
    wrong_oracle.require(
        "transformed points match the target control points within the stated accuracy budget (0.01 m)",
        bool(swapped_gaps) and max(swapped_gaps) <= 0.01,
        round(max(swapped_gaps), 1) if swapped_gaps else None,
        0.01,
    )
    wrong_control = wrong(
        "swapped-axis-order",
        "The same points are written with latitude and longitude exchanged; the CRS is defined and "
        "the record count matches, so only an independent control-point comparison catches it.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "crs-axis-datum-control",
        correct_control,
        [wrong_control],
        automated_scope=[
            "crs.defined and scope.record_count on the transformed output against the observations",
            "independent control-point distances that expose an axis-order swap",
            "offline PROJ operation/grid availability report for the datum case",
        ],
        remaining=[
            "The grid-present variant needs the datum transformation grid, which is unavailable offline; publishing an accurate result with the lower-quality fallback remains a human decision.",
            "The written answer must state the axis convention and stop the accuracy claim when the required grid is missing; the harness cannot grade that statement.",
        ],
    )


def _read_points(path: str) -> list[tuple[float, float]]:
    import pyogrio.raw
    import shapely

    _meta, _fids, geoms, _fields = pyogrio.raw.read(path)
    return [(geom.x, geom.y) for geom in shapely.from_wkb(geoms)]


def _grid_availability(source: str, target: str) -> dict:
    """Inspect PROJ's operation list offline; no download is attempted."""
    import warnings

    from pyproj.transformer import TransformerGroup

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        group = TransformerGroup(source, target)
    best = group.transformers[0]
    missing = []
    for operation in group.unavailable_operations:
        for grid in getattr(operation, "grids", []) or []:
            name = getattr(grid, "short_name", None) or str(grid)
            if name not in missing:
                missing.append(name)
    return {
        "source": source,
        "target": target,
        "best_name": best.name,
        "best_accuracy_m": best.accuracy,
        "best_available": bool(group.best_available),
        "available_operations": len(group.transformers),
        "unavailable_operations": len(group.unavailable_operations),
        "missing_grids": missing,
    }


def crs_crossing_scope(root: Path):
    """Task 3: an antimeridian-crossing archipelago and a polar layer must not be combined as-is."""
    west = [(179.40, -16.50), (180.0, -16.50), (180.0, -16.00), (179.40, -16.00), (179.40, -16.50)]
    east = [(-180.0, -16.50), (-179.55, -16.50), (-179.55, -16.00), (-180.0, -16.00), (-180.0, -16.50)]
    features = [
        {"type": "Feature", "properties": {"island": "west"}, "geometry": {"type": "Polygon", "coordinates": [west]}},
        {"type": "Feature", "properties": {"island": "east"}, "geometry": {"type": "Polygon", "coordinates": [east]}},
    ]
    archipelago = write_geojson(root / "archipelago.geojson", features)
    polar_coords = [
        [(-500000.0, -2200000.0), (-400000.0, -2200000.0), (-400000.0, -2100000.0), (-500000.0, -2100000.0)]
    ]
    polar = write_vector(
        root / "polar.gpkg",
        [shapely.Polygon(polar_coords[0])],
        crs="EPSG:3413",
        geometry_type="Polygon",
    )

    steps = [
        check_step("check archipelago.geojson --operation area", [archipelago], operation="area"),
        check_step("check archipelago.geojson polar.gpkg", [archipelago, polar]),
    ]
    oracle = Oracle("antimeridian span and cross-CRS combination of the supplied layers")
    longitudes = sorted({lon for ring in (west, east) for lon, _lat in ring})
    naive_span = max(longitudes) - min(longitudes)
    gaps = [longitudes[index + 1] - longitudes[index] for index in range(len(longitudes) - 1)]
    gaps.append(360.0 - naive_span)
    crossing_span = 360.0 - max(gaps)
    oracle.require(
        "a naive longitude range spans the long way around Earth",
        naive_span > 100 * crossing_span,
        round(naive_span, 3),
        "more than 100x the true crossing width",
    )
    oracle.close(
        "the true crossing width is about one degree",
        crossing_span,
        1.05,
        0.2,
        note="west ring 179.40..180.0 plus east ring -180.0..-179.55",
    )
    geod = pyproj.Geod(ellps="WGS84")
    geodesic_area = sum(
        abs(geod.geometry_area_perimeter(shapely.Polygon(ring))[0]) for ring in (west, east)
    )
    oracle.require(
        "the layers are in different CRS kinds (geographic degrees vs projected metres)",
        pyproj.CRS.from_user_input(GEOGRAPHIC).is_geographic
        and pyproj.CRS.from_user_input("EPSG:3413").axis_info[0].unit_name in ("metre", "meter"),
        {"archipelago": "EPSG:4326", "polar": "EPSG:3413"},
        "geographic vs projected",
    )
    oracle.equal("geodesic area of the archipelago is a positive quantity", geodesic_area > 0, True)
    consistent = results_for(steps, "crs.consistent")
    metric = results_for(steps, "crs.metric_operation")
    oracle.require(
        "crs.consistent fails on the mixed pair",
        bool(consistent) and all(result.status == "fail" for result in consistent),
        [result.status for result in consistent],
        "fail",
    )
    oracle.require(
        "crs.metric_operation fails on the geographic input",
        bool(metric) and all(result.status == "fail" for result in metric),
        [result.status for result in metric],
        "fail",
    )
    correct_control = correct(
        "crossing-and-polar-preflight",
        "A valid antimeridian-split archipelago in WGS 84 and a valid polar GeoPackage in EPSG:3413, "
        "checked with --operation area and as a pair.",
        steps,
        oracle,
    )

    relabelled = write_vector(
        root / "archipelago_relabelled.gpkg",
        [shapely.Polygon(west), shapely.Polygon(east)],
        crs="EPSG:6933",
        geometry_type="Polygon",
    )
    relabelled_area = sum(shapely.Polygon(ring).area for ring in (west, east))
    wrong_steps = [
        check_step("check archipelago_relabelled.gpkg --operation area", [relabelled], operation="area"),
    ]
    wrong_oracle = Oracle("relabelling degrees as an equal-area CRS does not make the area measurement valid")
    wrong_oracle.require(
        "the measured area is within 5% of the independent geodesic area",
        relative_difference(relabelled_area, geodesic_area) <= 0.05,
        round(relabelled_area, 3),
        round(geodesic_area, 3),
    )
    wrong_control = wrong(
        "relabelled-projected-crs",
        "The geographic coordinates are relabelled as EPSG:6933 without transforming them, so the "
        "metric-operation preflight no longer fails.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "crs-crossing-scope-preflight",
        correct_control,
        [wrong_control],
        automated_scope=[
            "crs.defined, crs.consistent and crs.metric_operation on the deliberately unsafe inputs",
            "independent antimeridian longitude-span calculation and a geodesic area reference",
        ],
        remaining=[
            "Antimeridian bbox/edge validation and projection-domain fitness are not implemented checks; the answer must explain them.",
            "Choosing separate equal-area or geodesic measurements for the two regions requires expert review.",
        ],
    )


RECIPES = {
    "crs-local-metric-buffer": crs_local_metric_buffer,
    "crs-axis-datum-control": crs_axis_datum,
    "crs-crossing-scope-preflight": crs_crossing_scope,
}
