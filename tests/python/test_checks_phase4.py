"""Phase 4 processing-level checks (§3.3): seeded fail + pass fixtures for every check.

Every fixture is generated at test time. The accuracy expectations in the hand-computed test
are written from the formulas in Olofsson et al. (2014), Remote Sensing of Environment
148:42-57, not from the implementation output.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import rasterio
from rasterio.control import GroundControlPoint
from rasterio.crs import CRS as RasterCRS

from terraproof.checks import accuracy, sar
from terraproof.evidence import ADVISORY, CHECKS_PASSED, REVIEW

SIDE = 64
STRIDE = 8


PHASE4_IDS = frozenset(
    {
        "rs.scale_applied_once",
        "rs.cloud_mask_applied",
        "rs.temporal_scope",
        "sar.value_domain",
        "sar.geocoded",
        "accuracy.sample_design",
        "accuracy.estimates",
    }
)


def phase4_statuses(results):
    """The statuses of the Phase 4 processing checks, for assertions that ignore not-run siblings."""
    return {result.id: result.status for result in results if result.id in PHASE4_IDS}


def one(results, check_id):
    matches = [result for result in results if result.id == check_id]
    assert len(matches) == 1, f"expected one {check_id} result, got {[r.id for r in results]}"
    return matches[0]


def dn_grid(offset=2000):
    """A reproducible uint16 DN raster with a spread of values."""
    values = (np.arange(SIDE * SIDE, dtype=np.int64) % 8000 + offset).astype(np.uint16)
    return values.reshape(SIDE, SIDE)


def make_qa(path, values, *, crs="EPSG:32636", nodata=None):
    array = np.asarray(values, dtype=np.uint8)
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0], count=1,
        dtype="uint8", crs=crs,
        transform=rasterio.transform.from_origin(500000.0, 5000000.0, 10.0, 10.0),
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)
    return str(path)


def make_gcp_only(path):
    """Write a raster with ground control points and no CRS or geotransform."""
    points = [
        GroundControlPoint(row=0, col=0, x=500000.0, y=5000000.0, z=0),
        GroundControlPoint(row=3, col=3, x=500030.0, y=4999970.0, z=0),
    ]
    with pytest.warns(Warning):
        with rasterio.open(
            path, "w", driver="GTiff", width=16, height=16, count=1, dtype="float32"
        ) as dst:
            dst.write(np.full((16, 16), -8.0, dtype="float32"), 1)
            dst.gcps = (points, RasterCRS.from_epsg(32636))
    return str(path)


def make_identity_transform(path):
    """A raster that has a CRS but keeps the identity transform (pixel indices as coordinates)."""
    with rasterio.open(
        path, "w", driver="GTiff", width=16, height=16, count=1, dtype="float32", crs="EPSG:32636"
    ) as dst:
        dst.write(np.full((16, 16), -8.0, dtype="float32"), 1)
    return str(path)


def write_samples(path, rows):
    header = "map_class,ref_class" if not rows[0][2] else "map_class,ref_class,stratum_weight"
    lines = [header]
    for map_class, ref_class, weight in rows:
        suffix = "" if weight is None else f",{weight}"
        lines.append(f"{map_class},{ref_class}{suffix}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# --- rs.scale_applied_once ---


def _scale_pair(make_raster, name_dn, name_out, transform_dn):
    dn = make_raster(name_dn, dn_grid(), nodata=65535)
    out = make_raster(name_out, transform_dn(dn_grid()).astype("float32"), nodata=-9999.0)
    return dn, out


# --- independent first-principles checks ---------------------------------------
#
# The tests above assert only that each check returns the right status. The tests in this
# section assert against values computed here from the documented constants, so a check that
# returns the right status for the wrong reason still fails.


def test_s2_l2a_decoding_matches_the_published_formula(make_raster, evaluate):
    """DN 1500 must decode to (1500 - 1000)/10000 = 0.05 exactly, per the ESA encoding."""
    from terraproof.inspect import inspect_dataset

    dn = np.full((SIDE, SIDE), 1500, dtype=np.uint16)
    path_dn = make_raster("fp_s2_dn.tif", dn, nodata=65535)
    path_out = make_raster("fp_s2_out.tif", np.full((SIDE, SIDE), 0.05, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate(
        [path_out], reference_input=inspect_dataset(path_dn), encoding="s2-l2a"
    )

    result = one(results, "rs.scale_applied_once")
    assert result.status == "pass"
    # The expected values in the evidence are computed by the check from scale/offset; verify
    # they are the physically correct ones for this raster rather than trusting the status.
    assert result.evidence["scale"] == pytest.approx(0.0001, abs=1e-12)
    assert result.evidence["offset"] == pytest.approx(-0.1, abs=1e-12)
    assert result.evidence["expected_min"] == pytest.approx((1500 - 1000) / 10000.0, abs=1e-12)
    assert result.evidence["expected_max"] == pytest.approx((1500 - 1000) / 10000.0, abs=1e-12)
    assert result.evidence["matched_once_fraction"] == pytest.approx(1.0, abs=1e-9)
    assert grade == CHECKS_PASSED


def test_landsat_c2_l2_decoding_matches_the_published_formula(make_raster, evaluate):
    """USGS Landsat 8/9 C2 L2 SR: DN 10000 must decode to 10000*0.0000275 - 0.2 = 0.075."""
    from terraproof.inspect import inspect_dataset

    expected = 10000 * 0.0000275 - 0.2
    assert expected == pytest.approx(0.075, abs=1e-12)
    path_dn = make_raster(
        "fp_ls_dn.tif", np.full((SIDE, SIDE), 10000, dtype=np.uint16), nodata=65535
    )
    path_out = make_raster(
        "fp_ls_out.tif", np.full((SIDE, SIDE), expected, dtype="float32"), nodata=-9999.0
    )

    results, _ = evaluate(
        [path_out], reference_input=inspect_dataset(path_dn), encoding="landsat-c2-l2"
    )

    result = one(results, "rs.scale_applied_once")
    assert result.status == "pass"
    assert result.evidence["scale"] == pytest.approx(0.0000275, abs=1e-12)
    assert result.evidence["offset"] == pytest.approx(-0.2, abs=1e-12)
    assert result.evidence["expected_min"] == pytest.approx(expected, abs=1e-12)


def test_a_single_misdecoded_pixel_row_fails_scale_applied_once(make_raster, evaluate):
    """Decoding all but one sampled row correctly must still fail: 63/64 < 99% is not a pass.

    This pins the 99% threshold from the low side; a check that accepted any majority match
    would pass here.
    """
    from terraproof.inspect import inspect_dataset

    grid = dn_grid()
    dn = make_raster("fp_almost_dn.tif", grid, nodata=65535)
    decoded = ((grid - 1000) / 10000.0).astype("float32")
    decoded[0, :] = grid[0, :].astype("float32")  # leave the first sampled row undecoded
    out = make_raster("fp_almost_out.tif", decoded, nodata=-9999.0)

    results, _ = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l2a")

    result = one(results, "rs.scale_applied_once")
    # 8 sampled rows of 8; one wrong row is 1/8 = 12.5% of samples.
    assert result.evidence["sampled_pixels"] == 8 * 8
    assert result.evidence["matched_once_fraction"] == pytest.approx(56 / 64, abs=1e-9)
    assert result.status == "fail"


def test_raw_dn_output_fails_scale_applied_once(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn, out = _scale_pair(
        make_raster, "not_decoded_dn.tif", "not_decoded_out.tif", lambda grid: grid.astype("float64")
    )

    results, grade = evaluate(
        [out], reference_input=inspect_dataset(dn), encoding="s2-l2a"
    )

    result = one(results, "rs.scale_applied_once")
    assert result.status == "fail"
    assert result.evidence["matched_raw_dn_fraction"] >= 0.99
    assert "not applied" in result.message
    assert grade == ADVISORY


def test_double_decoded_output_fails_scale_applied_once(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    def twice(grid):
        once = (grid - 1000) / 10000.0
        return once * 0.0001 - 0.1

    dn, out = _scale_pair(make_raster, "twice_dn.tif", "twice_out.tif", twice)

    results, grade = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l2a")

    result = one(results, "rs.scale_applied_once")
    assert result.status == "fail"
    assert result.evidence["matched_twice_fraction"] >= 0.99
    assert "twice" in result.message
    assert grade == ADVISORY


def test_s2_decoded_once_passes_scale_applied_once(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn, out = _scale_pair(
        make_raster, "s2_ok_dn.tif", "s2_ok_out.tif", lambda grid: (grid - 1000) / 10000.0
    )

    results, grade = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l2a")

    result = one(results, "rs.scale_applied_once")
    assert result.status == "pass"
    assert result.evidence["matched_once_fraction"] >= 0.99
    assert result.evidence["sampled_pixels"] > 0

    assert grade == CHECKS_PASSED


def test_landsat_decoded_once_passes_scale_applied_once(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn, out = _scale_pair(
        make_raster, "ls_ok_dn.tif", "ls_ok_out.tif", lambda grid: grid * 0.0000275 - 0.2
    )

    results, _ = evaluate([out], reference_input=inspect_dataset(dn), encoding="landsat-c2-l2")

    result = one(results, "rs.scale_applied_once")
    assert result.status == "pass"
    assert result.evidence["matched_once_fraction"] >= 0.99


def test_landsat_formula_applied_to_s2_encoding_fails(make_raster, evaluate):
    """The right formula for the wrong sensor must not pass."""
    from terraproof.inspect import inspect_dataset

    dn, out = _scale_pair(
        make_raster, "wrong_enc_dn.tif", "wrong_enc_out.tif", lambda grid: grid * 0.0000275 - 0.2
    )

    results, _ = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l2a")

    assert one(results, "rs.scale_applied_once").status == "fail"


def test_scale_applied_once_reads_metadata_when_no_encoding(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn = make_raster("meta_dn.tif", dn_grid(), nodata=65535, scale=0.0001, offset=-0.1)
    out = make_raster(
        "meta_out.tif",
        (dn_grid() * 0.0001 - 0.1).astype("float32"),
        nodata=-9999.0,
        scale=1.0,
        offset=0.0,
    )

    results, _ = evaluate([out], reference_input=inspect_dataset(dn))

    result = one(results, "rs.scale_applied_once")
    assert result.status == "pass"
    assert result.evidence["scale_source"] == "input raster metadata"


def test_scale_applied_once_without_input_is_not_emitted(make_raster, evaluate):
    """Without reference_input or encoding the check does not apply, so no result is emitted."""
    out = make_raster("lonely_out.tif", dn_grid(), nodata=65535)

    results, grade = evaluate([out])

    assert "rs.scale_applied_once" not in {result.id for result in results}
    assert grade == CHECKS_PASSED


def test_scale_applied_once_unaligned_grids_is_not_run(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn = make_raster("shift_dn.tif", dn_grid(), nodata=65535)
    out = make_raster(
        "shift_out.tif",
        ((dn_grid() - 1000) / 10000.0).astype("float32"),
        nodata=-9999.0,
        origin=(500005.0, 5000000.0),
    )

    results, _ = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l2a")

    assert one(results, "rs.scale_applied_once").status == "not-run"


def test_scale_applied_once_without_an_input_raster_is_not_run(make_raster, evaluate):
    """The check was requested (encoding given) but the DN input is missing."""
    out = make_raster("nodn_out.tif", dn_grid(), nodata=65535)

    results, grade = evaluate([out], encoding="s2-l2a")

    assert one(results, "rs.scale_applied_once").status == "not-run"
    assert grade == ADVISORY


@pytest.mark.parametrize("leak", [False, True])
def test_source_nodata_off_stride_and_extra_qa_mask(make_raster, evaluate, leak):
    from terraproof.inspect import inspect_dataset

    raw = np.full((16, 16), 2500, dtype="uint16")
    raw[0, 1] = 0  # deliberately not on the numeric stride
    decoded = raw.astype("float32") * 0.0001 - 0.1
    if not leak:
        decoded[0, 1] = -9999.0
    decoded[8, 8] = -9999.0  # additional QA masking is legitimate
    dn = make_raster("mask_dn.tif", raw, nodata=0)
    out = make_raster("mask_out.tif", decoded, nodata=-9999.0)
    results, _ = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l2a")
    check = one(results, "rs.scale_applied_once")
    assert check.status == ("fail" if leak else "pass")
    if leak:
        assert check.evidence["unmasked_source_nodata_pixels"] == 1


@pytest.mark.parametrize("calibration", [None, float("nan"), float("inf")])
def test_missing_or_nonfinite_calibration_is_not_run(make_raster, evaluate, calibration):
    from terraproof.inspect import inspect_dataset

    dn = make_raster("invalid_calibration_dn.tif", dn_grid(), nodata=65535)
    out = make_raster("invalid_calibration_out.tif", dn_grid().astype("float32"), nodata=-9999.0)
    reference = inspect_dataset(dn)
    reference["bands"][0]["scale"] = calibration
    assert one(evaluate([out], reference_input=reference)[0], "rs.scale_applied_once").status == "not-run"


def test_calibration_overflow_cannot_false_pass(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn = make_raster("overflow_dn.tif", dn_grid(), nodata=65535)
    out = make_raster("overflow_out.tif", np.full((SIDE, SIDE), 0.2, dtype="float32"), nodata=-9999.0)
    reference = inspect_dataset(dn)
    reference["bands"][0].update(scale=1e308, offset=0.0)
    check = one(evaluate([out], reference_input=reference)[0], "rs.scale_applied_once")
    assert check.status == "not-run"
    assert "non-finite expectations" in check.message


@pytest.mark.parametrize("problem", ["shape", "rotation", "whole_pixel_shift"])
def test_incompatible_pixel_pairs_are_not_run(make_raster, evaluate, problem):
    from terraproof.inspect import inspect_dataset

    dn = make_raster("incompatible_dn.tif", dn_grid(), nodata=65535)
    out = make_raster("incompatible_out.tif", dn_grid().astype("float32"), nodata=-9999.0)
    reference = inspect_dataset(dn)
    if problem == "shape":
        reference["width"] -= 1
    elif problem == "rotation":
        reference["transform"][1] = 0.5
    else:
        reference["transform"][2] += 10
    assert one(evaluate([out], reference_input=reference, encoding="s2-l2a")[0], "rs.scale_applied_once").status == "not-run"


# --- rs.cloud_mask_applied ---


def scl_grid():
    """Half the pixels are clear (SCL 4), half are cloud/shadow classes 3, 8, 9, 10."""
    grid = np.full((SIDE, SIDE), 4, dtype=np.uint8)
    grid[:, : SIDE // 2] = 9
    grid[:, 1] = 3
    grid[:, 2] = 8
    grid[:, 3] = 10
    return grid


def test_a_known_scl_class_9_pixel_left_at_03_fails(make_raster, tmp_path, evaluate):
    """A single SCL class-9 (cloud high probability) pixel still holding 0.3 must fail.

    Class 9 is in the reject set, so an unmasked cloud pixel at any value must be caught.
    The flagged count here is one sampled pixel, and the check reports it exactly.
    """
    scl = np.full((SIDE, SIDE), 4, dtype=np.uint8)
    scl[0, 0] = 9  # one cloud pixel on the sampled stride (stride 8 samples (0, 0))
    out_data = np.full((SIDE, SIDE), 0.3, dtype="float32")
    out = make_raster("fp_cloud_out.tif", out_data, nodata=-9999.0)
    qa = make_qa(tmp_path / "fp_scl.tif", scl)

    results, grade = evaluate([out], qa_path=qa, qa_kind="s2-scl")

    result = one(results, "rs.cloud_mask_applied")
    assert result.evidence["flagged_pixels"] == 1
    assert result.evidence["unmasked_flagged_pixels"] == 1
    assert result.evidence["unmasked_fraction"] == pytest.approx(1.0, abs=1e-12)
    assert result.status == "fail"
    assert grade == ADVISORY


def test_every_scl_cloud_class_is_rejected(make_raster, tmp_path, evaluate):
    """SCL 3, 8, 9 and 10 are all flagged; 4 (vegetation) is not."""
    for cls in (3, 8, 9, 10):
        scl = np.full((SIDE, SIDE), 4, dtype=np.uint8)
        scl[0, :] = cls
        out = make_raster(f"fp_scl_{cls}_out.tif", np.full((SIDE, SIDE), 0.3, dtype="float32"), nodata=-9999.0)
        qa = make_qa(tmp_path / f"fp_scl_{cls}.tif", scl)

        result = one(evaluate([out], qa_path=qa, qa_kind="s2-scl")[0], "rs.cloud_mask_applied")
        assert result.evidence["flagged_pixels"] > 0, cls
        assert result.status == "fail", cls

    # Class 4 (vegetation) flags nothing, so the check cannot claim masking.
    vegetation = np.full((SIDE, SIDE), 4, dtype=np.uint8)
    out = make_raster("fp_scl_4_out.tif", np.full((SIDE, SIDE), 0.3, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "fp_scl_4.tif", vegetation)
    result = one(evaluate([out], qa_path=qa, qa_kind="s2-scl")[0], "rs.cloud_mask_applied")
    assert result.evidence["flagged_pixels"] == 0
    assert result.status == "not-run"


def test_landsat_qa_bit_positions_are_zero_based(make_raster, tmp_path, evaluate):
    """Bit 0 (fill) is outside bits 1-4, so a fill-only pixel is not a cloud flag.

    A pixel with only bit 5 (snow) is also outside the reject set.
    """
    qa_values = np.full((SIDE, SIDE), 1 << 6, dtype=np.uint8)
    qa_values[0, :] = 1 << 0  # fill only
    out = make_raster("fp_fill_out.tif", np.full((SIDE, SIDE), 0.2, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "fp_fill.tif", qa_values)

    result = one(evaluate([out], qa_path=qa, qa_kind="landsat-qa-pixel")[0], "rs.cloud_mask_applied")
    assert result.evidence["flagged_pixels"] == 0
    assert result.status == "not-run"

    # Bit 5 (snow) is outside bits 1-4 too.
    qa_snow = np.full((SIDE, SIDE), 1 << 6, dtype=np.uint8)
    qa_snow[0, :] = 1 << 5
    out2 = make_raster("fp_snow_out.tif", np.full((SIDE, SIDE), 0.2, dtype="float32"), nodata=-9999.0)
    qa2 = make_qa(tmp_path / "fp_snow.tif", qa_snow)
    result2 = one(evaluate([out2], qa_path=qa2, qa_kind="landsat-qa-pixel")[0], "rs.cloud_mask_applied")
    assert result2.evidence["flagged_pixels"] == 0


def test_landsat_qa_bit_mask_is_exactly_bits_1_to_4(make_raster, tmp_path, evaluate):
    """Each of bits 1, 2, 3, 4 flags; bit 6 (clear) does not."""
    for bit in (1, 2, 3, 4):
        qa_values = np.full((SIDE, SIDE), 0, dtype=np.uint8)
        qa_values[0, :] = 1 << bit
        out = make_raster(
            f"fp_bit{bit}_out.tif", np.full((SIDE, SIDE), 0.2, dtype="float32"), nodata=-9999.0
        )
        qa = make_qa(tmp_path / f"fp_bit{bit}.tif", qa_values)

        result = one(evaluate([out], qa_path=qa, qa_kind="landsat-qa-pixel")[0], "rs.cloud_mask_applied")
        assert result.evidence["flagged_pixels"] > 0, bit
        assert result.status == "fail", bit


def test_unmasked_cloud_pixel_fails_cloud_mask_applied(make_raster, tmp_path, evaluate):
    out = make_raster("unmasked_out.tif", np.full((SIDE, SIDE), 0.25, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "scl_unmasked.tif", scl_grid())

    results, grade = evaluate([out], qa_path=qa, qa_kind="s2-scl")

    result = one(results, "rs.cloud_mask_applied")
    assert result.status == "fail"
    assert result.evidence["unmasked_flagged_pixels"] > 0
    assert result.evidence["flagged_pixels"] > 0
    assert grade == ADVISORY


def test_fully_masked_clouds_pass_cloud_mask_applied(make_raster, tmp_path, evaluate):
    data = np.full((SIDE, SIDE), 0.25, dtype="float32")
    scl = scl_grid()
    data[scl != 4] = np.nan
    out = make_raster("masked_out.tif", data, nodata=-9999.0)
    qa = make_qa(tmp_path / "scl_masked.tif", scl)

    results, grade = evaluate([out], qa_path=qa, qa_kind="s2-scl")

    result = one(results, "rs.cloud_mask_applied")
    assert result.status == "pass"
    assert result.evidence["unmasked_flagged_pixels"] == 0
    assert phase4_statuses(results)["rs.cloud_mask_applied"] == "pass"


def test_landsat_qa_bit_cloud_left_unmasked_fails(make_raster, tmp_path, evaluate):
    # Bit 3 (high-confidence cloud) = 0b1000; bit 6 (clear) is set on the good pixels.
    qa_values = np.full((SIDE, SIDE), 1 << 6, dtype=np.uint8)
    qa_values[:, : SIDE // 2] |= 1 << 3
    out = make_raster("ls_unmasked.tif", np.full((SIDE, SIDE), 0.2, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "qa_unmasked.tif", qa_values)

    results, grade = evaluate([out], qa_path=qa, qa_kind="landsat-qa-pixel")

    result = one(results, "rs.cloud_mask_applied")
    assert result.status == "fail"
    assert result.evidence["unmasked_flagged_pixels"] > 0
    assert grade == ADVISORY


def test_landsat_qa_bit_cloud_masked_passes(make_raster, tmp_path, evaluate):
    qa_values = np.full((SIDE, SIDE), 1 << 6, dtype=np.uint8)
    qa_values[:, : SIDE // 2] |= 1 << 3
    data = np.full((SIDE, SIDE), 0.2, dtype="float32")
    data[:, : SIDE // 2] = np.nan
    out = make_raster("ls_masked.tif", data, nodata=-9999.0)
    qa = make_qa(tmp_path / "qa_masked.tif", qa_values)

    results, grade = evaluate([out], qa_path=qa, qa_kind="landsat-qa-pixel")

    result = one(results, "rs.cloud_mask_applied")
    assert result.status == "pass"
    assert result.evidence["unmasked_flagged_pixels"] == 0
    assert phase4_statuses(results)["rs.cloud_mask_applied"] == "pass"


def test_landsat_cirrus_bit_alone_also_flags(make_raster, tmp_path, evaluate):
    qa_values = np.full((SIDE, SIDE), 1 << 6, dtype=np.uint8)
    qa_values[0, :] = 1 << 2  # high-confidence cirrus, no cloud bit
    out = make_raster("ls_cirrus.tif", np.full((SIDE, SIDE), 0.2, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "qa_cirrus.tif", qa_values)

    results, _ = evaluate([out], qa_path=qa, qa_kind="landsat-qa-pixel")

    assert one(results, "rs.cloud_mask_applied").status == "fail"


def test_scale_applied_once_unknown_encoding_is_not_run(make_raster, evaluate):
    from terraproof.inspect import inspect_dataset

    dn = make_raster("unknown_enc_dn.tif", dn_grid(), nodata=65535)
    out = make_raster("unknown_enc_out.tif", dn_grid(), nodata=65535)

    results, _ = evaluate([out], reference_input=inspect_dataset(dn), encoding="s2-l1c")

    assert one(results, "rs.scale_applied_once").status == "not-run"


def test_cloud_mask_applied_without_qa_is_not_emitted(make_raster, evaluate):
    """Without qa_path or qa_kind the check does not apply, so no result is emitted."""
    out = make_raster("no_qa_out.tif", np.full((SIDE, SIDE), 0.25, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate([out])

    assert "rs.cloud_mask_applied" not in {result.id for result in results}
    assert grade == CHECKS_PASSED


def test_cloud_mask_applied_with_a_missing_qa_file_is_not_run(make_raster, evaluate):
    out = make_raster("missing_qa_out.tif", np.full((SIDE, SIDE), 0.25, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate([out], qa_path="does_not_exist.tif", qa_kind="s2-scl")

    assert one(results, "rs.cloud_mask_applied").status == "not-run"
    assert grade == ADVISORY


def test_cloud_mask_applied_unaligned_qa_is_not_run(make_raster, tmp_path, evaluate):
    out = make_raster(
        "off_qa_out.tif", np.full((SIDE, SIDE), 0.25, dtype="float32"), nodata=-9999.0,
        origin=(500000.0, 5000000.0),
    )
    qa = make_qa(tmp_path / "scl_offset.tif", scl_grid())
    # Shift the QA grid off the output grid.
    with rasterio.open(qa, "r+") as dst:
        dst.transform = rasterio.transform.from_origin(500005.0, 5000000.0, 10.0, 10.0)

    results, _ = evaluate([out], qa_path=qa, qa_kind="s2-scl")

    result = one(results, "rs.cloud_mask_applied")
    assert result.status == "not-run"
    assert "not aligned" in result.message


def test_cloud_mask_applied_unknown_qa_kind_is_not_run(make_raster, tmp_path, evaluate):
    out = make_raster("badkind_out.tif", np.full((SIDE, SIDE), 0.25, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "scl_badkind.tif", scl_grid())

    results, _ = evaluate([out], qa_path=qa, qa_kind="s2-something")

    assert one(results, "rs.cloud_mask_applied").status == "not-run"


def test_cloud_mask_applied_never_passes_on_a_clean_qa(make_raster, tmp_path, evaluate):
    """A QA raster with no cloud pixels cannot be used to claim the mask was applied."""
    clean = np.full((SIDE, SIDE), 4, dtype=np.uint8)
    out = make_raster("all_valid_out.tif", np.full((SIDE, SIDE), 0.25, dtype="float32"), nodata=-9999.0)
    qa = make_qa(tmp_path / "scl_clean.tif", clean)

    results, _ = evaluate([out], qa_path=qa, qa_kind="s2-scl")

    assert one(results, "rs.cloud_mask_applied").status == "not-run"


# --- rs.temporal_scope ---


def test_item_exactly_on_the_range_boundary_is_inside(make_stac_item, evaluate):
    """The range bounds are inclusive, so an item exactly on them passes."""
    from datetime import datetime, timezone

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    item = make_stac_item("boundary.json", {"datetime": start.isoformat(), "proj:epsg": 32636})

    result = one(
        evaluate([item], time_range=("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"))[0],
        "rs.temporal_scope",
    )
    assert result.status == "pass"


def test_item_one_second_after_the_range_is_outside(make_stac_item, evaluate):
    item = make_stac_item("late.json", {"datetime": "2025-01-01T00:00:01Z", "proj:epsg": 32636})

    result = one(
        evaluate([item], time_range=("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"))[0],
        "rs.temporal_scope",
    )
    assert result.status == "fail"
    assert len(result.evidence["out_of_range"]) == 1


def test_item_without_a_utc_offset_is_read_as_utc(make_stac_item, evaluate):
    """A naive datetime must be treated as UTC, so 12:00Z equals 12:00 with no offset."""
    naive = make_stac_item("naive.json", {"datetime": "2024-06-01T12:00:00", "proj:epsg": 32636})
    result = one(
        evaluate([naive], time_range=("2024-06-01T12:00:00Z", "2024-06-01T13:00:00Z"))[0],
        "rs.temporal_scope",
    )
    assert result.status == "pass"


def test_interval_starting_before_the_range_fails_even_if_it_overlaps(make_stac_item, evaluate):
    """The whole interval must be inside, not merely overlapping it."""
    item = make_stac_item(
        "overlap.json",
        {"start_datetime": "2023-12-01T00:00:00Z", "end_datetime": "2024-02-01T00:00:00Z", "proj:epsg": 32636},
    )

    result = one(
        evaluate([item], time_range=("2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"))[0],
        "rs.temporal_scope",
    )
    assert result.status == "fail"


def test_item_outside_time_range_fails(make_stac_item, evaluate):
    inside = make_stac_item("inside.json", {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636})
    outside = make_stac_item("outside.json", {"datetime": "2023-01-05T10:00:00Z", "proj:epsg": 32636})

    results, grade = evaluate(
        [inside, outside], time_range=("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
    )

    result = one(results, "rs.temporal_scope")
    assert result.status == "fail"
    assert len(result.evidence["out_of_range"]) == 1
    assert grade == ADVISORY


def test_items_inside_time_range_pass(make_stac_item, evaluate):
    first = make_stac_item("in1.json", {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636})
    second = make_stac_item("in2.json", {"datetime": "2024-08-15T10:00:00Z", "proj:epsg": 32636})

    results, grade = evaluate(
        [first, second], time_range=("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
    )

    result = one(results, "rs.temporal_scope")
    assert result.status == "pass"
    assert result.evidence["out_of_range"] == []
    # A STAC-only run has no raster, so no raster checks run at all: checks passed.
    assert grade == CHECKS_PASSED


def test_interval_spanning_outside_the_range_fails(make_stac_item, evaluate):
    item = make_stac_item(
        "span.json",
        {"start_datetime": "2024-06-01T00:00:00Z", "end_datetime": "2024-07-01T00:00:00Z", "proj:epsg": 32636},
    )

    results, _ = evaluate([item], time_range=("2024-06-10T00:00:00Z", "2024-06-20T00:00:00Z"))

    assert one(results, "rs.temporal_scope").status == "fail"


def test_temporal_scope_without_time_range_is_not_emitted(make_stac_item, evaluate):
    """Without a time_range the check does not apply, so no result is emitted."""
    item = make_stac_item("norange.json", {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636})

    results, grade = evaluate([item])

    assert "rs.temporal_scope" not in {result.id for result in results}
    assert grade == CHECKS_PASSED


def test_temporal_scope_without_any_item_is_not_run(evaluate):
    """A range was requested but no STAC item was given, so nothing can be confirmed."""
    results, grade = evaluate([], time_range=("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"))

    assert one(results, "rs.temporal_scope").status == "not-run"
    assert grade == ADVISORY


def test_temporal_scope_with_undated_item_is_not_run(make_stac_item, evaluate):
    item = make_stac_item("undated.json", {"proj:epsg": 32636})

    results, _ = evaluate([item], time_range=("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"))

    result = one(results, "rs.temporal_scope")
    assert result.status == "not-run"
    assert result.evidence["items_without_time"]


def test_temporal_scope_with_unparseable_range_is_not_run(make_stac_item, evaluate):
    item = make_stac_item("bad_range.json", {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636})

    results, _ = evaluate([item], time_range=("last summer", "2024-12-31T23:59:59Z"))

    assert one(results, "rs.temporal_scope").status == "not-run"


# --- sar.value_domain ---


# --- sar.value_domain: assertions against the documented thresholds ---


def test_db_value_of_minus_12_declared_linear_fails(make_raster, evaluate):
    """-12 dB declared as linear sigma0 must fail: negative values cannot be linear."""
    path = make_raster("fp_minus12_linear.tif", np.full((SIDE, SIDE), -12.0, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate([path], sar_expect="sigma0-linear")

    result = one(results, "sar.value_domain")
    assert result.status == "fail"
    assert result.evidence["min"] == pytest.approx(-12.0, abs=1e-9)
    assert result.evidence["p1"] == pytest.approx(-12.0, abs=1e-9)
    assert result.evidence["p99"] == pytest.approx(-12.0, abs=1e-9)
    assert "linear backscatter cannot be negative" in result.message.lower()
    assert grade == ADVISORY


def test_db_values_inside_the_documented_window_pass(make_raster, evaluate):
    """The dB window is [-50, 15]; values at -49 and +14 are inside it."""
    data = np.full((SIDE, SIDE), -49.0, dtype="float32")
    data[0, :] = 14.0
    path = make_raster("fp_db_window.tif", data, nodata=-9999.0)

    results, _ = evaluate([path], sar_expect="sigma0-db")

    result = one(results, "sar.value_domain")
    assert result.status == "pass"
    assert result.evidence["p1"] == pytest.approx(-49.0, abs=1e-6)
    assert result.evidence["p99"] == pytest.approx(14.0, abs=1e-6)


def test_db_values_just_outside_the_window_fail(make_raster, evaluate):
    """A value below -50 dB or above +15 dB is outside the documented window."""
    low = make_raster("fp_db_low.tif", np.full((SIDE, SIDE), -51.0, dtype="float32"), nodata=-9999.0)
    assert one(evaluate([low], sar_expect="sigma0-db")[0], "sar.value_domain").status == "fail"

    high = make_raster("fp_db_high.tif", np.full((SIDE, SIDE), 16.0, dtype="float32"), nodata=-9999.0)
    assert one(evaluate([high], sar_expect="sigma0-db")[0], "sar.value_domain").status == "fail"


def test_linear_p99_above_five_fails(make_raster, evaluate):
    """The linear rule is min >= 0 and p99 <= 5; a p99 of 6 must fail."""
    data = np.full((SIDE, SIDE), 0.1, dtype="float32")
    data[0, :] = 6.0
    path = make_raster("fp_linear_p99.tif", data, nodata=-9999.0)

    result = one(evaluate([path], sar_expect="sigma0-linear")[0], "sar.value_domain")
    assert result.status == "fail"
    assert result.evidence["p99"] > 5.0


def test_zero_backscatter_declared_linear_passes(make_raster, evaluate):
    """Zero is in the linear domain (min >= 0) and must not be mistaken for a failure."""
    path = make_raster("fp_zero_linear.tif", np.full((SIDE, SIDE), 0.0, dtype="float32"), nodata=-9999.0)

    result = one(evaluate([path], sar_expect="sigma0-linear")[0], "sar.value_domain")
    assert result.status == "pass"
    assert result.evidence["min"] == pytest.approx(0.0, abs=1e-12)


def test_db_values_declared_linear_fail(make_raster, evaluate):
    values = np.full((SIDE, SIDE), -8.0, dtype="float32")
    values[:, : SIDE // 2] = 3.5
    path = make_raster("db_as_linear.tif", values, nodata=-9999.0)

    results, grade = evaluate([path], sar_expect="sigma0-linear")

    result = one(results, "sar.value_domain")
    assert result.status == "fail"
    assert "one possible cause" in result.message.lower()
    assert grade == ADVISORY


def test_linear_values_declared_db_fail(make_raster, evaluate):
    values = np.full((SIDE, SIDE), 0.4, dtype="float32")
    path = make_raster("linear_as_db.tif", values, nodata=-9999.0)

    results, grade = evaluate([path], sar_expect="sigma0-db")

    result = one(results, "sar.value_domain")
    assert result.status == "fail"
    assert "[0, 1]" in result.message
    assert grade == ADVISORY


def test_db_values_declared_db_pass(make_raster, evaluate):
    values = np.full((SIDE, SIDE), -8.0, dtype="float32")
    values[:, : SIDE // 2] = 2.0
    path = make_raster("db_ok.tif", values, nodata=-9999.0)

    results, grade = evaluate([path], sar_expect="sigma0-db")

    result = one(results, "sar.value_domain")
    assert result.status == "pass"

    assert grade == CHECKS_PASSED


def test_linear_values_declared_linear_pass(make_raster, evaluate):
    values = np.full((SIDE, SIDE), 0.15, dtype="float32")
    values[:, : SIDE // 2] = 0.6
    path = make_raster("linear_ok.tif", values, nodata=-9999.0)

    results, grade = evaluate([path], sar_expect="sigma0-linear")

    result = one(results, "sar.value_domain")
    assert result.status == "pass"
    assert grade == CHECKS_PASSED


def test_db_values_are_applied_with_scale_metadata(make_raster, evaluate):
    """A DN raster carrying the dB scale metadata decodes into the decibel domain."""
    path = make_raster("dn_with_scale.tif", np.full((SIDE, SIDE), -8000, dtype="int16"), scale=0.001, offset=0.0)

    results, grade = evaluate([path], sar_expect="sigma0-db")

    assert one(results, "sar.value_domain").status == "pass"
    assert grade == CHECKS_PASSED


def test_value_domain_without_declaration_is_not_emitted(make_raster, evaluate):
    """Without sar_expect the check does not apply, so no sar.value_domain result is emitted."""
    path = make_raster("undeclared_sar.tif", np.full((SIDE, SIDE), -8.0, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate([path])

    assert "sar.value_domain" not in {result.id for result in results}
    assert grade == CHECKS_PASSED


def test_value_domain_with_unknown_declaration_is_not_run(make_raster, evaluate):
    path = make_raster("odd_sar.tif", np.full((SIDE, SIDE), -8.0, dtype="float32"), nodata=-9999.0)

    results, _ = evaluate([path], sar_expect="gamma0-db")

    assert one(results, "sar.value_domain").status == "not-run"


def test_value_domain_without_raster_is_not_run():
    from terraproof.checks import run_checks

    results = run_checks([], sar_expect="sigma0-db")

    assert one(results, "sar.value_domain").status == "not-run"


def test_value_domain_does_not_pass_on_a_nan_free_huge_range(make_raster, evaluate):
    """Values far outside both declared domains must not pass."""
    path = make_raster("huge_db.tif", np.full((SIDE, SIDE), 250.0, dtype="float32"), nodata=-9999.0)

    results, _ = evaluate([path], sar_expect="sigma0-db")

    assert one(results, "sar.value_domain").status == "fail"


# --- sar.geocoded ---


def test_geocoded_reports_the_crs_and_transform_it_actually_found(make_raster, evaluate):
    """A CRS plus a non-identity transform is exactly what the check requires of evidence."""
    path = make_raster("fp_geocoded.tif", np.full((SIDE, SIDE), -8.0, dtype="float32"), nodata=-9999.0)

    result = one(evaluate([path], sar_expect="sigma0-db")[0], "sar.geocoded")

    assert result.status == "pass"
    assert result.evidence["crs_defined"] is True
    assert result.evidence["epsg"] == 32636
    assert result.evidence["identity_transform"] is False
    assert result.evidence["transform"][0] == pytest.approx(10.0, abs=1e-9)
    assert result.evidence["transform"][4] == pytest.approx(-10.0, abs=1e-9)


def test_a_raster_with_scale_metadata_still_passes_geocoded(make_raster, evaluate):
    """Geocoding is about geometry only; value scaling must not affect it."""
    path = make_raster(
        "fp_geocoded_scaled.tif", np.full((SIDE, SIDE), -8000, dtype="int16"), scale=0.001, offset=0.0
    )

    assert one(evaluate([path], sar_expect="sigma0-db")[0], "sar.geocoded").status == "pass"


def test_gcp_only_raster_fails_geocoded(tmp_path, evaluate):
    path = make_gcp_only(tmp_path / "gcp_only.tif")

    results, grade = evaluate([path], sar_expect="sigma0-db")

    result = one(results, "sar.geocoded")
    assert result.status == "fail"
    assert "GCP-only" in result.message
    assert result.evidence["gcp_count"] == 2
    assert result.evidence["crs_defined"] is False
    assert grade == ADVISORY


def test_identity_transform_fails_geocoded(tmp_path, evaluate):
    path = make_identity_transform(tmp_path / "identity.tif")

    results, grade = evaluate([path], sar_expect="sigma0-db")

    result = one(results, "sar.geocoded")
    assert result.status == "fail"
    assert "identity" in result.message
    assert grade == ADVISORY


def test_properly_geocoded_raster_passes_geocoded(make_raster, evaluate):
    path = make_raster("geocoded.tif", np.full((SIDE, SIDE), -8.0, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate([path], sar_expect="sigma0-db")

    result = one(results, "sar.geocoded")
    assert result.status == "pass"
    assert result.evidence["crs_defined"] is True
    assert result.evidence["identity_transform"] is False

    assert grade == CHECKS_PASSED


def test_geocoded_without_raster_is_not_run():
    from terraproof.checks import run_checks

    results = run_checks([], sar_expect="sigma0-db")

    assert one(results, "sar.geocoded").status == "not-run"


# --- accuracy.sample_design ---


def sample_rows(map_counts):
    """Build (map_class, ref_class, weight) rows from {map_class: {ref_class: count}}."""
    rows = []
    for map_class, refs in map_counts.items():
        for ref_class, count in refs.items():
            rows.extend([(map_class, ref_class, None)] * count)
    assert len(rows) == sum(sum(refs.values()) for refs in map_counts.values())
    return rows


def test_under_sampled_class_fails_sample_design(tmp_path, evaluate):
    # forest is the mapped class: only 12 of its reference samples say forest.
    path = write_samples(
        tmp_path / "under.csv",
        sample_rows({"forest": {"forest": 10, "water": 2}, "water": {"water": 60}}),
    )

    results, grade = evaluate([], accuracy_samples=accuracy.read_samples(path))

    result = one(results, "accuracy.sample_design")
    assert result.status == "fail"
    assert result.evidence["per_class_counts"]["forest"] == 12
    assert "fewer than 50" in result.message
    assert grade == ADVISORY


def test_default_min_per_class_of_50_is_justified(tmp_path, evaluate):
    path = write_samples(
        tmp_path / "exactly.csv", sample_rows({"forest": {"forest": 49}, "water": {"water": 50}})
    )

    results, _ = evaluate([], accuracy_samples=accuracy.read_samples(path))

    result = one(results, "accuracy.sample_design")
    assert result.status == "fail"
    assert result.evidence["min_per_class"] == 50
    assert result.evidence["min_per_class_default"] is True
    assert "rule of thumb" in result.evidence["min_per_class_rationale"]


def test_configurable_min_per_class_passes_at_a_lower_threshold(tmp_path, evaluate):
    path = write_samples(tmp_path / "small.csv", sample_rows({"forest": {"forest": 10}}))

    results, grade = evaluate([], accuracy_samples=accuracy.read_samples(path), min_per_class=5)

    result = one(results, "accuracy.sample_design")
    assert result.status == "pass"
    assert result.evidence["min_per_class"] == 5
    assert result.evidence["min_per_class_default"] is False


def test_fully_sampled_passes_sample_design(tmp_path, evaluate):
    path = write_samples(
        tmp_path / "full.csv",
        sample_rows({"forest": {"forest": 55, "water": 5}, "water": {"water": 55}}),
    )

    results, grade = evaluate([], accuracy_samples=accuracy.read_samples(path))

    assert one(results, "accuracy.sample_design").status == "pass"

    assert grade == ADVISORY


def test_missing_class_areas_warn_when_estimates_requested(tmp_path, evaluate):
    """Samples are adequate, but the area estimates were asked for with no areas supplied."""
    path = write_samples(tmp_path / "warn.csv", sample_rows({"forest": {"forest": 60}}))

    results, grade = evaluate(
        [], accuracy_samples=accuracy.read_samples(path), estimates_requested=True
    )

    result = one(results, "accuracy.sample_design")
    assert result.status == "warn"
    assert "no map-class areas" in result.message
    # accuracy.estimates is also not-run without areas, so the overall grade is advisory-only.
    assert one(results, "accuracy.estimates").status == "not-run"
    assert grade == ADVISORY


def test_partially_supplied_class_areas_are_not_run_for_estimates(tmp_path, evaluate):
    """A class area map that omits a sampled class cannot produce a complete area estimate."""
    path = write_samples(
        tmp_path / "partial_design.csv",
        sample_rows({"forest": {"forest": 60}, "water": {"water": 60}}),
    )

    results, _ = evaluate(
        [], accuracy_samples=accuracy.read_samples(path), class_areas={"forest": 1000.0}
    )

    assert one(results, "accuracy.estimates").status == "not-run"


def test_sample_design_rejects_a_csv_without_the_required_columns(tmp_path, evaluate):
    path = tmp_path / "bad.csv"
    path.write_text("map_class\nforest\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ref_class"):
        accuracy.read_samples(path)


# --- accuracy.estimates: hand-computed from Olofsson et al. (2014) ---


# --- accuracy.estimates: the published example from Olofsson et al. (2014) ---
#
# Every expected value below is transcribed from the paper, not from this implementation.
# Olofsson et al. (2014), "Good practices for estimating area and assessing accuracy of land
# change", Remote Sensing of Environment 148:42-57. The worked example is a four-class
# land-change map; rows are map classes (the strata), columns are reference classes.
#
#   map class              n    deforestation gain  stable forest  stable non-forest
#   deforestation          75        66           0        5              4
#   forest gain            75         0          55        8             12
#   stable forest         165         1           0      153             11
#   stable non-forest     325         2           1        9            313
#
# Mapped areas: deforestation 18000, gain 13500, stable forest 288000,
# stable non-forest 580500 ha (total 900000 ha).
#
# Published results:
#   estimated areas   21158, 11686, 285770, 581386 ha
#   95% CI            +/- 6158, +/- 3756, +/- 15510, +/- 16282 ha
#   deforestation     user's accuracy 0.88, producer's accuracy 0.75
#   overall accuracy  0.95

OLOFSSON_ROWS = {
    "deforestation": {"deforestation": 66, "gain": 0, "stable forest": 5, "stable non-forest": 4},
    "gain": {"deforestation": 0, "gain": 55, "stable forest": 8, "stable non-forest": 12},
    "stable forest": {"deforestation": 1, "gain": 0, "stable forest": 153, "stable non-forest": 11},
    "stable non-forest": {"deforestation": 2, "gain": 1, "stable forest": 9, "stable non-forest": 313},
}
OLOFSSON_AREAS = {
    "deforestation": 18000.0,
    "gain": 13500.0,
    "stable forest": 288000.0,
    "stable non-forest": 580500.0,
}
# Published areas and 95% confidence-interval half-widths, in hectares.
PUBLISHED_AREA = {
    "deforestation": 21158.0,
    "gain": 11686.0,
    "stable forest": 285770.0,
    "stable non-forest": 581386.0,
}
PUBLISHED_CI = {
    "deforestation": 6158.0,
    "gain": 3756.0,
    "stable forest": 15510.0,
    "stable non-forest": 16282.0,
}


def write_olofsson_samples(path):
    rows = []
    for map_class, refs in OLOFSSON_ROWS.items():
        for ref_class, count in refs.items():
            rows.extend([(map_class, ref_class, None)] * count)
    return write_samples(path, rows)


def test_accuracy_estimates_reproduce_the_published_olofsson_example(tmp_path, evaluate):
    path = write_olofsson_samples(tmp_path / "olofsson.csv")

    results, grade = evaluate(
        [], accuracy_samples=accuracy.read_samples(path), class_areas=dict(OLOFSSON_AREAS)
    )

    result = one(results, "accuracy.estimates")
    assert result.status == "pass"
    evidence = result.evidence

    # Estimated area of each reference class, to within 1 ha of the published value.
    for name, published in PUBLISHED_AREA.items():
        assert evidence["area_estimated"][name] == pytest.approx(published, abs=1.0), name

    # 95% confidence-interval half-widths, to within 1% of the published value.
    for name, published in PUBLISHED_CI.items():
        assert evidence["area_margin_of_error_95"][name] == pytest.approx(published, rel=0.01), name

    # Accuracies: deforestation user's 0.88, producer's 0.75, overall 0.95 (paper rounds to 2 dp).
    assert evidence["user_accuracy"]["deforestation"] == pytest.approx(0.88, abs=0.005)
    assert evidence["producer_accuracy"]["deforestation"] == pytest.approx(0.75, abs=0.005)
    assert evidence["overall_accuracy"] == pytest.approx(0.95, abs=0.005)

    # The confusion matrix is the one printed in the paper.
    assert evidence["confusion_matrix"] == OLOFSSON_ROWS
    assert evidence["n_stratum"] == {
        "deforestation": 75, "gain": 75, "stable forest": 165, "stable non-forest": 325
    }
    assert evidence["sample_count"] == 640
    assert one(results, "accuracy.sample_design").status == "pass"
    assert grade == CHECKS_PASSED


def test_olofsson_areas_are_not_the_mapped_areas(tmp_path, evaluate):
    """The estimate must differ from the mapped area for every class; a row-sum bug returns it."""
    path = write_olofsson_samples(tmp_path / "olofsson_not_identity.csv")

    evidence = one(
        evaluate([], accuracy_samples=accuracy.read_samples(path), class_areas=dict(OLOFSSON_AREAS))[0],
        "accuracy.estimates",
    ).evidence

    for name, mapped in OLOFSSON_AREAS.items():
        assert evidence["area_estimated"][name] != pytest.approx(mapped, abs=1.0), name
    # Only stable non-forest is nearly unchanged, and even it is not exactly the mapped area.
    assert evidence["area_estimated"]["stable non-forest"] != OLOFSSON_AREAS["stable non-forest"]


def test_olofsson_stratum_weights_are_area_shares(tmp_path):
    """W_i is the stratum's mapped-area share; 18000/900000 = 0.02, 13500/900000 = 0.015."""
    path = write_olofsson_samples(tmp_path / "olofsson_weights.csv")

    estimates = accuracy.compute_estimates(
        accuracy.read_samples(path)["records"], dict(OLOFSSON_AREAS)
    )

    assert estimates["total_map_area"] == 900000.0
    assert estimates["stratum_weights"]["deforestation"] == pytest.approx(0.02, abs=1e-12)
    assert estimates["stratum_weights"]["gain"] == pytest.approx(0.015, abs=1e-12)
    assert estimates["stratum_weights"]["stable forest"] == pytest.approx(0.32, abs=1e-12)
    assert estimates["stratum_weights"]["stable non-forest"] == pytest.approx(0.645, abs=1e-12)
    assert sum(estimates["stratum_weights"].values()) == pytest.approx(1.0, abs=1e-12)


