"""Fixtures and oracles for the `spectral-indices` task specs."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from terraproof.evals.fixtures import FLOAT_NODATA, UTM, read_raster, write_raster
from terraproof.evals.harness import Step
from terraproof.evals.oracles import Oracle, evi, nbr, ndvi, ndwi_gao, ndwi_mcfeeters, mndwi, savi
from terraproof.evals.recipes._util import check_step, correct, recipe, results_for, wrong

SHAPE = (32, 32)


def _band(base: float, step: float, shape=SHAPE) -> np.ndarray:
    rows, cols = np.indices(shape)
    return (base + step * ((rows * 2 + cols) % 23)).astype("float32")


def _write_index(path: Path, values: np.ndarray) -> str:
    array = np.full(values.shape, FLOAT_NODATA, dtype="float32")
    valid = np.isfinite(values)
    array[valid] = values[valid]
    return write_raster(path, array, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")


def _index_ok(steps: list[Step], check_id: str) -> list:
    return results_for(steps, check_id)


def indices_ndvi_physical(root: Path):
    """Task 1: NDVI from decoded physical reflectance, with masks and a valid zero."""
    red = _band(0.05, 0.004)
    nir = _band(0.25, 0.006)
    red[0, 0], nir[0, 0] = 0.10, 0.40
    red[0, 1], nir[0, 1] = 0.15, 0.15
    red[0, 2], nir[0, 2] = 0.0, 0.0
    red[2, 2] = FLOAT_NODATA
    valid = (red != FLOAT_NODATA) & (nir != FLOAT_NODATA)
    values = np.full(SHAPE, np.nan, dtype="float64")
    denominator = np.where(valid, nir.astype("float64") + red.astype("float64"), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        values[valid] = (nir[valid] - red[valid]) / denominator[valid]
    values[denominator == 0] = np.nan
    ndvi_path = _write_index(root / "ndvi.tif", values)

    safe_red = np.where(valid, red, 0.0)
    safe_nir = np.where(valid, nir, 0.0)
    dn_red = np.round((safe_red + 0.1) / 0.0001).astype("uint16")
    dn_nir = np.round((safe_nir + 0.1) / 0.0001).astype("uint16")
    dn_red[2, 2] = 0
    dn_red_path = write_raster(root / "red_dn.tif", dn_red, crs=UTM, nodata=0, dtype="uint16", scale=0.0001, offset=-0.1)
    dn_nir_path = write_raster(root / "nir_dn.tif", dn_nir, crs=UTM, nodata=0, dtype="uint16", scale=0.0001, offset=-0.1)

    steps = [check_step("check ndvi.tif --expect index", [ndvi_path], expect="index")]
    delivered = read_raster(ndvi_path)
    oracle = Oracle("NDVI from physical reflectance, not a DN ratio")
    oracle.close("control NDVI (red 0.10, NIR 0.40)", float(np.ma.getdata(delivered)[0, 0]), ndvi(0.10, 0.40), 1e-6)
    oracle.close("a valid zero NDVI stays valid", float(np.ma.getdata(delivered)[0, 1]), 0.0, 1e-9)
    oracle.require(
        "a valid zero is not masked as nodata",
        not bool(np.ma.getmaskarray(delivered)[0, 1]),
        "masked" if np.ma.getmaskarray(delivered)[0, 1] else "valid",
        "valid",
    )
    oracle.require(
        "a zero denominator becomes nodata, not a clipped value",
        bool(np.ma.getmaskarray(delivered)[0, 2]),
        "masked" if np.ma.getmaskarray(delivered)[0, 2] else "valid",
        "masked",
    )
    oracle.require(
        "the input mask is propagated",
        bool(np.ma.getmaskarray(delivered)[2, 2]),
        "masked" if np.ma.getmaskarray(delivered)[2, 2] else "valid",
        "masked",
    )
    dn_ratio = (dn_nir[0, 0].astype("float64") - dn_red[0, 0]) / (dn_nir[0, 0].astype("float64") + dn_red[0, 0])
    oracle.differs_by(
        "a DN ratio differs from the physical NDVI",
        dn_ratio,
        ndvi(0.10, 0.40),
        0.05,
        note="both values lie inside the index range, so the range screen cannot separate them",
    )
    index_status = _index_ok(steps, "rs.index_range")
    nodata_status = _index_ok(steps, "raster.nodata_declared")
    oracle.require(
        "rs.index_range passes on the NDVI output",
        bool(index_status) and index_status[0].status == "pass",
        index_status[0].status if index_status else None,
        "pass",
    )
    oracle.require(
        "raster.nodata_declared passes on the NDVI output",
        bool(nodata_status) and nodata_status[0].status == "pass",
        nodata_status[0].status if nodata_status else None,
        "pass",
    )
    correct_control = correct(
        "physical-reflectance-ndvi",
        "Physical reflectance red/NIR with a valid zero, a zero denominator, an input nodata pixel and "
        "an independently checked NDVI control.",
        steps,
        oracle,
    )

    dn_values = np.full(SHAPE, np.nan, dtype="float64")
    dn_valid = (dn_red != 0) & (dn_nir != 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        dn_values[dn_valid] = (dn_nir[dn_valid].astype("float64") - dn_red[dn_valid]) / (
            dn_nir[dn_valid].astype("float64") + dn_red[dn_valid]
        )
    dn_ndvi_path = _write_index(root / "ndvi_dn_ratio.tif", dn_values)
    wrong_steps = [check_step("check ndvi_dn_ratio.tif --expect index", [dn_ndvi_path], expect="index")]
    wrong_oracle = Oracle("an unscaled DN ratio stays in range and is not calibrated NDVI")
    wrong_values = read_raster(dn_ndvi_path)
    wrong_oracle.close(
        "control NDVI (red 0.10, NIR 0.40)",
        float(np.ma.getdata(wrong_values)[0, 0]),
        ndvi(0.10, 0.40),
        1e-6,
    )
    wrong_oracle.differs_by(
        "the DN-ratio value differs from the physical NDVI",
        float(np.ma.getdata(wrong_values)[0, 0]),
        ndvi(0.10, 0.40),
        0.05,
    )
    wrong_control = wrong(
        "unscaled-dn-ratio",
        "NDVI is computed from raw DN after the offset encoding, so the additive offsets do not cancel; "
        "the values still fall inside [-1, 1].",
        wrong_steps,
        wrong_oracle,
        notes="rs.index_range cannot identify this; only the independent physical calculation can.",
    )
    return recipe(
        "indices-ndvi-physical-inputs",
        correct_control,
        [wrong_control],
        automated_scope=[
            "rs.index_range and raster.nodata_declared on the NDVI output",
            "independent physical-reflectance NDVI values, mask propagation and valid-zero handling",
            "a DN-ratio control showing that the range screen accepts uncalibrated input",
        ],
        remaining=[
            "The answer must explain that additive offsets do not cancel in the ratio and that a plausible range does not prove calibration; prose is not graded.",
            "Review of the sensor band mapping for the actual products.",
        ],
    )


def indices_water(root: Path):
    """Task 2: McFeeters NDWI and MNDWI on the same grid."""
    green = _band(0.12, 0.003)
    nir = _band(0.03, 0.002)
    swir1 = _band(0.08, 0.003)
    green[0, 0], nir[0, 0], swir1[0, 0] = 0.15, 0.05, 0.10
    green[1, 1], nir[1, 1], swir1[1, 1] = 0.20, 0.20, 0.20
    mcfeeters = _write_index(root / "ndwi_mcfeeters.tif", ndwi_mcfeeters(green, nir))
    mndwi_path = _write_index(root / "mndwi.tif", mndwi(green, swir1))
    steps = [
        check_step(
            "check ndwi_mcfeeters.tif mndwi.tif --expect index",
            [mcfeeters, mndwi_path],
            expect="index",
        )
    ]
    oracle = Oracle("two named water indices on one grid")
    oracle.close("McFeeters NDWI control (green 0.15, NIR 0.05)", ndwi_mcfeeters(0.15, 0.05), 0.5, 1e-6)
    oracle.close("MNDWI control (green 0.15, SWIR1 0.10)", mndwi(0.15, 0.10), 0.2, 1e-6)
    oracle.close("Gao's moisture NDWI on the same control", ndwi_gao(0.05, 0.10), -1 / 3, 1e-6)
    oracle.differs_by(
        "the Gao definition differs from McFeeters NDWI on the control",
        float(ndwi_gao(0.05, 0.10)),
        float(ndwi_mcfeeters(0.15, 0.05)),
        0.5,
    )
    for check_id, count in (("rs.index_range", 2), ("raster.nodata_declared", 2), ("raster.grid_alignment", 1)):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} emits the expected pass results",
            len(observed) == count and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    correct_control = correct(
        "named-water-indices",
        "Physical green/NIR/SWIR1 bands producing McFeeters NDWI and MNDWI on one grid with declared nodata.",
        steps,
        oracle,
    )

    mislabeled = _write_index(root / "ndwi_mislabeled.tif", ndwi_gao(nir, swir1))
    wrong_steps = [
        check_step("check ndwi_mislabeled.tif mndwi.tif --expect index", [mislabeled, mndwi_path], expect="index"),
    ]
    wrong_oracle = Oracle("the Gao moisture ratio is not the McFeeters NDWI definition")
    mislabeled_values = read_raster(mislabeled)
    wrong_oracle.close(
        "McFeeters NDWI control (green 0.15, NIR 0.05)",
        float(np.ma.getdata(mislabeled_values)[0, 0]),
        ndwi_mcfeeters(0.15, 0.05),
        1e-6,
    )
    wrong_oracle.differs_by(
        "the mislabeled layer differs from McFeeters NDWI",
        float(np.ma.getdata(mislabeled_values)[0, 0]),
        ndwi_mcfeeters(0.15, 0.05),
        0.1,
    )
    wrong_control = wrong(
        "gao-moisture-mislabeled",
        "The Gao moisture ratio is exported under the McFeeters NDWI name; both layers stay inside the "
        "index range.",
        wrong_steps,
        wrong_oracle,
    )
    return recipe(
        "indices-water-definition-grid",
        correct_control,
        [wrong_control],
        automated_scope=[
            "rs.index_range, raster.grid_alignment and raster.nodata_declared on both water-index outputs",
            "independent McFeeters/MNDWI/Gao formula controls on the same pixels",
        ],
        remaining=[
            "The answer must name the formula each layer uses, explain the effective SWIR resolution and choose a threshold from the local reference sample; prose is not graded.",
            "Review of the coarser SWIR alignment for the real Sentinel-2 grid.",
        ],
    )


def indices_burn_evi(root: Path):
    """Task 3: NBR/dNBR, EVI and SAVI with formula controls that leave the nominal range."""
    pre_nir = _band(0.30, 0.01)
    pre_swir2 = _band(0.12, 0.004)
    pre_nir[0, 0], pre_swir2[0, 0] = 0.90, 0.01
    post_nir = _band(0.30, 0.008)
    post_swir2 = _band(0.14, 0.006)
    post_nir[0, 0], post_swir2[0, 0] = 0.01, 0.60
    pre_nbr_values = nbr(pre_nir, pre_swir2)
    post_nbr_values = nbr(post_nir, post_swir2)
    pre_nbr = _write_index(root / "nbr_prefire.tif", pre_nbr_values)
    post_nbr = _write_index(root / "nbr_postfire.tif", post_nbr_values)
    steps = [
        check_step(
            "check nbr_prefire.tif nbr_postfire.tif --expect index",
            [pre_nbr, post_nbr],
            expect="index",
        )
    ]
    control_pre = float(nbr(0.90, 0.01))
    control_post = float(nbr(0.01, 0.60))
    d_nbr = control_pre - control_post
    oracle = Oracle("NBR/dNBR sign and the EVI/SAVI formulas outside the nominal range")
    oracle.close("pre-fire NBR control", control_pre, 0.978, 0.001)
    oracle.close("post-fire NBR control", control_post, -0.967213, 0.001)
    oracle.close("dNBR control is pre minus post", d_nbr, 1.945235, 0.001)
    oracle.require("dNBR exceeds 1 and is not clipped", d_nbr > 1.0, round(d_nbr, 6), "> 1.0")
    evi_control = float(evi(0.215, 0.10, 0.30))
    savi_control = float(savi(0.10, 0.30, 0.5))
    oracle.close("EVI control (blue 0.215, red 0.10, NIR 0.30)", evi_control, 1.7391304347826089, 1e-6)
    oracle.require("EVI is finite and outside [-1, 1]", np.isfinite(evi_control) and evi_control > 1.0, round(evi_control, 6), "> 1.0")
    oracle.close("SAVI control with L=0.5", savi_control, 0.3333333333333333, 1e-6)
    oracle.require(
        "SAVI differs from the NDVI value on the same bands",
        abs(savi_control - float(ndvi(0.10, 0.30))) > 1e-6,
        round(savi_control, 6),
        round(float(ndvi(0.10, 0.30)), 6),
    )
    for check_id, count in (("rs.index_range", 2), ("raster.grid_alignment", 1), ("raster.nodata_declared", 2)):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} emits the expected pass results",
            len(observed) == count and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    correct_control = correct(
        "nbr-evi-savi-formulas",
        "Same-grid physical blue/red/NIR/SWIR2 bands; NBR pre/post outputs are in [-1, 1], while the EVI "
        "and dNBR controls are finite but outside the nominal range.",
        steps,
        oracle,
    )

    reversed_dnbr = _write_index(root / "dnbr_reversed.tif", -(pre_nbr_values.astype("float64") - post_nbr_values.astype("float64")))
    wrong_steps = [
        check_step(
            "check nbr_prefire.tif nbr_postfire.tif --expect index",
            [pre_nbr, post_nbr],
            expect="index",
        ),
    ]
    wrong_oracle = Oracle("dNBR sign: pre-fire minus post-fire")
    wrong_values = read_raster(reversed_dnbr)
    wrong_oracle.close(
        "dNBR control is positive (pre minus post)",
        float(np.ma.getdata(wrong_values)[0, 0]),
        d_nbr,
        0.001,
    )
    wrong_oracle.require("dNBR is positive", float(np.ma.getdata(wrong_values)[0, 0]) > 0, float(np.ma.getdata(wrong_values)[0, 0]), "> 0")
    wrong_control = wrong(
        "reversed-dnbr-sign",
        "dNBR is post minus pre; the sign is inverted but every index value remains in range.",
        wrong_steps,
        wrong_oracle,
        notes="The reversed dNBR is a valid index range; only the sign oracle rejects it.",
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        wrong_pre = nbr(pre_nir, pre_swir2 * 0.5 + 0.05)  # SWIR1-like band, still inside [-1, 1]
    wrong_pre_path = _write_index(root / "nbr_swir1.tif", wrong_pre)
    swir_oracle = Oracle("NBR must use SWIR2, not SWIR1")
    wrong_pre_values = read_raster(wrong_pre_path)
    swir_oracle.close(
        "pre-fire NBR control",
        float(np.ma.getdata(wrong_pre_values)[0, 0]),
        control_pre,
        0.001,
    )
    swir_oracle.differs_by(
        "the SWIR1-based value differs from the SWIR2-based NBR",
        float(np.ma.getdata(wrong_pre_values)[0, 0]),
        control_pre,
        0.01,
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "nbr-wrong-swir-band",
            "NBR is computed from SWIR1; the value is still inside [-1, 1] and passes the range screen.",
            [
                check_step(
                    "check nbr_swir1.tif nbr_postfire.tif --expect index",
                    [wrong_pre_path, post_nbr],
                    expect="index",
                )
            ],
            swir_oracle,
        ),
    ]
    return recipe(
        "indices-burn-evi-savi-ranges",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.index_range, raster.grid_alignment and raster.nodata_declared on the NBR outputs",
            "independent NBR/dNBR, EVI (gain 2.5, 6, 7.5, 1) and SAVI (L=0.5) controls, including out-of-nominal finite values",
        ],
        remaining=[
            "The answer must explain why dNBR spans [-2, 2], why EVI is not universally bounded and why valid changes are not clipped; prose is not graded.",
            "Review of the burn-severity threshold and seasonal confounding for the study.",
        ],
    )


RECIPES = {
    "indices-ndvi-physical-inputs": indices_ndvi_physical,
    "indices-water-definition-grid": indices_water,
    "indices-burn-evi-savi-ranges": indices_burn_evi,
}
