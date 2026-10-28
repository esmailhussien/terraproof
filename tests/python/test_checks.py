"""Check-level tests: each seeded error must produce the expected check status and grade."""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from terraproof.evidence import ADVISORY, CHECKS_PASSED, REVIEW
from terraproof.inspect import inspect_stac_item


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def one(results, check_id):
    matches = [result for result in results if result.id == check_id]
    assert len(matches) == 1, f"expected one {check_id} result, got {[r.id for r in results]}"
    return matches[0]


def test_clean_projected_polygons_are_decision_grade(make_vector, evaluate):
    path = make_vector("parcels.gpkg", [square(500000, 5000000), square(500100, 5000100)])

    results, grade = evaluate([path], operation="area")

    assert one(results, "crs.metric_operation").status == "pass"
    assert one(results, "crs.defined").status == "pass"
    assert one(results, "geometry.valid").status == "pass"
    assert grade == CHECKS_PASSED


def test_vector_without_crs_fails_and_metric_operation_not_run(make_vector, evaluate):
    path = make_vector("no_crs.gpkg", [square(500000, 5000000)], crs=None)

    results, grade = evaluate([path], operation="buffer")

    assert one(results, "crs.defined").status == "fail"
    assert one(results, "crs.metric_operation").status == "not-run"
    assert grade == ADVISORY


def test_geographic_crs_fails_metric_buffer(make_vector, evaluate):
    path = make_vector("lonlat.gpkg", [square(30.0, 30.0, 0.01)], crs="EPSG:4326")

    results, grade = evaluate([path], operation="buffer")

    assert one(results, "crs.metric_operation").status == "fail"
    assert grade == ADVISORY


def test_self_intersecting_polygon_fails_geometry_valid(make_vector, evaluate):
    bow_tie = Polygon([(500000, 5000000), (500010, 5000010), (500010, 5000000), (500000, 5000010)])
    path = make_vector("bowtie.gpkg", [bow_tie, square(500100, 5000100)])

    results, grade = evaluate([path])

    result = one(results, "geometry.valid")
    assert result.status == "fail"
    assert result.evidence["first_invalid_indices"] == [0]
    assert grade == ADVISORY


def test_empty_geometry_warns_non_empty(make_vector, evaluate):
    path = make_vector("with_empty.gpkg", [square(500000, 5000000), Polygon()])

    results, grade = evaluate([path])

    result = one(results, "geometry.non_empty")
    assert result.status == "warn"
    assert result.evidence["empty_count"] == 1
    assert grade == REVIEW


def test_mixed_points_and_polygons_warn_type_consistent(make_geojson, evaluate):
    path = make_geojson(
        "mixed.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"id": 1},
                 "geometry": {"type": "Point", "coordinates": [30.0, 30.0]}},
                {"type": "Feature", "properties": {"id": 2},
                 "geometry": {"type": "Polygon",
                              "coordinates": [[[30, 30], [30.01, 30], [30.01, 30.01], [30, 30.01], [30, 30]]]}},
            ],
        },
    )

    results, grade = evaluate([path])

    assert one(results, "geometry.type_consistent").status == "warn"
    assert grade == REVIEW


def test_two_inputs_in_different_crs_fail_consistency(make_vector, evaluate):
    projected = make_vector("utm.gpkg", [square(500000, 5000000)], crs="EPSG:32636")
    geographic = make_vector("wgs84.gpkg", [square(30.0, 30.0, 0.01)], crs="EPSG:4326")

    results, grade = evaluate([projected, geographic])

    assert one(results, "crs.consistent").status == "fail"
    assert grade == ADVISORY


def test_output_with_fewer_features_warns_record_count(make_vector, evaluate):
    source = make_vector("source.gpkg", [square(500000, 5000000), square(500100, 5000000), square(500200, 5000000)])
    output = make_vector("output.gpkg", [square(500000, 5000000), square(500100, 5000000)])

    results, grade = evaluate([output], compare_to=source)

    result = one(results, "scope.record_count")
    assert result.status == "warn"
    assert result.evidence["output_count"] == 2
    assert result.evidence["compare_count"] == 3
    assert result.evidence["difference"] == -1
    assert grade == REVIEW


def test_raster_without_nodata_warns(make_raster, evaluate):
    path = make_raster("dem_no_nodata.tif", np.ones((64, 64), dtype="float32"), nodata=None)

    results, grade = evaluate([path])

    assert one(results, "raster.nodata_declared").status == "warn"
    assert grade == REVIEW


def test_categorical_bilinear_resampling_fails_and_nearest_passes(make_raster, evaluate):
    landcover = make_raster("landcover.tif", np.arange(64 * 64, dtype="uint8").reshape(64, 64) % 7)

    results, grade = evaluate([landcover], resampling="bilinear", categorical=True)
    assert one(results, "raster.resampling").status == "fail"
    assert grade == ADVISORY

    results, grade = evaluate([landcover], resampling="nearest", categorical=True)
    assert one(results, "raster.resampling").status == "pass"
    assert grade == CHECKS_PASSED


