"""Preflight checks: assess a declared processing plan against real inputs before running it.

A preflight run takes the inspected profiles of the datasets a plan will use plus a
small JSON plan, and returns seven ``preflight.*`` check results. These checks judge
whether the plan as declared is consistent with the inputs; they do **not** verify
that any processing step was actually applied.

Plan JSON schema
----------------

All fields are optional. Unknown fields are rejected.

.. code-block:: json

    {
      "operation": "buffer" | "distance" | "area" | "length" | null,
      "target_crs": "EPSG:xxxx" | {"epsg": 1234} | {"wkt": "..."} | null,
      "reproject": true | false,
      "resampling": "nearest" | "bilinear" | "cubic" | ... | null,
      "categorical": true | false,
      "combine": true | false,
      "alignment": true | false,
      "decode": true | false,
      "encoding": "s2-l2a" | "landsat-c2-l2" | null,
      "time_range": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"] | null,
      "expect": "reflectance" | "index" | null,
      "measurement_units": "metres" | "feet" | "sq metres" | "acres" | ... | null,
      "unit_conversion": true | false
    }

Semantics
---------

* ``reproject`` must be ``true`` to declare that inputs will be reprojected to
  ``target_crs`` before the operation. ``target_crs`` by itself is treated as the
  output CRS, not as an implicit reprojection step.
* ``encoding`` names a known product encoding (e.g. Sentinel-2 L2A). It is used by
  the reflectance/index checks to recognise encoded inputs; a decode step is still
  required unless the raster is already decoded.
* ``measurement_units`` states the units the result must be reported in, using
  aliases such as ``m``/``metres``/``meters`` or ``ft``/``feet``. For ``area`` the
  unit should be an area unit (``sq metres``, ``acres``, ``hectares``); for other
  metric operations it should be a linear unit. Mismatched units fail unless
  ``unit_conversion`` is declared.

Rule summary
------------

* ``preflight.metric_crs`` — a metric ``operation`` on a geographic/geocentric CRS,
  unless ``reproject`` is declared to ``target_crs``.
* ``preflight.alignment`` — ``combine`` inputs that differ in CRS or grid (including
  rotation/shear) without ``alignment`` declared.
* ``preflight.categorical_resampling`` — ``categorical`` raster with a resampling
  method other than ``nearest``/``mode``.
* ``preflight.reflectance_decode`` — ``expect`` reflectance on encoded/integer DN
  without a declared ``decode`` step.
* ``preflight.temporal_scope`` — ``time_range`` incompatible with the datetimes of
  the supplied STAC items. Bounds are inclusive; an interval passes only when its
  whole span is inside the range.
* ``preflight.index_inputs`` — ``expect`` index on encoded/integer DN without a
  declared ``decode`` step.
* ``preflight.output_units`` — ``operation`` metric with ``target_crs`` units
  incompatible with ``measurement_units``.

Missing facts produce ``not-run`` or ``warn`` outcomes; the checks never fabricate a
pass.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from pyproj import CRS

from terraproof._common import InputError, crs_summary
from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, CheckResult, result
from terraproof.checks.raster import GRID_TOLERANCE, SAFE_CATEGORICAL_METHODS, check_grid_alignment

_OPERATIONS = frozenset({"buffer", "distance", "area", "length"})
_EXPECTS = frozenset({"reflectance", "index"})


def _label(dataset: dict) -> str:
    return dataset.get("path", "(dataset)")


def _is_metric_or_foot(units: str | None) -> bool:
    lowered = (units or "").lower()
    return any(word in lowered for word in ("metre", "meter", "foot", "feet"))


def _parse_crs_value(value: Any) -> dict:
    """Parse a plan target_crs value into a crs_summary dictionary."""
    if value is None:
        raise InputError("target_crs value is null")
    if isinstance(value, str):
        crs = CRS.from_user_input(value)
    elif isinstance(value, dict):
        if "epsg" in value:
            crs = CRS.from_epsg(int(value["epsg"]))
        elif "wkt" in value:
            crs = CRS.from_wkt(str(value["wkt"]))
        elif "proj4" in value:
            crs = CRS.from_proj4(str(value["proj4"]))
        else:
            raise InputError("target_crs object must contain epsg, wkt, or proj4")
    else:
        raise InputError(f"target_crs must be a string or object, got {type(value).__name__}")
    summary = crs_summary(crs)
    if summary is None:
        raise InputError("could not summarise target_crs")
    return summary


def _parse_iso_time(value: Any, field: str) -> float:
    """Parse an ISO 8601 bound from the plan, rejecting invalid values."""
    if not isinstance(value, str):
        raise InputError(f"{field} must be an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InputError(f"{field} is not a valid ISO 8601 date-time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _validate_plan(plan: Any) -> dict:
    """Return a normalised plan dict, raising ``InputError`` for invalid values."""
    if not isinstance(plan, dict):
        raise InputError("plan must be a JSON object")

    allowed = {
        "operation",
        "target_crs",
        "reproject",
        "resampling",
        "categorical",
        "combine",
        "alignment",
        "decode",
        "encoding",
        "time_range",
        "expect",
        "measurement_units",
        "unit_conversion",
    }
    unknown = set(plan) - allowed
    if unknown:
        raise InputError(f"unknown plan field(s): {', '.join(sorted(unknown))}")

    normalised: dict = {}

    operation = plan.get("operation")
    if operation is not None and operation not in _OPERATIONS:
        raise InputError(f"operation must be one of {', '.join(sorted(_OPERATIONS))}, got {operation!r}")
    normalised["operation"] = operation

    target_crs = plan.get("target_crs")
    if target_crs is not None:
        normalised["target_crs"] = _parse_crs_value(target_crs)
    else:
        normalised["target_crs"] = None

    reproject = plan.get("reproject", False)
    if not isinstance(reproject, bool):
        raise InputError("reproject must be a boolean")
    normalised["reproject"] = reproject

    resampling = plan.get("resampling")
    if resampling is not None and not isinstance(resampling, str):
        raise InputError("resampling must be a string")
    normalised["resampling"] = resampling

    for boolean_field in ("categorical", "combine", "alignment", "decode"):
        value = plan.get(boolean_field, False)
        if not isinstance(value, bool):
            raise InputError(f"{boolean_field} must be a boolean")
        normalised[boolean_field] = value

    time_range = plan.get("time_range")
    if time_range is not None:
        if not isinstance(time_range, (list, tuple)) or len(time_range) != 2:
            raise InputError("time_range must be a list of two ISO 8601 strings")
        start = _parse_iso_time(time_range[0], "time_range start")
        end = _parse_iso_time(time_range[1], "time_range end")
        if start > end:
            raise InputError("time_range start is after its end")
        normalised["time_range"] = (start, end, list(time_range))
    else:
        normalised["time_range"] = None

    expect = plan.get("expect")
    if expect is not None and expect not in _EXPECTS:
        raise InputError(f"expect must be one of {', '.join(sorted(_EXPECTS))}, got {expect!r}")
    normalised["expect"] = expect

    encoding = plan.get("encoding")
    if encoding is not None and encoding not in ("s2-l2a", "landsat-c2-l2"):
        raise InputError(f"encoding must be 's2-l2a' or 'landsat-c2-l2', got {encoding!r}")
    normalised["encoding"] = encoding

    measurement_units = plan.get("measurement_units")
    if measurement_units is not None and not isinstance(measurement_units, str):
        raise InputError("measurement_units must be a string")
    normalised["measurement_units"] = measurement_units

    unit_conversion = plan.get("unit_conversion", False)
    if not isinstance(unit_conversion, bool):
        raise InputError("unit_conversion must be a boolean")
    normalised["unit_conversion"] = unit_conversion

    return normalised


def _georeferenced(datasets: list[dict]) -> list[dict]:
    return [d for d in datasets if d.get("kind") in ("vector", "raster")]


def _rasters(datasets: list[dict]) -> list[dict]:
    return [d for d in datasets if d.get("kind") == "raster"]


def _stac_items(datasets: list[dict]) -> list[dict]:
    return [d for d in datasets if d.get("kind") == "stac"]


def _integer_scaled_bands(datasets: list[dict]) -> tuple[list[tuple[str, int]], list[tuple[str, int, str]]]:
    """Return (integer-scaled bands, metadata problems).

    A band is integer-scaled when it is integer typed and has a non-identity
    scale or offset. Missing or broken metadata is reported as a problem so the
    caller can avoid fabricating a pass on inputs it cannot assess.
    """
    found = []
    problems = []
    for dataset in datasets:
        for band in dataset.get("bands", []):
            dtype_value = band.get("dtype")
            try:
                dtype = np.dtype(dtype_value or "")
            except (TypeError, ValueError):
                problems.append((_label(dataset), band.get("index", 1), f"invalid dtype: {dtype_value!r}"))
                continue

            scale = band.get("scale")
            offset = band.get("offset")
            if scale is None or offset is None:
                problems.append((_label(dataset), band.get("index", 1), "missing scale/offset metadata"))
                continue
            if not isinstance(scale, (int, float)) or not isinstance(offset, (int, float)):
                problems.append((_label(dataset), band.get("index", 1), f"non-numeric scale/offset: {scale!r}, {offset!r}"))
                continue
            if not math.isfinite(scale) or not math.isfinite(offset):
                problems.append((_label(dataset), band.get("index", 1), f"non-finite scale={scale}, offset={offset}"))
                continue

            if dtype.kind not in ("i", "u"):
                continue
            nontrivial = (scale not in (None, 1, 1.0)) or (offset not in (None, 0, 0.0))
            if nontrivial:
                found.append((_label(dataset), band.get("index", 1)))
    return found, problems


def _crs_kind_label(crs: dict | None) -> str:
    if crs is None:
        return "no CRS"
    return crs.get("horizontal_kind", "unknown")


def _metric_crs_result(
    datasets: list[dict],
    operation: str | None,
    reproject: bool,
    target_crs: dict | None,
) -> CheckResult:
    """Assess metric operations on geographic/geocentric CRS inputs.

    If ``reproject`` is declared together with ``target_crs``, the operation is
    assessed against ``target_crs`` rather than the original inputs.
    """
    georef = _georeferenced(datasets)
    if operation is None or not georef:
        return result(
            "preflight.metric_crs",
            NOT_RUN,
            "No metric operation or no georeferenced inputs; CRS suitability was not assessed." if operation is None
            else f"Operation '{operation}' declared, but no georeferenced inputs were supplied.",
            operation=operation,
            reproject=reproject,
            inputs=[_label(d) for d in georef],
        )

    if reproject:
        if target_crs is None:
            return result(
                "preflight.metric_crs",
                NOT_RUN,
                f"Operation '{operation}' declares reproject=true but no target_crs is given.",
                operation=operation,
                reproject=True,
                inputs=[_label(d) for d in georef],
            )
        status, message, evidence = _metric_crs_assessment(
            target_crs,
            f"Planned reprojection target for operation '{operation}'",
            operation=operation,
            reproject=True,
        )
        return result("preflight.metric_crs", status, message, **evidence)

    per_input = []
    any_fail = False
    any_warn = False
    any_not_run = False
    for dataset in georef:
        path = _label(dataset)
        crs = dataset.get("crs")
        if crs is None:
            any_not_run = True
            per_input.append({"input": path, "status": "not-run", "reason": "no CRS"})
            continue
        outcome = _crs_suitability(crs)
        per_input.append({"input": path, **outcome})
        if outcome["status"] == "fail":
            any_fail = True
        elif outcome["status"] == "warn":
            any_warn = True
        elif outcome["status"] == "not-run":
            any_not_run = True

    if any_fail:
        bad = [entry["input"] for entry in per_input if entry["status"] == "fail"]
        return result(
            "preflight.metric_crs",
            FAIL,
            f"Planned metric operation '{operation}' uses a geographic or geocentric CRS for: {', '.join(bad)}. "
            "Reproject to a projected CRS with metric or foot units before measuring.",
            operation=operation,
            reproject=reproject,
            inputs=[_label(d) for d in georef],
            per_input=per_input,
        )
    if any_warn:
        return result(
            "preflight.metric_crs",
            WARN,
            f"Planned metric operation '{operation}' has inputs whose CRS units cannot be confirmed as metric/foot.",
            operation=operation,
            reproject=reproject,
            inputs=[_label(d) for d in georef],
            per_input=per_input,
        )
    if any_not_run:
        return result(
            "preflight.metric_crs",
            NOT_RUN,
            f"Planned metric operation '{operation}', but some inputs have no CRS so suitability could not be assessed.",
            operation=operation,
            reproject=reproject,
            inputs=[_label(d) for d in georef],
            per_input=per_input,
        )
    return result(
        "preflight.metric_crs",
        PASS,
        f"Planned metric operation '{operation}' uses projected CRS inputs with suitable units.",
        operation=operation,
        reproject=reproject,
        inputs=[_label(d) for d in georef],
        per_input=per_input,
    )


def _crs_suitability(crs: dict) -> dict:
    """Return a suitability dict for a single CRS (status, kind, units, epsg)."""
    kind = crs.get("horizontal_kind")
    units = crs.get("horizontal_axis_units")
    evidence = {
        "horizontal_kind": kind,
        "horizontal_axis_units": units,
        "epsg": crs.get("epsg"),
    }
    if kind in ("geographic", "geocentric"):
        return {"status": "fail", **evidence}
    if kind == "projected" and _is_metric_or_foot(units):
        return {"status": "pass", **evidence}
    if kind == "projected":
        return {"status": "warn", **evidence}
    return {"status": "warn", **evidence}


def _metric_crs_assessment(crs: dict, label: str, **extra_evidence) -> tuple[str, str, dict]:
    """Return (status, message, evidence) for a single CRS used in a metric operation."""
    outcome = _crs_suitability(crs)
    evidence = dict(extra_evidence)
    evidence.update(
        {
            "target_crs": crs,
            "horizontal_kind": outcome["horizontal_kind"],
            "horizontal_axis_units": outcome["horizontal_axis_units"],
            "epsg": outcome["epsg"],
        }
    )
    if outcome["status"] == "fail":
        message = (
            f"{label} is {outcome['horizontal_kind']} (units: {outcome['horizontal_axis_units']}); "
            "metric distances/areas would be wrong."
        )
        return FAIL, message, evidence
    if outcome["status"] == "warn":
        message = (
            f"{label} uses units '{outcome['horizontal_axis_units']}'; confirm they are metric or foot-based."
        )
        return WARN, message, evidence
    message = f"{label} is projected in {outcome['horizontal_axis_units']}, suitable for metric measurement."
    return PASS, message, evidence


# Exact alias table: normalized unit string -> (conversion factor to SI metres or metres², is_area)
_UNIT_ALIASES = {
    # Linear
    "m": (1.0, False),
    "meter": (1.0, False),
    "meters": (1.0, False),
    "metre": (1.0, False),
    "metres": (1.0, False),
    "km": (1000.0, False),
    "kilometer": (1000.0, False),
    "kilometers": (1000.0, False),
    "kilometre": (1000.0, False),
    "kilometres": (1000.0, False),
    "ft": (0.3048, False),
    "foot": (0.3048, False),
    "feet": (0.3048, False),
    "ft us": (0.3048006096, False),
    "us survey foot": (0.3048006096, False),
    "us survey feet": (0.3048006096, False),
    "survey foot": (0.3048006096, False),
    "mi": (1609.344, False),
    "mile": (1609.344, False),
    "miles": (1609.344, False),
    "yd": (0.9144, False),
    "yard": (0.9144, False),
    "yards": (0.9144, False),
    # Area
    "m2": (1.0, True),
    "m 2": (1.0, True),
    "sq m": (1.0, True),
    "sq meter": (1.0, True),
    "sq meters": (1.0, True),
    "sq metre": (1.0, True),
    "sq metres": (1.0, True),
    "square m": (1.0, True),
    "square meter": (1.0, True),
    "square meters": (1.0, True),
    "square metre": (1.0, True),
    "square metres": (1.0, True),
    "ft2": (0.09290304, True),
    "sq ft": (0.09290304, True),
    "sq foot": (0.09290304, True),
    "sq feet": (0.09290304, True),
    "square ft": (0.09290304, True),
    "square foot": (0.09290304, True),
    "square feet": (0.09290304, True),
    "km2": (1_000_000.0, True),
    "sq km": (1_000_000.0, True),
    "square km": (1_000_000.0, True),
    "square kilometer": (1_000_000.0, True),
    "square kilometers": (1_000_000.0, True),
    "ha": (10_000.0, True),
    "hectare": (10_000.0, True),
    "hectares": (10_000.0, True),
    "acre": (4046.8564224, True),
    "acres": (4046.8564224, True),
    "mi2": (2_589_988.110336, True),
    "sq mi": (2_589_988.110336, True),
    "square mi": (2_589_988.110336, True),
    "square mile": (2_589_988.110336, True),
    "square miles": (2_589_988.110336, True),
}


def _normalise_unit_text(text: str) -> str:
    """Collapse spacing and punctuation; preserve exact words for alias lookup."""
    lowered = text.lower()
    for char in "-_^²":
        lowered = lowered.replace(char, " ")
    lowered = lowered.replace("2", " 2 ")
    return " ".join(lowered.split())


def _parse_measurement_units(text: str | None) -> tuple[float, bool, bool]:
    """Return (factor_in_metres_or_metres2, is_area, is_known) for a unit string."""
    if not text:
        return 0.0, False, False
    canonical = _normalise_unit_text(text)
    if canonical in _UNIT_ALIASES:
        factor, is_area = _UNIT_ALIASES[canonical]
        return factor, is_area, True
    return 0.0, False, False


def _crs_axis_conversion_factor(crs: dict) -> float | None:
    """Return the horizontal axis conversion factor to metres from a crs_summary dict."""
    wkt = crs.get("wkt")
    if not wkt:
        return None
    try:
        parsed = CRS.from_wkt(wkt)
    except Exception:
        return None
    horizontal = parsed
    if parsed.is_compound:
        for component in parsed.sub_crs_list:
            if not component.is_vertical:
                horizontal = component
                break
    if not horizontal.axis_info:
        return None
    return horizontal.axis_info[0].unit_conversion_factor


def _output_units_result(
    operation: str | None,
    target_crs: dict | None,
    measurement_units: str | None,
    unit_conversion: bool,
) -> CheckResult:
    """Assess whether the target CRS units fit the requested measurement units."""
    if operation is None or target_crs is None:
        return result(
            "preflight.output_units",
            NOT_RUN,
            "No operation or target_crs declared; output unit compatibility was not assessed.",
            operation=operation,
            target_crs=target_crs,
        )
    if not measurement_units:
        return result(
            "preflight.output_units",
            NOT_RUN,
            "No measurement_units declared; cannot confirm target CRS units match the requested units.",
            operation=operation,
            target_crs=target_crs,
        )

    requested_factor, requested_area, requested_known = _parse_measurement_units(measurement_units)
    target_factor = _crs_axis_conversion_factor(target_crs)
    operation_is_area = operation == "area"
    evidence = {
        "operation": operation,
        "target_crs": target_crs,
        "measurement_units": measurement_units,
        "unit_conversion": unit_conversion,
        "requested_factor": requested_factor,
        "requested_area": requested_area,
        "target_axis_factor": target_factor,
    }

    target_kind = target_crs.get("horizontal_kind")
    if target_kind in ("geographic", "geocentric"):
        return result(
            "preflight.output_units",
            FAIL,
            f"Target CRS is {target_kind}; results would be in degrees or Earth-centred "
            f"Cartesian units, not in the requested '{measurement_units}'.",
            **evidence,
        )

    if not requested_known:
        return result(
            "preflight.output_units",
            WARN,
            f"Requested measurement units '{measurement_units}' are not recognised; "
            "confirm they are compatible with the target CRS before reporting.",
            **evidence,
        )

    if requested_area != operation_is_area:
        dimension = "area" if requested_area else "linear"
        expected = "area units (e.g. sq metres, acres, hectares)" if operation_is_area else "linear units (e.g. metres, feet)"
        return result(
            "preflight.output_units",
            WARN,
            f"Operation '{operation}' expects {expected}, but '{measurement_units}' looks like {dimension} units.",
            **evidence,
        )

    if target_factor is None:
        return result(
            "preflight.output_units",
            WARN,
            "Target CRS axis conversion factor is not available; confirm it matches the requested units.",
            **evidence,
        )

    # Compare linear factors. For area units the equivalent linear factor is sqrt(area_factor).
    requested_linear_factor = math.sqrt(requested_factor) if requested_area else requested_factor
    tolerance = 1e-9 * max(requested_linear_factor, target_factor, 1.0)
    factors_match = abs(requested_linear_factor - target_factor) <= tolerance

    if not factors_match:
        if unit_conversion:
            return result(
                "preflight.output_units",
                PASS,
                f"Target CRS axis factor ({target_factor:.6g} m) differs from requested '{measurement_units}' "
                "but unit_conversion is declared.",
                **evidence,
            )
        return result(
            "preflight.output_units",
            FAIL,
            f"Target CRS axis factor ({target_factor:.6g} m) is incompatible with requested "
            f"'{measurement_units}'. Declare unit_conversion or choose a matching target CRS.",
            **evidence,
        )

    return result(
        "preflight.output_units",
        PASS,
        f"Target CRS axis factor ({target_factor:.6g} m) is compatible with requested '{measurement_units}'.",
        **evidence,
    )


def _same_crs(first: dict, second: dict) -> bool:
    first_crs = first.get("crs")
    second_crs = second.get("crs")
    if first_crs is None or second_crs is None:
        return first_crs is None and second_crs is None
    return CRS.from_user_input(first_crs["wkt"]).equals(CRS.from_user_input(second_crs["wkt"]))


def _valid_affine(transform: list) -> tuple[bool, str]:
    """Check that a 6-element GeoTransform is finite and invertible."""
    if not isinstance(transform, (list, tuple)) or len(transform) != 6:
        return False, "missing or malformed transform"
    a, b, _, d, e, _ = transform
    if not all(math.isfinite(x) for x in transform):
        return False, "non-finite transform coefficients"
    det = a * e - b * d
    if det == 0:
        return False, "singular (non-invertible) transform"
    if a == 0 or e == 0:
        return False, "zero pixel size"
    return True, ""


def _rotation_shear_problems(rasters: list[dict]) -> list[str]:
    """Detect rotation or shear by comparing off-diagonal transform terms."""
    if len(rasters) < 2:
        return []
    problems = []
    ref_transform = rasters[0].get("transform")
    ref_ok, ref_reason = _valid_affine(ref_transform)
    if not ref_ok:
        problems.append(f"{_label(rasters[0])} has an invalid transform ({ref_reason})")
        return problems
    ref_b, ref_d = ref_transform[1], ref_transform[3]
    for other in rasters[1:]:
        other_transform = other.get("transform")
        other_ok, other_reason = _valid_affine(other_transform)
        if not other_ok:
            problems.append(f"{_label(other)} has an invalid transform ({other_reason})")
            continue
        if (
            abs(other_transform[1] - ref_b) > GRID_TOLERANCE * max(abs(ref_b), abs(other_transform[1]), 1.0)
            or abs(other_transform[3] - ref_d) > GRID_TOLERANCE * max(abs(ref_d), abs(other_transform[3]), 1.0)
        ):
            problems.append(f"rotation/shear of {_label(other)} differs from {_label(rasters[0])}")
    return problems


def _raster_grid_problems(rasters: list[dict]) -> list[str]:
    """Assess raster grid alignment using the existing raster check plus rotation/shear."""
    if len(rasters) < 2:
        return []
    grid_results = check_grid_alignment(rasters)
    problems = list(grid_results[0].evidence.get("problems", [])) if grid_results else []
    problems.extend(_rotation_shear_problems(rasters))
    return problems


def _alignment_result(datasets: list[dict], combine: bool, alignment: bool) -> CheckResult:
    """Assess combining inputs that differ in CRS or grid without an alignment step."""
    georef = _georeferenced(datasets)
    if not combine:
        return result(
            "preflight.alignment",
            NOT_RUN,
            "No combine step declared; alignment was not assessed.",
            combine=False,
            alignment=False,
            inputs=[_label(d) for d in georef],
        )
    if len(georef) < 2:
        return result(
            "preflight.alignment",
            NOT_RUN,
            "Combine declared, but fewer than two georeferenced inputs were supplied.",
            combine=True,
            alignment=alignment,
            inputs=[_label(d) for d in georef],
        )

    missing_crs = [d for d in georef if d.get("crs") is None]
    if missing_crs:
        return result(
            "preflight.alignment",
            NOT_RUN,
            "Combine declared, but some inputs have no CRS so alignment cannot be assessed: "
            + ", ".join(_label(d) for d in missing_crs) + ".",
            combine=True,
            alignment=alignment,
            inputs=[_label(d) for d in georef],
        )

    rasters = [d for d in georef if d.get("kind") == "raster"]

    invalid_transforms = []
    for raster in rasters:
        transform = raster.get("transform")
        ok, reason = _valid_affine(transform)
        if not ok:
            invalid_transforms.append(f"{_label(raster)}: {reason}")
    if invalid_transforms:
        return result(
            "preflight.alignment",
            NOT_RUN,
            "Combine declared, but some raster transforms are invalid or missing: " + "; ".join(invalid_transforms),
            combine=True,
            alignment=alignment,
            inputs=[_label(d) for d in georef],
            invalid_transforms=invalid_transforms,
        )

    crs_problems = []
    reference = georef[0]
    for other in georef[1:]:
        if not _same_crs(reference, other):
            crs_problems.append(f"CRS of {_label(other)} differs from {_label(reference)}")

    grid_problems = _raster_grid_problems(rasters)
    problems = crs_problems + grid_problems

    evidence = {
        "combine": True,
        "alignment": alignment,
        "inputs": [_label(d) for d in georef],
        "reference": _label(reference),
        "crs_problems": crs_problems,
        "grid_problems": grid_problems,
        "problems": problems,
    }

    if alignment:
        # An explicit alignment step is part of the declared plan, so observed
        # mismatches are expected to be resolved before the data is combined.
        if problems:
            message = (
                "Combine and alignment are declared; the plan includes an alignment step before combining. "
                "Observed mismatches that the alignment must resolve: " + "; ".join(problems) + "."
            )
        else:
            message = "Combine and alignment are declared, and all georeferenced inputs already share CRS and grid alignment."
        return result("preflight.alignment", PASS, message, **evidence)

    if problems:
        return result(
            "preflight.alignment",
            FAIL,
            "Combine declared without alignment, but inputs are not aligned: " + "; ".join(problems) + ".",
            **evidence,
        )
    return result(
        "preflight.alignment",
        PASS,
        "Combine declared without alignment, but all georeferenced inputs share CRS and (for rasters) grid alignment.",
        **evidence,
    )


def _categorical_resampling_result(
    datasets: list[dict], categorical: bool, resampling: str | None
) -> CheckResult:
    """Assess resampling choice for categorical rasters."""
    rasters = _rasters(datasets)
    if not categorical:
        return result(
            "preflight.categorical_resampling",
            NOT_RUN,
            "Rasters are not declared categorical; resampling method was not assessed.",
            categorical=False,
            resampling=resampling,
            inputs=[_label(d) for d in rasters],
        )
    if not rasters:
        return result(
            "preflight.categorical_resampling",
            NOT_RUN,
            "Categorical raster declared, but no raster inputs were supplied.",
            categorical=True,
            resampling=resampling,
            inputs=[],
        )
    if resampling is None:
        return result(
            "preflight.categorical_resampling",
            NOT_RUN,
            "Categorical raster declared, but no resampling method was supplied.",
            categorical=True,
            resampling=None,
            inputs=[_label(d) for d in rasters],
        )

    evidence = {
        "categorical": True,
        "resampling": resampling,
        "inputs": [_label(d) for d in rasters],
    }
    if resampling.lower() in SAFE_CATEGORICAL_METHODS:
        return result(
            "preflight.categorical_resampling",
            PASS,
            f"Resampling '{resampling}' is suitable for categorical rasters.",
            **evidence,
        )
    return result(
        "preflight.categorical_resampling",
        FAIL,
        f"Resampling '{resampling}' blends category codes. Use 'nearest' or 'mode' for categorical rasters.",
        **evidence,
    )


def _decode_assessment(
    rasters: list[dict],
    decode: bool,
    encoding: str | None,
    purpose: str,
) -> tuple[str, str, dict]:
    """Return (status, message, evidence) for reflectance/index decode checks.

    A pass is only justified when a decode step is explicitly declared, or when an
    explicit safe input source leaves no doubt the values are already physical. In
    all other cases the check returns ``not-run`` or ``fail`` rather than fabricating
    a pass.
    """
    integer_scaled, nonfinite = _integer_scaled_bands(rasters)
    evidence = {
        "decode": decode,
        "encoding": encoding,
        "inputs": [_label(d) for d in rasters],
        "integer_scaled_bands": integer_scaled,
        "nonfinite_metadata": nonfinite,
    }

    if nonfinite:
        listed = ", ".join(f"{path} band {index}" for path, index, _ in nonfinite)
        message = f"Non-finite scale/offset metadata on {listed}; cannot assess whether {purpose} needs decoding."
        return WARN, message, evidence

    if decode:
        if integer_scaled:
            message = f"Integer DN bands with scale/offset are present and a decode step is declared before {purpose}."
        else:
            message = f"A decode step is declared before {purpose}."
        return PASS, message, evidence

    if integer_scaled:
        listed = ", ".join(f"{path} band {index}" for path, index in integer_scaled)
        message = (
            f"Integer DN bands with scale/offset are present ({listed}) but no decode step is declared. "
            f"Decode to physical values before {purpose}."
        )
        return FAIL, message, evidence

    if encoding:
        message = (
            f"Product encoding '{encoding}' is declared, but no decode step is listed and the bands do not "
            f"carry scale/offset metadata; cannot confirm whether {purpose} is safe."
        )
        return NOT_RUN, message, evidence

    message = (
        f"No decode step, product encoding, or scale/offset metadata; cannot confirm whether {purpose} is safe."
    )
    return NOT_RUN, message, evidence


def _reflectance_decode_result(
    datasets: list[dict], expect: str | None, decode: bool, encoding: str | None
) -> CheckResult:
    """Assess reflectance plans on encoded/integer DN without a decode step."""
    rasters = _rasters(datasets)
    if expect != "reflectance":
        return result(
            "preflight.reflectance_decode",
            NOT_RUN,
            "Expect is not 'reflectance'; decode step was not assessed.",
            expect=expect,
            decode=decode,
            encoding=encoding,
            inputs=[_label(d) for d in rasters],
        )
    if not rasters:
        return result(
            "preflight.reflectance_decode",
            NOT_RUN,
            "Expect reflectance declared, but no raster inputs were supplied.",
            expect=expect,
            decode=decode,
            encoding=encoding,
            inputs=[],
        )
    status, message, evidence = _decode_assessment(
        rasters, decode, encoding, "using the values as reflectance"
    )
    return result("preflight.reflectance_decode", status, message, **evidence)


def _index_inputs_result(
    datasets: list[dict], expect: str | None, decode: bool, encoding: str | None
) -> CheckResult:
    """Assess index plans on encoded/integer DN without a decode step."""
    rasters = _rasters(datasets)
    if expect != "index":
        return result(
            "preflight.index_inputs",
            NOT_RUN,
            "Expect is not 'index'; input decoding was not assessed.",
            expect=expect,
            decode=decode,
            encoding=encoding,
            inputs=[_label(d) for d in rasters],
        )
    if not rasters:
        return result(
            "preflight.index_inputs",
            NOT_RUN,
            "Expect index declared, but no raster inputs were supplied.",
            expect=expect,
            decode=decode,
            encoding=encoding,
            inputs=[],
        )
    status, message, evidence = _decode_assessment(
        rasters, decode, encoding, "computing spectral indices"
    )
    return result("preflight.index_inputs", status, message, **evidence)


def _stac_time_bounds(item: dict) -> tuple[float | None, float | None, str | None]:
    """Return (low, high, error) for a STAC item's acquisition time."""
    if item.get("datetime") is not None:
        try:
            low = _parse_iso_time(item["datetime"], "datetime")
        except InputError as exc:
            return None, None, str(exc)
        return low, low, None
    if item.get("start_datetime") is not None and item.get("end_datetime") is not None:
        try:
            low = _parse_iso_time(item["start_datetime"], "start_datetime")
            high = _parse_iso_time(item["end_datetime"], "end_datetime")
        except InputError as exc:
            return None, None, str(exc)
        if low > high:
            return None, None, "inverted interval: start_datetime is after end_datetime"
        return low, high, None
    return None, None, "no datetime or start/end_datetime"


