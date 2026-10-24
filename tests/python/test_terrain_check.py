"""terrain.slope_consistent: a slope raster against the DEM's vertical unit and pixel spacing."""

from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pytest
from rasterio.transform import from_origin

from terraproof.checks import run_checks
from terraproof.checks.terrain import check_slope_consistent
from terraproof.evals.fixtures import write_raster_grid
from terraproof.inspect import inspect_dataset

NODATA = -9999.0
GRID = from_origin(500000, 5000000, 30, 60)  # anisotropic: 30 m wide, 60 m tall


def _dem(tmp_path, unit="ft", transform=GRID, crs="EPSG:32636"):
    r, c = np.indices((12, 12))
    z = ((40 + 0.5 * c * c + 0.3 * r * r) / 0.3048).astype("float32")
    z[4, 6] = NODATA
    path = write_raster_grid(tmp_path / "dem.tif", z, transform=transform, crs=crs, unit=unit)
    return path, z


def _slope(z, factor, dx, dy):
    values = z.astype("float64") * factor
    out = np.full(z.shape, NODATA)
    gx = (values[1:-1, 2:] - values[1:-1, :-2]) / (2 * dx)
    gy = (values[2:, 1:-1] - values[:-2, 1:-1]) / (2 * dy)
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(gx, gy)))
    bad = np.zeros(z.shape, bool)
    for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
        bad |= np.roll(np.roll(z == NODATA, dr, axis=0), dc, axis=1)
    out[bad] = NODATA
    return out.astype("float32")


def _check(tmp_path, slope, dem_path, name="slope.tif", transform=GRID, crs="EPSG:32636"):
    out = write_raster_grid(tmp_path / name, slope, transform=transform, crs=crs)
    (only,) = check_slope_consistent(inspect_dataset(out), inspect_dataset(dem_path))
    return only


def test_slope_with_declared_units_and_spacing_passes(tmp_path):
    dem, z = _dem(tmp_path)
    found = _check(tmp_path, _slope(z, 0.3048, 30, 60), dem)
    assert found.id == "terrain.slope_consistent" and found.status == "pass"
    assert found.evidence["vertical_unit"] == "ft" and found.evidence["declared_match_fraction"] == 1.0


@pytest.mark.parametrize("factor, dx, dy, mistake", [
    (1.0, 30, 60, "vertical units ignored"),
    (0.3048, 30, 30, "square pixels assumed (x spacing)"),
    (0.3048, 60, 60, "square pixels assumed (y spacing)"),
])
def test_known_unit_and_spacing_mistakes_fail(tmp_path, factor, dx, dy, mistake):
    dem, z = _dem(tmp_path)
    found = _check(tmp_path, _slope(z, factor, dx, dy), dem)
    assert found.status == "fail" and mistake in found.message
    assert found.evidence["mistake_match_fractions"][mistake] == 1.0


def test_a_slope_matching_no_known_mistake_only_warns(tmp_path):
    dem, z = _dem(tmp_path)
    slope = _slope(z, 0.3048, 30, 60)
    slope[slope != NODATA] *= 1.2  # e.g. another stencil: not identified as a unit mistake
    assert _check(tmp_path, slope, dem).status == "warn"


def test_a_dem_without_a_vertical_unit_is_read_in_horizontal_units(tmp_path):
    dem, z = _dem(tmp_path, unit=None)
    found = _check(tmp_path, _slope(z, 1.0, 30, 60), dem)
    assert found.status == "pass" and found.evidence["vertical_unit"] is None


def test_unknown_units_geographic_and_unaligned_grids_are_not_run(tmp_path):
    dem, z = _dem(tmp_path, unit="furlong")
    assert _check(tmp_path, _slope(z, 1.0, 30, 60), dem).status == "not-run"

    geographic = tmp_path / "geo"
    geographic.mkdir()
    transform = from_origin(30, 10, 0.001, 0.001)
    dem, z = _dem(geographic, transform=transform, crs="EPSG:4326")
    found = _check(geographic, _slope(z, 0.3048, 30, 60), dem, transform=transform, crs="EPSG:4326")
    assert found.status == "not-run" and "projected" in found.message

    dem, z = _dem(tmp_path)
    shifted = from_origin(500015, 5000000, 30, 60)
    found = _check(tmp_path, _slope(z, 0.3048, 30, 60), dem, name="shifted.tif", transform=shifted)
    assert found.status == "not-run" and "same grid" in found.message


def test_run_checks_emits_the_check_only_when_a_dem_is_given(tmp_path):
    dem, z = _dem(tmp_path)
    out = inspect_dataset(write_raster_grid(tmp_path / "slope.tif", _slope(z, 1.0, 30, 60), transform=GRID))
    assert "terrain.slope_consistent" not in [r.id for r in run_checks([out])]
    found = [r for r in run_checks([out], dem=inspect_dataset(dem)) if r.id == "terrain.slope_consistent"]
    assert [r.status for r in found] == ["fail"]


def test_cli_dem_flag_runs_the_check_and_records_the_dem(tmp_path):
    dem, z = _dem(tmp_path)
    out = write_raster_grid(tmp_path / "slope.tif", _slope(z, 0.3048, 30, 60), transform=GRID)
    completed = subprocess.run([sys.executable, "-m", "terraproof", "check", out, "--dem", dem, "--format", "json"],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    report = json.loads(completed.stdout)
    statuses = {c["id"]: c["status"] for c in report["checks"]}
    assert statuses["terrain.slope_consistent"] == "pass"
    assert report["parameters"]["dem"] == dem
    assert any(item["role"] == "dem" for item in report["inputs"])
    for lang in ("en", "ar"):  # the Markdown report labels the dem role in both languages
        markdown = subprocess.run([sys.executable, "-m", "terraproof", "check", out, "--dem", dem, "--lang", lang],
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert markdown.returncode in (0, 1, 2) and "terrain.slope_consistent" in markdown.stdout, markdown.stderr
