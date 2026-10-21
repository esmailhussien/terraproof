"""CRS and units checks: crs.defined, crs.consistent, crs.metric_operation."""

from __future__ import annotations

from pyproj import CRS

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result


def _label(dataset: dict) -> str:
    return dataset["path"]


def check_defined(datasets: list[dict]) -> list:
    results = []
    for dataset in datasets:
        crs = dataset["crs"]
        if crs is None:
            results.append(result("crs.defined", FAIL, f"No CRS defined for {_label(dataset)}.", input=_label(dataset)))
        else:
            results.append(
                result(
                    "crs.defined",
                    PASS,
                    f"CRS defined for {_label(dataset)}.",
                    input=_label(dataset),
                    epsg=crs["epsg"],
                    axis_units=crs["axis_units"],
                )
            )
    return results


def check_consistent(datasets: list[dict]) -> list:
    """Compare every input's CRS with the first one using pyproj CRS.equals."""
    if len(datasets) < 2:
        return []
    inputs = [d["path"] for d in datasets]
    epsg_codes = [d["crs"]["epsg"] if d["crs"] else None for d in datasets]
    missing = [d["path"] for d in datasets if d["crs"] is None]
    if missing:
        return [
            result(
                "crs.consistent",
                NOT_RUN,
                "Cannot compare CRSs because some inputs have no CRS: " + ", ".join(missing) + ".",
                inputs=inputs,
                epsg_codes=epsg_codes,
            )
        ]

    reference = datasets[0]
    reference_crs = CRS.from_user_input(reference["crs"]["wkt"])
    mismatched = [
        d for d in datasets[1:] if not reference_crs.equals(CRS.from_user_input(d["crs"]["wkt"]))
    ]
    if mismatched:
        names = ", ".join(d["path"] for d in mismatched)
        return [
            result(
                "crs.consistent",
                FAIL,
                f"CRS differs from {_label(reference)} for: {names}. Reproject to one CRS before combining.",
                inputs=inputs,
                epsg_codes=epsg_codes,
            )
        ]
    return [
        result(
            "crs.consistent",
            PASS,
            f"All {len(datasets)} inputs share one CRS.",
            inputs=inputs,
            epsg_codes=epsg_codes,
        )
    ]


def _is_metric_or_foot(units: str | None) -> bool:
    lowered = (units or "").lower()
    return any(word in lowered for word in ("metre", "meter", "foot", "feet"))


def check_metric_operation(datasets: list[dict], operation: str) -> list:
    if not datasets:
        return [
            result(
                "crs.metric_operation",
                NOT_RUN,
                f"No vector or raster input to check for operation '{operation}'.",
                operation=operation,
            )
        ]
    results = []
    for dataset in datasets:
        path = _label(dataset)
        crs = dataset["crs"]
        if crs is None:
            results.append(
                result(
                    "crs.metric_operation",
                    NOT_RUN,
                    f"Cannot check operation '{operation}' on {path}: no CRS defined.",
                    input=path,
                    operation=operation,
                )
            )
        elif crs["is_geographic"]:
            results.append(
                result(
                    "crs.metric_operation",
                    FAIL,
                    f"Operation '{operation}' on {path} uses a geographic CRS (units: {crs['axis_units']}), "
                    "so distances and areas would be in degrees. Reproject to a projected CRS first.",
                    input=path,
                    operation=operation,
                    epsg=crs["epsg"],
                    axis_units=crs["axis_units"],
                )
            )
        elif _is_metric_or_foot(crs["axis_units"]):
            results.append(
                result(
                    "crs.metric_operation",
                    PASS,
                    f"Projected CRS in {crs['axis_units']} is suitable for '{operation}' on {path}.",
                    input=path,
                    operation=operation,
                    epsg=crs["epsg"],
                    axis_units=crs["axis_units"],
                )
            )
        else:
            results.append(
                result(
                    "crs.metric_operation",
                    WARN,
                    f"Projected CRS on {path} uses units '{crs['axis_units']}'. Confirm they are metric or "
                    f"foot-based before '{operation}'.",
                    input=path,
                    operation=operation,
                    epsg=crs["epsg"],
                    axis_units=crs["axis_units"],
                )
            )
    return results
