"""Fixture factories. Every dataset is generated at test time inside tmp_path; no binary data is committed."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pyogrio.raw
import pytest
import rasterio
import shapely
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from shapely.geometry import Polygon

from terraproof.checks import run_checks
from terraproof.evidence import grade_for
from terraproof.inspect import inspect_dataset

UTM36 = "EPSG:32636"


def pytest_configure(config):
    """pytest does not create the parent of --basetemp (set in pyproject.toml); a fresh checkout has no .pytest_cache yet."""
    if config.option.basetemp:
        Path(config.option.basetemp).parent.mkdir(parents=True, exist_ok=True)


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


@pytest.fixture
def evaluate():
    """Inspect the inputs, run the checks, and return (results, grade)."""

    def _evaluate(paths, *, compare_to=None, **params):
        inspections = [inspect_dataset(path) for path in paths]
        compare = inspect_dataset(compare_to) if compare_to else None
        results = run_checks(inspections, compare_to=compare, **params)
        return results, grade_for(results)

    return _evaluate


@pytest.fixture
def make_vector(tmp_path):
    """Write a GeoPackage layer with the given geometries. crs=None writes a layer with no SRS."""

    def _make(name, geoms, *, crs=UTM36, geometry_type="Polygon"):
        path = tmp_path / name
        wkb = [shapely.to_wkb(geom) for geom in geoms]
        with warnings.catch_warnings():
            # pyogrio warns that a layer without a CRS is unusable elsewhere; that is the point of the fixture.
            warnings.simplefilter("ignore", UserWarning)
            pyogrio.raw.write(str(path), wkb, [], [], geometry_type=geometry_type, crs=crs, driver="GPKG")
        return str(path)

    return _make


@pytest.fixture
def make_geojson(tmp_path):
    """Write a GeoJSON file from raw text. A GeoJSON without a crs member is read as EPSG:4326."""

    def _make(name, document):
        path = tmp_path / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)

    return _make


@pytest.fixture
def make_raster(tmp_path):
    """Write a GeoTIFF. By default it is tiled, has overviews, and declares nodata, so checks pass unless a test breaks it."""

    def _make(
        name,
        data,
        *,
        crs=UTM36,
        origin=(500000.0, 5000000.0),
        resolution=10.0,
        nodata="auto",
        scale=None,
        offset=None,
        tiled=True,
        overviews=True,
    ):
        path = tmp_path / name
        array = np.asarray(data)
        if array.ndim == 2:
            array = array[np.newaxis]
        bands, height, width = array.shape
        if nodata == "auto":
            nodata = -9999.0 if array.dtype.kind == "f" else float(np.iinfo(array.dtype).max)
        profile = dict(
            driver="GTiff",
            width=width,
            height=height,
            count=bands,
            dtype=array.dtype.name,
            crs=crs,
            transform=from_origin(origin[0], origin[1], resolution, resolution),
            nodata=nodata,
        )
        if tiled:
            profile.update(tiled=True, blockxsize=256, blockysize=256)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(array)
            if scale is not None:
                dst.scales = (scale,) * bands
            if offset is not None:
                dst.offsets = (offset,) * bands
        if overviews:
            with rasterio.open(path, "r+") as dst:
                dst.build_overviews([2, 4], Resampling.nearest)
        return str(path)

    return _make


@pytest.fixture
def make_stac_item(tmp_path):
    """Write a local STAC Item JSON file."""

    def _make(name, properties, assets=None):
        document = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "S2A_TEST_ITEM",
            "collection": "sentinel-2-l2a",
            "bbox": [30.0, 30.0, 31.0, 31.0],
            "geometry": None,
            "properties": properties,
            "links": [],
            "assets": assets or {},
        }
        path = tmp_path / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)

    return _make