def test_half_pixel_offset_fails_grid_alignment(make_raster, evaluate):
    reference = make_raster("grid_a.tif", np.ones((64, 64), dtype="float32"), origin=(500000.0, 5000000.0))
    shifted = make_raster("grid_b.tif", np.ones((64, 64), dtype="float32"), origin=(500005.0, 5000000.0))

    results, grade = evaluate([reference, shifted])

    assert one(results, "raster.grid_alignment").status == "fail"
    assert grade == ADVISORY


def test_identical_grids_pass_grid_alignment(make_raster, evaluate):
    first = make_raster("same_a.tif", np.ones((64, 64), dtype="float32"))
    second = make_raster("same_b.tif", np.full((64, 64), 2.0, dtype="float32"))

    results, grade = evaluate([first, second])

    assert one(results, "raster.grid_alignment").status == "pass"
    assert grade == CHECKS_PASSED


def test_striped_geotiff_without_overviews_warns_cog_layout(make_raster, evaluate):
    path = make_raster("striped.tif", np.ones((512, 512), dtype="float32"), tiled=False, overviews=False)

    results, grade = evaluate([path])

    assert one(results, "raster.cog_layout").status == "warn"
    assert grade == REVIEW


def test_tiled_geotiff_with_overviews_passes_cog_layout(make_raster, evaluate):
    path = make_raster("cog.tif", np.ones((512, 512), dtype="float32"), tiled=True, overviews=True)

    results, grade = evaluate([path])

    assert one(results, "raster.cog_layout").status == "pass"
    assert grade == CHECKS_PASSED


def test_reflectance_stored_as_dn_fails(make_raster, evaluate):
    dn = make_raster("s2_dn.tif", np.linspace(0, 10000, 64 * 64).astype("uint16").reshape(64, 64),
                     nodata=65535)

    results, grade = evaluate([dn], expect="reflectance")

    result = one(results, "rs.reflectance_range")
    assert result.status == "fail"
    assert result.evidence["bands"][0]["p99"] > 1.5
    assert grade == ADVISORY


def test_reflectance_scaled_to_unit_range_passes(make_raster, evaluate):
    scaled = make_raster("s2_scaled.tif", np.linspace(0, 1, 64 * 64, dtype="float32").reshape(64, 64))

    results, grade = evaluate([scaled], expect="reflectance")

    assert one(results, "rs.reflectance_range").status == "pass"
    assert grade == CHECKS_PASSED


def test_index_values_above_one_fail(make_raster, evaluate):
    index = make_raster("ndvi_bad.tif", np.linspace(-1.0, 3.0, 64 * 64, dtype="float32").reshape(64, 64))

    results, grade = evaluate([index], expect="index")

    assert one(results, "rs.index_range").status == "fail"
    assert grade == ADVISORY


def test_index_values_within_range_pass(make_raster, evaluate):
    index = make_raster("ndvi_ok.tif", np.linspace(-1.0, 1.0, 64 * 64, dtype="float32").reshape(64, 64))

    results, grade = evaluate([index], expect="index")

    assert one(results, "rs.index_range").status == "pass"
    assert grade == CHECKS_PASSED


def test_stac_item_missing_datetime_warns_and_complete_item_passes(make_stac_item, evaluate):
    assets = {
        "B04": {
            "href": "B04.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "raster:bands": [{"scale": 0.0001, "offset": -0.1}],
        }
    }
    missing_time = make_stac_item("no_time.json", {"proj:epsg": 32636}, assets)
    complete = make_stac_item(
        "complete.json",
        {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636},
        assets,
    )

    results, grade = evaluate([missing_time])
    assert one(results, "stac.provenance").status == "warn"
    assert grade == REVIEW

    results, grade = evaluate([complete])
    assert one(results, "stac.provenance").status == "pass"
    assert grade == CHECKS_PASSED


def test_inspect_stac_item_returns_asset_scale_and_offset(make_stac_item):
    assets = {
        "B04": {
            "href": "B04.tif",
            "roles": ["data"],
            "raster:bands": [{"scale": 0.0001, "offset": -0.1}],
        }
    }
    path = make_stac_item("item.json", {"datetime": "2024-06-01T10:00:00Z", "proj:code": "EPSG:32636"}, assets)

    description = inspect_stac_item(path)

    assert description["id"] == "S2A_TEST_ITEM"
    assert description["datetime"] == "2024-06-01T10:00:00Z"
    assert description["assets"]["B04"]["bands"] == [{"scale": 0.0001, "offset": -0.1}]