def _temporal_scope_result(datasets: list[dict], time_range: tuple | None) -> CheckResult:
    """Assess declared time range against STAC item datetimes."""
    stac = _stac_items(datasets)
    if time_range is None:
        return result(
            "preflight.temporal_scope",
            NOT_RUN,
            "No time_range declared; temporal coverage was not assessed.",
            time_range=None,
            inputs=[_label(d) for d in stac],
        )
    start, end, original = time_range
    evidence_common = {
        "time_range": original,
        "inputs": [_label(d) for d in stac],
    }
    if not stac:
        return result(
            "preflight.temporal_scope",
            NOT_RUN,
            f"Time range {original[0]}..{original[1]} declared, but no STAC items were supplied.",
            **evidence_common,
        )

    out_of_range = []
    undated = []
    invalid_intervals = []
    inside = []
    for item in stac:
        low, high, error = _stac_time_bounds(item)
        record = {
            "item": _label(item),
            "id": item.get("id"),
            "datetime": item.get("datetime"),
            "start_datetime": item.get("start_datetime"),
            "end_datetime": item.get("end_datetime"),
        }
        if error:
            if "inverted interval" in error:
                invalid_intervals.append({"record": record, "reason": error})
            else:
                undated.append({"record": record, "reason": error})
            continue
        if low < start or high > end:
            out_of_range.append(record)
        else:
            inside.append(record)

    evidence = dict(evidence_common)
    evidence.update({
        "inside_range": inside,
        "out_of_range": out_of_range,
        "items_without_time": undated,
        "invalid_intervals": invalid_intervals,
    })

    if invalid_intervals:
        listed = ", ".join(record["record"]["item"] for record in invalid_intervals)
        return result(
            "preflight.temporal_scope",
            FAIL,
            f"{len(invalid_intervals)} of {len(stac)} STAC items have an inverted acquisition interval: {listed}.",
            **evidence,
        )

    if out_of_range:
        listed = ", ".join(
            f"{record['id'] or record['item']} ({record['datetime'] or record['start_datetime']})"
            for record in out_of_range
        )
        return result(
            "preflight.temporal_scope",
            FAIL,
            f"{len(out_of_range)} of {len(stac)} STAC items fall outside {original[0]}..{original[1]}: {listed}.",
            **evidence,
        )
    if undated:
        listed = ", ".join(record["record"]["item"] for record in undated)
        return result(
            "preflight.temporal_scope",
            NOT_RUN,
            f"{len(inside)} items are inside {original[0]}..{original[1]}, but {len(undated)} items have "
            f"no usable acquisition time and could not be confirmed: {listed}.",
            **evidence,
        )
    return result(
        "preflight.temporal_scope",
        PASS,
        f"All {len(stac)} STAC items lie inside {original[0]}..{original[1]}.",
        **evidence,
    )


