"""Phase 6 C: the extended rs.index_formula and the new rs.stack_reduction (source-aware checks)."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
from rasterio.transform import from_origin

from terraproof.checks import run_checks
from terraproof.checks.index_formula import check_index_formula
from terraproof.checks.stack_reduction import check_stack_reduction
from terraproof.cli import main
from terraproof.evals.fixtures import write_raster_grid
from terraproof.inspect import inspect_dataset

GRID = from_origin(500000, 5000000, 20, 20)
NODATA = -9999.0


def _write(path, values, **kwargs):
    return write_raster_grid(path, np.asarray(values, dtype=kwargs.pop("dtype", "float32")), transform=GRID, **kwargs)


def _bands(tmp_path, **arrays):
    return {role: _write(tmp_path / f"{role}.tif", values) for role, values in arrays.items()}


def _inspected(paths, numbers=None):
    return {role: dict(inspect_dataset(path), band=(numbers or {}).get(role)) for role, path in paths.items()}


def _expected(values):
    out = np.full(values.shape, NODATA, dtype="float32")
    ok = np.isfinite(values)
    out[ok] = values[ok]
    return out


R, C = np.indices((6, 7))
GREEN = 0.12 + 0.01 * R
NIR = 0.30 + 0.02 * C
RED = 0.08 + 0.005 * (R + C)
SWIR1 = 0.15 + 0.004 * R
SWIR2 = 0.10 + 0.003 * C
BLUE = 0.05 + 0.002 * R

FORMULA_CASES = {
    "nbr": ({"nir": NIR, "swir2": SWIR2}, (NIR - SWIR2) / (NIR + SWIR2)),
    "ndwi": ({"green": GREEN, "nir": NIR}, (GREEN - NIR) / (GREEN + NIR)),
    "mndwi": ({"green": GREEN, "swir1": SWIR1}, (GREEN - SWIR1) / (GREEN + SWIR1)),
    "ndmi": ({"nir": NIR, "swir1": SWIR1}, (NIR - SWIR1) / (NIR + SWIR1)),
    "savi": ({"nir": NIR, "red": RED}, 1.5 * (NIR - RED) / (NIR + RED + 0.5)),
    "evi": ({"blue": BLUE, "red": RED, "nir": NIR}, 2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)),
}


@pytest.mark.parametrize("formula", sorted(FORMULA_CASES))
def test_each_formula_passes_its_own_index_and_fails_a_lookalike(tmp_path, formula):
    arrays, values = FORMULA_CASES[formula]
    paths = _bands(tmp_path, **arrays)
    out = _write(tmp_path / "out.tif", _expected(values), nodata=NODATA)
    assert check_index_formula(inspect_dataset(out), formula, None, None, _inspected(paths))[0].status == "pass"
    _write(tmp_path / "out.tif", _expected(values * 1.01 + 0.002), nodata=NODATA)
    found = check_index_formula(inspect_dataset(out), formula, None, None, _inspected(paths))[0]
    assert found.status == "fail" and found.evidence["mismatched_cells"] > 0


def test_ndwi_names_the_mcfeeters_formula_so_gao_moisture_fails(tmp_path):
    paths = _bands(tmp_path, green=GREEN, nir=NIR)
    gao = _write(tmp_path / "gao.tif", _expected((NIR - SWIR1) / (NIR + SWIR1)), nodata=NODATA)
    assert check_index_formula(inspect_dataset(gao), "ndwi", None, None, _inspected(paths))[0].status == "fail"


def test_dnbr_is_pre_minus_post_and_a_reversed_sign_fails(tmp_path):
    post_nir, post_swir2 = NIR * 0.1, SWIR2 * 5 + 0.2
    paths = _bands(tmp_path, pre_nir=NIR, pre_swir2=SWIR2, post_nir=post_nir, post_swir2=post_swir2)
    dnbr = (NIR - SWIR2) / (NIR + SWIR2) - (post_nir - post_swir2) / (post_nir + post_swir2)
    assert dnbr.max() > 1  # a dNBR outside [-1, 1] is valid, not clipped
    for values, status in ((dnbr, "pass"), (-dnbr, "fail")):
        out = _write(tmp_path / "dnbr.tif", _expected(values), nodata=NODATA)
        assert check_index_formula(inspect_dataset(out), "dnbr", None, None, _inspected(paths))[0].status == status


def test_multiband_source_needs_band_numbers_and_uses_each_bands_calibration(tmp_path):
    raw = np.stack([np.full((6, 7), 1500), np.full((6, 7), 1200), np.full((6, 7), 12000)]).astype("uint16")
    bands = write_raster_grid(tmp_path / "bands.tif", raw, transform=GRID, nodata=65535,
                              scales=[0.0001, 0.0002, 5e-05], offsets=[-0.08, -0.12, -0.02])
    blue, red, nir = 1500 * 0.0001 - 0.08, 1200 * 0.0002 - 0.12, 12000 * 5e-05 - 0.02
    out = _write(tmp_path / "evi.tif", np.full((6, 7), 2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)), nodata=NODATA)
    roles = {"blue": bands, "red": bands, "nir": bands}
    named = _inspected(roles, {"blue": 1, "red": 2, "nir": 3})
    found = check_index_formula(inspect_dataset(out), "evi", None, None, named)[0]
    assert found.status == "pass" and found.evidence["bands"] == {"blue": 1, "red": 2, "nir": 3}
    unnamed = check_index_formula(inspect_dataset(out), "evi", None, None, _inspected(roles))[0]
    assert unnamed.status == "not-run" and "Name the band" in unnamed.message
    stored = _write(tmp_path / "stored.tif", np.full((6, 7), 2.5 * (12000 - 1200) / (12000 + 6 * 1200 - 7.5 * 1500 + 1)),
                    nodata=NODATA)
    assert check_index_formula(inspect_dataset(stored), "evi", None, None, named)[0].status == "fail"


def test_missing_roles_are_not_run_and_ndvi_keeps_its_nir_red_arguments(tmp_path):
    paths = _bands(tmp_path, nir=NIR, red=RED)
    out = _write(tmp_path / "ndvi.tif", _expected((NIR - RED) / (NIR + RED)), nodata=NODATA)
    assert check_index_formula(inspect_dataset(out), "nbr", None, None, _inspected(paths))[0].status == "not-run"
    nir, red = (inspect_dataset(paths[role]) for role in ("nir", "red"))
    assert check_index_formula(inspect_dataset(out), "ndvi", nir, red)[0].status == "pass"


def _stack_files(tmp_path, layers):
    return [_write(tmp_path / f"layer{i}.tif", layer, nodata=NODATA) for i, layer in enumerate(layers)]


def _stack_check(out, files, reduction, weights=None, min_count=None):
    return check_stack_reduction(inspect_dataset(out), [inspect_dataset(f) for f in files], reduction, weights, min_count)[0]


LAYERS = [0.2 + 0.01 * R, 0.3 + 0.01 * C, 0.25 + 0.0 * R, 0.4 - 0.01 * R]


def _masked(layers):
    layers = [np.array(layer, dtype="float64") for layer in layers]
    layers[1][0, 0] = NODATA
    layers[2][0, 0] = NODATA
    layers[3][0, 0] = NODATA  # one valid layer at (0, 0)
    for layer in layers:
        layer[1, 1] = NODATA  # no valid layer at (1, 1)
    return layers


def _reference(layers, reduction, weights=None, min_count=1):
    """Scalar per-pixel reference, independent of the checker's vectorised code."""
    out = np.full(layers[0].shape, NODATA, dtype="float64")
    for r, c in np.ndindex(out.shape):
        pairs = [(w, layer[r, c]) for w, layer in zip(weights or [0] * len(layers), layers) if layer[r, c] != NODATA]
        if reduction == "weighted-sum" and len(pairs) < len(layers) or len(pairs) < max(1, min_count):
            continue
        ys = [y for _, y in pairs]
        if reduction == "median":
            out[r, c] = float(np.median(ys))
        elif reduction == "weighted-sum":
            out[r, c] = sum(w * y for w, y in pairs)
        elif reduction == "mean-power-db":
            out[r, c] = 10 * math.log10(sum(10 ** (y / 10) for y in ys) / len(ys))
        elif reduction == "ols-slope":
            xs = [w for w, _ in pairs]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            den = sum((x - mx) ** 2 for x in xs)
            out[r, c] = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den > 1e-12 else NODATA
    return out


