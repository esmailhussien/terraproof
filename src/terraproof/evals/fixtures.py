"""Deterministic fixture writers for the benchmark tasks.

Every dataset is generated at run time inside a temporary directory; no binary fixture is
committed. Contents, array shapes, transforms and seeds are fixed so two runs produce the
same check statuses.

This module is production code: it must not import anything from `tests/`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pyogrio.raw
import rasterio
import shapely
from rasterio.enums import Resampling
from rasterio.transform import from_origin

UTM = "EPSG:32636"          # projected, metres
EQUAL_AREA = "EPSG:6933"    # projected equal-area, metres
GEOGRAPHIC = "EPSG:4326"    # longitude/latitude degrees

DEFAULT_ORIGIN = (500000.0, 5000000.0)
DEFAULT_RESOLUTION = 10.0
FLOAT_NODATA = -9999.0


def _nodata_for(array: np.ndarray) -> float:
    if array.dtype.kind == "f":
        return FLOAT_NODATA
    return float(np.iinfo(array.dtype).max)


def write_raster(
    path: str | os.PathLike,
    array,
    *,
    crs: str | None = UTM,
    origin: tuple[float, float] = DEFAULT_ORIGIN,
    resolution: float = DEFAULT_RESOLUTION,
    nodata="auto",
    scale: float | None = None,
    offset: float | None = None,
    tiled: bool = True,
    overviews: tuple[int, ...] | None = (2, 4),
    driver: str = "GTiff",
    dtype: str | None = None,
    blocksize: int = 256,
    compress: str = "deflate",
) -> str:
    """Write a one-band raster. `crs=None` writes a raster with no SRS."""
    path = Path(path)
    values = np.asarray(array)
    if values.ndim != 2:
        raise ValueError(f"write_raster expects a 2-D array, got shape {values.shape}")
    if dtype is not None:
        values = values.astype(dtype)
    if nodata == "auto":
        nodata = _nodata_for(values)
    profile = dict(
        driver=driver,
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=values.dtype.name,
        nodata=nodata,
        transform=from_origin(origin[0], origin[1], resolution, resolution),
    )
    if crs is not None:
        profile["crs"] = crs
    if tiled and driver == "GTiff":
        profile.update(tiled=True, blockxsize=blocksize, blockysize=blocksize)
    if compress and driver == "COG":
        profile.update(compress=compress, blocksize=min(blocksize, 512))
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values, 1)
        if scale is not None or offset is not None:
            dst.scales = (1.0 if scale is None else scale,)
            dst.offsets = (0.0 if offset is None else offset,)
    if overviews and driver == "GTiff":
        with rasterio.open(path, "r+") as dst:
            dst.build_overviews(list(overviews), Resampling.nearest)
    return str(path)


def write_cog(
    path: str | os.PathLike,
    array,
    *,
    crs: str = UTM,
    origin: tuple[float, float] = DEFAULT_ORIGIN,
    resolution: float = DEFAULT_RESOLUTION,
    nodata="auto",
    compress: str = "deflate",
    blocksize: int = 128,
) -> str:
    """Write a Cloud Optimized GeoTIFF with the GDAL COG driver (overviews are built by it)."""
    return write_raster(
        path,
        array,
        crs=crs,
        origin=origin,
        resolution=resolution,
        nodata=nodata,
        driver="COG",
        overviews=None,
        blocksize=blocksize,
        compress=compress,
    )


def write_vector(
    path: str | os.PathLike,
    geometries,
    *,
    crs: str | None = UTM,
    geometry_type: str = "Unknown",
    fields: list[str] | None = None,
    field_data: list | None = None,
    driver: str = "GPKG",
) -> str:
    """Write a vector layer. `crs=None` writes a layer with no declared SRS."""
    path = Path(path)
    wkb = [None if geom is None else shapely.to_wkb(geom) for geom in geometries]
    names = np.asarray(fields or [], dtype=object)
    columns = [np.asarray(column, dtype=object) for column in (field_data or [])]
    pyogrio.raw.write(
        str(path),
        wkb,
        columns,
        names,
        geometry_type=geometry_type,
        crs=crs,
        driver=driver,
    )
    return str(path)


def write_geojson(path: str | os.PathLike, features: list[dict], *, crs_member: dict | None = None) -> str:
    """Write a GeoJSON FeatureCollection. A missing `crs` member is read as EPSG:4326."""
    path = Path(path)
    document = {"type": "FeatureCollection", "features": features}
    if crs_member is not None:
        document["crs"] = crs_member
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def write_stac_item(
    path: str | os.PathLike,
    *,
    item_id: str,
    collection: str = "sentinel-2-l2a",
    datetime: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    bbox: list[float] | None = None,
    proj_code: str | None = "EPSG:32636",
    extra_properties: dict | None = None,
    assets: dict | None = None,
) -> str:
    """Write a local STAC Item JSON document."""
    path = Path(path)
    properties: dict = {}
    if datetime is not None:
        properties["datetime"] = datetime
    if start_datetime is not None and end_datetime is not None:
        properties["start_datetime"] = start_datetime
        properties["end_datetime"] = end_datetime
    if proj_code is not None:
        properties["proj:code"] = proj_code
    if extra_properties:
        properties.update(extra_properties)
    document = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": collection,
        "bbox": bbox or [30.0, 30.0, 30.2, 30.2],
        "geometry": None,
        "properties": properties,
        "links": [],
        "assets": assets or {},
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def write_csv(path: str | os.PathLike, header: list[str], rows: list[list]) -> str:
    path = Path(path)
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join("" if value is None else str(value) for value in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return str(path)


def write_gcp_only_vrt(path: str | os.PathLike, array, *, pixel_points: list[tuple[float, float]]) -> str:
    """Write a raster with ground control points and no CRS (ground-range-like geometry).

    rasterio refuses to write a GeoTIFF with GCPs but no CRS, so the outer dataset is a VRT
    whose GCPList carries the geolocation and whose source is a plain GeoTIFF.
    """
    path = Path(path)
    source = path.with_name(path.stem + "_source.tif")
    values = np.asarray(array)
    write_raster(source, values, crs=None, nodata=_nodata_for(values), tiled=False, overviews=None)
    gcps = "\n".join(
        f'    <GCP Id="{index + 1}" Pixel="{col}" Line="{row}" X="{x}" Y="{y}" Z="0" />'
        for index, (row, col, x, y) in enumerate(pixel_points)
    )
    path.write_text(
        f"""<VRTDataset rasterXSize="{values.shape[1]}" rasterYSize="{values.shape[0]}">
  <GCPList>
{gcps}
  </GCPList>
  <VRTRasterBand dataType="{values.dtype.name}" band="1">
    <SimpleSource>
      <SourceFilename relativeToVRT="0">{source.as_posix()}</SourceFilename>
      <SourceBand>1</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="{values.shape[1]}" ySize="{values.shape[0]}" />
      <DstRect xOff="0" yOff="0" xSize="{values.shape[1]}" ySize="{values.shape[0]}" />
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>
""",
        encoding="utf-8",
    )
    return str(path)


def read_raster(path: str | os.PathLike) -> np.ma.MaskedArray:
    """Read band 1 as a masked array, applying any declared scale/offset."""
    with rasterio.open(path) as src:
        return src.read(1, masked=True)


def read_transform(path: str | os.PathLike) -> list[float]:
    with rasterio.open(path) as src:
        return list(src.transform)[:6]


def read_features(path: str | os.PathLike, fields: list[str] | None = None):
    """Read geometries and the requested attribute columns from a vector layer (no pandas)."""
    meta, _fids, geoms, field_data = pyogrio.raw.read(str(path))
    names = [str(name) for name in meta["fields"]]
    columns = {name: field_data[index] for index, name in enumerate(names)}
    wanted = fields or names
    missing = [name for name in wanted if name not in columns]
    if missing:
        raise ValueError(f"{path} has no field(s): {missing}")
    return shapely.from_wkb(geoms), {name: columns[name] for name in wanted}
