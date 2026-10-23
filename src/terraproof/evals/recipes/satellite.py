"""Fixtures and oracles for the `satellite-preprocessing` task specs."""

from __future__ import annotations

from pathlib import Path
import warnings

import numpy as np
import rasterio

from terraproof.evals.fixtures import FLOAT_NODATA, UTM, read_raster, write_raster, write_stac_item
from terraproof.evals.oracles import Oracle, landsat_decode, s2_decode
from terraproof.evals.recipes._util import check_step, correct, recipe, results_for, wrong
from terraproof.inspect import inspect_dataset

SCL_CLOUD = (3, 8, 9, 10)
LANDSAT_QA_MASK = 0b111111  # fill, dilated cloud, cirrus, cloud, shadow, snow (snow-free policy)
SHAPE = (32, 32)


def _control_grid(seed_dn: int = 800) -> np.ndarray:
    rows, cols = np.indices(SHAPE)
    return np.asarray(seed_dn + 60 * ((rows + cols) % 30), dtype="uint16")


def _scl() -> np.ndarray:
    scl = np.full(SHAPE, 4, dtype="uint8")
    scl[20:26, 20:26] = 6  # water
    for (row, col), code in (((0, 0), 8), ((8, 8), 3), ((16, 16), 9), ((24, 24), 10)):
        scl[row, col] = code
    return scl


def _masked_decode(dn: np.ndarray, scl: np.ndarray, *, offset: float = -0.1, scale: float = 0.0001) -> np.ndarray:
    output = np.full(dn.shape, FLOAT_NODATA, dtype="float32")
    valid = (dn != 0) & ~np.isin(scl, SCL_CLOUD)
    output[valid] = dn[valid] * scale + offset
    return output