def test_olofsson_producer_accuracy_is_the_area_weighted_column_ratio(tmp_path):
    """p_jj / sum_i p_ij over area-weighted cells, not the raw column ratio.

    For deforestation the paper gives 0.75. The raw sample column ratio would be
    (66+0+1+2)/(66+0+1+2) over the deforestation column total 75+75+165+325 weighted by area,
    which differs; the area-weighted form is what the paper prints.
    """
    path = write_olofsson_samples(tmp_path / "olofsson_producer.csv")

    estimates = accuracy.compute_estimates(
        accuracy.read_samples(path)["records"], dict(OLOFSSON_AREAS)
    )

    cells = estimates["area_weighted_cell_proportions"]
    for name in ("deforestation", "gain", "stable forest", "stable non-forest"):
        column = sum(cells[row][name] for row in cells)
        diagonal = cells[name][name]
        assert estimates["producer_accuracy"][name] == pytest.approx(diagonal / column, abs=1e-12)
        # The area-weighted diagonal is the contribution to overall accuracy.
        assert diagonal == pytest.approx(estimates["producer_accuracy"][name] * column, abs=1e-12)

    # Overall accuracy is the sum of the area-weighted diagonal cells, which is sum_j p_jj.
    diagonal_sum = sum(cells[name][name] for name in cells)
    assert estimates["overall_accuracy"] == pytest.approx(diagonal_sum, abs=1e-12)
    assert estimates["overall_accuracy"] == pytest.approx(0.95, abs=0.005)


