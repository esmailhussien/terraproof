"""Opt-in temporal-label check: rs.stack_window.

The output is labelled with a declared window (`stack_window`, start and end), and each ordered
`stack` layer with the interval it covers (`stack_times`, one ISO 8601 "START/END" each). Every
layer must lie inside the window and no two layers may overlap, so nothing outside the label or
counted twice reaches the output. For an accumulation (`stack_reduction` weighted-sum) the layers
must also cover the whole window without gaps, and each weight must equal its layer's duration in
hours. Times without a zone are UTC. The layer pixels are checked by rs.stack_reduction.
"""
from __future__ import annotations

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result
from terraproof.checks.rs_processing import _parse_time

CHECK_ID = "rs.stack_window"
HOUR = 3600.0
WEIGHT_RTOL = 1e-6


def _interval(text, field):
    if not isinstance(text, str) or text.count("/") != 1:
        return None, f"{field} '{text}' is not an ISO 8601 START/END interval"
    start, start_error = _parse_time(text.split("/")[0], field + " start")
    end, end_error = _parse_time(text.split("/")[1], field + " end")
    if start_error or end_error:
        return None, start_error or end_error
    if end <= start:
        return None, f"{field} '{text}' ends before it starts"
    return (start, end), None


def check_stack_window(output: dict, stack: list | None, stack_times: list | None, window: list | None,
                       reduction: str | None = None, weights: list | None = None) -> list:
    evidence = {"output": output.get("path"), "stack_window": window, "stack_times": stack_times,
                "reduction": reduction}
    missing = [key for key, value in (("stack", stack), ("stack_times", stack_times), ("stack_window", window))
               if not value]
    if missing:
        return [result(CHECK_ID, NOT_RUN, "Declare " + ", ".join(missing) + " to check the output's time label.",
                       missing_bindings=missing, **evidence)]
    if len(stack_times) != len(stack) or len(window) != 2:
        return [result(CHECK_ID, NOT_RUN, "Give one stack_times interval per stack layer and a two-bound "
                       "stack_window.", **evidence)]
    bounds, error = _interval("/".join(map(str, window)), "stack_window")
    layers = []
    for index, text in enumerate(stack_times):
        if error:
            break
        layer, error = _interval(text, f"stack_times[{index}]")
        layers.append(layer)
    if error:
        return [result(CHECK_ID, NOT_RUN, f"Cannot compare times: {error}.", **evidence)]
    start, end = bounds
    outside = [i for i, (a, b) in enumerate(layers) if a < start or b > end]
    ordered = sorted(range(len(layers)), key=lambda i: layers[i])
    overlaps = [[i, j] for i, j in zip(ordered, ordered[1:]) if layers[j][0] < layers[i][1]]
    problems = []
    if outside:
        problems.append(f"layers {outside} reach outside the window")
    if overlaps:
        problems.append(f"layer pairs {overlaps} overlap, so their time is counted twice")
    evidence.update(layers_outside=outside, overlapping_layers=overlaps)
    if reduction == "weighted-sum":
        gaps, cursor = [], start
        for i in ordered:
            if layers[i][0] > cursor:
                gaps.append([cursor, layers[i][0]])
            cursor = max(cursor, layers[i][1])
        if cursor < end:
            gaps.append([cursor, end])
        gap_hours = sum(b - a for a, b in gaps) / HOUR
        evidence["uncovered_hours"] = gap_hours
        if gaps:
            problems.append(f"{gap_hours:g} hours of the window are covered by no layer")
        if weights is not None:
            hours = [(b - a) / HOUR for a, b in layers]
            wrong = [i for i, (w, h) in enumerate(zip(weights, hours)) if abs(w - h) > WEIGHT_RTOL * h]
            evidence.update(layer_hours=hours, weights_not_matching_hours=wrong)
            if len(weights) != len(layers) or wrong:
                problems.append(f"weights of layers {wrong or 'all'} are not their durations in hours {hours}")
    if problems:
        return [result(CHECK_ID, FAIL, "The output's time label disagrees with its layers: " + "; ".join(problems) + ".",
                       **evidence)]
    return [result(CHECK_ID, PASS, f"All {len(layers)} layers lie inside the window without overlap"
                   + (", cover it fully, and are weighted by their hours." if reduction == "weighted-sum" else "."),
                   **evidence)]
