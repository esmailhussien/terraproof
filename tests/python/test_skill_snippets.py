"""Executable checks for code that skills hand to agents: a wrong snippet is a wrong answer."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[2]


def _terrain_metrics():
    """Load terrain_metrics() exactly as written in skills/geomaster/SKILL.md."""
    text = (ROOT / "skills" / "geomaster" / "SKILL.md").read_text(encoding="utf-8")
    section = text.split("### Terrain Analysis", 1)[1]
    code = re.search(r"```python\n(.*?)```", section, re.S).group(1)
    namespace = {"np": np, "rasterio": rasterio}
    exec(compile(code, "geomaster/SKILL.md#terrain-analysis", "exec"), namespace)
    return namespace["terrain_metrics"]


def _plane_dem(path, *, east, north, pixel=(30.0, 60.0), unit=None, z_per_metre=1.0, crs="EPSG:32636",
               nodata=None, transform=None):
    """A planar DEM z = east * x + north * y (metres), stored in the given vertical unit."""
    rows, cols = 12, 10
    width, height = pixel
    x = (np.arange(cols) + 0.5) * width
    y = -(np.arange(rows) + 0.5) * height  # rows run southward
    z = (east * x[None, :] + north * y[:, None] + 500.0) * z_per_metre
    profile = dict(driver="GTiff", width=cols, height=rows, count=1, dtype="float64", crs=crs, nodata=nodata,
                   transform=transform or Affine(width, 0, 500000, 0, -height, 4000000))
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(z, 1)
        if unit:
            dst.set_band_unit(1, unit)
    return str(path)


@pytest.mark.parametrize("east,north", [(0.1, 0.0), (0.0, -0.2), (-0.05, 0.08), (0.3, 0.3)])
def test_slope_and_aspect_use_real_pixel_spacing_and_vertical_units(tmp_path, east, north):
    terrain_metrics = _terrain_metrics()
    metres = _plane_dem(tmp_path / "m.tif", east=east, north=north, unit="m")
    feet = _plane_dem(tmp_path / "ft.tif", east=east, north=north, unit="ft", z_per_metre=1 / 0.3048)
    expected_slope = np.degrees(np.arctan(np.hypot(east, north)))
    expected_aspect = np.degrees(np.arctan2(-east, -north)) % 360  # downslope direction
    for path in (metres, feet):
        slope, aspect, hillshade = terrain_metrics(path)
        assert np.allclose(slope, expected_slope, atol=1e-6)
        assert np.allclose(aspect, expected_aspect, atol=1e-6)
        assert np.all((hillshade >= 0) & (hillshade <= 1))


def test_hillshade_is_brightest_facing_the_sun_and_flat_cells_have_no_aspect(tmp_path):
    terrain_metrics = _terrain_metrics()
    # A slope facing north-west (downslope toward 315 degrees) faces the default sun.
    _, aspect, sunny = terrain_metrics(_plane_dem(tmp_path / "nw.tif", east=0.2, north=-0.2, unit="m"))
    _, _, shaded = terrain_metrics(_plane_dem(tmp_path / "se.tif", east=-0.2, north=0.2, unit="m"))
    assert np.allclose(aspect, 315.0)
    assert sunny.mean() > np.sin(np.radians(45)) > shaded.mean()
    slope, flat_aspect, flat_shade = terrain_metrics(_plane_dem(tmp_path / "flat.tif", east=0, north=0, unit="m"))
    assert np.all(slope == 0) and np.all(np.isnan(flat_aspect))
    assert np.allclose(flat_shade, np.sin(np.radians(45)))


def test_nodata_becomes_nan_and_unsupported_grids_are_refused(tmp_path):
    terrain_metrics = _terrain_metrics()
    path = _plane_dem(tmp_path / "hole.tif", east=0.1, north=0.0, unit="m", nodata=-9999.0)
    with rasterio.open(path, "r+") as dst:
        values = dst.read(1)
        values[5, 5] = -9999.0
        dst.write(values, 1)
    slope, _, _ = terrain_metrics(path)
    assert np.isnan(slope[5, 5]) and np.isnan(slope[5, 4]) and np.isnan(slope[4, 5])
    assert np.isclose(slope[0, 0], np.degrees(np.arctan(0.1)))

    with pytest.raises(ValueError, match="projected"):
        terrain_metrics(_plane_dem(tmp_path / "geo.tif", east=0.1, north=0, unit="m", crs="EPSG:4326",
                                   transform=Affine(0.001, 0, 30, 0, -0.001, 31)))
    with pytest.raises(ValueError, match="north-up"):
        terrain_metrics(_plane_dem(tmp_path / "sheared.tif", east=0.1, north=0, unit="m",
                                   transform=Affine(30, 5, 500000, 0, -60, 4000000)))
    with pytest.raises(ValueError, match="unknown elevation unit"):
        terrain_metrics(_plane_dem(tmp_path / "fathoms.tif", east=0.1, north=0, unit="fathom"))
    assert np.allclose(terrain_metrics(_plane_dem(tmp_path / "z.tif", east=0.1, north=0, unit="fathom"),
                                       z_factor=1.0)[0], np.degrees(np.arctan(0.1)))