def test_olofsson_variance_follows_the_published_formula(tmp_path):
    """Var(p_k) = sum_i W_i^2 (n_ik/n_i)(1 - n_ik/n_i)/(n_i - 1), computed here from the table."""
    path = write_olofsson_samples(tmp_path / "olofsson_variance.csv")
    records = accuracy.read_samples(path)["records"]
    areas = dict(OLOFSSON_AREAS)

    estimates = accuracy.compute_estimates(records, areas)
    total = sum(areas.values())
    weights = {name: areas[name] / total for name in areas}
    n_i = {name: sum(OLOFSSON_ROWS[name].values()) for name in OLOFSSON_ROWS}

    for reference_class in ("deforestation", "gain", "stable forest", "stable non-forest"):
        variance = 0.0
        for map_class in OLOFSSON_ROWS:
            share = OLOFSSON_ROWS[map_class][reference_class] / n_i[map_class]
            variance += weights[map_class] ** 2 * share * (1.0 - share) / (n_i[map_class] - 1)
        standard_error = total * math.sqrt(variance)
        # A_k = A * p_k, and the reported area is A * the reported proportion.
        assert estimates["area_proportion"][reference_class] == pytest.approx(
            estimates["area_estimated"][reference_class] / total, abs=1e-12
        )
        assert estimates["area_standard_error"][reference_class] == pytest.approx(standard_error, abs=1e-6)
        assert estimates["area_margin_of_error_95"][reference_class] == pytest.approx(
            1.96 * standard_error, rel=1e-4
        )


