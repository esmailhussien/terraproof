"""Deterministic checks. Checks that do not apply to an input are omitted; checks that apply but cannot run are not-run."""

from __future__ import annotations

from terraproof.checks import accuracy, crs, geometry, raster, rs, rs_processing, sar, scope, stac, terrain
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
    reference_input: dict | None = None,
    encoding: str | None = None,
    qa_path: str | None = None,
    qa_kind: str | None = None,
    time_range: tuple[str, str] | list | None = None,
    sar_expect: str | None = None,
    accuracy_samples: dict | None = None,
    class_areas=None,
    min_per_class: int | None = None,
    estimates_requested: bool = False,
    dem: dict | None = None,
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

    # Processing-level checks (§3.3). Each one is emitted only when its own input was supplied:
    # a check that applies but cannot run reports not-run itself rather than being omitted.
    if reference_input is not None or encoding is not None:
        for dataset in rasters:
            results += rs_processing.check_scale_applied_once(dataset, reference_input, encoding)
    if qa_path is not None or qa_kind is not None:
        for dataset in rasters:
            results += rs_processing.check_cloud_mask_applied(dataset, qa_path, qa_kind)
    if time_range is not None:
        results += rs_processing.check_temporal_scope(stac_items, time_range)

    if dem is not None:
        for dataset in rasters:
            results += terrain.check_slope_consistent(dataset, dem)

    if sar_expect is not None:
        results += sar.check_value_domain(rasters, sar_expect)
        results += sar.check_geocoded(rasters)

    if accuracy_samples is not None:
        design_kwargs = {} if min_per_class is None else {"min_per_class": min_per_class}
        results += accuracy.check_sample_design(
            accuracy_samples,
            class_areas=class_areas,
            estimates_requested=estimates_requested,
            **design_kwargs,
        )
        results += accuracy.check_estimates(accuracy_samples, class_areas=class_areas)
    return results
