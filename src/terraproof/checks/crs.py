"""CRS and units checks: crs.defined, crs.consistent, crs.metric_operation."""

from __future__ import annotations

from pyproj import CRS

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, CheckResult, result


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
        else:
            results.append(_metric_operation_result(path, operation, crs))
    return results


def _metric_operation_result(path: str, operation: str, crs: dict) -> CheckResult:
    """Decision rules, applied to the horizontal component of the CRS (see crs_summary):

    - geographic: fail (distances and areas would be in degrees);
    - geocentric: fail (Earth-centred X/Y/Z, not map distances);
    - projected with metre or foot units: pass;
    - projected with other units, or any other kind (vertical-only, engineering, unknown): warn,
      because the units for the operation cannot be confirmed.
    """
    kind = crs["horizontal_kind"]
    units = crs["horizontal_axis_units"]
    evidence = {
        "input": path,
        "operation": operation,
        "epsg": crs["epsg"],
        "axis_units": crs["axis_units"],
        "horizontal_kind": kind,
        "horizontal_axis_units": units,
        "is_geocentric": crs["is_geocentric"],
    }
    if kind == "geographic":
        return result(
            "crs.metric_operation",
            FAIL,
            f"Operation '{operation}' on {path} uses a geographic CRS (units: {units}), "
            "so distances and areas would be in degrees. Reproject to a projected CRS first.",
            **evidence,
        )
    if kind == "geocentric":
        return result(
            "crs.metric_operation",
            FAIL,
            f"Operation '{operation}' on {path} uses a geocentric CRS (units: {units}); its X, Y and Z axes are "
            "Earth-centred Cartesian coordinates, not map distances. Reproject to a projected CRS first.",
            **evidence,
        )
    if kind == "projected" and _is_metric_or_foot(units):
        return result(
            "crs.metric_operation",
            PASS,
            f"Projected CRS in {units} is suitable for '{operation}' on {path}.",
            **evidence,
        )
    if kind == "projected":
        return result(
            "crs.metric_operation",
            WARN,
            f"Units for '{operation}' on {path} cannot be confirmed: the projected CRS uses units '{units}'. "
            "Confirm they are metric or foot-based before the operation.",
            **evidence,
        )
    return result(
        "crs.metric_operation",
        WARN,
        f"Units for '{operation}' on {path} cannot be confirmed: {crs['name']} has no projected horizontal "
        "component. Confirm the operation's units before using it.",
        **evidence,
    )