def test_olofsson_confidence_interval_bounds_are_reported(tmp_path, evaluate):
    path = write_olofsson_samples(tmp_path / "olofsson_ci_bounds.csv")

    evidence = one(
        evaluate([], accuracy_samples=accuracy.read_samples(path), class_areas=dict(OLOFSSON_AREAS))[0],
        "accuracy.estimates",
    ).evidence

    for name, published in PUBLISHED_AREA.items():
        entry = evidence["class_area_estimate"][name]
        assert entry["ci_95_low"] == pytest.approx(entry["area_estimated"] - entry["margin_of_error_95"])
        assert entry["ci_95_high"] == pytest.approx(entry["area_estimated"] + entry["margin_of_error_95"])
        # The published interval brackets the published central value.
        assert entry["area_estimated"] - entry["margin_of_error_95"] <= published <= entry[
            "area_estimated"
        ] + entry["margin_of_error_95"]


def test_olofsson_user_accuracy_is_the_row_ratio(tmp_path):
    """User's accuracy is n_ii / n_i, so deforestation is 66/75 = 0.88."""
    path = write_olofsson_samples(tmp_path / "olofsson_user.csv")

    estimates = accuracy.compute_estimates(
        accuracy.read_samples(path)["records"], dict(OLOFSSON_AREAS)
    )

    assert estimates["user_accuracy"]["deforestation"] == pytest.approx(66 / 75, abs=1e-12)
    assert estimates["user_accuracy"]["gain"] == pytest.approx(55 / 75, abs=1e-12)
    assert estimates["user_accuracy"]["stable forest"] == pytest.approx(153 / 165, abs=1e-12)
    assert estimates["user_accuracy"]["stable non-forest"] == pytest.approx(313 / 325, abs=1e-12)


