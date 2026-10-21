"""Inspector tests: the description fields that checks and reports rely on."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import Polygon

from terraproof._common import InputError
from terraproof.inspect import inspect_dataset, inspect_raster, inspect_vector


def test_vector_description_has_crs_fields_and_geometry_counts(make_vector):
    polygon = Polygon([(500000, 5000000), (500010, 5000000), (500010, 5000010), (500000, 5000010)])
    path = make_vector("parcels.gpkg", [polygon, Polygon()])

    description = inspect_vector(path)

    assert description["kind"] == "vector"
    assert description["feature_count"] == 2
    assert description["geometry_types"] == ["Polygon"]
    assert description["crs"]["epsg"] == 32636
    assert description["crs"]["is_geographic"] is False
    assert description["crs"]["axis_units"] == "metre"
    assert description["crs"]["wkt"]
    assert description["geometry"]["empty_count"] == 1
    assert description["geometry"]["invalid_count"] == 0
    assert description["bounds"] == pytest.approx([500000.0, 5000000.0, 500010.0, 5000010.0])


def test_vector_null_field_values_are_counted(make_geojson):
    path = make_geojson(
        "fields.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"value": 1, "label": "a"},
                 "geometry": {"type": "Point", "coordinates": [30.0, 30.0]}},
                {"type": "Feature", "properties": {"value": None, "label": None},
                 "geometry": {"type": "Point", "coordinates": [30.1, 30.1]}},
                {"type": "Feature", "properties": {"value": 3, "label": "c"}, "geometry": None},
            ],
        },
    )

    description = inspect_vector(path)

    nulls = {field["name"]: field["null_count"] for field in description["fields"]}
    assert nulls == {"value": 1, "label": 1}
    assert description["geometry"]["null_count"] == 1
    assert description["geometry_type_counts"] == {"Point": 2}


def test_raster_reports_scale_offset_and_applied_statistics(make_raster):
    dn = np.full((64, 64), 1000, dtype="uint16")
    path = make_raster("scaled.tif", dn, scale=0.0001, offset=-0.1)

    description = inspect_raster(path)

    band = description["bands"][0]
    assert band["scale"] == pytest.approx(0.0001)
    assert band["offset"] == pytest.approx(-0.1)
    assert band["stats"]["valid_sample_count"] == 64 * 64
    assert band["stats"]["p99"] == pytest.approx(1000 * 0.0001 - 0.1)
    assert description["tiled"] is True
    assert description["compression"] is None


def test_raster_excludes_nodata_from_statistics(make_raster):
    data = np.array([[1.0, -9999.0], [2.0, 3.0]], dtype="float32")
    path = make_raster("holes.tif", data, nodata=-9999.0, tiled=False, overviews=False)

    band = inspect_raster(path)["bands"][0]

    assert band["stats"]["valid_sample_count"] == 3
    assert band["stats"]["min"] == pytest.approx(1.0)
    assert band["stats"]["max"] == pytest.approx(3.0)


def test_unsupported_extension_is_an_input_error(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")

    with pytest.raises(InputError, match="unsupported file type"):
        inspect_dataset(str(path))


def test_missing_file_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="file not found"):
        inspect_dataset(str(tmp_path / "missing.gpkg"))


def test_dispatch_picks_stac_for_json_items(make_stac_item):
    path = make_stac_item("item.json", {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636})

    assert inspect_dataset(path)["kind"] == "stac"