@pytest.mark.parametrize("reduction, weights, min_count, wrong", [
    ("median", None, None, lambda layers, ref: np.where(ref != NODATA, np.mean([np.where(l == NODATA, 0, l) for l in layers], axis=0), NODATA)),
    ("weighted-sum", [1, 4.5, 7.5, 11], None, lambda layers, ref: np.where(ref != NODATA, sum(layers), NODATA)),
    ("mean-power-db", None, None, lambda layers, ref: np.where(ref != NODATA, ref + 0.5, NODATA)),
    ("ols-slope", [0.0, 0.25, 0.87, 1.72], 3, lambda layers, ref: np.where(ref != NODATA, ref * 1.3, NODATA)),
])
def test_each_reduction_passes_the_reference_and_fails_a_mistake(tmp_path, reduction, weights, min_count, wrong):
    layers = [np.array(l, dtype="float64") for l in LAYERS]
    if reduction == "mean-power-db":
        layers = [-12 + 3 * l for l in layers]
    layers = _masked(layers) if reduction != "weighted-sum" else layers
    files = _stack_files(tmp_path, layers)
    reference = _reference(layers, reduction, weights, min_count or 1)
    out = _write(tmp_path / "out.tif", reference, nodata=NODATA)
    assert _stack_check(out, files, reduction, weights, min_count).status == "pass"
    _write(tmp_path / "out.tif", wrong(layers, reference), nodata=NODATA)
    assert _stack_check(out, files, reduction, weights, min_count).status == "fail"