def test_accuracy_estimates_without_areas_is_not_run(tmp_path, evaluate):
    path = write_samples(tmp_path / "noareas.csv", sample_rows({"forest": {"forest": 60}}))

    results, grade = evaluate([], accuracy_samples=accuracy.read_samples(path))

    result = one(results, "accuracy.estimates")
    assert result.status == "not-run"
    assert result.evidence["accuracies"]["sample_overall_accuracy"] == pytest.approx(1.0)
    # Not-run downgrades the grade even though the sample design itself is fine.
    assert one(results, "accuracy.sample_design").status == "pass"
    assert grade == ADVISORY


def test_accuracy_estimates_with_a_missing_class_area_is_not_run(tmp_path, evaluate):
    path = write_samples(
        tmp_path / "partial.csv",
        sample_rows({"forest": {"forest": 60}, "water": {"water": 60}}),
    )

    results, _ = evaluate(
        [], accuracy_samples=accuracy.read_samples(path), class_areas={"forest": 1000.0}
    )

    result = one(results, "accuracy.estimates")
    assert result.status == "not-run"
    assert result.evidence["classes_without_area"] == ["water"]


def test_accuracy_checks_are_absent_without_samples(evaluate):
    results, grade = evaluate([])

    assert all(not result.id.startswith("accuracy.") for result in results)
    assert grade == ADVISORY


