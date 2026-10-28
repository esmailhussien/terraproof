"""Regression tests for reviewed false passes: a check must not pass when the data is wrong or unverifiable."""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Polygon

from terraproof.cli import main
from terraproof.evidence import ADVISORY, CHECKS_PASSED, REVIEW
from terraproof.inspect import inspect_raster


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def one(results, check_id):
    matches = [result for result in results if result.id == check_id]
    assert len(matches) == 1, f"expected one {check_id} result, got {[r.id for r in results]}"
    return matches[0]


# --- crs.metric_operation: only projected horizontal CRSs in metre or foot units pass ---


def test_geocentric_vector_fails_metric_operation(make_vector, evaluate):
    path = make_vector("ecef.gpkg", [square(500000, 5000000)], crs="EPSG:4978")

    results, grade = evaluate([path], operation="area")

    result = one(results, "crs.metric_operation")
    assert result.status == "fail"
    assert result.evidence["horizontal_kind"] == "geocentric"
    assert grade == ADVISORY


def test_geocentric_raster_fails_metric_operation(make_raster, evaluate):
    path = make_raster("ecef.tif", np.ones((64, 64), dtype="float32"), crs="EPSG:4978")

    results, grade = evaluate([path], operation="area")

    assert one(results, "crs.metric_operation").status == "fail"
    assert grade == ADVISORY


def test_projected_plus_vertical_compound_passes_metric_operation(make_vector, evaluate):
    path = make_vector("utm_height.gpkg", [square(500000, 5000000)], crs="EPSG:32636+5773")

    results, grade = evaluate([path], operation="area")

    result = one(results, "crs.metric_operation")
    assert result.status == "pass"
    assert result.evidence["horizontal_kind"] == "projected"
    assert grade == CHECKS_PASSED


def test_geographic_plus_vertical_compound_fails_metric_operation(make_vector, evaluate):
    path = make_vector("wgs84_height.gpkg", [square(30.0, 30.0, 0.01)], crs="EPSG:4326+5773")

    results, grade = evaluate([path], operation="buffer")

    assert one(results, "crs.metric_operation").status == "fail"
    assert grade == ADVISORY


def test_vertical_only_crs_warns_metric_operation(make_vector, evaluate):
    path = make_vector("height_only.gpkg", [square(500000, 5000000)], crs="EPSG:5773")

    results, grade = evaluate([path], operation="length")

    result = one(results, "crs.metric_operation")
    assert result.status == "warn"
    assert "cannot be confirmed" in result.message
    assert grade == REVIEW


def test_geocentric_vector_through_cli_exits_advisory(make_vector):
    path = make_vector("ecef_cli.gpkg", [square(500000, 5000000)], crs="EPSG:4978")

    assert main(["check", path, "--operation", "area"]) == 3


# --- rs.reflectance_range and rs.index_range: non-finite data never passes ---


def test_nan_scale_fails_reflectance_range(make_raster, evaluate):
    path = make_raster(
        "nan_scale_sr.tif", np.full((64, 64), 1000, dtype="uint16"), nodata=65535, scale=float("nan")
    )

    results, grade = evaluate([path], expect="reflectance")

    result = one(results, "rs.reflectance_range")
    assert result.status == "fail"
    assert "band 1" in result.message
    assert any("scale" in problem for problem in result.evidence["bands"][0]["non_finite_problems"])
    assert grade == ADVISORY


def test_nan_scale_fails_index_range(make_raster, evaluate):
    path = make_raster(
        "nan_scale_index.tif", np.full((64, 64), 1000, dtype="uint16"), nodata=65535, scale=float("nan")
    )

    results, grade = evaluate([path], expect="index")

    assert one(results, "rs.index_range").status == "fail"
    assert grade == ADVISORY


def test_nan_scale_is_reported_as_non_finite_by_inspector(make_raster):
    path = make_raster(
        "nan_scale_inspect.tif", np.full((64, 64), 1000, dtype="uint16"), nodata=65535, scale=float("nan")
    )

    band = inspect_raster(path)["bands"][0]

    assert math.isnan(band["scale"])
    assert band["decoded_finite"] is False
    assert band["stats"]["valid_sample_count"] == 64 * 64
    assert band["stats"]["nonfinite_count"] == 64 * 64


def test_infinite_decoded_values_fail_reflectance_range(make_raster, evaluate):
    # 1000 * 1e306 overflows float64 to +inf after scale is applied; the raw DN is finite.
    path = make_raster(
        "overflow_sr.tif", np.full((64, 64), 1000, dtype="uint16"), nodata=65535, scale=1e306, offset=0.0
    )

    results, grade = evaluate([path], expect="reflectance")

    result = one(results, "rs.reflectance_range")
    assert result.status == "fail"
    assert grade == ADVISORY


def test_infinite_decoded_values_fail_index_range(make_raster, evaluate):
    path = make_raster(
        "overflow_index.tif", np.full((64, 64), 1000, dtype="uint16"), nodata=65535, scale=1e306, offset=0.0
    )

    results, grade = evaluate([path], expect="index")

    assert one(results, "rs.index_range").status == "fail"
    assert grade == ADVISORY


def test_raw_infinite_pixels_fail_index_range(make_raster, evaluate):
    data = np.linspace(-1.0, 1.0, 64 * 64, dtype="float32").reshape(64, 64)
    data[0, 0] = np.inf
    path = make_raster("raw_inf_index.tif", data, nodata=-9999.0)

    results, grade = evaluate([path], expect="index")

    result = one(results, "rs.index_range")
    assert result.status == "fail"
    assert result.evidence["bands"][0]["nonfinite_count"] == 1
    assert grade == ADVISORY