def run_preflight(datasets: list[dict], plan: Any) -> list[CheckResult]:
    """Run the seven preflight checks for ``datasets`` and the given ``plan``.

    ``plan`` may be the dict read from a JSON plan file. Invalid plan values raise
    ``InputError`` so the caller can turn them into a usage-level failure.
    """
    validated = _validate_plan(plan)

    results: list[CheckResult] = []
    if validated["operation"] is not None:
        results.append(
            _metric_crs_result(
                datasets,
                validated["operation"],
                validated["reproject"],
                validated["target_crs"],
            )
        )
    if validated["combine"]:
        results.append(_alignment_result(datasets, validated["combine"], validated["alignment"]))
    if validated["categorical"]:
        results.append(_categorical_resampling_result(datasets, validated["categorical"], validated["resampling"]))
    if validated["expect"] == "reflectance":
        results.append(
            _reflectance_decode_result(
                datasets, validated["expect"], validated["decode"], validated["encoding"]
            )
        )
    if validated["time_range"] is not None:
        results.append(_temporal_scope_result(datasets, validated["time_range"]))
    if validated["expect"] == "index":
        results.append(
            _index_inputs_result(
                datasets, validated["expect"], validated["decode"], validated["encoding"]
            )
        )
    if validated["operation"] is not None and validated["target_crs"] is not None:
        results.append(
            _output_units_result(
                validated["operation"],
                validated["target_crs"],
                validated["measurement_units"],
                validated["unit_conversion"],
            )
        )
    # Deterministic order: stable by check id.
    return sorted(results, key=lambda r: r.id)