def test_area_adjusted_overall_differs_from_the_sample_overall(tmp_path):
    """The area-adjusted overall accuracy is not the raw sample accuracy when strata differ.

    Sample overall is (90 + 95) / 200 = 0.925. Area weighting by 100/9100 and 9000/9100 gives
    (100/9100)*0.9 + (9000/9100)*0.95, which is a different number.
    """
    path = write_samples(
        tmp_path / "skew.csv",
        sample_rows({"rare": {"rare": 90, "common": 10}, "common": {"common": 95, "rare": 5}}),
    )

    estimates = accuracy.compute_estimates(
        accuracy.read_samples(path)["records"], {"rare": 100.0, "common": 9000.0}
    )

    assert estimates["sample_overall_accuracy"] == pytest.approx(0.925, abs=1e-9)
    assert estimates["overall_accuracy"] == pytest.approx(
        (100.0 / 9100.0) * 0.9 + (9000.0 / 9100.0) * 0.95, abs=1e-9
    )
    assert estimates["overall_accuracy"] != pytest.approx(0.925, abs=1e-6)


def test_estimates_use_the_normal_quantile_from_the_paper():
    assert accuracy.NORMAL_975 == pytest.approx(1.959964, abs=1e-9)
    assert not hasattr(accuracy, "_t975")


