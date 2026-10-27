"""Independent scalar answers for the Phase 6 headroom cohort.

Each answer reopens the declared input files and their metadata (GeoTIFF tags, band units and
descriptions, STAC Items, catalogs) and computes every expected cell with scalar arithmetic in
a plain loop. Nothing here imports the recipes, reads a reference or seeded output, or calls
a Terraproof check. Geodesic quantities use pyproj's ellipsoidal `Geod`; the recipes use
closed-form spherical formulas, and the tolerances below accept both, so an Earth-model choice
is never what separates a right answer from a wrong one.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Geod

from terraproof.evals.oracles import Oracle

WGS84 = Geod(ellps="WGS84")
FOOT = 0.3048
KELVIN = 273.15
DEFAULT_TOLERANCE = (2e-06, 1e-06)  # (relative, absolute)
# Tolerances wider than float32 rounding, with the reason recorded beside each.
TOLERANCES = {
    "hr-forest-area-geographic": (0.01, 0.0),  # spherical vs ellipsoidal cell area differ by < 0.7%
    "hr-station-distance": (0.01, 0.0),  # spherical vs ellipsoidal distance differ by < 0.6%
    "hr-slope-geographic": (0.0, 0.25),  # degrees; Earth model and stencil choices differ by < 0.1 deg
    "hr-flood-depth-feet": (0.0, 1e-04),  # international vs US survey foot differ by 2 ppm
}


def _raster(path: Path) -> dict:
    with rasterio.open(path) as src:
        return {"data": src.read(), "nodata": src.nodata, "scales": src.scales, "offsets": src.offsets,
                "units": src.units, "descriptions": src.descriptions, "crs": src.crs,
                "transform": src.transform, "height": src.height, "width": src.width}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bitfield(item: dict, asset: str) -> dict:
    return {field["name"]: field for field in item["assets"][asset]["classification:bitfields"]}


def _flag(value: int, field: dict) -> int:
    return (int(value) >> field["offset"]) & ((1 << field["length"]) - 1)


def _band(item: dict, asset: str) -> dict:
    return item["assets"][asset]["raster:bands"][0]


def _blank(grid: dict):
    return np.zeros((grid["height"], grid["width"])), np.zeros((grid["height"], grid["width"]), dtype=bool)


def _cells(grid: dict):
    return product(range(grid["height"]), range(grid["width"]))


def _centre(grid: dict, row: int, col: int) -> tuple[float, float]:
    return grid["transform"] * (col + 0.5, row + 0.5)


def _containing(grid: dict, x: float, y: float) -> tuple[int, int]:
    col, row = ~grid["transform"] * (x, y)
    return int(math.floor(row)), int(math.floor(col))


def _unit_factor(unit: str) -> float:
    return {"m": 1.0, "metre": 1.0, "ft": FOOT, "foot": FOOT}[unit]


def _decoded(item: dict, asset: str, raster: dict, row: int, col: int, band: int = 0):
    """Calibrated value from STAC raster:bands, or None for the declared fill value."""
    meta = _band(item, asset)
    value = int(raster["data"][band, row, col])
    if value == meta["nodata"]:
        return None
    return value * meta.get("scale", 1.0) + meta.get("offset", 0.0)


# -- QA and SCL masking -----------------------------------------------------------------------
def _landsat_clear_red(root):
    item, red, qa = _json(root / "item.json"), _raster(root / "red.tif"), _raster(root / "qa_pixel.tif")
    bits = _bitfield(item, "qa_pixel")
    unusable = ("fill", "dilated_cloud", "cirrus", "cloud", "cloud_shadow", "snow")
    expected, valid = _blank(red)
    for r, c in _cells(red):
        value = _decoded(item, "red", red, r, c)
        if value is None or any(_flag(qa["data"][0, r, c], bits[name]) for name in unusable):
            continue
        expected[r, c], valid[r, c] = value, True
    return expected, valid, red


def _scl_classes(item: dict) -> dict[int, str]:
    return {entry["value"]: entry["name"] for entry in item["assets"]["scl"]["classification:classes"]}


SCL_USABLE = ("vegetation", "not_vegetated", "water")


def _s2_scl_red(root):
    item, red, scl = _json(root / "item.json"), _raster(root / "B04.tif"), _raster(root / "SCL.tif")
    names = _scl_classes(item)
    expected, valid = _blank(red)
    for r, c in _cells(red):
        value = _decoded(item, "red", red, r, c)
        if value is None or names.get(int(scl["data"][0, r, c])) not in SCL_USABLE:
            continue
        expected[r, c], valid[r, c] = value, True
    return expected, valid, red


def _hls_fmask_nir(root):
    item, nir, fmask = _json(root / "item.json"), _raster(root / "B8A.tif"), _raster(root / "Fmask.tif")
    bits = _bitfield(item, "fmask")
    unusable = ("cirrus", "cloud", "adjacent_to_cloud_or_shadow", "cloud_shadow", "snow_ice")
    expected, valid = _blank(nir)
    for r, c in _cells(nir):
        value = _decoded(item, "nir", nir, r, c)
        flags = int(fmask["data"][0, r, c])
        if value is None or flags == fmask["nodata"] or any(_flag(flags, bits[name]) for name in unusable):
            continue
        expected[r, c], valid[r, c] = value, True
    return expected, valid, nir


def _modis_lst_quality(root):
    item, lst, qc = _json(root / "item.json"), _raster(root / "LST_Day_1km.tif"), _raster(root / "QC_Day.tif")
    bits = _bitfield(item, "qc_day")
    expected, valid = _blank(lst)
    for r, c in _cells(lst):
        stored = int(lst["data"][0, r, c])
        flags = int(qc["data"][0, r, c])
        if stored == lst["nodata"]:
            continue
        if _flag(flags, bits["mandatory_qa"]) != 0 or _flag(flags, bits["lst_error"]) != 0:
            continue
        kelvin = stored * lst["scales"][0] + lst["offsets"][0]
        assert lst["units"][0] == "K"
        expected[r, c], valid[r, c] = kelvin - KELVIN, True
    return expected, valid, lst


def _landsat_red_saturation(root):
    item, red, radsat = _json(root / "item.json"), _raster(root / "red.tif"), _raster(root / "qa_radsat.tif")
    bits = _bitfield(item, "qa_radsat")
    band_name = item["assets"]["red"]["eo:bands"][0]["name"]  # "B4"
    field = bits[f"saturation_{band_name.lower()}"]
    expected, valid = _blank(red)
    for r, c in _cells(red):
        value = _decoded(item, "red", red, r, c)
        if value is None or _flag(radsat["data"][0, r, c], field):
            continue
        expected[r, c], valid[r, c] = value, True
    return expected, valid, red


def _s2_scl_20m_nir(root):
    item, nir, scl = _json(root / "item.json"), _raster(root / "B08.tif"), _raster(root / "SCL.tif")
    names = _scl_classes(item)
    expected, valid = _blank(nir)
    for r, c in _cells(nir):
        value = _decoded(item, "nir", nir, r, c)
        sr, sc = _containing(scl, *_centre(nir, r, c))
        if value is None or names.get(int(scl["data"][0, sr, sc])) not in SCL_USABLE:
            continue
        expected[r, c], valid[r, c] = value, True
    return expected, valid, nir


# -- scale, offset and processing baselines ---------------------------------------------------
def _s2_offset(item: dict) -> float:
    """BOA_ADD_OFFSET is -1000 DN from processing baseline 04.00 on, absent before."""
    major, minor = (int(part) for part in item["properties"]["s2:processing_baseline"].split("."))
    return -0.1 if (major, minor) >= (4, 0) else 0.0


def _s2_reflectance(item: dict, raster: dict, r: int, c: int):
    stored = int(raster["data"][0, r, c])
    if stored == 0:
        return None
    return stored / 10000 + _s2_offset(item)


def _s2_baseline_nir(root):
    item, nir = _json(root / "item.json"), _raster(root / "B08.tif")
    expected, valid = _blank(nir)
    for r, c in _cells(nir):
        value = _s2_reflectance(item, nir, r, c)
        if value is not None:
            expected[r, c], valid[r, c] = value, True
    return expected, valid, nir


def _s2_mixed_baseline_change(root):
    early, late = _raster(root / "B08_2021.tif"), _raster(root / "B08_2023.tif")
    early_item, late_item = _json(root / "item_2021.json"), _json(root / "item_2023.json")
    expected, valid = _blank(early)
    for r, c in _cells(early):
        before, after = _s2_reflectance(early_item, early, r, c), _s2_reflectance(late_item, late, r, c)
        if before is not None and after is not None:
            expected[r, c], valid[r, c] = after - before, True
    return expected, valid, early


def _landsat_surface_temperature(root):
    item, st = _json(root / "item.json"), _raster(root / "st_b10.tif")
    assert _band(item, "lwir11")["unit"] == "kelvin"
    expected, valid = _blank(st)
    for r, c in _cells(st):
        kelvin = _decoded(item, "lwir11", st, r, c)
        if kelvin is not None:
            expected[r, c], valid[r, c] = kelvin - KELVIN, True
    return expected, valid, st


def _reanalysis_air_temperature(root):
    t2m = _raster(root / "t2m.tif")
    assert t2m["units"][0] == "K"
    expected, valid = _blank(t2m)
    for r, c in _cells(t2m):
        stored = int(t2m["data"][0, r, c])
        if stored != t2m["nodata"]:
            expected[r, c], valid[r, c] = stored * t2m["scales"][0] + t2m["offsets"][0] - KELVIN, True
    return expected, valid, t2m


def _modis_ndvi_scaled(root):
    ndvi = _raster(root / "ndvi.tif")
    expected, valid = _blank(ndvi)
    for r, c in _cells(ndvi):
        stored = int(ndvi["data"][0, r, c])
        if stored != ndvi["nodata"]:
            expected[r, c], valid[r, c] = stored * ndvi["scales"][0] + ndvi["offsets"][0], True
    return expected, valid, ndvi


def _hls_nir_reflectance(root):
    item, nir = _json(root / "item.json"), _raster(root / "B8A.tif")
    expected, valid = _blank(nir)
    for r, c in _cells(nir):
        value = _decoded(item, "nir", nir, r, c)
        if value is not None:
            expected[r, c], valid[r, c] = value, True
    return expected, valid, nir


# -- nodata stored as zero (and zero that is data) ---------------------------------------------
def _landsat_undeclared_fill(root):
    item, red = _json(root / "item.json"), _raster(root / "red.tif")
    expected, valid = _blank(red)
    for r, c in _cells(red):
        value = _decoded(item, "red", red, r, c)  # the fill value comes from the Item, not the file
        if value is not None:
            expected[r, c], valid[r, c] = value, True
    return expected, valid, red


def _strip_mosaic(root):
    strips = [_raster(root / name) for name in ("strip_a.tif", "strip_b.tif")]
    expected, valid = _blank(strips[0])
    for r, c in _cells(strips[0]):
        values = [float(s["data"][0, r, c]) for s in strips if float(s["data"][0, r, c]) != s["nodata"]]
        if values:
            expected[r, c], valid[r, c] = sum(values) / len(values), True
    return expected, valid, strips[0]


def _rainfall_dry_days(root):
    days = [_raster(root / f"rain_day{index}.tif") for index in (1, 2, 3)]
    expected, valid = _blank(days[0])
    for r, c in _cells(days[0]):
        values = [float(d["data"][0, r, c]) for d in days if float(d["data"][0, r, c]) != d["nodata"]]
        if len(values) == len(days):
            expected[r, c], valid[r, c] = sum(values) / len(values), True
    return expected, valid, days[0]


def _fill_values(item: dict, asset: str) -> set[int]:
    return {entry["value"] for entry in item["assets"][asset]["classification:classes"] if entry.get("nodata")}


def _landcover_change_fill(root):
    first, second = _raster(root / "landcover_2019.tif"), _raster(root / "landcover_2023.tif")
    items = _json(root / "item_2019.json"), _json(root / "item_2023.json")
    fill = [_fill_values(items[0], "landcover"), _fill_values(items[1], "landcover")]
    expected, valid = _blank(first)
    for r, c in _cells(first):
        a, b = int(first["data"][0, r, c]), int(second["data"][0, r, c])
        if a in fill[0] or b in fill[1]:
            continue
        expected[r, c], valid[r, c] = (1 if a != b else 0), True
    return expected, valid, first


def _s2_ndwi_footprint(root):
    item, green, nir = _json(root / "item.json"), _raster(root / "B03.tif"), _raster(root / "B08.tif")
    expected, valid = _blank(green)
    for r, c in _cells(green):
        g, n = _decoded(item, "green", green, r, c), _decoded(item, "nir", nir, r, c)
        if g is None or n is None or abs(g + n) <= 1e-12:
            continue
        expected[r, c], valid[r, c] = (g - n) / (g + n), True
    return expected, valid, green


def _coarsen_reflectance_fill(root):
    fine, grid = _raster(root / "red_10m.tif"), _raster(root / "target_grid.tif")
    expected, valid = _blank(grid)
    sums: dict[tuple[int, int], list[float]] = {}
    for r, c in _cells(fine):
        value = float(fine["data"][0, r, c])
        if value == fine["nodata"]:
            continue
        sums.setdefault(_containing(grid, *_centre(fine, r, c)), []).append(value)
    for (r, c), values in sums.items():
        expected[r, c], valid[r, c] = sum(values) / len(values), True
    return expected, valid, grid


# -- dtype overflow ----------------------------------------------------------------------------
def _ndvi_8bit(root):
    red, nir = _raster(root / "red.tif"), _raster(root / "nir.tif")
    expected, valid = _blank(red)
    for r, c in _cells(red):
        a, b = int(red["data"][0, r, c]), int(nir["data"][0, r, c])
        if a == red["nodata"] or b == nir["nodata"] or a + b == 0:
            continue
        expected[r, c], valid[r, c] = (b - a) / (b + a), True
    return expected, valid, red


def _visible_brightness_sum(root):
    bands = _raster(root / "visible.tif")
    expected, valid = _blank(bands)
    for r, c in _cells(bands):
        values = [int(bands["data"][i, r, c]) for i in range(bands["data"].shape[0])]
        if any(value == bands["nodata"] for value in values):
            continue
        expected[r, c], valid[r, c] = sum(values), True
    return expected, valid, bands


def _three_date_mean_8bit(root):
    dates = [_raster(root / f"brightness_{index}.tif") for index in (1, 2, 3)]
    expected, valid = _blank(dates[0])
    for r, c in _cells(dates[0]):
        values = [int(d["data"][0, r, c]) for d in dates if int(d["data"][0, r, c]) != d["nodata"]]
        if len(values) == len(dates):
            expected[r, c], valid[r, c] = sum(values) / len(values), True
    return expected, valid, dates[0]


# -- categorical resampling -------------------------------------------------------------------
def _containing_class(root, source_name: str):
    source, grid = _raster(root / source_name), _raster(root / "target_grid.tif")
    expected, valid = _blank(grid)
    for r, c in _cells(grid):
        sr, sc = _containing(source, *_centre(grid, r, c))
        label = int(source["data"][0, sr, sc])
        if label != source["nodata"]:
            expected[r, c], valid[r, c] = label, True
    return expected, valid, grid


def _landcover_upsample(root):
    return _containing_class(root, "landcover_30m.tif")


def _landcover_shifted_grid(root):
    return _containing_class(root, "landcover.tif")


def _landcover_dominant_class(root):
    source, grid = _raster(root / "landcover_10m.tif"), _raster(root / "target_grid.tif")
    expected, valid = _blank(grid)
    votes: dict[tuple[int, int], dict[int, int]] = {}
    for r, c in _cells(source):
        label = int(source["data"][0, r, c])
        if label == source["nodata"]:
            continue
        cell = votes.setdefault(_containing(grid, *_centre(source, r, c)), {})
        cell[label] = cell.get(label, 0) + 1
    for (r, c), counts in votes.items():
        ranked = sorted(counts.values(), reverse=True)
        assert len(ranked) == 1 or ranked[0] > ranked[1], "fixture must not contain ties"
        expected[r, c], valid[r, c] = max(counts, key=counts.get), True
    return expected, valid, grid


# -- metric work in a geographic CRS -----------------------------------------------------------
def _forest_area_geographic(root):
    forest = _raster(root / "forest_fraction.tif")
    assert forest["crs"].to_epsg() == 4326
    expected, valid = _blank(forest)
    t = forest["transform"]
    for r, c in _cells(forest):
        fraction = float(forest["data"][0, r, c])
        if fraction == forest["nodata"]:
            continue
        west, north = t * (c, r)
        east, south = t * (c + 1, r + 1)
        area, _ = WGS84.polygon_area_perimeter([west, east, east, west], [south, south, north, north])
        expected[r, c], valid[r, c] = fraction * abs(area) / 10000, True
    return expected, valid, forest


def _slope_geographic(root):
    dem = _raster(root / "dem.tif")
    assert dem["crs"].to_epsg() == 4326 and dem["units"][0] in ("m", "metre")
    expected, valid = _blank(dem)
    for r, c in _cells(dem):
        if r in (0, dem["height"] - 1) or c in (0, dem["width"] - 1):
            continue
        west, east = _centre(dem, r, c - 1), _centre(dem, r, c + 1)
        north, south = _centre(dem, r - 1, c), _centre(dem, r + 1, c)
        _, _, dx = WGS84.inv(*west, *east)
        _, _, dy = WGS84.inv(*north, *south)
        gx = (float(dem["data"][0, r, c + 1]) - float(dem["data"][0, r, c - 1])) / dx
        gy = (float(dem["data"][0, r - 1, c]) - float(dem["data"][0, r + 1, c])) / dy
        expected[r, c], valid[r, c] = math.degrees(math.atan(math.hypot(gx, gy))), True
    return expected, valid, dem


def _station_distance(root):
    grid = _raster(root / "grid.tif")
    station = _json(root / "station.geojson")["features"][0]["geometry"]["coordinates"]
    expected, valid = _blank(grid)
    for r, c in _cells(grid):
        _, _, metres = WGS84.inv(*_centre(grid, r, c), station[0], station[1])
        expected[r, c], valid[r, c] = metres / 1000, True
    return expected, valid, grid


# -- vertical units ----------------------------------------------------------------------------
FLOOD_LEVEL_M = 12.0  # stated in the task prompt


def _flood_depth_feet(root):
    dem = _raster(root / "dem.tif")
    factor = _unit_factor(dem["units"][0])
    expected, valid = _blank(dem)
    for r, c in _cells(dem):
        stored = float(dem["data"][0, r, c])
        if stored == dem["nodata"]:
            continue
        expected[r, c], valid[r, c] = max(0.0, FLOOD_LEVEL_M - stored * factor), True
    return expected, valid, dem


def _orthometric_height(root):
    heights, geoid = _raster(root / "heights.tif"), _raster(root / "geoid.tif")
    assert "ellipsoid" in heights["descriptions"][0] and "undulation" in geoid["descriptions"][0]
    expected, valid = _blank(heights)
    for r, c in _cells(heights):
        h, n = float(heights["data"][0, r, c]), float(geoid["data"][0, r, c])
        if h == heights["nodata"] or n == geoid["nodata"]:
            continue
        expected[r, c], valid[r, c] = h - n, True
    return expected, valid, heights


def _elevation_change_mixed_units(root):
    early, late = _raster(root / "dem_2015.tif"), _raster(root / "dem_2023.tif")
    f_early, f_late = _unit_factor(early["units"][0]), _unit_factor(late["units"][0])
    expected, valid = _blank(early)
    for r, c in _cells(early):
        a, b = float(early["data"][0, r, c]), float(late["data"][0, r, c])
        if a == early["nodata"] or b == late["nodata"]:
            continue
        expected[r, c], valid[r, c] = b * f_late - a * f_early, True
    return expected, valid, early


# -- dB versus linear --------------------------------------------------------------------------
def _sar_change_ratio(root):
    first, second = _raster(root / "vv_2023.tif"), _raster(root / "vv_2024.tif")
    assert first["units"][0] == second["units"][0] == "dB"
    expected, valid = _blank(first)
    for r, c in _cells(first):
        a, b = float(first["data"][0, r, c]), float(second["data"][0, r, c])
        if a == first["nodata"] or b == second["nodata"]:
            continue
        power_ratio = 10 ** (b / 10) / 10 ** (a / 10)
        expected[r, c], valid[r, c] = 10 * math.log10(power_ratio), True
    return expected, valid, first


def _sar_boxcar_db(root):
    vv = _raster(root / "vv_db.tif")
    assert vv["units"][0] == "dB"
    expected, valid = _blank(vv)
    for r, c in _cells(vv):
        if r in (0, vv["height"] - 1) or c in (0, vv["width"] - 1):
            continue
        window = [float(vv["data"][0, r + dr, c + dc]) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
        if any(value == vv["nodata"] for value in window):
            continue
        power = sum(10 ** (value / 10) for value in window) / len(window)
        expected[r, c], valid[r, c] = 10 * math.log10(power), True
    return expected, valid, vv


def _sar_amplitude_db(root):
    vv = _raster(root / "vv_amplitude.tif")
    assert vv["units"][0] == "amplitude"
    expected, valid = _blank(vv)
    for r, c in _cells(vv):
        amplitude = float(vv["data"][0, r, c])
        if amplitude == vv["nodata"] or amplitude <= 0:
            continue
        expected[r, c], valid[r, c] = 10 * math.log10(amplitude * amplitude), True
    return expected, valid, vv


# -- temporal scope ----------------------------------------------------------------------------
def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _july_median_ndvi(root):
    scenes = []
    for index in range(1, 6):
        when = _instant(_json(root / f"scene-{index}.json")["properties"]["datetime"])
        if (when.year, when.month) == (2024, 7):
            scenes.append(_raster(root / f"scene-{index}.tif"))
    expected, valid = _blank(scenes[0])
    for r, c in _cells(scenes[0]):
        values = sorted(float(s["data"][0, r, c]) for s in scenes if float(s["data"][0, r, c]) != s["nodata"])
        if not values:
            continue
        middle = len(values) // 2
        expected[r, c] = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        valid[r, c] = True
    return expected, valid, scenes[0]


def _interval_total(root, start: datetime, end: datetime):
    catalog = _json(root / "catalog.json")
    chosen = []
    for feature in catalog["features"]:
        properties = feature["properties"]
        first, last = _instant(properties["start_datetime"]), _instant(properties["end_datetime"])
        if first >= start and last <= end:
            chosen.append(_raster(root / feature["assets"]["data"]["href"]))
        else:
            assert last <= start or first >= end, "fixture accumulations never straddle the requested window"
    expected, valid = _blank(chosen[0])
    for r, c in _cells(chosen[0]):
        values = [float(a["data"][0, r, c]) for a in chosen]
        if any(value == a["nodata"] for value, a in zip(values, chosen)):
            continue
        expected[r, c], valid[r, c] = sum(values), True
    return expected, valid, chosen[0]


def _cairo_day_rainfall(root):
    cairo = timezone(timedelta(hours=2))  # Egypt kept EET (UTC+2) until daylight time began on 26 April 2024
    start = datetime(2024, 3, 5, tzinfo=cairo)
    return _interval_total(root, start, start + timedelta(days=1))


def _dekad_rainfall(root):
    return _interval_total(root, datetime(2024, 5, 11, tzinfo=timezone.utc), datetime(2024, 5, 21, tzinfo=timezone.utc))


ANSWERS = {
    "hr-landsat-clear-red": _landsat_clear_red,
    "hr-s2-scl-red": _s2_scl_red,
    "hr-hls-fmask-nir": _hls_fmask_nir,
    "hr-modis-lst-quality": _modis_lst_quality,
    "hr-landsat-red-saturation": _landsat_red_saturation,
    "hr-s2-scl-20m-nir": _s2_scl_20m_nir,
    "hr-s2-baseline-nir": _s2_baseline_nir,
    "hr-s2-mixed-baseline-change": _s2_mixed_baseline_change,
    "hr-landsat-surface-temperature": _landsat_surface_temperature,
    "hr-reanalysis-air-temperature": _reanalysis_air_temperature,
    "hr-modis-ndvi-scaled": _modis_ndvi_scaled,
    "hr-hls-nir-reflectance": _hls_nir_reflectance,
    "hr-landsat-undeclared-fill": _landsat_undeclared_fill,
    "hr-strip-mosaic": _strip_mosaic,
    "hr-rainfall-dry-days": _rainfall_dry_days,
    "hr-landcover-change-fill": _landcover_change_fill,
    "hr-s2-ndwi-footprint": _s2_ndwi_footprint,
    "hr-coarsen-reflectance-fill": _coarsen_reflectance_fill,
    "hr-ndvi-8bit": _ndvi_8bit,
    "hr-visible-brightness-sum": _visible_brightness_sum,
    "hr-three-date-mean-8bit": _three_date_mean_8bit,
    "hr-landcover-upsample": _landcover_upsample,
    "hr-landcover-shifted-grid": _landcover_shifted_grid,
    "hr-landcover-dominant-class": _landcover_dominant_class,
    "hr-forest-area-geographic": _forest_area_geographic,
    "hr-slope-geographic": _slope_geographic,
    "hr-station-distance": _station_distance,
    "hr-flood-depth-feet": _flood_depth_feet,
    "hr-orthometric-height": _orthometric_height,
    "hr-elevation-change-mixed-units": _elevation_change_mixed_units,
    "hr-sar-change-ratio": _sar_change_ratio,
    "hr-sar-boxcar-db": _sar_boxcar_db,
    "hr-sar-amplitude-db": _sar_amplitude_db,
    "hr-july-median-ndvi": _july_median_ndvi,
    "hr-cairo-day-rainfall": _cairo_day_rainfall,
    "hr-dekad-rainfall": _dekad_rainfall,
}


def grade(task_id: str, root: Path, delivered) -> Oracle:
    """Compare every delivered cell, the full validity mask and the grid with the scalar answer."""
    expected, valid, grid = ANSWERS[task_id](Path(root))
    got = _raster(Path(delivered))
    oracle = Oracle("Every delivered cell, validity and spatial metadata against independent input arithmetic")
    shape = (1, *expected.shape)
    oracle.equal("delivered band count and shape", got["data"].shape, shape)
    oracle.require("delivered CRS", got["crs"] == grid["crs"], str(got["crs"]), str(grid["crs"]))
    oracle.equal("delivered affine grid", tuple(got["transform"]), tuple(grid["transform"]))
    if got["data"].shape != shape:
        return oracle
    values = got["data"][0].astype("float64")
    observed_valid = np.ones(expected.shape, dtype=bool) if got["nodata"] is None else ~np.isclose(
        values, got["nodata"], rtol=0, atol=0)
    if got["nodata"] is not None and math.isnan(got["nodata"]):
        observed_valid = ~np.isnan(values)
    oracle.equal("full delivered mask equals required support", int(np.count_nonzero(observed_valid != valid)), 0)
    rtol, atol = TOLERANCES.get(task_id, DEFAULT_TOLERANCE)
    matches = np.isfinite(values) & np.isclose(values, expected, rtol=rtol, atol=atol)
    oracle.equal("all supported delivered pixels match independent values", int(np.count_nonzero(valid & ~matches)), 0)
    return oracle
