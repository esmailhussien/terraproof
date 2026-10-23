"""Fixtures and oracles for the `vector-quality` task specs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyproj
import shapely

from terraproof.evals.fixtures import UTM, read_features, write_geojson, write_vector
from terraproof.evals.oracles import Oracle
from terraproof.evals.recipes._util import check_step, correct, recipe, results_for, wrong


def _ids(path: str, field: str = "pid") -> list:
    _geoms, fields = read_features(path, fields=[field])
    return [str(value) for value in fields[field]]


def vector_repair_inventory(root: Path):
    """Task 1: an inventory with invalid, null, empty and mixed-family geometries."""
    bowtie = shapely.Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
    intended_bowtie = shapely.box(0, 0, 10, 10)  # the parcel the bow-tie was meant to describe
    collapsed = shapely.Polygon([(20, 10), (20, 20), (20, 10)])
    valid_a = shapely.box(30, 0, 40, 10)
    valid_b = shapely.MultiPolygon([shapely.box(50, 0, 60, 5), shapely.box(60, 5, 70, 10)])
    point = shapely.Point(35, 5)
    geometries = [bowtie, collapsed, None, shapely.Polygon(), valid_a, valid_b, point]
    parcels = write_vector(
        root / "parcels.gpkg",
        geometries,
        crs=UTM,
        geometry_type="Unknown",
        fields=["pid", "owner"],
        field_data=[
            np.array([f"P{index}" for index in range(1, 8)], dtype=object),
            np.array(["a", None, "c", "d", "e", None, "g"], dtype=object),
        ],
    )

    steps = [check_step("check parcels.gpkg", [parcels])]
    oracle = Oracle("repair inventory: counts, dimensions and the intended repair regions")
    expected_invalid = 2
    expected_null = 1
    expected_empty = 1
    oracle.equal("invalid geometries", sum(1 for geom in geometries if geom is not None and not shapely.is_valid(geom)), expected_invalid)
    oracle.equal("null geometries", sum(1 for geom in geometries if geom is None), expected_null)
    oracle.equal("empty geometries", sum(1 for geom in geometries if geom is not None and shapely.is_empty(geom)), expected_empty)
    families = {"polygon", "point"}
    oracle.equal("geometry families present", families, {"polygon", "point"})
    oracle.require(
        "the bow-tie is invalid and a make_valid repair changes its dimension/area",
        not shapely.is_valid(bowtie) and shapely.make_valid(bowtie).area != intended_bowtie.area,
        {"make_valid_area": shapely.make_valid(bowtie).area, "intended_area": intended_bowtie.area},
        "repair does not recover the intended 100 m2 region",
    )
    collapsed_fix = shapely.make_valid(collapsed)
    oracle.require(
        "the collapsed ring repairs to a lower-dimensional geometry",
        shapely.get_dimensions(collapsed_fix) < 2,
        shapely.get_type_id(collapsed_fix).item(),
        "dimension < 2 (points/line, not a polygon)",
    )
    valid_count = results_for(steps, "geometry.valid")
    non_empty = results_for(steps, "geometry.non_empty")
    type_consistent = results_for(steps, "geometry.type_consistent")
    oracle.require(
        "geometry.valid fails on the seeded inventory",
        bool(valid_count) and valid_count[0].status == "fail",
        valid_count[0].status if valid_count else None,
        "fail",
    )
    oracle.require(
        "geometry.non_empty warns about null and empty records",
        bool(non_empty) and non_empty[0].status == "warn",
        non_empty[0].status if non_empty else None,
        "warn",
    )
    oracle.require(
        "geometry.type_consistent warns about the mixed families",
        bool(type_consistent) and type_consistent[0].status == "warn",
        type_consistent[0].status if type_consistent else None,
        "warn",
    )
    correct_control = correct(
        "repair-inventory",
        "A GeoPackage with a bow-tie, a collapsed ring, a null geometry, an empty polygon, valid "
        "polygons/multipolygons and a valid point.",
        steps,
        oracle,
    )

    repaired = write_vector(
        root / "parcels_repaired.gpkg",
        [shapely.make_valid(bowtie), valid_a, valid_b],
        crs=UTM,
        geometry_type="Unknown",
        fields=["pid"],
        field_data=[np.array(["P1", "P5", "P6"], dtype=object)],
    )
    wrong_steps = [check_step("check parcels_repaired.gpkg", [repaired])]
    wrong_oracle = Oracle("a valid-looking repair must still account for every original record")
    repaired_ids = _ids(repaired)
    wrong_oracle.equal("original parcel ids retained", sorted(repaired_ids), sorted([f"P{index}" for index in range(1, 8)]))
    wrong_oracle.require(
        "the bow-tie repair keeps the intended parcel region",
        abs(shapely.make_valid(bowtie).area - intended_bowtie.area) < 0.5,
        shapely.make_valid(bowtie).area,
        intended_bowtie.area,
    )
    wrong_oracle.require(
        "the collapsed record is not silently dropped",
        len(repaired_ids) == 7,
        len(repaired_ids),
        7,
    )
    wrong_control = wrong(
        "silent-repair-drop",
        "The layer is rewritten with make_valid geometry and the null, empty and collapsed records are "
        "dropped, so every per-feature check passes.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "vector-repair-inventory",
        correct_control,
        [wrong_control],
        automated_scope=[
            "geometry.valid, geometry.non_empty and geometry.type_consistent on the seeded input inventory",
            "independent shapely counts and a make_valid repair ledger showing area loss and dimension drops",
        ],
        remaining=[
            "The proposed repair ledger and the decision to keep or drop each record are written deliverables; the harness does not grade them.",
            "Review against the authoritative intended parcel regions.",
        ],
    )


def vector_coverage(root: Path):
    """Task 2: individually valid polygons with coverage defects."""
    boundary = shapely.box(0, 0, 200, 200)
    hole = shapely.box(40, 40, 60, 60)
    z1 = shapely.Polygon(
        [(0, 0), (120, 0), (120, 200), (0, 200), (0, 0)],
        [[(40, 40), (40, 60), (60, 60), (60, 40), (40, 40)]],
    )
    z2 = shapely.box(110, 0, 200, 120)
    z3 = shapely.box(110, 120, 190, 200)  # leaves a gap at x 190..200
    sliver = shapely.box(120, 0, 120.2, 120)
    duplicate = shapely.Polygon([(190, 200), (110, 200), (110, 120), (190, 120), (190, 200)])
    zones = [z1, z2, z3, sliver, duplicate]
    zone_path = write_vector(
        root / "zones.gpkg",
        zones,
        crs=UTM,
        geometry_type="Polygon",
        fields=["zone_id", "label"],
        field_data=[
            np.array(["Z1", "Z2", "Z3", "Z4", "Z5"], dtype=object),
            np.array(["a", "b", "c", "sliver", "duplicate"], dtype=object),
        ],
    )

    steps = [check_step("check zones.gpkg", [zone_path])]
    oracle = Oracle("coverage topology that per-feature validity cannot see")
    union = shapely.union_all(zones)
    overlap = z1.intersection(z2).area
    gap = boundary.difference(union).difference(hole).area
    oracle.require(
        "every zone is individually valid",
        all(shapely.is_valid(zone) for zone in zones),
        [shapely.is_valid(zone) for zone in zones],
        [True] * len(zones),
    )
    oracle.close("positive-area overlap between Z1 and Z2 (m2)", overlap, 1200.0, 0.5)
    oracle.close("uncovered boundary strip excluding the authorised hole (m2)", gap, 800.0, 0.5)
    oracle.close(
        "the authorised hole is kept as an interior ring (m2)",
        shapely.Polygon(z1.exterior).area - z1.area,
        hole.area,
        0.5,
    )
    oracle.close("narrow overlay sliver area (m2)", sliver.area, 24.0, 0.01)
    duplicate_pairs = [
        (index, other)
        for index, zone in enumerate(zones)
        for other in range(index + 1, len(zones))
        if shapely.equals(zone, zones[other]) and shapely.to_wkb(zone) != shapely.to_wkb(zones[other])
    ]
    oracle.equal("topologically duplicate zones with different WKB", len(duplicate_pairs), 1)
    for check_id, expected in (
        ("geometry.valid", "pass"),
        ("geometry.non_empty", "pass"),
        ("geometry.type_consistent", "pass"),
    ):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} passes despite the coverage defects",
            bool(observed) and all(result.status == expected for result in observed),
            [result.status for result in observed],
            expected,
        )
    correct_control = correct(
        "valid-features-coverage-defects",
        "Five individually valid polygons with an overlap, a boundary gap, an authorised interior hole, "
        "a sliver and a topologically duplicate shape.",
        steps,
        oracle,
    )

    dissolved = write_vector(
        root / "zones_dissolved.gpkg",
        [shapely.union_all(zones)],
        crs=UTM,
        geometry_type="Polygon",
        fields=["zone_id"],
        field_data=[np.array(["all"], dtype=object)],
    )
    wrong_steps = [check_step("check zones_dissolved.gpkg", [dissolved])]
    wrong_oracle = Oracle("dissolving away zone identities loses the coverage ledger")
    wrong_oracle.equal("zone ids retained", _ids(dissolved, "zone_id"), ["Z1", "Z2", "Z3", "Z4", "Z5"])
    wrong_oracle.close(
        "overlap measured between distinct zones (m2)",
        max(zone.intersection(other).area for index, zone in enumerate(zones) for other in zones[index + 1 :]),
        1200.0,
        0.5,
    )
    wrong_control = wrong(
        "dissolve-away-identities",
        "All zones are dissolved into one polygon, which removes the overlap and gap but also every "
        "zone identity.",
        wrong_steps,
        wrong_oracle,
        notes="The per-feature checks still pass, so the checker alone cannot see the lost identities.",
    )
    return recipe(
        "vector-coverage-and-duplicates",
        correct_control,
        [wrong_control],
        automated_scope=[
            "geometry.valid, geometry.non_empty and geometry.type_consistent on the individually valid coverage",
            "independent overlap, gap, hole, sliver and topology-duplicate measurements",
            "confirmation that the checks pass although coverage topology is defective",
        ],
        remaining=[
            "Overlap/gap/sliver policy and the legitimacy of co-located records need review; coverage topology is not an implemented check.",
            "The answer must state the limits of per-feature validity; the harness cannot grade prose.",
        ],
    )


def _project_geometry(geometry, transformer):
    def _transform(coordinates):
        lon, lat = transformer.transform(coordinates[:, 0], coordinates[:, 1])
        return np.column_stack([lon, lat])

    return shapely.transform(geometry, _transform)


def _winding_export(root: Path, *, counterclockwise: bool) -> str:
    """Write a WGS 84 GeoJSON of the corrected parcels with the requested ring winding."""
    from shapely.geometry import mapping
    from shapely.geometry.polygon import orient

    transformer = pyproj.Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)
    features = []
    for parcel_id, geometry in _corrected_parcels():
        lonlat = _project_geometry(geometry, transformer)
        oriented = orient(lonlat, sign=1.0 if counterclockwise else -1.0)
        features.append(
            {"type": "Feature", "properties": {"pid": parcel_id}, "geometry": mapping(oriented)}
        )
    return write_geojson(root / ("parcels_correct.geojson" if counterclockwise else "parcels_cw.geojson"), features)


def _corrected_parcels() -> list[tuple[str, shapely.Polygon]]:
    parcels = []
    for index in range(1, 7):
        origin_x = 10.0 * index
        outer = shapely.box(origin_x, 0, origin_x + 8, 8)
        hole = shapely.box(origin_x + 2, 2, origin_x + 4, 4)
        parcels.append((f"P{index}", shapely.Polygon(outer.exterior.coords, [hole.exterior.coords])))
    return parcels


def vector_join_scope(root: Path):
    """Task 3: a legacy inner join that looks complete and an RFC 7946 GeoJSON export."""
    parcels = write_vector(
        root / "parcels.gpkg",
        [geometry for _pid, geometry in _corrected_parcels()],
        crs=UTM,
        geometry_type="Polygon",
        fields=["pid"],
        field_data=[np.array([pid for pid, _geometry in _corrected_parcels()], dtype=object)],
    )
    writes = []
    for index, (pid, geometry) in enumerate(_corrected_parcels()):
        if pid in {"P3", "P5"}:
            continue
        writes.append((pid, geometry))
    legacy = write_vector(
        root / "legacy_join.gpkg",
        [geometry for _pid, geometry in writes],
        crs=UTM,
        geometry_type="Polygon",
        fields=["pid", "owner"],
        field_data=[
            np.array([pid for pid, _geometry in writes], dtype=object),
            np.array(["owner-1", "owner-2", "owner-4", "owner-6"], dtype=object),
        ],
    )

    steps = [check_step("check legacy_join.gpkg --compare-to parcels.gpkg", [legacy], compare_to=parcels)]
    oracle = Oracle("join scope: preserved ids, duplicate/null keys and RFC 7946 winding")
    parcel_ids = [pid for pid, _geometry in _corrected_parcels()]
    legacy_ids = _ids(legacy)
    oracle.equal("parcel ids in the source layer", parcel_ids, [f"P{index}" for index in range(1, 7)])
    oracle.equal("source parcels unmatched by the legacy output", sorted(set(parcel_ids) - set(legacy_ids)), ["P3", "P5"])
    oracle.equal("legacy output ids", legacy_ids, ["P1", "P2", "P4", "P6"])
    corrected = write_vector(
        root / "parcels_owner_join.gpkg",
        [geometry for _pid, geometry in _corrected_parcels()],
        crs=UTM,
        geometry_type="Polygon",
        fields=["pid", "owner"],
        field_data=[
            np.array(parcel_ids, dtype=object),
            np.array(["owner-1", "owner-2", "owner-3", "owner-4", None, "owner-6"], dtype=object),
        ],
    )
    corrected_ids = _ids(corrected)
    _geoms, corrected_fields = read_features(corrected, fields=["pid", "owner"])
    owners = [None if value is None else str(value) for value in corrected_fields["owner"]]
    oracle.equal("the reviewed left join keeps every parcel id", corrected_ids, parcel_ids)
    oracle.equal("the unmatched parcel has an explicit null owner", owners[4], None)
    oracle.equal("the duplicate owner key is resolved to one explicit policy", owners.count("owner-2"), 1)
    oracle.require(
        "the null join key is reported, not dropped",
        "P3" in corrected_ids,
        corrected_ids,
        "P3 present",
    )
    export = _winding_export(root, counterclockwise=True)
    geoms, field_data = read_features(export, fields=["pid"])
    exported_ids = [str(value) for value in field_data["pid"]]
    oracle.equal("exported GeoJSON keeps every parcel id", sorted(exported_ids), sorted(parcel_ids))
    ccw_exteriors = all(shapely.is_ccw(geom.exterior) for geom in geoms)
    cw_holes = all(not shapely.is_ccw(interior) for geom in geoms for interior in geom.interiors)
    oracle.require("GeoJSON exteriors are counterclockwise", ccw_exteriors, ccw_exteriors, True)
    oracle.require("GeoJSON holes are clockwise", cw_holes, cw_holes, True)
    lonlat_bounds = shapely.total_bounds(geoms)
    oracle.require(
        "GeoJSON coordinates are longitude/latitude degrees",
        -180 <= lonlat_bounds[0] <= 180 and -180 <= lonlat_bounds[2] <= 180,
        [round(value, 6) for value in lonlat_bounds],
        "all longitudes within [-180, 180]",
    )
    record_count = results_for(steps, "scope.record_count")
    oracle.require(
        "scope.record_count warns about the missing records",
        bool(record_count) and record_count[0].status == "warn",
        record_count[0].status if record_count else None,
        "warn",
    )
    correct_control = correct(
        "legacy-inner-join",
        "A valid six-parcel layer and a legacy inner-join output with four records, plus a corrected "
        "left-join GeoJSON export with counterclockwise exteriors and clockwise holes.",
        steps,
        oracle,
    )

    padded = write_vector(
        root / "legacy_join_padded.gpkg",
        [geometry for _pid, geometry in writes] + [_corrected_parcels()[1][1], _corrected_parcels()[0][1]],
        crs=UTM,
        geometry_type="Polygon",
        fields=["pid", "owner"],
        field_data=[
            np.array([pid for pid, _geometry in writes] + ["P2", "P1"], dtype=object),
            np.array(["owner-1", "owner-2", "owner-4", "owner-6", "owner-2", "owner-1"], dtype=object),
        ],
    )
    wrong_steps = [check_step("check legacy_join_padded.gpkg --compare-to parcels.gpkg", [padded], compare_to=parcels)]
    wrong_oracle = Oracle("equal record counts can hide record substitution")
    wrong_oracle.equal("padded output ids", _ids(padded), ["P1", "P2", "P4", "P6", "P2", "P1"])
    wrong_oracle.equal(
        "the set of parcel ids is preserved",
        sorted(set(_ids(padded))) == sorted(set(parcel_ids)),
        sorted(set(_ids(padded))) == sorted(set(parcel_ids)),
        True,
    )
    wrong_oracle.require(
        "the unmatched parcel P5 is present exactly once",
        _ids(padded).count("P5") == 1,
        _ids(padded).count("P5"),
        1,
    )
    wrong_controls = [
        wrong(
            "padded-record-substitution",
            "The legacy output is padded with a duplicate parcel so the total count matches the source, "
            "while P5 is still missing.",
            wrong_steps,
            wrong_oracle,
        )
    ]

    clockwise_export = _winding_export(root, counterclockwise=False)
    cw_geoms, _fields = read_features(clockwise_export, fields=["pid"])
    cw_steps = [
        check_step("check legacy_join.gpkg --compare-to parcels.gpkg", [legacy], compare_to=parcels),
        check_step("check parcels_cw.geojson", [clockwise_export]),
    ]
    cw_oracle = Oracle("RFC 7946 ring winding is not an implemented check")
    cw_oracle.require(
        "GeoJSON exteriors are counterclockwise",
        all(shapely.is_ccw(geom.exterior) for geom in cw_geoms),
        [bool(shapely.is_ccw(geom.exterior)) for geom in cw_geoms],
        True,
    )
    wrong_controls.append(
        wrong(
            "clockwise-geojson-winding",
            "A complete GeoJSON export with clockwise exteriors; the geometry checks still pass.",
            cw_steps,
            cw_oracle,
            notes="The checker cannot see ring winding, so only the oracle rejects this artifact.",
        )
    )
    return recipe(
        "vector-join-scope-and-geojson",
        correct_control,
        wrong_controls,
        automated_scope=[
            "geometry.valid, geometry.non_empty and scope.record_count on the seeded legacy join",
            "independent id-set, duplicate/null-key, winding and coordinate-range checks on the corrected export",
        ],
        remaining=[
            "The owner-resolution policy and the legacy-join diagnosis are written deliverables; the harness does not grade them.",
            "Review of the join semantics against the owner table and parcel registry.",
        ],
    )


RECIPES = {
    "vector-repair-inventory": vector_repair_inventory,
    "vector-coverage-and-duplicates": vector_coverage,
    "vector-join-scope-and-geojson": vector_join_scope,
}
