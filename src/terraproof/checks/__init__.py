"""Deterministic checks. Checks that do not apply to an input are omitted; checks that apply but cannot run are not-run."""

from __future__ import annotations

from terraproof.checks import crs, geometry, raster, rs, scope, stac
from terraproof.checks.base import STATUSES, CheckResult, result

__all__ = ["STATUSES", "CheckResult", "result", "run_checks"]


def run_checks(
    inputs: list[dict],
    *,
    compare_to: dict | None = None,
    operation: str | None = None,
    resampling: str | None = None,
    categorical: bool = False,
    expect: str | None = None,
) -> list[CheckResult]:
    """Run every check that applies to the inspected inputs, in a fixed order."""
    vectors = [d for d in inputs if d["kind"] == "vector"]
    rasters = [d for d in inputs if d["kind"] == "raster"]
    stac_items = [d for d in inputs if d["kind"] == "stac"]
    georeferenced = [d for d in inputs if d["kind"] in ("vector", "raster")]

    results: list[CheckResult] = []
    results += crs.check_defined(georeferenced)
    if len(georeferenced) >= 2:
        results += crs.check_consistent(georeferenced)
    if operation:
        results += crs.check_metric_operation(georeferenced, operation)

    for dataset in vectors:
        results += geometry.check_geometry(dataset)
    if compare_to is not None:
        results += scope.check_record_count(vectors, compare_to)

    for dataset in rasters:
        results += raster.check_nodata(dataset)
        results += raster.check_cog_layout(dataset)
    if len(rasters) >= 2:
        results += raster.check_grid_alignment(rasters)
    if resampling is not None and categorical:
        results += raster.check_resampling(rasters, resampling)

    if expect == "reflectance":
        results += rs.check_reflectance(rasters)
    elif expect == "index":
        results += rs.check_index(rasters)

    for dataset in stac_items:
        results += stac.check_provenance(dataset)
    return results
