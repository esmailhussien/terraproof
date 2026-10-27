"""Independent local corruptions that a sparse processing screen can miss."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from terraproof.checks import run_checks
from terraproof.inspect import inspect_dataset

GRID = from_origin(500000, 5000000, 10, 10)


def write(path, values, nodata, scales=None, offsets=None):
    values = values[None] if values.ndim == 2 else values
    with rasterio.open(path, "w", driver="GTiff", height=values.shape[1], width=values.shape[2],
                       count=values.shape[0], dtype=values.dtype, crs="EPSG:32636", transform=GRID,
                       nodata=nodata, tiled=True, blockxsize=128, blockysize=128) as dst:
        dst.write(values)
        if scales is not None:
            dst.scales = scales
        if offsets is not None:
            dst.offsets = offsets
    return path


def evaluate(output, *, source=None, qa=None, kind="s2-scl", full=True):
    options = {"processing_full_scan": full}
    if source:
        options["reference_input"] = inspect_dataset(source)
    if qa:
        options.update(qa_path=str(qa), qa_kind=kind)
    checks = run_checks([inspect_dataset(output)], **options)
    return {c.id: c for c in checks}


def calibrated(tmp_path, shape=(129, 131), bands=2):
    raw = np.full((bands, *shape), 2500, dtype="uint16")
    factors = [.0001*(i+1) for i in range(bands)]
    offsets = [-.1*(i+1) for i in range(bands)]
    decoded = np.stack([raw[i].astype("float64")*factors[i]+offsets[i] for i in range(bands)]).astype("float32")
    source = write(tmp_path/"raw.tif", raw, 65535, factors, offsets)
    output = write(tmp_path/"decoded.tif", decoded, -9999)
    return source, output, decoded


@pytest.mark.parametrize("defect", ["off-stride", "small-sampled", "other-band"])
def test_exhaustive_calibration_rejects_errors_that_legacy_screen_passes(tmp_path, defect):
    source, output, data = calibrated(tmp_path)
    band, row, col = (1, 1, 1) if defect == "other-band" else (0, 0, 0) if defect == "small-sampled" else (0, 1, 1)
    data[band, row, col] += .125
    with rasterio.open(output, "r+") as dst:
        dst.write(data)
    assert evaluate(output, source=source, full=False)["rs.scale_applied_once"].status == "pass"
    check = evaluate(output, source=source)["rs.scale_applied_once"]
    assert check.status == "fail" and check.evidence["mismatched_pixels"] == 1
    assert check.evidence["compared_pixels"] == data.size


def test_full_calibration_uses_each_band_metadata_across_window_boundaries(tmp_path):
    source, output, data = calibrated(tmp_path, shape=(271, 269), bands=3)
    check = evaluate(output, source=source)["rs.scale_applied_once"]
    assert check.status == "pass" and check.evidence["compared_pixels"] == data.size
    data[2, 256, 256] += .125
    with rasterio.open(output, "r+") as dst:
        dst.write(data)
    assert evaluate(output, source=source)["rs.scale_applied_once"].evidence["mismatched_pixels"] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_unmasked_nonfinite_output_is_not_accepted(tmp_path, value):
    source, output, data = calibrated(tmp_path)
    data[1, 1, 1] = value
    with rasterio.open(output, "r+") as dst:
        dst.write(data)
    check = evaluate(output, source=source)["rs.scale_applied_once"]
    assert check.status == "fail" and check.evidence["nonfinite_output_pixels"] == 1


def test_all_band_source_invalidity_and_output_encoding_are_checked(tmp_path):
    source, output, data = calibrated(tmp_path)
    with rasterio.open(source, "r+") as src:
        raw = src.read(); raw[1, 1, 1] = 65535; src.write(raw)
    check = evaluate(output, source=source)["rs.scale_applied_once"]
    assert check.status == "fail" and check.evidence["unmasked_source_nodata_pixels"] == 1
    data[1, 1, 1] = -9999
    with rasterio.open(output, "r+") as dst:
        dst.write(data)
    assert evaluate(output, source=source)["rs.scale_applied_once"].status == "pass"
    with rasterio.open(output, "r+") as dst:
        dst.scales = (.0001, .0001)
    assert evaluate(output, source=source)["rs.scale_applied_once"].status == "fail"


@pytest.mark.parametrize("kind,flag", [("s2-scl", 9), ("landsat-qa-pixel", 1 << 3)])
@pytest.mark.parametrize("defect", ["off-stride", "other-band", "seam"])
def test_cloud_errors_are_found_at_every_location_and_band(tmp_path, kind, flag, defect):
    shape = (271, 269)
    codes = np.full(shape, 4 if kind == "s2-scl" else 64, dtype="uint16")
    codes[0, 0] = flag
    row, col = (256, 256) if defect == "seam" else (1, 1)
    codes[row, col] = flag
    data = np.full((2, *shape), .3, dtype="float32")
    data[:, 0, 0] = -9999
    data[:, row, col] = -9999
    qa = write(tmp_path/"qa.tif", codes, 65535)
    output = write(tmp_path/"out.tif", data, -9999)
    assert evaluate(output, qa=qa, kind=kind)["rs.cloud_mask_applied"].status == "pass"
    data[1 if defect == "other-band" else 0, row, col] = .3
    with rasterio.open(output, "r+") as dst:
        dst.write(data)
    # The other sampled cloud is correctly masked; the small corruption is invisible to band-1 stride sampling.
    legacy = evaluate(output, qa=qa, kind=kind, full=False)["rs.cloud_mask_applied"]
    if defect != "seam":
        assert legacy.status == "pass"
    check = evaluate(output, qa=qa, kind=kind)["rs.cloud_mask_applied"]
    assert check.status == "fail" and check.evidence["unmasked_flagged_pixels"] == 1
    assert check.evidence["unmasked_flagged_band_pixels"] == 1


@pytest.mark.parametrize("defect", ["nodata", "unknown-code", "float-qa"])
def test_missing_or_unsupported_qa_cannot_claim_a_complete_pass(tmp_path, defect):
    codes = np.full((17, 19), 4, dtype="uint16")
    codes[0, 0] = 9
    codes[1, 1] = 65535 if defect == "nodata" else 12 if defect == "unknown-code" else 4
    if defect == "float-qa":
        codes = codes.astype("float32")
    data = np.full((2, 17, 19), .2, dtype="float32")
    data[:, 0, 0] = -9999
    qa = write(tmp_path/"qa.tif", codes, 65535)
    output = write(tmp_path/"out.tif", data, -9999)
    assert evaluate(output, qa=qa)["rs.cloud_mask_applied"].status == "not-run"


@pytest.mark.parametrize("side", ["source", "output"])
def test_large_integers_cannot_round_into_a_false_calibration_pass(tmp_path, side):
    raw = np.full((1, 3, 5), 2**53, dtype="uint64")
    delivered = raw.copy()
    (raw if side == "source" else delivered)[0, 1, 1] += 1
    source = write(tmp_path/"raw.tif", raw, 0)
    output = write(tmp_path/"decoded.tif", delivered, 0)
    assert evaluate(output, source=source)["rs.scale_applied_once"].status == "not-run"


def test_all_masked_calibration_and_cloud_free_qa_do_not_confirm_processing(tmp_path):
    source, output, data = calibrated(tmp_path)
    with rasterio.open(output, "r+") as dst:
        dst.write(np.full_like(data, -9999))
    assert evaluate(output, source=source)["rs.scale_applied_once"].status == "not-run"
    qa = write(tmp_path/"qa.tif", np.full((129, 131), 4, dtype="uint16"), 65535)
    assert evaluate(output, qa=qa)["rs.cloud_mask_applied"].status == "not-run"
