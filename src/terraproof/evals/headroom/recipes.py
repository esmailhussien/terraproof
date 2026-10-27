"""Reference solutions and seeded mistakes for the Phase 6 headroom cohort.

Each recipe writes the task's inputs (rasters with their own metadata, STAC Items, catalogs),
builds the reference deliverable and one or more seeded-wrong deliverables with array
operations, and grades each through the separate scalar oracle in `headroom.oracles`.
Rasters are written through `fixtures.write_raster_grid` looked up at call time, so the lift
harness can substitute an agent's file for the deliverable.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

from terraproof.evals import fixtures
from terraproof.evals.headroom.oracles import grade
from terraproof.evals.recipes._util import check_step, correct, recipe, wrong

UTM = "EPSG:32636"
GEOGRAPHIC = "EPSG:4326"
NODATA = -9999.0
N = 12
GRID = from_origin(500000, 5000000, 10, 10)
R, C = np.indices((N, N))
EARTH_RADIUS = 6371007.2  # authalic sphere, used by the closed-form references only


def _raster(root: Path, name: str, data, *, transform=GRID, crs=UTM, nodata=NODATA, **metadata) -> str:
    return fixtures.write_raster_grid(root / name, data, transform=transform, crs=crs, nodata=nodata, **metadata)


def _json(root: Path, name: str, document: dict) -> None:
    (root / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _item(item_id: str, collection: str, when: str, assets: dict, **properties) -> dict:
    return {"type": "Feature", "stac_version": "1.0.0", "id": item_id, "collection": collection,
            "bbox": [33.0, 45.1, 33.002, 45.102], "geometry": None,
            "properties": {"datetime": when, "proj:code": UTM, **properties}, "links": [], "assets": assets}


def _asset(href: str, **fields) -> dict:
    return {"href": href, "type": "image/tiff; application=geotiff", **fields}


def _bitfields(*fields: tuple[str, int, int]) -> list[dict]:
    return [{"name": name, "offset": offset, "length": length} for name, offset, length in fields]


def _finish(root: Path, task_id: str, expected, valid, mistakes, *, transform=GRID, crs=UTM,
            dtype="float32", nodata=NODATA):
    """Write the reference and each seeded mistake, check them, and grade them with the oracle."""

    def control(name, values, support, is_wrong):
        data = np.where(support, values, nodata).astype(dtype)
        path = _raster(root, name + ".tif", data, transform=transform, crs=crs, nodata=nodata)
        steps = [check_step(f"check {name}.tif", [path])]
        build = wrong if is_wrong else correct
        return build(name, "Synthetic headroom artifact graded cell by cell from the declared inputs and metadata.",
                     steps, grade(task_id, root, path))

    reference = control("result", expected, valid, False)
    seeded = [control(name, values, support, True) for name, values, support in mistakes]
    return recipe(task_id, reference, seeded,
                  automated_scope=["Every delivered pixel and the full validity mask against independent scalar "
                                   "arithmetic on the inputs and their metadata; grid, dtype and nodata contract."],
                  remaining=["Difficulty for a live agent is unmeasured until the approved E2-E6 runs; this is an "
                             "offline synthetic task, not scientific certification."])


# -- QA and SCL masking -----------------------------------------------------------------------
LANDSAT_SCALE, LANDSAT_OFFSET = 2.75e-05, -0.2
LANDSAT_QA_FIELDS = _bitfields(("fill", 0, 1), ("dilated_cloud", 1, 1), ("cirrus", 2, 1), ("cloud", 3, 1),
                               ("cloud_shadow", 4, 1), ("snow", 5, 1), ("clear", 6, 1), ("water", 7, 1),
                               ("cloud_confidence", 8, 2), ("cloud_shadow_confidence", 10, 2),
                               ("snow_ice_confidence", 12, 2), ("cirrus_confidence", 14, 2))


def _landsat_dn():
    dn = (7273 + 310 * ((3 * R + 5 * C) % 37)).astype("uint16")
    dn[0, :3] = 0
    return dn


def landsat_clear_red(root):
    dn = _landsat_dn()
    qa = np.full((N, N), 21824, dtype="uint16")  # clear, low confidences
    qa[0, :3] = 1
    qa[2:4, 2:5] = 22280  # cloud, high confidence
    qa[4, 2:6] = 21762  # dilated cloud
    qa[6, 1:5] = 21840  # cloud shadow while the clear bit is still set
    qa[7, 6:9] = 21856  # snow while the clear bit is still set
    qa[9, 2:5] = 54596  # cirrus while the clear bit is still set
    qa[8:11, 8:11] = 21952  # water
    _raster(root, "red.tif", dn, nodata=0)
    _raster(root, "qa_pixel.tif", qa, nodata=1)
    _json(root, "item.json", _item("LC09_L2SP_177029_20240614_02_T1", "landsat-c2-l2", "2024-06-14T08:41:12Z", {
        "red": _asset("red.tif", **{"eo:bands": [{"name": "B4", "common_name": "red"}],
                                    "raster:bands": [{"nodata": 0, "data_type": "uint16", "scale": LANDSAT_SCALE,
                                                      "offset": LANDSAT_OFFSET, "unit": "reflectance"}]}),
        "qa_pixel": _asset("qa_pixel.tif", **{"classification:bitfields": LANDSAT_QA_FIELDS}),
    }, platform="landsat-9"))
    sr = dn.astype("float64") * LANDSAT_SCALE + LANDSAT_OFFSET
    bad = (qa & 0b111111) != 0
    valid = (dn != 0) & ~bad
    clear_only = (dn != 0) & ((qa & 64) != 0)
    water_masked = valid & ((qa & 128) == 0)
    return _finish(root, "hr-landsat-clear-red", sr, valid, [
        ("clear-bit-only", sr, clear_only), ("water-masked", sr, water_masked), ("unscaled", dn, valid)])


S2_SCL_CLASSES = [{"value": v, "name": n, **({"nodata": True} if v == 0 else {})} for v, n in (
    (0, "no_data"), (1, "saturated_or_defective"), (2, "dark_area_pixels"), (3, "cloud_shadows"),
    (4, "vegetation"), (5, "not_vegetated"), (6, "water"), (7, "unclassified"), (8, "cloud_medium_probability"),
    (9, "cloud_high_probability"), (10, "thin_cirrus"), (11, "snow"))]


def _s2_band(href: str, name: str, common: str, *, offset=-0.1, nodata=0) -> dict:
    return _asset(href, **{"eo:bands": [{"name": name, "common_name": common}],
                           "raster:bands": [{"nodata": nodata, "data_type": "uint16", "scale": 0.0001, "offset": offset}]})


def _scl_layout(shape):
    rows, cols = np.indices(shape)
    scl = np.where((rows + cols) % 3 == 0, 5, 4).astype("uint8")
    return scl


def s2_scl_red(root):
    dn = (1200 + 45 * ((2 * R + 7 * C) % 41)).astype("uint16")
    dn[11, 9:] = 0
    scl = _scl_layout((N, N))
    scl[8:12, 0:4] = 6
    scl[1:3, 1:5] = 9
    scl[3, 1:5] = 8
    scl[5, 6:10] = 3
    scl[6, 9:12] = 10
    scl[9, 6:9] = 11
    scl[0, 9:12] = 1
    scl[11, 9:] = 0
    _raster(root, "B04.tif", dn, nodata=0)
    _raster(root, "SCL.tif", scl, nodata=0)
    _json(root, "item.json", _item("S2B_MSIL2A_20240617T083559_N0510_R064_T36TWR", "sentinel-2-l2a",
                                   "2024-06-17T08:35:59Z", {"red": _s2_band("B04.tif", "B04", "red"),
                                                            "scl": _asset("SCL.tif", **{"classification:classes": S2_SCL_CLASSES})},
                                   **{"s2:processing_baseline": "05.10"}))
    sr = dn.astype("float64") * 0.0001 - 0.1
    valid = (dn != 0) & np.isin(scl, (4, 5, 6))
    clouds_only = (dn != 0) & ~np.isin(scl, (0, 8, 9, 10))
    return _finish(root, "hr-s2-scl-red", sr, valid, [
        ("clouds-only", sr, clouds_only), ("no-offset", dn * 0.0001, valid)])


HLS_FMASK_FIELDS = _bitfields(("cirrus", 0, 1), ("cloud", 1, 1), ("adjacent_to_cloud_or_shadow", 2, 1),
                              ("cloud_shadow", 3, 1), ("snow_ice", 4, 1), ("water", 5, 1), ("aerosol_level", 6, 2))


def hls_fmask_nir(root):
    dn = (1800 + 70 * ((5 * R + 3 * C) % 43)).astype("int16")
    dn[11, :2] = -9999
    fmask = np.full((N, N), 64, dtype="uint8")  # low aerosol, nothing else flagged
    fmask[0:3, 8:12] = 96  # water
    fmask[3, 8:12] = 100  # water next to cloud
    fmask[5:7, 1:4] = 66  # cloud
    fmask[4, 1:5] = 68  # adjacent to cloud
    fmask[7, 1:5] = 72  # cloud shadow
    fmask[9, 6:9] = 80  # snow/ice
    fmask[10, 3:6] = 65  # cirrus
    fmask[11, :2] = 255
    _raster(root, "B8A.tif", dn, nodata=-9999)
    _raster(root, "Fmask.tif", fmask, nodata=255)
    _json(root, "item.json", _item("HLS.S30.T36TWR.2024169T083559.v2.0", "HLSS30_2.0", "2024-06-17T08:35:59Z", {
        "nir": _asset("B8A.tif", **{"eo:bands": [{"name": "B8A", "common_name": "nir08"}],
                                    "raster:bands": [{"nodata": -9999, "data_type": "int16", "scale": 0.0001, "offset": 0}]}),
        "fmask": _asset("Fmask.tif", **{"raster:bands": [{"nodata": 255, "data_type": "uint8"}],
                                        "classification:bitfields": HLS_FMASK_FIELDS}),
    }))
    sr = dn.astype("float64") * 0.0001
    present = (dn != -9999) & (fmask != 255)
    valid = present & ((fmask & 0b11111) == 0)
    water_masked = present & ((fmask & 0b111111) == 0)
    adjacent_kept = present & ((fmask & 0b11011) == 0)
    return _finish(root, "hr-hls-fmask-nir", sr, valid, [
        ("water-masked", sr, water_masked), ("adjacent-kept", sr, adjacent_kept)])


MODIS_QC_FIELDS = _bitfields(("mandatory_qa", 0, 2), ("data_quality", 2, 2), ("emissivity_error", 4, 2),
                             ("lst_error", 6, 2))


def modis_lst_quality(root):
    dn = (14400 + 23 * ((4 * R + 9 * C) % 53)).astype("uint16")
    qc = np.zeros((N, N), dtype="uint8")
    qc[1:3, 1:6] = 1  # other quality, LST error <= 1 K
    qc[4, 2:8] = 64  # good mandatory QA, LST error <= 2 K
    qc[6:8, 6:10] = 2  # not produced, cloud
    qc[9, 1:4] = 3  # not produced, other
    qc[10, 7:11] = 129  # other quality, LST error <= 3 K
    dn[(qc == 2) | (qc == 3)] = 0
    _raster(root, "LST_Day_1km.tif", dn, nodata=0, scales=[0.02], offsets=[0.0], unit="K",
            descriptions=("Daytime Land Surface Temperature",))
    _raster(root, "QC_Day.tif", qc, nodata=None, descriptions=("Quality control for daytime LST and emissivity",))
    _json(root, "item.json", _item("MOD11A1.A2024169.h21v04.061", "modis-11A1-061", "2024-06-17T00:00:00Z", {
        "lst_day_1km": _asset("LST_Day_1km.tif"),
        "qc_day": _asset("QC_Day.tif", **{"classification:bitfields": MODIS_QC_FIELDS}),
    }))
    kelvin = dn.astype("float64") * 0.02
    produced = dn != 0
    valid = produced & ((qc & 3) == 0) & ((qc >> 6) == 0)
    return _finish(root, "hr-modis-lst-quality", kelvin - 273.15, valid, [
        ("kelvin", kelvin, valid), ("mandatory-only", kelvin - 273.15, produced & ((qc & 3) == 0)),
        ("lst-error-only", kelvin - 273.15, produced & ((qc >> 6) == 0))])


LANDSAT_RADSAT_FIELDS = _bitfields(*[(f"saturation_b{band}", band - 1, 1) for band in range(1, 8)],
                                   ("saturation_b9", 8, 1), ("terrain_occlusion", 11, 1))


def landsat_red_saturation(root):
    dn = _landsat_dn()
    dn[3:5, 3:7] = 65000
    radsat = np.zeros((N, N), dtype="uint16")
    radsat[3:5, 3:7] = 8  # red (band 4) saturated
    radsat[6, 2:9] = 16  # NIR (band 5) saturated only
    radsat[8, 1:5] = 4  # green (band 3) saturated only
    radsat[10, 6:10] = 24  # red and NIR saturated
    _raster(root, "red.tif", dn, nodata=0)
    _raster(root, "qa_radsat.tif", radsat, nodata=None)
    _json(root, "item.json", _item("LC08_L2SP_177029_20240622_02_T1", "landsat-c2-l2", "2024-06-22T08:41:05Z", {
        "red": _asset("red.tif", **{"eo:bands": [{"name": "B4", "common_name": "red"}],
                                    "raster:bands": [{"nodata": 0, "data_type": "uint16", "scale": LANDSAT_SCALE,
                                                      "offset": LANDSAT_OFFSET}]}),
        "qa_radsat": _asset("qa_radsat.tif", **{"classification:bitfields": LANDSAT_RADSAT_FIELDS}),
    }, platform="landsat-8"))
    sr = dn.astype("float64") * LANDSAT_SCALE + LANDSAT_OFFSET
    present = dn != 0
    valid = present & ((radsat & 8) == 0)
    return _finish(root, "hr-landsat-red-saturation", sr, valid, [
        ("any-band-saturation", sr, present & (radsat == 0)), ("off-by-one-bit", sr, present & ((radsat & 16) == 0))])


def s2_scl_20m_nir(root):
    dn = (2400 + 52 * ((3 * R + 4 * C) % 47)).astype("uint16")
    rows, cols = np.indices((6, 6))
    scl = np.where((rows + 2 * cols) % 4 == 0, 5, 4).astype("uint8")
    scl[0:2, 3:5] = 9
    scl[3, 0:2] = 3
    scl[4, 4] = 8
    scl[5, 1:3] = 6
    scl[2, 5] = 11
    scl_grid = from_origin(500000, 5000000, 20, 20)
    _raster(root, "B08.tif", dn, nodata=0)
    _raster(root, "SCL.tif", scl, transform=scl_grid, nodata=0)
    _json(root, "item.json", _item("S2A_MSIL2A_20240620T083601_N0510_R064_T36TWR", "sentinel-2-l2a",
                                   "2024-06-20T08:36:01Z", {"nir": _s2_band("B08.tif", "B08", "nir"),
                                                            "scl": _asset("SCL.tif", gsd=20, **{"classification:classes": S2_SCL_CLASSES})},
                                   **{"s2:processing_baseline": "05.10"}))
    sr = dn.astype("float64") * 0.0001 - 0.1
    scl_10m = np.kron(scl, np.ones((2, 2), dtype="uint8"))
    valid = np.isin(scl_10m, (4, 5, 6))
    smooth = np.zeros((N, N), dtype="float32")
    reproject(scl.astype("float32"), smooth, src_transform=scl_grid, src_crs=UTM, dst_transform=GRID, dst_crs=UTM,
              resampling=Resampling.bilinear)
    bilinear_valid = np.isin(np.rint(smooth), (4, 5, 6))
    clouds_only = ~np.isin(scl_10m, (8, 9, 10))
    return _finish(root, "hr-s2-scl-20m-nir", sr, valid, [
        ("bilinear-scl", sr, bilinear_valid), ("clouds-only", sr, clouds_only)])


# -- scale, offset and processing baselines ---------------------------------------------------
def s2_baseline_nir(root):
    dn = (2100 + 61 * ((2 * R + 3 * C) % 59)).astype("uint16")
    dn[:2, 10:] = 0
    _raster(root, "B08.tif", dn, nodata=0)
    _json(root, "item.json", _item("S2B_MSIL2A_20240707T083559_N0511_R064_T36TWR", "sentinel-2-l2a",
                                   "2024-07-07T08:35:59Z", {"nir": _s2_band("B08.tif", "B08", "nir")},
                                   **{"s2:processing_baseline": "05.11"}))
    sr = dn.astype("float64") * 0.0001 - 0.1
    valid = dn != 0
    return _finish(root, "hr-s2-baseline-nir", sr, valid, [
        ("no-offset", dn * 0.0001, valid), ("fill-decoded", sr, np.ones((N, N), bool))])


def s2_mixed_baseline_change(root):
    early = (2600 + 40 * ((R + 2 * C) % 31)).astype("uint16")
    late = (early.astype("int32") + 1000 - 25 * ((R * C) % 7)).astype("uint16")
    early[11, :3] = 0
    late[11, :3] = 0
    _raster(root, "B08_2021.tif", early, nodata=0)
    _raster(root, "B08_2023.tif", late, nodata=0)
    _json(root, "item_2021.json", _item("S2A_MSIL2A_20210703T083601_N0301_R064_T36TWR", "sentinel-2-l2a",
                                        "2021-07-03T08:36:01Z", {"nir": _s2_band("B08_2021.tif", "B08", "nir", offset=0)},
                                        **{"s2:processing_baseline": "03.01"}))
    _json(root, "item_2023.json", _item("S2B_MSIL2A_20230708T083559_N0509_R064_T36TWR", "sentinel-2-l2a",
                                        "2023-07-08T08:35:59Z", {"nir": _s2_band("B08_2023.tif", "B08", "nir")},
                                        **{"s2:processing_baseline": "05.09"}))
    before = early.astype("float64") * 0.0001
    after = late.astype("float64") * 0.0001 - 0.1
    valid = (early != 0) & (late != 0)
    return _finish(root, "hr-s2-mixed-baseline-change", after - before, valid, [
        ("offset-on-both", after - (before - 0.1), valid), ("offset-on-neither", after + 0.1 - before, valid)])


def landsat_surface_temperature(root):
    dn = (43000 + 37 * ((3 * R + 2 * C) % 61)).astype("uint16")
    dn[11, 10:] = 0
    _raster(root, "st_b10.tif", dn, nodata=0)
    _json(root, "item.json", _item("LC09_L2SP_177029_20240716_02_T1", "landsat-c2-l2", "2024-07-16T08:41:20Z", {
        "lwir11": _asset("st_b10.tif", **{"eo:bands": [{"name": "B10", "common_name": "lwir11"}],
                                          "raster:bands": [{"nodata": 0, "data_type": "uint16", "scale": 0.00341802,
                                                            "offset": 149.0, "unit": "kelvin"}]}),
    }, platform="landsat-9"))
    kelvin = dn.astype("float64") * 0.00341802 + 149.0
    valid = dn != 0
    return _finish(root, "hr-landsat-surface-temperature", kelvin - 273.15, valid, [
        ("kelvin", kelvin, valid), ("scale-without-offset", dn * 0.00341802 - 273.15, valid)])


def reanalysis_air_temperature(root):
    packed = (-4000 + 97 * ((5 * R + 7 * C) % 67)).astype("int16")
    packed[0, 0] = -32767
    _raster(root, "t2m.tif", packed, nodata=-32767, scales=[0.0018], offsets=[285.0], unit="K",
            descriptions=("2 metre temperature",))
    kelvin = packed.astype("float64") * 0.0018 + 285.0
    valid = packed != -32767
    return _finish(root, "hr-reanalysis-air-temperature", kelvin - 273.15, valid, [
        ("kelvin", kelvin, valid), ("packed-values", packed.astype("float64") - 273.15, valid)])


def modis_ndvi_scaled(root):
    stored = (-1500 + 151 * ((2 * R + 5 * C) % 71)).astype("int16")
    stored[10:, :2] = -3000
    _raster(root, "ndvi.tif", stored, nodata=-3000, scales=[0.0001], offsets=[0.0],
            descriptions=("250m 16 days NDVI",))
    ndvi = stored.astype("float64") * 0.0001
    valid = stored != -3000
    return _finish(root, "hr-modis-ndvi-scaled", ndvi, valid, [
        ("unscaled", stored.astype("float64"), valid), ("fill-as-value", ndvi, np.ones((N, N), bool))])


def hls_nir_reflectance(root):
    dn = (1500 + 83 * ((4 * R + C) % 53)).astype("int16")
    dn[:2, :2] = -9999
    _raster(root, "B8A.tif", dn, nodata=-9999)
    _json(root, "item.json", _item("HLS.S30.T36TWR.2024190T083559.v2.0", "HLSS30_2.0", "2024-07-08T08:35:59Z", {
        "nir": _asset("B8A.tif", **{"eo:bands": [{"name": "B8A", "common_name": "nir08"}],
                                    "raster:bands": [{"nodata": -9999, "data_type": "int16", "scale": 0.0001, "offset": 0}]}),
    }, **{"instruments": ["msi"], "constellation": "sentinel-2"}))
    sr = dn.astype("float64") * 0.0001
    valid = dn != -9999
    return _finish(root, "hr-hls-nir-reflectance", sr, valid, [
        ("s2-offset-applied", sr - 0.1, valid), ("unscaled", dn.astype("float64"), valid)])


# -- nodata stored as zero (and zero that is data) ---------------------------------------------
def landsat_undeclared_fill(root):
    dn = _landsat_dn()
    dn[R + C < 4] = 0
    dn[R - C > 8] = 0
    _raster(root, "red.tif", dn, nodata=None)
    _json(root, "item.json", _item("LC09_L2SP_177029_20240801_02_T1", "landsat-c2-l2", "2024-08-01T08:41:30Z", {
        "red": _asset("red.tif", **{"eo:bands": [{"name": "B4", "common_name": "red"}],
                                    "raster:bands": [{"nodata": 0, "data_type": "uint16", "scale": LANDSAT_SCALE,
                                                      "offset": LANDSAT_OFFSET}]}),
    }, platform="landsat-9"))
    sr = dn.astype("float64") * LANDSAT_SCALE + LANDSAT_OFFSET
    valid = dn != 0
    return _finish(root, "hr-landsat-undeclared-fill", sr, valid, [("fill-decoded", sr, np.ones((N, N), bool))])


def strip_mosaic(root):
    a = (0.12 + 0.004 * R + 0.002 * C).astype("float32")
    b = (0.13 + 0.003 * R + 0.003 * C).astype("float32")
    a[:, 8:] = 0
    b[:, :5] = 0
    a[11, :] = 0
    b[11, :] = 0
    _raster(root, "strip_a.tif", a, nodata=0)
    _raster(root, "strip_b.tif", b, nodata=0)
    fa, fb = a.astype("float64"), b.astype("float64")
    va, vb = a != 0, b != 0
    mean = np.where(va & vb, (fa + fb) / 2, np.where(va, fa, fb))
    valid = va | vb
    return _finish(root, "hr-strip-mosaic", mean, valid, [
        ("zeros-averaged", (fa + fb) / 2, valid), ("first-strip-wins", np.where(va, fa, fb), valid)])


def rainfall_dry_days(root):
    days = []
    for index in range(3):
        rain = (0.4 * ((R + 2 * C + 3 * index) % 9)).astype("float32")
        rain[(R + C + index) % 4 == 0] = 0
        rain[:2, :3] = -1
        days.append(rain)
        _raster(root, f"rain_day{index + 1}.tif", rain, nodata=-1, unit="mm", descriptions=("daily precipitation",))
    stack = np.array(days, dtype="float64")
    valid = (stack != -1).all(axis=0)
    mean = stack.mean(axis=0)
    wet = stack > 0
    counts = wet.sum(axis=0)
    wet_mean = np.divide((stack * wet).sum(axis=0), counts, out=np.zeros((N, N)), where=counts > 0)
    return _finish(root, "hr-rainfall-dry-days", mean, valid, [("dry-as-missing", wet_mean, valid & (counts > 0))])


LANDCOVER_CLASSES = [{"value": 0, "name": "no_data", "nodata": True}] + [
    {"value": v, "name": n} for v, n in ((1, "tree_cover"), (2, "shrubland"), (3, "grassland"), (4, "cropland"),
                                          (5, "built_up"), (6, "bare"), (7, "water"))]


def landcover_change_fill(root):
    first = (1 + (R // 3 + C // 4) % 7).astype("uint8")
    second = first.copy()
    second[2:5, 3:7] = 4
    second[8, :] = 5
    first[0, :4] = 0
    second[11, 6:] = 0
    first[11, 9:] = 0
    _raster(root, "landcover_2019.tif", first, nodata=None)
    _raster(root, "landcover_2023.tif", second, nodata=None)
    for year, name in ((2019, "landcover_2019.tif"), (2023, "landcover_2023.tif")):
        _json(root, f"item_{year}.json", _item(f"landcover-{year}", "annual-landcover", f"{year}-01-01T00:00:00Z", {
            "landcover": _asset(name, **{"classification:classes": LANDCOVER_CLASSES})}))
    changed = (first != second).astype("uint8")
    valid = (first != 0) & (second != 0)
    return _finish(root, "hr-landcover-change-fill", changed, valid, [
        ("fill-as-class", changed, np.ones((N, N), bool))], dtype="uint8", nodata=255)


def s2_ndwi_footprint(root):
    green = (1600 + 37 * ((R + 3 * C) % 29)).astype("uint16")
    nir = (2400 + 59 * ((2 * R + C) % 31)).astype("uint16")
    nir[7:10, 2:6] = 1150  # open water
    outside = C - R > 6
    green[outside] = 0
    nir[outside] = 0
    _raster(root, "B03.tif", green, nodata=None)
    _raster(root, "B08.tif", nir, nodata=None)
    _json(root, "item.json", _item("S2A_MSIL2A_20240710T083601_N0510_R064_T36TWR", "sentinel-2-l2a",
                                   "2024-07-10T08:36:01Z", {"green": _s2_band("B03.tif", "B03", "green"),
                                                            "nir": _s2_band("B08.tif", "B08", "nir")},
                                   **{"s2:processing_baseline": "05.10"}))
    g = green.astype("float64") * 0.0001 - 0.1
    n = nir.astype("float64") * 0.0001 - 0.1
    ndwi = (g - n) / (g + n)
    valid = ~outside
    raw_g, raw_n = green.astype("float64"), nir.astype("float64")
    no_offset = np.divide(raw_g - raw_n, raw_g + raw_n, out=np.zeros((N, N)), where=(raw_g + raw_n) > 0)
    return _finish(root, "hr-s2-ndwi-footprint", ndwi, valid, [
        ("fill-as-zero-index", np.where(outside, 0, ndwi), np.ones((N, N), bool)),
        ("offset-ignored", no_offset, valid)])


def coarsen_reflectance_fill(root):
    fine = (0.08 + 0.006 * R + 0.003 * C).astype("float32")
    fine[0:2, 0:2] = 0
    fine[3, 5] = 0
    fine[8:10, 7] = 0
    fine[10, 0:3] = 0
    target = from_origin(500000, 5000000, 20, 20)
    _raster(root, "red_10m.tif", fine, nodata=0)
    _raster(root, "target_grid.tif", np.zeros((6, 6), "float32"), transform=target)
    blocks = fine.astype("float64").reshape(6, 2, 6, 2).transpose(0, 2, 1, 3).reshape(6, 6, 4)
    good = blocks != 0
    counts = good.sum(axis=2)
    mean = np.divide((blocks * good).sum(axis=2), counts, out=np.zeros((6, 6)), where=counts > 0)
    valid = counts > 0
    return _finish(root, "hr-coarsen-reflectance-fill", mean, valid, [
        ("zeros-averaged", blocks.mean(axis=2), valid)], transform=target)


# -- dtype overflow ----------------------------------------------------------------------------
def ndvi_8bit(root):
    red = (40 + 9 * ((R + 2 * C) % 13)).astype("uint8")
    nir = (110 + 11 * ((2 * R + C) % 12)).astype("uint8")
    red[5:7, 5:9] = 180  # bare soil, red above NIR
    nir[5:7, 5:9] = 150
    red[0, 0] = nir[0, 0] = 0
    _raster(root, "red.tif", red, nodata=0)
    _raster(root, "nir.tif", nir, nodata=0)
    a, b = red.astype("float64"), nir.astype("float64")
    valid = (red != 0) & (nir != 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (b - a) / (b + a)
        wrapped = (nir - red).astype("float64") / (nir + red).astype("float64")
    wrapped = np.where(np.isfinite(wrapped), wrapped, 0)
    return _finish(root, "hr-ndvi-8bit", ndvi, valid, [("uint8-arithmetic", wrapped, valid)])


def visible_brightness_sum(root):
    bands = np.array([15000 + 211 * ((R + C + k) % 17) + 4000 * k for k in range(3)], dtype="uint16")
    bands[:, 0, 0] = 0
    _raster(root, "visible.tif", bands, nodata=0, descriptions=("blue", "green", "red"))
    total = bands.astype("uint64").sum(axis=0)
    valid = (bands != 0).all(axis=0)
    wrapped = bands.sum(axis=0, dtype="uint16")
    return _finish(root, "hr-visible-brightness-sum", total, valid, [("wrapped-uint16", wrapped, valid)],
                   dtype="uint32", nodata=0)


def three_date_mean_8bit(root):
    dates = []
    for index in range(3):
        value = (120 + 9 * ((R + 2 * C + 4 * index) % 14)).astype("uint8")
        value[11, 11] = 255
        dates.append(value)
        _raster(root, f"brightness_{index + 1}.tif", value, nodata=255)
    stack = np.array(dates)
    valid = (stack != 255).all(axis=0)
    mean = stack.astype("float64").mean(axis=0)
    wrapped = stack.sum(axis=0, dtype="uint8").astype("float64") / 3
    return _finish(root, "hr-three-date-mean-8bit", mean, valid, [("uint8-sum", wrapped, valid)])


# -- categorical resampling -------------------------------------------------------------------
def _categorical_transfer(root, task_id, source, source_grid, source_name, target_grid, shape):
    _raster(root, source_name, source, transform=source_grid, nodata=255)
    _raster(root, "target_grid.tif", np.zeros(shape, "uint8"), transform=target_grid, nodata=255)
    results = {}
    for method in (Resampling.nearest, Resampling.bilinear, Resampling.cubic):
        out = np.full(shape, 255, dtype="uint8")
        reproject(source, out, src_transform=source_grid, src_crs=UTM, src_nodata=255, dst_transform=target_grid,
                  dst_crs=UTM, dst_nodata=255, resampling=method)
        results[method] = out
    nearest = results[Resampling.nearest]
    valid = nearest != 255
    mistakes = [(name, results[method], results[method] != 255)
                for name, method in (("bilinear", Resampling.bilinear), ("cubic", Resampling.cubic))]
    return _finish(root, task_id, nearest, valid, mistakes, transform=target_grid, dtype="uint8", nodata=255)


def landcover_upsample(root):
    source = np.array([[1, 4, 4, 7], [1, 3, 6, 7], [2, 3, 6, 5], [2, 2, 5, 5]], dtype="uint8")
    source[3, 0] = 255
    return _categorical_transfer(root, "hr-landcover-upsample", source, from_origin(500000, 5000000, 30, 30),
                                 "landcover_30m.tif", GRID, (N, N))


def landcover_shifted_grid(root):
    source = (1 + (R // 2 + 3 * (C // 3)) % 7).astype("uint8")
    source[0, 5] = 7
    source[6, 6] = 1
    source[9:, 10:] = 255
    return _categorical_transfer(root, "hr-landcover-shifted-grid", source, GRID, "landcover.tif",
                                 from_origin(500002, 4999998, 10, 10), (N, N))


def landcover_dominant_class(root):
    patterns = [[1, 1, 1, 3], [2, 2, 1, 4], [3, 3, 3, 3], [4, 1, 4, 2], [5, 6, 6, 6], [1, 7, 7, 3]]
    source = np.zeros((N, N), dtype="uint8")
    for br, bc in np.ndindex(6, 6):
        block = patterns[(br + 2 * bc) % len(patterns)]
        source[2 * br:2 * br + 2, 2 * bc:2 * bc + 2] = np.array(block, dtype="uint8").reshape(2, 2)
    source[10:12, 0:2] = 255
    target = from_origin(500000, 5000000, 20, 20)
    _raster(root, "landcover_10m.tif", source, nodata=255)
    _raster(root, "target_grid.tif", np.zeros((6, 6), "uint8"), transform=target, nodata=255)
    blocks = source.reshape(6, 2, 6, 2).transpose(0, 2, 1, 3).reshape(6, 6, 4)
    counts = np.stack([(blocks == label).sum(axis=2) for label in range(1, 8)])
    dominant = (1 + counts.argmax(axis=0)).astype("uint8")
    valid = (blocks != 255).any(axis=2)
    nearest = source[::2, ::2]
    mean_class = np.rint(np.where(blocks == 255, 0, blocks).mean(axis=2))
    return _finish(root, "hr-landcover-dominant-class", dominant, valid, [
        ("nearest", nearest, valid), ("average-rounded", mean_class, valid)], transform=target, dtype="uint8", nodata=255)


# -- metric work in a geographic CRS -----------------------------------------------------------
def forest_area_geographic(root):
    grid = from_origin(24.5, 61.12, 0.01, 0.01)
    fraction = (0.05 + 0.07 * ((R + 3 * C) % 13)).astype("float32")
    fraction[0, :2] = NODATA
    _raster(root, "forest_fraction.tif", fraction, transform=grid, crs=GEOGRAPHIC,
            descriptions=("tree canopy fraction of the cell (0-1)",))
    north = np.radians(61.12 - 0.01 * R)
    south = north - np.radians(0.01)
    area_m2 = EARTH_RADIUS ** 2 * np.radians(0.01) * (np.sin(north) - np.sin(south))
    f = fraction.astype("float64")
    valid = fraction != NODATA
    equator_degree = f * (111320 * 0.01) ** 2 / 10000
    return _finish(root, "hr-forest-area-geographic", f * area_m2 / 10000, valid, [
        ("equator-degree-cells", equator_degree, valid), ("square-degrees", f * 0.0001, valid)],
        transform=grid, crs=GEOGRAPHIC)


def slope_geographic(root):
    lon0, lat0, step = 26.4, 60.25, 0.0005
    grid = from_origin(lon0, lat0, step, step)
    lat = lat0 - step * (R + 0.5)
    lon = lon0 + step * (C + 0.5)
    east = EARTH_RADIUS * np.cos(np.radians(60.25)) * np.radians(lon - lon0)
    north = EARTH_RADIUS * np.radians(lat - lat0)
    dem = (250 + 0.30 * east + 0.05 * north).astype("float32")
    _raster(root, "dem.tif", dem, transform=grid, crs=GEOGRAPHIC, unit="m", descriptions=("elevation",))
    z = dem.astype("float64")
    dx = EARTH_RADIUS * np.cos(np.radians(lat)) * np.radians(step) * 2
    dy = EARTH_RADIUS * np.radians(step) * 2
    gx = np.zeros((N, N))
    gy = np.zeros((N, N))
    gx[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / dx[:, 1:-1]
    gy[1:-1, :] = (z[:-2, :] - z[2:, :]) / dy
    valid = np.zeros((N, N), bool)
    valid[1:-1, 1:-1] = True

    def slope(x, y):
        return np.degrees(np.arctan(np.hypot(x, y)))
    degree_dx = np.zeros((N, N))
    degree_dx[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / (2 * step)
    degree_dy = np.zeros((N, N))
    degree_dy[1:-1, :] = (z[:-2, :] - z[2:, :]) / (2 * step)
    return _finish(root, "hr-slope-geographic", slope(gx, gy), valid, [
        ("degrees-as-metres", slope(degree_dx, degree_dy), valid),
        ("no-latitude-scaling", slope(gx * np.cos(np.radians(lat)), gy), valid)], transform=grid, crs=GEOGRAPHIC)


def station_distance(root):
    grid = from_origin(31.0, 30.6, 0.05, 0.05)
    _raster(root, "grid.tif", np.zeros((N, N), "float32"), transform=grid, crs=GEOGRAPHIC,
            descriptions=("analysis grid template",))
    station = (31.237, 30.044)
    _json(root, "station.geojson", {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "gauge 17"},
        "geometry": {"type": "Point", "coordinates": list(station)}}]})
    lon = np.radians(31.0 + 0.05 * (C + 0.5))
    lat = np.radians(30.6 - 0.05 * (R + 0.5))
    slon, slat = np.radians(station[0]), np.radians(station[1])
    h = np.sin((lat - slat) / 2) ** 2 + np.cos(lat) * np.cos(slat) * np.sin((lon - slon) / 2) ** 2
    km = 2 * 6371.0088 * np.arcsin(np.sqrt(h))
    valid = np.ones((N, N), bool)
    dlon = np.degrees(lon - slon)
    dlat = np.degrees(lat - slat)
    return _finish(root, "hr-station-distance", km, valid, [
        ("degree-euclidean", np.hypot(dlon, dlat) * 111.32, valid), ("degrees", np.hypot(dlon, dlat), valid)],
        transform=grid, crs=GEOGRAPHIC)


# -- vertical units ----------------------------------------------------------------------------
def flood_depth_feet(root):
    dem = (22 + 1.7 * R + 1.1 * C).astype("float32")
    dem[0, 11] = NODATA
    _raster(root, "dem.tif", dem, unit="ft", descriptions=("ground elevation, NAVD88",))
    metres = dem.astype("float64") * 0.3048
    valid = dem != NODATA
    feet = dem.astype("float64")
    return _finish(root, "hr-flood-depth-feet", np.maximum(0, 12.0 - metres), valid, [
        ("feet-as-metres", np.maximum(0, 12.0 - feet), valid),
        ("depth-in-feet", np.maximum(0, 12.0 - metres) / 0.3048, valid)])


def orthometric_height(root):
    geoid = (14.2 + 0.11 * R - 0.07 * C).astype("float32")
    heights = (180 + 3.5 * R + 2.25 * C).astype("float32")
    heights[11, 0] = NODATA
    _raster(root, "heights.tif", heights, unit="m", descriptions=("height above the WGS 84 ellipsoid",))
    _raster(root, "geoid.tif", geoid, unit="m", descriptions=("EGM2008 geoid undulation N above the WGS 84 ellipsoid",))
    h, n = heights.astype("float64"), geoid.astype("float64")
    valid = heights != NODATA
    return _finish(root, "hr-orthometric-height", h - n, valid, [
        ("undulation-added", h + n, valid), ("ellipsoidal-unchanged", h, valid)])


def elevation_change_mixed_units(root):
    early_m = 95 + 0.8 * R + 0.6 * C
    change = 0.35 * ((R + C) % 5) - 0.7
    early = (early_m / 0.3048).astype("float32")
    late = (early_m + change).astype("float32")
    early[0, 0] = NODATA
    _raster(root, "dem_2015.tif", early, unit="ft", descriptions=("elevation 2015 survey",))
    _raster(root, "dem_2023.tif", late, unit="m", descriptions=("elevation 2023 survey",))
    a, b = early.astype("float64"), late.astype("float64")
    valid = early != NODATA
    return _finish(root, "hr-elevation-change-mixed-units", b - a * 0.3048, valid, [
        ("units-ignored", b - a, valid), ("change-in-feet", b / 0.3048 - a, valid)])


# -- dB versus linear --------------------------------------------------------------------------
def _db_field(base, amplitude, phase):
    return (base + amplitude * np.sin(0.7 * R + 1.3 * C + phase)).astype("float32")


def sar_change_ratio(root):
    first = _db_field(-13.0, 3.0, 0.0)
    second = _db_field(-11.5, 3.5, 0.9)
    first[0, :2] = NODATA
    for name, data in (("vv_2023.tif", first), ("vv_2024.tif", second)):
        _raster(root, name, data, unit="dB", descriptions=("sigma0 VV backscatter",))
    valid = first != NODATA
    a, b = np.where(valid, first, -13.0).astype("float64"), second.astype("float64")
    return _finish(root, "hr-sar-change-ratio", b - a, valid, [
        ("ratio-of-db", b / a, valid), ("linear-ratio", 10 ** (b / 10) / 10 ** (a / 10), valid)])


def sar_boxcar_db(root):
    vv = _db_field(-12.0, 5.0, 0.3)
    _raster(root, "vv_db.tif", vv, unit="dB", descriptions=("sigma0 VV backscatter",))
    db = vv.astype("float64")
    power = 10 ** (db / 10)

    def box(values):
        out = np.zeros((N, N))
        out[1:-1, 1:-1] = sum(values[1 + dr:N - 1 + dr, 1 + dc:N - 1 + dc] for dr in (-1, 0, 1) for dc in (-1, 0, 1)) / 9
        return out
    valid = np.zeros((N, N), bool)
    valid[1:-1, 1:-1] = True
    linear_mean = box(power)
    return _finish(root, "hr-sar-boxcar-db", 10 * np.log10(np.where(valid, linear_mean, 1)), valid, [
        ("averaged-in-db", box(db), valid), ("linear-power-delivered", linear_mean, valid)])


def sar_amplitude_db(root):
    amplitude = (0.12 + 0.05 * np.abs(np.sin(0.5 * R + 0.8 * C))).astype("float32")
    amplitude[11, 11] = NODATA
    _raster(root, "vv_amplitude.tif", amplitude, unit="amplitude", descriptions=("sigma0 VV amplitude (linear)",))
    a = amplitude.astype("float64")
    valid = amplitude != NODATA
    safe = np.where(valid, a, 1)
    return _finish(root, "hr-sar-amplitude-db", 20 * np.log10(safe), valid, [
        ("amplitude-as-power", 10 * np.log10(safe), valid)])


# -- temporal scope ----------------------------------------------------------------------------
def july_median_ndvi(root):
    dates = ["2024-06-28T08:36:01Z", "2024-07-04T08:35:59Z", "2024-07-15T08:36:01Z", "2024-07-29T08:35:59Z",
             "2024-08-02T08:36:01Z"]
    levels = [0.31, 0.52, 0.61, 0.47, 0.22]
    scenes = []
    for index, (when, level) in enumerate(zip(dates, levels), start=1):
        ndvi = (level + 0.01 * ((R + 2 * C + index) % 7)).astype("float32")
        scenes.append(ndvi)
        _raster(root, f"scene-{index}.tif", ndvi, descriptions=("NDVI",))
        _json(root, f"scene-{index}.json", _item(f"ndvi-scene-{index}", "ndvi-derived", when,
                                                 {"ndvi": _asset(f"scene-{index}.tif")}))
    stack = np.array(scenes, dtype="float64")
    valid = np.ones((N, N), bool)
    return _finish(root, "hr-july-median-ndvi", np.median(stack[1:4], axis=0), valid, [
        ("all-scenes", np.median(stack, axis=0), valid), ("june-included", np.median(stack[0:4], axis=0), valid)])


def _accumulations(root, start: datetime, step: timedelta, count: int, *, prefix: str, label_by_end: bool):
    features, frames, intervals = [], [], []
    for index in range(count):
        first = start + index * step
        last = first + step
        stamp = last if label_by_end else first
        name = f"{prefix}_{stamp:%Y%m%d}.tif" if step >= timedelta(days=1) else f"{prefix}_{stamp:%Y%m%dT%H%M}.tif"
        rain = (0.2 * ((R + C + 3 * index) % 6) + 0.1 * (index % 4)).astype("float32")
        rain[(R * 3 + C + index) % 5 == 0] = 0
        _raster(root, name, rain, nodata=-1, unit="mm", descriptions=("accumulated precipitation",))
        features.append({"type": "Feature", "id": name[:-4], "geometry": None, "assets": {"data": {"href": name}},
                         "properties": {"datetime": f"{stamp:%Y-%m-%dT%H:%M:%SZ}",
                                        "start_datetime": f"{first:%Y-%m-%dT%H:%M:%SZ}",
                                        "end_datetime": f"{last:%Y-%m-%dT%H:%M:%SZ}"}})
        frames.append(rain.astype("float64"))
        intervals.append((first, last))
    _json(root, "catalog.json", {"type": "FeatureCollection", "features": features})
    return np.array(frames), intervals


def _window_sum(frames, intervals, start, end):
    keep = [index for index, (first, last) in enumerate(intervals) if first >= start and last <= end]
    return frames[keep].sum(axis=0)


def cairo_day_rainfall(root):
    utc = timezone.utc
    frames, intervals = _accumulations(root, datetime(2024, 3, 4, 18, tzinfo=utc), timedelta(hours=2), 15,
                                       prefix="rain", label_by_end=False)
    local_start = datetime(2024, 3, 4, 22, tzinfo=utc)
    valid = np.ones((N, N), bool)
    total = _window_sum(frames, intervals, local_start, local_start + timedelta(days=1))
    utc_day = _window_sum(frames, intervals, datetime(2024, 3, 5, tzinfo=utc), datetime(2024, 3, 6, tzinfo=utc))
    return _finish(root, "hr-cairo-day-rainfall", total, valid, [("utc-day", utc_day, valid)])


def dekad_rainfall(root):
    utc = timezone.utc
    frames, intervals = _accumulations(root, datetime(2024, 5, 8, tzinfo=utc), timedelta(days=1), 15,
                                       prefix="precip", label_by_end=True)
    valid = np.ones((N, N), bool)
    total = _window_sum(frames, intervals, datetime(2024, 5, 11, tzinfo=utc), datetime(2024, 5, 21, tzinfo=utc))
    by_label = _window_sum(frames, intervals, datetime(2024, 5, 10, tzinfo=utc), datetime(2024, 5, 20, tzinfo=utc))
    return _finish(root, "hr-dekad-rainfall", total, valid, [("labels-as-days", by_label, valid)])


RECIPES = {
    "hr-landsat-clear-red": landsat_clear_red,
    "hr-s2-scl-red": s2_scl_red,
    "hr-hls-fmask-nir": hls_fmask_nir,
    "hr-modis-lst-quality": modis_lst_quality,
    "hr-landsat-red-saturation": landsat_red_saturation,
    "hr-s2-scl-20m-nir": s2_scl_20m_nir,
    "hr-s2-baseline-nir": s2_baseline_nir,
    "hr-s2-mixed-baseline-change": s2_mixed_baseline_change,
    "hr-landsat-surface-temperature": landsat_surface_temperature,
    "hr-reanalysis-air-temperature": reanalysis_air_temperature,
    "hr-modis-ndvi-scaled": modis_ndvi_scaled,
    "hr-hls-nir-reflectance": hls_nir_reflectance,
    "hr-landsat-undeclared-fill": landsat_undeclared_fill,
    "hr-strip-mosaic": strip_mosaic,
    "hr-rainfall-dry-days": rainfall_dry_days,
    "hr-landcover-change-fill": landcover_change_fill,
    "hr-s2-ndwi-footprint": s2_ndwi_footprint,
    "hr-coarsen-reflectance-fill": coarsen_reflectance_fill,
    "hr-ndvi-8bit": ndvi_8bit,
    "hr-visible-brightness-sum": visible_brightness_sum,
    "hr-three-date-mean-8bit": three_date_mean_8bit,
    "hr-landcover-upsample": landcover_upsample,
    "hr-landcover-shifted-grid": landcover_shifted_grid,
    "hr-landcover-dominant-class": landcover_dominant_class,
    "hr-forest-area-geographic": forest_area_geographic,
    "hr-slope-geographic": slope_geographic,
    "hr-station-distance": station_distance,
    "hr-flood-depth-feet": flood_depth_feet,
    "hr-orthometric-height": orthometric_height,
    "hr-elevation-change-mixed-units": elevation_change_mixed_units,
    "hr-sar-change-ratio": sar_change_ratio,
    "hr-sar-boxcar-db": sar_boxcar_db,
    "hr-sar-amplitude-db": sar_amplitude_db,
    "hr-july-median-ndvi": july_median_ndvi,
    "hr-cairo-day-rainfall": cairo_day_rainfall,
    "hr-dekad-rainfall": dekad_rainfall,
}