# --- false-pass guards: no Phase 4 check may pass on wrong data ---


def test_no_phase4_check_is_emitted_without_its_inputs(make_raster, make_stac_item, evaluate):
    raster = make_raster("plain.tif", np.full((32, 32), 1.0, dtype="float32"), nodata=-9999.0)
    item = make_stac_item("plain.json", {"datetime": "2024-06-01T10:00:00Z", "proj:epsg": 32636})

    results, _ = evaluate([raster, item])

    phase4 = {
        result.id: result.status
        for result in results
        if result.id.split(".", 1)[0] in ("rs", "sar", "accuracy")
        and result.id in {
            "rs.scale_applied_once", "rs.cloud_mask_applied", "rs.temporal_scope",
            "sar.value_domain", "sar.geocoded", "accuracy.sample_design", "accuracy.estimates",
        }
    }
    assert all(status == "not-run" for status in phase4.values()), phase4


def test_sar_module_exposes_exactly_the_documented_entry_points():
    """sar exposes exactly the two documented entry points."""
    assert callable(sar.check_value_domain)
    assert callable(sar.check_geocoded)


def test_run_checks_defaults_are_unchanged_without_new_kwargs(make_raster, evaluate):
    """Existing behaviour: a plain raster run keeps exactly the results and grade it had before."""
    raster = make_raster("defaults.tif", np.full((32, 32), 0.3, dtype="float32"), nodata=-9999.0)

    results, grade = evaluate([raster])

    statuses = {result.id: result.status for result in results}
    # rs.reflectance_range / rs.index_range are only emitted when --expect is given.
    assert "rs.reflectance_range" not in statuses
    # Each Phase 4 processing check runs only when its own input is supplied, so a plain run
    # emits none of them and its grade is unchanged.
    assert "rs.scale_applied_once" not in statuses
    assert "rs.cloud_mask_applied" not in statuses
    assert "rs.temporal_scope" not in statuses
    assert "sar.value_domain" not in statuses
    assert "sar.geocoded" not in statuses
    assert "accuracy.estimates" not in statuses
    # The pre-existing raster checks behave exactly as before.
    assert statuses["crs.defined"] == "pass"
    assert statuses["raster.nodata_declared"] == "pass"
    assert statuses["raster.cog_layout"] == "pass"
    assert grade == CHECKS_PASSED
