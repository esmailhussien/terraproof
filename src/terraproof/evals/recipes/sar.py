"""Fixtures and oracles for the `sar-basics` task specs."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio

from terraproof.evals.fixtures import FLOAT_NODATA, UTM, read_raster, write_gcp_only_vrt, write_raster, write_stac_item
from terraproof.evals.oracles import Oracle, arithmetic_mean_db, power_mean_db
from terraproof.evals.recipes._util import check_step, correct, recipe, results_for, wrong

DB_NODATA = FLOAT_NODATA


def sar_db_linear_mean(root: Path):
    """Task 1: mean dB backscatter averaged in linear power."""
    shape = (16, 16)
    rows, cols = np.indices(shape)
    dates = [
        (-9.0 + 0.2 * ((rows + cols) % 5)).astype("float32"),
        (-8.5 + 0.2 * ((rows * 2 + cols) % 5)).astype("float32"),
        (-9.5 + 0.2 * ((rows + cols * 2) % 5)).astype("float32"),
    ]
    dates[0][0, 0], dates[1][0, 0], dates[2][0, 0] = -5.0, -15.0, DB_NODATA
    dates[1][1, 1] = DB_NODATA
    dates[2][1, 1] = DB_NODATA
    for index, values in enumerate(dates):
        write_raster(root / f"vv_date{index + 1}.tif", values, crs=UTM, nodata=DB_NODATA, dtype="float32", scale=1.0, offset=0.0)
    stack = np.stack(dates)
    valid = stack != DB_NODATA
    with np.errstate(all="ignore"):
        linear = np.power(10.0, np.where(valid, stack, np.nan) / 10.0)
        mean_linear = np.nanmean(linear, axis=0)
        mean_db = 10.0 * np.log10(mean_linear)
    mean_db[~np.any(valid, axis=0)] = DB_NODATA
    counts = valid.sum(axis=0).astype("uint8")
    mean_path = write_raster(root / "vv_monthly_mean_db.tif", mean_db, crs=UTM, nodata=DB_NODATA, dtype="float32")
    count_path = write_raster(root / "vv_valid_dates.tif", counts, crs=UTM, nodata=255, dtype="uint8")

    field_slice = (slice(8, 12), slice(8, 12))
    field_linear = float(np.nanmean(linear[:, field_slice[0], field_slice[1]]))
    field_db = 10.0 * math.log10(field_linear)
    field_db_expected = float(
        10.0
        * math.log10(
            np.nanmean(
                np.power(
                    10.0,
                    np.where(valid[:, field_slice[0], field_slice[1]], stack[:, field_slice[0], field_slice[1]], np.nan) / 10.0,
                )
            )
        )
    )

    steps = [check_step("check vv_monthly_mean_db.tif --sar-expect sigma0-db", [mean_path], sar_expect="sigma0-db")]
    delivered = read_raster(mean_path)
    control = float(np.ma.getdata(delivered)[0, 0])
    oracle = Oracle("average in linear power, then convert back to dB")
    oracle.close("control pixel power mean (-5 dB and -15 dB on two dates)", control, -7.596, 0.01)
    oracle.differs_by("the control is not the naive dB mean", control, -10.0, 0.5)
    oracle.close("control pixel power mean from the independent calculation", control, float(power_mean_db([-5.0, -15.0])), 1e-6)
    oracle.close("a single-valid-date pixel keeps that date's value", float(np.ma.getdata(delivered)[1, 1]), float(dates[0][1, 1]), 1e-6)
    oracle.equal("contributing dates at the control pixel", int(np.ma.getdata(read_raster(count_path))[0, 0]), 2)
    oracle.equal("contributing date at the single-date pixel", int(np.ma.getdata(read_raster(count_path))[1, 1]), 1)
    oracle.close("field polygon mean in dB", field_db, field_db_expected, 1e-6)
    oracle.differs_by(
        "the field polygon mean is computed in linear power, not by averaging dB values",
        field_db,
        float(np.nanmean(stack[:, field_slice[0], field_slice[1]])),
        0.01,
    )
    oracle.equal(
        "the naive dB mean would be -10 dB at the control pixel",
        round(arithmetic_mean_db([-5.0, -15.0]), 6),
        -10.0,
    )
    for check_id in ("sar.value_domain", "raster.nodata_declared", "crs.defined"):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} passes on the monthly mean",
            bool(observed) and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    correct_control = correct(
        "linear-power-mean",
        "Three co-registered sigma0 VV dB rasters with layover/shadow nodata, averaged in linear power "
        "and returned in dB with a contributing-date count.",
        steps,
        oracle,
    )

    naive = np.full(shape, DB_NODATA, dtype="float32")
    with np.errstate(all="ignore"):
        naive_mean = np.nanmean(np.where(valid, stack, np.nan), axis=0)
    naive[~np.any(valid, axis=0)] = DB_NODATA
    naive[np.any(valid, axis=0)] = naive_mean[np.any(valid, axis=0)]
    naive_path = write_raster(root / "vv_monthly_mean_naive_db.tif", naive, crs=UTM, nodata=DB_NODATA, dtype="float32")
    wrong_steps = [check_step("check vv_monthly_mean_naive_db.tif --sar-expect sigma0-db", [naive_path], sar_expect="sigma0-db")]
    wrong_oracle = Oracle("averaging dB values computes a geometric mean")
    naive_values = read_raster(naive_path)
    wrong_oracle.close(
        "control pixel power mean",
        float(np.ma.getdata(naive_values)[0, 0]),
        -7.596,
        0.01,
    )
    wrong_oracle.differs_by(
        "the naive dB mean differs from the power mean",
        float(np.ma.getdata(naive_values)[0, 0]),
        -7.596,
        0.5,
    )
    wrong_control = wrong(
        "naive-db-average",
        "The dB values are averaged directly, giving -10 dB at the control pixel, which is still a "
        "plausible sigma0 dB value.",
        wrong_steps,
        wrong_oracle,
        notes="sar.value_domain cannot distinguish a geometric mean from a power mean.",
    )
    return recipe(
        "sar-db-linear-monthly-mean",
        correct_control,
        [wrong_control],
        automated_scope=[
            "sar.value_domain, raster.nodata_declared and crs.defined on the monthly mean",
            "independent linear-power mean (-7.596 dB), the naive dB mean (-10 dB), contributing-date counts and a polygon mean",
        ],
        remaining=[
            "The answer must name the quantity and scale (sigma0 VV, dB) and report the per-pixel contributing-date count; prose is not graded.",
            "Review of the layover/shadow masking source for the real scene.",
        ],
    )


def _amplitude() -> np.ndarray:
    shape = (64, 64)
    amplitude = np.full(shape, 1200, dtype="uint16")
    amplitude[:20, :] = 200
    amplitude[30, 30] = 1400
    return amplitude


def sar_grd_gcp_only(root: Path):
    """Task 2: a GCP-only GRD measurement cannot yield a hectare area."""
    amplitude = _amplitude()
    pixel_points = [
        (0, 0, 30.00, 30.00),
        (0, 63, 30.00 + 63 * 0.0003, 30.00),
        (63, 0, 30.00, 30.00 - 63 * 0.0003),
        (63, 63, 30.00 + 63 * 0.0003, 30.00 - 63 * 0.0003),
    ]
    vrt = write_gcp_only_vrt(root / "grd_measurement.vrt", amplitude, pixel_points=pixel_points)
    steps = [check_step("check grd_measurement.vrt --sar-expect sigma0-linear", [vrt], sar_expect="sigma0-linear")]
    with rasterio.open(vrt) as src:
        gcps, gcp_crs = src.gcps
        crs_defined = src.crs is not None
        identity = tuple(src.transform)[:6] == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        gcp_count = len(gcps)
    amplitude_calibrated = amplitude.astype("float64") ** 2 / 1000.0 ** 2
    water_db = 10.0 * math.log10(float(amplitude_calibrated[:20, :].mean()))
    land_db = 10.0 * math.log10(float(amplitude_calibrated[20:, :].mean()))
    universal_threshold_linear = 10.0 ** (-18.0 / 10.0)
    flagged_by_universal = int(np.count_nonzero(amplitude_calibrated < universal_threshold_linear))
    local_threshold_db = (water_db + land_db) / 2.0
    flagged_by_local = int(np.count_nonzero(amplitude_calibrated < 10.0 ** (local_threshold_db / 10.0)))
    water_pixels = int(np.count_nonzero((amplitude[:20, :] == 200)))
    oracle = Oracle("GCP-only ground-range geometry and a threshold that does not transfer")
    oracle.require("the input has no CRS", not crs_defined, "no CRS" if not crs_defined else "CRS present", "no CRS")
    oracle.equal("the input carries ground control points", gcp_count, 4)
    oracle.require("the transform is the identity (pixel coordinates)", identity, "identity", "identity")
    oracle.require(
        "no hectare area can be computed without a real geotransform",
        identity and not crs_defined,
        "pixel area 1",
        "no ground pixel size",
    )
    oracle.close("water mode in dB after amplitude calibration", water_db, -13.979, 0.01)
    oracle.close("land mode in dB after amplitude calibration", land_db, 1.583, 0.01)
    oracle.equal("a -18 dB threshold flags no pixel in this scene", flagged_by_universal, 0)
    oracle.equal("a local bimodal threshold flags exactly the water pixels", flagged_by_local, water_pixels)
    reference_area_ha = 115.2  # 1,280 water pixels x 900 m2, the authored reference-outline area
    oracle.close(
        "reference flood outline area (ha) for the water region",
        water_pixels * 900 / 10_000,
        reference_area_ha,
        1e-9,
        note="the reference outline is the authored water region at the 30 m GCP pixel size",
    )
    geocoded = results_for(steps, "sar.geocoded")
    oracle.require(
        "sar.geocoded fails on the GCP-only measurement",
        bool(geocoded) and geocoded[0].status == "fail",
        geocoded[0].status if geocoded else None,
        "fail",
    )
    correct_control = correct(
        "gcp-only-grd-preflight",
        "A Level-1 amplitude GeoTIFF exposed as GCP-only ground-range geometry, with the requested -18 dB "
        "threshold taken from an unrelated study.",
        steps,
        oracle,
    )

    fake_crs = write_raster(root / "grd_measurement_fake_geo.tif", amplitude, crs=UTM, nodata=0, dtype="uint16", resolution=10.0)
    fake_steps = [check_step("check grd_measurement_fake_geo.tif --sar-expect sigma0-linear", [fake_crs], sar_expect="sigma0-linear")]
    fake_area_ha = water_pixels * 10.0 * 10.0 / 10_000
    wrong_oracle = Oracle("assigning a fake geotransform produces a wrong area")
    wrong_oracle.close(
        "flooded area (ha) matches the reference outline",
        fake_area_ha,
        reference_area_ha,
        reference_area_ha * 0.05,
    )
    wrong_oracle.require(
        "the input is not terrain corrected",
        False,
        "fake 10 m geotransform",
        "GCP-only ground-range geometry until terrain correction",
    )
    wrong_control = wrong(
        "fake-geotransform",
        "A CRS and 10 m geotransform are assigned to the measurement raster so sar.geocoded passes; the "
        "resulting flooded area is 12.8 ha instead of the 115.2 ha reference outline.",
        fake_steps,
        wrong_oracle,
    )
    return recipe(
        "sar-grd-gcp-only-preflight",
        correct_control,
        [wrong_control],
        automated_scope=[
            "sar.geocoded on the supplied GCP-only measurement raster",
            "independent CRS/GCP/transform inspection, amplitude-to-sigma0 calibration and the -18 dB vs local threshold counts",
            "the reference outline area that a hectare computation would have to reproduce",
        ],
        remaining=[
            "Calibration with the product LUT, noise handling and DEM-based terrain correction are a processing deliverable; the harness only proves the input is not geocoded.",
            "Review of the locally derived water threshold against the reference outline.",
        ],
    )


def _orbit_item(path: Path, item_id: str, datetime: str, relative_orbit: int, orbit_state: str) -> str:
    return write_stac_item(
        path,
        item_id=item_id,
        datetime=datetime,
        extra_properties={"sat:relative_orbit": relative_orbit, "sat:orbit_state": orbit_state},
    )


def sar_orbit_log_ratio(root: Path):
    """Task 3: pre/post gamma0 log ratio from the same relative orbit."""
    shape = (32, 32)
    pre = np.full(shape, 0.02, dtype="float32")
    post = np.full(shape, 0.02, dtype="float32")
    post[:8, :8] = 0.002  # flooded field: a clear backscatter decrease
    post[:8, 8:16] = 0.05  # wind-roughened water: a brightening that is not flooding
    for row, col in ((16, 16), (24, 24)):
        pre[row, col] = FLOAT_NODATA
        post[row, col] = FLOAT_NODATA
    pre_path = write_raster(root / "pre_gamma0_vv.tif", pre, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    post_path = write_raster(root / "post_gamma0_vv.tif", post, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    pre_item = _orbit_item(root / "pre-item.json", "S1A_PRE_ORBIT15", "2024-04-01T15:30:00Z", 15, "ascending")
    post_item = _orbit_item(root / "post-item.json", "S1A_POST_ORBIT15", "2024-04-13T15:30:00Z", 15, "ascending")
    descending_item = _orbit_item(root / "descending-item.json", "S1A_POST_ORBIT42", "2024-04-12T05:30:00Z", 42, "descending")
    steps = [
        check_step(
            "check pre_gamma0_vv.tif post_gamma0_vv.tif --sar-expect sigma0-linear",
            [pre_path, post_path],
            sar_expect="sigma0-linear",
        ),
        check_step("check post-item.json", [post_item]),
    ]
    ratio = np.full(shape, np.nan, dtype="float64")
    valid = (pre != FLOAT_NODATA) & (post != FLOAT_NODATA) & (pre > 0) & (post > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio[valid] = np.log10(post[valid].astype("float64") / pre[valid].astype("float64"))
    reference = np.zeros(shape, dtype=bool)
    reference[:8, :8] = True
    threshold = -0.5
    flooded = ratio < threshold
    intersection = np.count_nonzero(flooded & reference)
    union = np.count_nonzero(flooded | reference)
    oracle = Oracle("same-orbit gamma0 log ratio, layover masks and a local threshold")
    oracle.close("flooded-field log10(post/pre)", float(ratio[4, 4]), -1.0, 1e-6)
    oracle.close("wind-roughened water log10(post/pre)", float(ratio[4, 12]), float(np.log10(0.05 / 0.02)), 1e-6)
    oracle.require(
        "wind-roughened water brightens instead of decreasing",
        float(ratio[4, 12]) > 0,
        round(float(ratio[4, 12]), 6),
        "> 0",
    )
    oracle.close("stable field log10(post/pre)", float(ratio[20, 20]), 0.0, 1e-6)
    oracle.close(
        "the local threshold separates flooded from stable (IoU with the reference sample)",
        intersection / union if union else 0.0,
        1.0,
        1e-9,
    )
    pre_properties = _item_properties(pre_item)
    post_properties = _item_properties(post_item)
    descending_properties = _item_properties(descending_item)
    oracle.equal("pre-event relative orbit matches the post event", post_properties["sat:relative_orbit"], pre_properties["sat:relative_orbit"])
    oracle.equal("pre-event orbit direction matches the post event", post_properties["sat:orbit_state"], pre_properties["sat:orbit_state"])
    oracle.require(
        "the descending acquisition is excluded from the pair",
        descending_properties["sat:orbit_state"] != pre_properties["sat:orbit_state"]
        or descending_properties["sat:relative_orbit"] != pre_properties["sat:relative_orbit"],
        descending_properties,
        "not the pre-event orbit",
    )
    delivered = read_raster(pre_path)
    post_delivered = read_raster(post_path)
    oracle.require(
        "layover/shadow nodata is preserved in both inputs",
        bool(np.ma.getmaskarray(delivered)[16, 16]) and bool(np.ma.getmaskarray(post_delivered)[24, 24]),
        "masked",
        "masked",
    )
    for check_id, count in (("sar.value_domain", 2), ("sar.geocoded", 2), ("raster.grid_alignment", 1)):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} emits the expected pass results",
            len(observed) == count and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    stac_status = results_for(steps, "stac.provenance")
    oracle.require(
        "stac.provenance passes on the post-event Item",
        bool(stac_status) and stac_status[0].status == "pass",
        stac_status[0].status if stac_status else None,
        "pass",
    )
    correct_control = correct(
        "same-orbit-log-ratio",
        "Pre-event and post-event gamma0 VV on one grid from relative orbit 15 ascending, with layover "
        "nodata, a wind-roughened water control and a reference flood sample.",
        steps,
        oracle,
    )

    post_desc_path = write_raster(
        root / "post_gamma0_vv_descending.tif",
        post + 0.002,
        crs=UTM,
        nodata=FLOAT_NODATA,
        dtype="float32",
    )
    wrong_steps = [
        check_step(
            "check pre_gamma0_vv.tif post_gamma0_vv_descending.tif --sar-expect sigma0-linear",
            [pre_path, post_desc_path],
            sar_expect="sigma0-linear",
        ),
        check_step("check descending-item.json", [descending_item]),
    ]
    wrong_oracle = Oracle("differencing across orbit geometries maps geometry as change")
    pre_props = _item_properties(pre_item)
    desc_props = _item_properties(descending_item)
    wrong_oracle.equal(
        "the selected post-event relative orbit matches the pre-event orbit",
        desc_props["sat:relative_orbit"],
        pre_props["sat:relative_orbit"],
    )
    wrong_oracle.equal(
        "the selected post-event orbit direction matches the pre-event direction",
        desc_props["sat:orbit_state"],
        pre_props["sat:orbit_state"],
    )
    wrong_control = wrong(
        "descending-post-event",
        "The post-event scene comes from relative orbit 42 descending while the pre-event scene is orbit 15 "
        "ascending; the value-domain and geocoding checks still pass.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "sar-orbit-consistent-log-ratio",
        correct_control,
        [wrong_control],
        automated_scope=[
            "sar.value_domain, sar.geocoded, raster.grid_alignment and stac.provenance on the inputs and Item",
            "independent log10(post/pre) controls, layover masking, orbit/state pairing and a locally derived threshold with a reference sample",
        ],
        remaining=[
            "Incidence-angle normalisation for a non-anniversary pair and the flood-map validation on the reference sample are a processing deliverable; the harness only checks the supplied pair.",
            "The answer must explain calm vs wind-roughened water and why the threshold is local; prose is not graded.",
        ],
    )


def _item_properties(path: str) -> dict:
    import json

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["properties"]


RECIPES = {
    "sar-db-linear-monthly-mean": sar_db_linear_mean,
    "sar-grd-gcp-only-preflight": sar_grd_gcp_only,
    "sar-orbit-consistent-log-ratio": sar_orbit_log_ratio,
}