def test_finite_scaled_reflectance_still_passes(make_raster, evaluate):
    path = make_raster(
        "finite_sr.tif", np.full((64, 64), 5000, dtype="uint16"), nodata=65535, scale=0.0001, offset=-0.1
    )

    results, grade = evaluate([path], expect="reflectance")

    assert one(results, "rs.reflectance_range").status == "pass"
    assert grade == CHECKS_PASSED


# --- raster.cog_layout: a layout heuristic that does not declare COG validity ---


def test_small_tiled_raster_without_overviews_passes_cog_layout(make_raster, evaluate):
    path = make_raster("small_cog.tif", np.ones((64, 64), dtype="float32"), tiled=True, overviews=False)

    results, grade = evaluate([path])

    result = one(results, "raster.cog_layout")
    assert result.status == "pass"
    assert result.evidence["fits_one_block"] is True
    assert "not Cloud Optimized GeoTIFF validation" in result.message
    assert grade == CHECKS_PASSED


def test_large_striped_raster_warns_cog_layout_with_heuristic_wording(make_raster, evaluate):
    path = make_raster("large_striped.tif", np.ones((512, 512), dtype="float32"), tiled=False, overviews=False)

    results, grade = evaluate([path])

    result = one(results, "raster.cog_layout")
    assert result.status == "warn"
    assert "not tiled (striped layout)" in result.message
    assert "no internal overviews" in result.message
    assert "COG validator" in result.message
    assert "not a valid" not in result.message
    assert grade == REVIEW


def test_large_tiled_raster_without_overviews_warns_cog_layout(make_raster, evaluate):
    path = make_raster("large_tiled.tif", np.ones((512, 512), dtype="float32"), tiled=True, overviews=False)

    results, grade = evaluate([path])

    result = one(results, "raster.cog_layout")
    assert result.status == "warn"
    assert "no internal overviews" in result.message
    assert "not tiled" not in result.message
    assert grade == REVIEW


# --- raster.cog_layout: lossy JPEG compression is not an analysis-value delivery ---


def _jpeg_tiff(path, data):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin

    profile = dict(driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype="uint8",
                   crs="EPSG:32636", transform=from_origin(500000, 5000000, 10, 10), nodata=0,
                   tiled=True, blockxsize=128, blockysize=128, compress="JPEG")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
        dst.build_overviews([2, 4], Resampling.average)
    return str(path)


def test_tiled_jpeg_raster_with_overviews_warns_cog_layout(tmp_path, evaluate):
    rows, cols = np.indices((256, 256))
    path = _jpeg_tiff(tmp_path / "lossy.tif", (40 + (rows // 8 + cols // 8) % 90).astype("uint8"))

    results, grade = evaluate([path])

    result = one(results, "raster.cog_layout")
    assert result.status == "warn"
    assert "lossy JPEG compression" in result.message
    assert result.evidence["compression"].lower() == "jpeg"
    assert grade == REVIEW


def test_deflate_raster_does_not_warn_about_lossy_compression(make_raster, evaluate):
    path = make_raster("deflate.tif", np.ones((64, 64), dtype="uint8"), overviews=False)

    results, _ = evaluate([path])

    result = one(results, "raster.cog_layout")
    assert result.status == "pass"
    assert "lossy" not in result.message


# --- geometry.winding: GeoJSON polygon rings must follow the RFC 7946 right-hand rule ---


def _polygon_feature(exterior, holes=()):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [exterior, *holes]}}


CCW_EXTERIOR = [[30.0, 30.0], [30.1, 30.0], [30.1, 30.1], [30.0, 30.1], [30.0, 30.0]]
CW_HOLE = [[30.02, 30.02], [30.02, 30.08], [30.08, 30.08], [30.08, 30.02], [30.02, 30.02]]


def test_clockwise_geojson_exterior_fails_winding(make_geojson, evaluate):
    document = {"type": "FeatureCollection", "features": [
        _polygon_feature(CCW_EXTERIOR),
        _polygon_feature(list(reversed(CCW_EXTERIOR))),
    ]}
    path = make_geojson("clockwise.geojson", document)

    results, grade = evaluate([path])

    result = one(results, "geometry.winding")
    assert result.status == "fail"
    assert result.evidence["first_break_indices"] == [1]
    assert one(results, "geometry.valid").status == "pass"
    assert grade == ADVISORY


def test_counterclockwise_hole_fails_winding(make_geojson, evaluate):
    document = {"type": "FeatureCollection", "features": [_polygon_feature(CCW_EXTERIOR, [list(reversed(CW_HOLE))])]}
    path = make_geojson("ccw_hole.geojson", document)

    results, _ = evaluate([path])

    assert one(results, "geometry.winding").status == "fail"


def test_right_hand_rule_geojson_passes_winding(make_geojson, evaluate):
    document = {"type": "FeatureCollection", "features": [_polygon_feature(CCW_EXTERIOR, [CW_HOLE])]}
    path = make_geojson("rfc7946.geojson", document)

    results, grade = evaluate([path])

    assert one(results, "geometry.winding").status == "pass"
    assert grade == CHECKS_PASSED


def test_winding_is_not_checked_outside_geojson(make_vector, evaluate):
    clockwise = Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])
    path = make_vector("clockwise.gpkg", [clockwise])

    results, _ = evaluate([path])

    assert [result for result in results if result.id == "geometry.winding"] == []
