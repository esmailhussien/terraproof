"""Geometry checks: geometry.valid, geometry.non_empty, geometry.type_consistent, geometry.winding."""

from __future__ import annotations

from terraproof.checks.base import FAIL, PASS, WARN, result

# Multi-part and single-part types count as one family, so Polygon + MultiPolygon is consistent.
GEOMETRY_FAMILY = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "LinearRing": "line",
    "MultiLineString": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
    "GeometryCollection": "collection",
}


def check_geometry(dataset: dict) -> list:
    path = dataset["path"]
    geometry = dataset["geometry"]
    results = []

    invalid = geometry["invalid_count"]
    if invalid:
        results.append(
            result(
                "geometry.valid",
                FAIL,
                f"{invalid} invalid geometries in {path}; first feature indices (0-based): "
                f"{geometry['invalid_indices']}.",
                input=path,
                invalid_count=invalid,
                first_invalid_indices=geometry["invalid_indices"],
            )
        )
    else:
        results.append(result("geometry.valid", PASS, f"All geometries in {path} are valid.", input=path))

    null_count, empty_count = geometry["null_count"], geometry["empty_count"]
    if null_count or empty_count:
        results.append(
            result(
                "geometry.non_empty",
                WARN,
                f"{path} has {null_count} null and {empty_count} empty geometries.",
                input=path,
                null_count=null_count,
                empty_count=empty_count,
                null_indices=geometry["null_indices"],
                empty_indices=geometry["empty_indices"],
            )
        )
    else:
        results.append(result("geometry.non_empty", PASS, f"No null or empty geometries in {path}.", input=path))

    counts = dataset["geometry_type_counts"]
    families = sorted({GEOMETRY_FAMILY.get(name, name) for name in counts})
    if len(families) > 1:
        results.append(
            result(
                "geometry.type_consistent",
                WARN,
                f"{path} mixes geometry families: {', '.join(families)}.",
                input=path,
                geometry_type_counts=counts,
                families=families,
            )
        )
    else:
        results.append(
            result("geometry.type_consistent", PASS, f"{path} has one geometry family.", input=path,
                   geometry_type_counts=counts)
        )

    # Only GeoJSON has a ring-orientation rule (RFC 7946); other drivers are not checked.
    winding = geometry.get("winding")
    if winding is not None:
        breaks = winding["right_hand_rule_break_count"]
        if breaks:
            results.append(
                result(
                    "geometry.winding",
                    FAIL,
                    f"{breaks} features in {path} break the RFC 7946 right-hand rule (exterior rings counterclockwise, "
                    f"holes clockwise); first feature indices (0-based): {winding['right_hand_rule_break_indices']}. "
                    "Rewrite the rings, e.g. with GDAL's RFC7946=YES layer option.",
                    input=path,
                    right_hand_rule_break_count=breaks,
                    first_break_indices=winding["right_hand_rule_break_indices"],
                )
            )
        else:
            results.append(
                result("geometry.winding", PASS, f"Polygon rings in {path} follow the RFC 7946 right-hand rule.", input=path)
            )
    return results