def satellite_s2_baseline_offset(root: Path):
    """Task 1: Sentinel-2 L2A offset decode with SCL cloud/shadow masking."""
    red_dn = _control_grid(800)
    nir_dn = _control_grid(1200)
    red_dn[1, 0] = 800
    red_dn[0, 1] = 2500
    red_dn[0, 2] = 0
    nir_dn[0, 2] = 0
    scl = _scl()
    red = _masked_decode(red_dn, scl)
    nir = _masked_decode(nir_dn, scl)
    dn_red = write_raster(root / "red_dn.tif", red_dn, crs=UTM, nodata=65535, dtype="uint16", scale=0.0001, offset=-0.1)
    dn_nir = write_raster(root / "nir_dn.tif", nir_dn, crs=UTM, nodata=65535, dtype="uint16", scale=0.0001, offset=-0.1)
    scl_path = write_raster(root / "scl.tif", scl, crs=UTM, nodata=0, dtype="uint8")
    sr_red = write_raster(root / "sr_red.tif", red, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    sr_nir = write_raster(root / "sr_nir.tif", nir, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")

    steps = [
        check_step("check sr_red.tif sr_nir.tif --expect reflectance", [sr_red, sr_nir], expect="reflectance"),
        check_step(
            "run_checks(['sr_red.tif'], encoding='s2-l2a', reference_input='red_dn.tif')",
            [sr_red],
            reference_input=inspect_dataset(dn_red),
            encoding="s2-l2a",
        ),
        check_step(
            "run_checks(['sr_red.tif'], qa_path='scl.tif', qa_kind='s2-scl')",
            [sr_red],
            qa_path=scl_path,
            qa_kind="s2-scl",
        ),
    ]
    oracle = Oracle("Sentinel-2 L2A decode once and mask SCL 3/8/9/10")
    delivered = read_raster(sr_red)
    oracle.close(
        "DN 800 decodes to reflectance -0.02 (negative reflectance kept)",
        float(np.ma.getdata(delivered)[1, 0]),
        s2_decode(800),
        1e-6,
    )
    oracle.close(
        "DN 2500 decodes to 0.15",
        float(np.ma.getdata(delivered)[0, 1]),
        s2_decode(_dn_at(red_dn, 0, 1)),
        1e-6,
        note="control pixel holds DN 2,500",
    )
    oracle.require(
        "DN 0 is nodata, not -0.1 reflectance",
        bool(np.ma.getmaskarray(delivered)[0, 2]),
        "masked" if np.ma.getmaskarray(delivered)[0, 2] else "valid",
        "masked",
    )
    for row, col in ((0, 0), (8, 8), (16, 16), (24, 24)):
        oracle.require(
            f"SCL class {int(scl[row, col])} pixel ({row},{col}) is masked",
            bool(np.ma.getmaskarray(delivered)[row, col]),
            "masked" if np.ma.getmaskarray(delivered)[row, col] else "valid",
            "masked",
        )
    water = (22, 22)
    oracle.require(
        "water (SCL 6) stays valid",
        not bool(np.ma.getmaskarray(delivered)[water]),
        "masked" if np.ma.getmaskarray(delivered)[water] else "valid",
        "valid",
    )
    with rasterio.open(sr_red) as src:
        oracle.equal("the physical reflectance has identity scale/offset", (src.scales[0], src.offsets[0]), (1.0, 0.0))
        oracle.equal("nodata is declared on the decoded output", src.nodatavals[0], FLOAT_NODATA)
    reflectance = results_for(steps, "rs.reflectance_range")
    grid = results_for(steps, "raster.grid_alignment")
    nodata = results_for(steps, "raster.nodata_declared")
    scale_once = results_for(steps, "rs.scale_applied_once")
    clouds = results_for(steps, "rs.cloud_mask_applied")
    oracle.require(
        "rs.reflectance_range passes on both decoded bands",
        len(reflectance) == 2 and all(result.status == "pass" for result in reflectance),
        [result.status for result in reflectance],
        "pass",
    )
    oracle.require(
        "raster.grid_alignment passes on the decoded pair",
        bool(grid) and grid[0].status == "pass",
        grid[0].status if grid else None,
        "pass",
    )
    oracle.require(
        "raster.nodata_declared passes on every decoded band",
        bool(nodata) and all(result.status == "pass" for result in nodata),
        [result.status for result in nodata],
        "pass",
    )
    oracle.require(
        "rs.scale_applied_once confirms one offset application",
        bool(scale_once) and scale_once[0].status == "pass",
        scale_once[0].status if scale_once else None,
        "pass",
    )
    oracle.require(
        "rs.cloud_mask_applied confirms the SCL mask",
        bool(clouds) and clouds[0].status == "pass",
        clouds[0].status if clouds else None,
        "pass",
    )
    correct_control = correct(
        "decoded-once-scl-masked",
        "Original L2A DN with the baseline offset, decoded exactly once to physical reflectance with SCL "
        "3/8/9/10 masked and DN 0 as nodata.",
        steps,
        oracle,
    )

    no_offset = _masked_decode(red_dn, scl, offset=0.0)
    no_offset_path = write_raster(root / "sr_red_no_offset.tif", no_offset, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    wrong_steps = [
        check_step("check sr_red_no_offset.tif sr_nir.tif --expect reflectance", [no_offset_path, sr_nir], expect="reflectance"),
        check_step("run_checks(no_offset, reference_input=red_dn, encoding='s2-l2a')", [no_offset_path],
                   reference_input=inspect_dataset(dn_red), encoding="s2-l2a"),
    ]
    wrong_oracle = Oracle("the offset must be applied from the product baseline, not the acquisition date")
    wrong_values = read_raster(no_offset_path)
    oracle_offset_missing = float(np.ma.getdata(wrong_values)[1, 0])
    wrong_oracle.close(
        "DN 800 decodes to reflectance -0.02",
        oracle_offset_missing,
        s2_decode(800),
        1e-6,
    )
    wrong_oracle.differs_by(
        "the no-offset decode differs from the calibrated value",
        oracle_offset_missing,
        s2_decode(800),
        0.05,
    )
    wrong_control = wrong(
        "offset-skipped",
        "The DN is divided by 10,000 without the -1,000 BOA offset, which stays inside the reflectance "
        "plausibility interval and passes rs.reflectance_range.",
        wrong_steps,
        wrong_oracle,
        notes="rs.reflectance_range is a range screen; it cannot see a uniform 0.1 reflectance bias.",
    )

    unmasked = np.full(red_dn.shape, FLOAT_NODATA, dtype="float32")
    valid_dn = red_dn != 0
    unmasked[valid_dn] = red_dn[valid_dn] * 0.0001 - 0.1
    unmasked_path = write_raster(root / "sr_red_unmasked.tif", unmasked, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    unmasked_steps = [
        check_step("check sr_red_unmasked.tif sr_nir.tif --expect reflectance", [unmasked_path, sr_nir], expect="reflectance"),
        check_step(
            "run_checks(['sr_red_unmasked.tif'], qa_path='scl.tif', qa_kind='s2-scl')",
            [unmasked_path],
            qa_path=scl_path,
            qa_kind="s2-scl",
        ),
    ]
    unmasked_oracle = Oracle("cloud and shadow pixels must be nodata in the decoded output")
    unmasked_values = read_raster(unmasked_path)
    for row, col in ((0, 0), (8, 8), (16, 16), (24, 24)):
        unmasked_oracle.require(
            f"SCL class {int(scl[row, col])} pixel ({row},{col}) is masked",
            bool(np.ma.getmaskarray(unmasked_values)[row, col]),
            "masked" if np.ma.getmaskarray(unmasked_values)[row, col] else "valid",
            "masked",
        )
    cloud_status = results_for(unmasked_steps, "rs.cloud_mask_applied")
    unmasked_oracle.require(
        "rs.cloud_mask_applied reports the unmasked cloud pixels",
        bool(cloud_status) and cloud_status[0].status == "fail",
        cloud_status[0].status if cloud_status else None,
        "fail",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "cloud-mask-skipped",
            "The offset is applied but SCL cloud/shadow pixels keep their reflectance values.",
            unmasked_steps,
            unmasked_oracle,
        ),
    ]
    return recipe(
        "satellite-s2-baseline-offset-mask",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.reflectance_range, raster.grid_alignment and raster.nodata_declared on the decoded outputs",
            "rs.scale_applied_once against the original DN and rs.cloud_mask_applied against the SCL raster",
            "independent decode controls (DN 800 -> -0.02, DN 0 -> nodata) and the SCL masking policy",
        ],
        remaining=[
            "The answer must explain that a range pass does not prove masks or exact-once offset application, and state the metadata source for the baseline; prose is not graded.",
            "Review of the snow, unclassified and cast-shadow policy for the scene.",
        ],
    )


def _dn_at(array: np.ndarray, row: int, col: int) -> float:
    return float(array[row, col])


def _landsat_qa() -> np.ndarray:
    qa = np.full(SHAPE, 64, dtype="uint16")  # clear
    qa[0, 0] = 1  # fill
    qa[8, 8] = 8 | 64  # cloud and clear
    qa[16, 16] = 16 | 64  # shadow and clear
    qa[24, 24] = 32 | 64  # snow and clear
    qa[4, 4] = 2  # dilated cloud
    qa[5, 5] = 4  # cirrus
    qa[6, 6] = 128 | 64  # water, retained
    return qa


def satellite_landsat_qa(root: Path):
    """Task 2: Landsat Collection 2 decode once and a complete QA_PIXEL policy."""
    rows, cols = np.indices(SHAPE)
    dn = (4000 + 800 * ((rows * 3 + cols) % 28)).astype("uint16")
    dn[0, 0] = 0
    dn[10, 10] = 25000
    qa = _landsat_qa()
    masked = (qa & LANDSAT_QA_MASK) != 0
    reflectance = np.full(SHAPE, FLOAT_NODATA, dtype="float32")
    reflectance[~masked] = landsat_decode(dn[~masked])
    sr_path = write_raster(root / "landsat_sr.tif", reflectance, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    dn_path = write_raster(root / "landsat_dn.tif", dn, crs=UTM, nodata=0, dtype="uint16", scale=0.0000275, offset=-0.2)
    qa_path = write_raster(root / "qa_pixel.tif", qa, crs=UTM, nodata=0, dtype="uint16")

    steps = [
        check_step("check landsat_sr.tif --expect reflectance", [sr_path], expect="reflectance"),
        check_step("run_checks(sr, reference_input=landsat_dn, encoding='landsat-c2-l2')", [sr_path],
                   reference_input=inspect_dataset(dn_path), encoding="landsat-c2-l2"),
        check_step(
            "run_checks(['landsat_sr.tif'], qa_path='qa_pixel.tif', qa_kind='landsat-qa-pixel')",
            [sr_path],
            qa_path=qa_path,
            qa_kind="landsat-qa-pixel",
        ),
    ]
    control_dn = 25000
    control_reflectance = landsat_decode(control_dn)
    delivered = read_raster(sr_path)
    steady = (10, 10)
    oracle = Oracle("Landsat C2 L2: one decode and complete QA_PIXEL semantics")
    oracle.close(
        "control DN 25,000 decodes to 0.4875",
        float(np.ma.getdata(delivered)[steady]),
        control_reflectance,
        1e-6,
        note=f"the fixture pixel at {steady} holds DN 25,000",
    )
    oracle.close(
        "a second decode would give -0.19999, still inside the reflectance screen",
        landsat_decode(control_reflectance),
        -0.1999866,
        1e-5,
    )
    oracle.differs_by(
        "the double-decoded control is clearly separated from the correct one",
        landsat_decode(control_reflectance),
        control_reflectance,
        0.1,
    )
    for (row, col), label in (((0, 0), "fill"), ((8, 8), "cloud"), ((16, 16), "shadow"), ((24, 24), "snow")):
        oracle.require(
            f"{label} pixel ({row},{col}) is nodata",
            bool(np.ma.getmaskarray(delivered)[row, col]),
            "masked" if np.ma.getmaskarray(delivered)[row, col] else "valid",
            "masked",
        )
    water = (6, 6)
    oracle.require(
        "water (QA_PIXEL bit 7) stays valid",
        not bool(np.ma.getmaskarray(delivered)[water]),
        "masked" if np.ma.getmaskarray(delivered)[water] else "valid",
        "valid",
    )
    with rasterio.open(sr_path) as src:
        oracle.equal("output scale/offset is identity", (src.scales[0], src.offsets[0]), (1.0, 0.0))
        oracle.equal("nodata is declared", src.nodatavals[0], FLOAT_NODATA)
    reflectance_status = results_for(steps, "rs.reflectance_range")
    nodata_status = results_for(steps, "raster.nodata_declared")
    cloud_status = results_for(steps, "rs.cloud_mask_applied")
    oracle.require(
        "rs.reflectance_range passes on the decoded output",
        bool(reflectance_status) and reflectance_status[0].status == "pass",
        reflectance_status[0].status if reflectance_status else None,
        "pass",
    )
    oracle.require(
        "raster.nodata_declared passes on the decoded output",
        bool(nodata_status) and nodata_status[0].status == "pass",
        nodata_status[0].status if nodata_status else None,
        "pass",
    )
    oracle.require(
        "rs.cloud_mask_applied passes with the complete QA policy",
        bool(cloud_status) and cloud_status[0].status == "pass",
        cloud_status[0].status if cloud_status else None,
        "pass",
    )
    correct_control = correct(
        "landsat-decode-once-qa",
        "SR DN decoded once with 0.0000275 * DN - 0.2, a complete QA_PIXEL policy (fill, dilated cloud, "
        "cirrus, cloud, shadow, snow) and water retained.",
        steps,
        oracle,
    )

    double = np.full(SHAPE, FLOAT_NODATA, dtype="float32")
    double[~masked] = landsat_decode(landsat_decode(dn[~masked]))
    double_path = write_raster(root / "landsat_sr_double.tif", double, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    wrong_steps = [check_step(
        "run_checks(double, expect='reflectance', reference_input=landsat_dn, encoding='landsat-c2-l2')",
        [double_path], expect="reflectance", reference_input=inspect_dataset(dn_path), encoding="landsat-c2-l2",
    )]
    wrong_oracle = Oracle("a loader that already decoded the raster must not be decoded twice")
    wrong_values = read_raster(double_path)
    wrong_oracle.close(
        "control DN 25,000 decodes once to 0.4875",
        float(np.ma.getdata(wrong_values)[steady]),
        control_reflectance,
        1e-6,
    )
    wrong_oracle.differs_by(
        "the double-decoded value differs from the correct reflectance",
        float(np.ma.getdata(wrong_values)[steady]),
        control_reflectance,
        0.1,
    )
    wrong_control = wrong(
        "double-decoded-loader",
        "The loader already applied the calibration, so applying 0.0000275 * DN - 0.2 again yields values "
        "such as -0.2 that still pass the reflectance range screen.",
        wrong_steps,
        wrong_oracle,
        notes="The range screen accepts the double decode; only an exact-once comparison sees it.",
    )

    clear_only = np.full(SHAPE, FLOAT_NODATA, dtype="float32")
    clear_bit = (qa & 64) != 0
    clear_only[clear_bit] = landsat_decode(dn[clear_bit])
    clear_path = write_raster(root / "landsat_sr_clear_only.tif", clear_only, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    clear_steps = [
        check_step("check landsat_sr_clear_only.tif --expect reflectance", [clear_path], expect="reflectance"),
        check_step(
            "run_checks(['landsat_sr_clear_only.tif'], qa_path='qa_pixel.tif', qa_kind='landsat-qa-pixel')",
            [clear_path],
            qa_path=qa_path,
            qa_kind="landsat-qa-pixel",
        ),
    ]
    clear_oracle = Oracle("the clear bit alone is not a complete quality mask")
    clear_values = read_raster(clear_path)
    for (row, col), label in (((8, 8), "cloud"), ((16, 16), "shadow"), ((24, 24), "snow")):
        clear_oracle.require(
            f"{label} pixel ({row},{col}) is nodata",
            bool(np.ma.getmaskarray(clear_values)[row, col]),
            "masked" if np.ma.getmaskarray(clear_values)[row, col] else "valid",
            "masked",
        )
    clear_cloud = results_for(clear_steps, "rs.cloud_mask_applied")
    clear_oracle.require(
        "rs.cloud_mask_applied reports the clear-but-cloudy pixels",
        bool(clear_cloud) and clear_cloud[0].status == "fail",
        clear_cloud[0].status if clear_cloud else None,
        "fail",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "clear-bit-only-mask",
            "Only QA_PIXEL bit 6 (clear) decides validity, so pixels that are clear and cloudy or snowy "
            "stay in the snow-free product.",
            clear_steps,
            clear_oracle,
        ),
    ]
    return recipe(
        "satellite-landsat-qa-once",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.reflectance_range and raster.nodata_declared on the decoded output",
            "rs.cloud_mask_applied against the generated QA_PIXEL raster",
            "independent decode controls and the per-bit QA masking policy, including water retention",
        ],
        remaining=[
            "The answer must explain why exact-once decoding and QA semantics need independent tests even when the range check passes; prose is not graded.",
            "Review of the saturation/aerosol policy for the actual product.",
        ],
    )


S2_DATES = (0.05, 0.10, 0.04)
NIR_DATES = (0.40, 0.20, 0.30)
COMPOSITE_NODATA = FLOAT_NODATA


def satellite_seasonal_composite(root: Path):
    """Task 3: a cloud-screened seasonal composite with a valid-observation count layer."""
    shape = (16, 16)
    rows, cols = np.indices(shape)
    red_dates = []
    nir_dates = []
    for index, (red_base, nir_base) in enumerate(zip(S2_DATES, NIR_DATES)):
        red = red_base + 0.01 * ((rows + cols + index) % 5)
        nir = nir_base + 0.01 * ((rows * 2 + cols + index) % 7)
        red_dates.append(red.astype("float32"))
        nir_dates.append(nir.astype("float32"))
    qa_masks = [
        np.zeros(shape, dtype=bool),
        np.zeros(shape, dtype=bool),
        (rows >= 8) & (cols >= 8),  # a cloudy third date over the south-east block
    ]
    qa_masks[0][0, 0] = True
    qa_masks[1][0, 0] = True
    qa_masks[2][0, 0] = True  # a wholly invalid pixel
    qa_masks[1][2, 3] = True

    for index in range(3):
        for suffix, values in (("red", red_dates), ("nir", nir_dates)):
            array = values[index].copy()
            array[qa_masks[index]] = COMPOSITE_NODATA
            write_raster(
                root / f"s2_date{index + 1}_{suffix}.tif",
                array,
                crs=UTM,
                nodata=COMPOSITE_NODATA,
                dtype="float32",
            )
    stack = np.stack([red_dates[index] for index in range(3)])
    valid = np.stack([~qa_masks[index] for index in range(3)])
    values = np.where(valid, stack, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        composite = np.nanmedian(values, axis=0).astype("float32")
    counts = valid.sum(axis=0).astype("uint8")
    composite[counts == 0] = COMPOSITE_NODATA
    composite_path = write_raster(root / "composite.tif", composite, crs=UTM, nodata=COMPOSITE_NODATA, dtype="float32")
    counts_path = write_raster(root / "composite_counts.tif", counts, crs=UTM, nodata=255, dtype="uint8")
    item = write_stac_item(
        root / "source-item.json",
        item_id="S2B_COMPOSITE_SOURCE",
        datetime="2024-06-15T10:30:00Z",
        proj_code="EPSG:32636",
        assets={"red": {"href": "https://example.invalid/red.tif", "raster:bands": [{"scale": 0.0001, "offset": -0.1, "nodata": 0}]}},
    )

    steps = [
        check_step("check composite.tif --expect reflectance", [composite_path], expect="reflectance"),
        check_step("check source-item.json", [item]),
    ]
    delivered = read_raster(composite_path)
    oracle = Oracle("masked median composite and per-pixel valid-observation counts")
    expected_median = float(np.nanmedian([red_dates[0][5, 5], red_dates[1][5, 5], red_dates[2][5, 5]]))
    oracle.close("control pixel composite median (reflectance)", float(np.ma.getdata(delivered)[5, 5]), expected_median, 1e-6)
    oracle.equal("control pixel valid-observation count", int(np.ma.getdata(read_raster(counts_path))[5, 5]), 3)
    oracle.require(
        "the wholly invalid pixel is nodata",
        bool(np.ma.getmaskarray(delivered)[0, 0]),
        "masked" if np.ma.getmaskarray(delivered)[0, 0] else "valid",
        "masked",
    )
    red_at = [float(red_dates[index][9, 9]) for index in range(3)]
    valid_red = [red_at[index] for index in range(3) if not qa_masks[index][9, 9]]
    oracle.close(
        "cloudy-date exclusion changes the median in the masked block",
        float(np.ma.getdata(delivered)[9, 9]),
        float(np.median(valid_red)),
        1e-6,
    )
    oracle.differs_by(
        "including the cloudy observation would change the composite value",
        float(np.median(red_at)),
        float(np.median(valid_red)),
        0.005,
    )
    reflectance_status = results_for(steps, "rs.reflectance_range")
    nodata_status = results_for(steps, "raster.nodata_declared")
    stac_status = results_for(steps, "stac.provenance")
    oracle.require(
        "rs.reflectance_range passes on the composite",
        bool(reflectance_status) and reflectance_status[0].status == "pass",
        reflectance_status[0].status if reflectance_status else None,
        "pass",
    )
    oracle.require(
        "raster.nodata_declared passes on the composite",
        bool(nodata_status) and nodata_status[0].status == "pass",
        nodata_status[0].status if nodata_status else None,
        "pass",
    )
    oracle.require(
        "stac.provenance passes on the source Item",
        bool(stac_status) and stac_status[0].status == "pass",
        stac_status[0].status if stac_status else None,
        "pass",
    )
    correct_control = correct(
        "cloud-screened-median-composite",
        "Three physical-reflectance dates with a cloudy block, a masked single-date observation and a "
        "wholly invalid pixel; the composite is a masked median with a count layer.",
        steps,
        oracle,
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        inclusive = np.nanmedian(stack, axis=0).astype("float32")
    inclusive[counts == 0] = COMPOSITE_NODATA
    inclusive_path = write_raster(root / "composite_cloudy.tif", inclusive, crs=UTM, nodata=COMPOSITE_NODATA, dtype="float32")
    wrong_steps = [
        check_step("check composite_cloudy.tif --expect reflectance", [inclusive_path], expect="reflectance"),
        check_step("check source-item.json", [item]),
    ]
    wrong_oracle = Oracle("a composite that includes cloudy observations is biased")
    wrong_values = read_raster(inclusive_path)
    wrong_oracle.close(
        "control pixel composite median (reflectance)",
        float(np.ma.getdata(wrong_values)[5, 5]),
        expected_median,
        1e-6,
    )
    wrong_oracle.close(
        "cloudy-block median excludes the cloudy observation",
        float(np.ma.getdata(wrong_values)[9, 9]),
        float(np.median(valid_red)),
        1e-6,
    )
    wrong_control = wrong(
        "cloudy-dates-included",
        "The median includes the cloudy third date, which biases the composite while staying in the "
        "reflectance plausibility interval.",
        wrong_steps,
        wrong_oracle,
        notes="rs.reflectance_range accepts the biased composite; only the independent median sees it.",
    )

    zero_filled = composite.copy()
    zero_filled[0, 0] = 0.0
    zero_path = write_raster(root / "composite_zero_filled.tif", zero_filled, crs=UTM, nodata=COMPOSITE_NODATA, dtype="float32")
    zero_steps = [
        check_step("check composite_zero_filled.tif --expect reflectance", [zero_path], expect="reflectance"),
    ]
    zero_oracle = Oracle("an all-invalid pixel must stay nodata, not become 0")
    zero_values = read_raster(zero_path)
    zero_oracle.require(
        "the wholly invalid pixel is nodata",
        bool(np.ma.getmaskarray(zero_values)[0, 0]),
        "masked" if np.ma.getmaskarray(zero_values)[0, 0] else "valid 0.0",
        "masked",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "invalid-pixel-zero-filled",
            "The wholly invalid pixel is written as valid 0.0 reflectance instead of nodata.",
            zero_steps,
            zero_oracle,
        ),
    ]
    return recipe(
        "satellite-seasonal-harmonized-composite",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.reflectance_range and raster.nodata_declared on the composite, stac.provenance on the source Item",
            "independent masked-median values, valid-observation counts and all-invalid nodata handling",
        ],
        remaining=[
            "Sensor harmonization, residual angular/spectral differences and a documented harmonized-product contract need expert review; the harness only compares physical-reflectance values.",
            "The answer must state that stac.provenance does not verify harmonization, masks, all scene dates or licenses.",
        ],
    )


RECIPES = {
    "satellite-s2-baseline-offset-mask": satellite_s2_baseline_offset,
    "satellite-landsat-qa-once": satellite_landsat_qa,
    "satellite-seasonal-harmonized-composite": satellite_seasonal_composite,
}