def test_unsupported_cells_must_be_nodata_and_extra_masking_warns(tmp_path):
    layers = _masked(LAYERS)
    files = _stack_files(tmp_path, layers)
    reference = _reference(layers, "median")
    filled = reference.copy()
    filled[1, 1] = 0.0  # no valid layer, but a value is delivered
    out = _write(tmp_path / "out.tif", filled, nodata=NODATA)
    assert _stack_check(out, files, "median").status == "fail"
    masked = reference.copy()
    masked[2, 2] = NODATA
    _write(tmp_path / "out.tif", masked, nodata=NODATA)
    assert _stack_check(out, files, "median").status == "warn"


def test_weighted_reductions_need_one_weight_per_layer_and_grids_must_match(tmp_path):
    files = _stack_files(tmp_path, LAYERS)
    out = _write(tmp_path / "out.tif", np.zeros((6, 7)), nodata=NODATA)
    assert _stack_check(out, files, "weighted-sum", [1, 2]).status == "not-run"
    assert _stack_check(out, files, "ols-slope", None).status == "not-run"
    assert _stack_check(out, files, "guess").status == "not-run"
    shifted = write_raster_grid(tmp_path / "shifted.tif", np.zeros((6, 7), dtype="float32"),
                                transform=from_origin(500010, 5000000, 20, 20))
    assert _stack_check(shifted, files, "median").status == "not-run"


def test_checks_run_only_when_declared(tmp_path):
    files = _stack_files(tmp_path, LAYERS)
    out = inspect_dataset(_write(tmp_path / "out.tif", np.zeros((6, 7)), nodata=NODATA))
    ids = {r.id for r in run_checks([out])}
    assert "rs.stack_reduction" not in ids and "rs.index_formula" not in ids
    found = run_checks([out], stack=[inspect_dataset(f) for f in files], stack_reduction="median")
    assert [r.id for r in found if r.id == "rs.stack_reduction"] == ["rs.stack_reduction"]


def test_cli_band_and_stack_flags_match_the_python_api(tmp_path, capsys):
    paths = _bands(tmp_path, nir=NIR, swir2=SWIR2)
    nbr = _write(tmp_path / "nbr.tif", _expected((NIR - SWIR2) / (NIR + SWIR2)), nodata=NODATA)
    main(["check", nbr, "--index-formula", "nbr", "--band", f"nir={paths['nir']}", "--band", f"swir2={paths['swir2']}",
          "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert {c["id"]: c["status"] for c in report["checks"]}["rs.index_formula"] == "pass"
    assert sum(item["role"] == "index-band" for item in report["inputs"]) == 2
    files = _stack_files(tmp_path, LAYERS)
    total = _write(tmp_path / "total.tif", sum(w * l for w, l in zip([1, 2, 3, 4], LAYERS)), nodata=NODATA)
    argv = ["check", total, "--stack-reduction", "weighted-sum", "--format", "json"]
    for path, weight in zip(files, [1, 2, 3, 4]):
        argv += ["--stack", path, "--stack-weight", str(weight)]
    main(argv)
    report = json.loads(capsys.readouterr().out)
    assert {c["id"]: c["status"] for c in report["checks"]}["rs.stack_reduction"] == "pass"
    assert report["parameters"]["stack_weights"] == [1.0, 2.0, 3.0, 4.0]
    for lang in ("en", "ar"):  # the Markdown report labels both new input roles
        main(argv[:-2] + ["--format", "md", "--lang", lang])
        assert "rs.stack_reduction" in capsys.readouterr().out
