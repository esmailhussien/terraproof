#!/usr/bin/env python3
"""Phase 7 V4: measure the declared-coverage configuration once on the sealed held-out cases.

    python tests/phase7_v4.py GENERATED_DIR --out v4.json

GENERATED_DIR is the output of `evals/verification-heldout/generate.py`. Each case's `declared` block
is translated into Terraproof arguments by one rule per declared `operation` (`declare` below), fixed
before any result was seen. A declared fact that no Terraproof argument can express is not
translated; the case then runs with what can be declared, or with no requirement at all, and is
counted as such. Every case also runs undeclared, with no arguments and no contract.

Ground truth is the case's `kind`, which the held-out oracle confirms. The production grade is never
ground truth.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from terraproof.checks import run_checks  # noqa: E402
from terraproof.evidence import build_report, input_record  # noqa: E402
from terraproof.evidence.contract import SCHEMA, profile_contract  # noqa: E402
from terraproof.inspect import inspect_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "verification-heldout" / "cases.json"
METRIC_OPERATIONS = {"polygon_area_calculation": "area", "line_buffer_generation": "buffer",
                     "geodesic_length_calculation": "length"}


def _codes(path: Path) -> list[int]:
    with rasterio.open(path) as src:
        return sorted(int(code) for code in np.unique(src.read(1)))


def declare(case: dict, base: Path) -> tuple[dict, list | None, list[str], list[str]]:
    """(arguments, profiles or explicit checks, untranslated declared facts, notes) for one case."""
    d = case["declared"]
    op = d.get("operation")
    primary = str(base / d["primary_source"])
    args: dict = {}
    untranslated: list[str] = []
    notes: list[str] = []
    if op in ("dem_elevation_difference", "canopy_height_model"):
        # The primary surface minus the secondary, each in its declared unit.
        args = dict(vertical_operation="difference", vertical_sources=[primary, str(base / d["secondary_source"])],
                    vertical_source_units=[d["source_vertical_unit"], d["secondary_vertical_unit"]],
                    vertical_unit=d["target_vertical_unit"])
        return args, ["vertical-units"], untranslated, notes
    if op == "unit_conversion":
        args = dict(vertical_operation="convert", vertical_sources=[primary],
                    vertical_source_units=[d["source_vertical_unit"]], vertical_unit=d["target_vertical_unit"])
        untranslated.append("conversion_factor")  # implied by the declared units
        return args, ["vertical-units"], untranslated, notes
    if op == "geoid_height_correction":
        untranslated += ["source_datum", "target_datum", "geoid_undulation_m", "secondary_source"]
        notes.append("vertical datum transformations have no Terraproof argument")
        return args, None, untranslated, notes
    if op in ("qa_class_masking", "qa_bitmask_filtering"):
        qa = base / d["qa_layer"]
        if "valid_qa_classes" in d:
            keep = list(d["valid_qa_classes"])
        elif "invalid_bit_indices" in d:
            mask = sum(1 << bit for bit in d["invalid_bit_indices"])
            keep = [code for code in _codes(qa) if not code & mask]
            notes.append("keep codes derived from the declared invalid bits and the QA layer's codes")
        elif "valid_mandatory_qa_value" in d:
            keep = [code for code in _codes(qa) if code & 0b11 == d["valid_mandatory_qa_value"]]
            notes.append("keep codes derived from the declared mandatory-QA value (bits 0-1) and the QA layer's codes")
        else:
            return args, None, ["qa rule"], notes
        args = dict(qa_path=str(qa), qa_kind="keep-codes", qa_keep_codes=keep, processing_full_scan=True)
        return args, ["qa-masked"], untranslated, notes
    if op == "scale_and_offset_unpacking":
        args = dict(reference_input=primary, decode_scale=d["scale_factor"], decode_offset=d["add_offset"],
                    processing_full_scan=True)
        if d.get("physical_quantity") == "surface_reflectance":
            args["expect"] = "reflectance"
            return args, ["scaled-reflectance"], untranslated, notes
        return args, ["rs.scale_applied_once"], untranslated, notes
    if op == "nodata_handling":
        args = dict(support_sources=[primary], support_source_nodata=[d["fill_value"]], support_rule="all")
        return args, ["nodata-support"], untranslated, notes
    if op in METRIC_OPERATIONS:
        args = dict(operation=METRIC_OPERATIONS[op])
        untranslated += [key for key in ("intended_metric_crs", "metric_property_name", "buffer_distance_m")
                         if key in d]
        return args, ["metric-operation"], untranslated, notes
    if op == "terrain_slope_calculation":
        args = dict(dem=primary)
        untranslated.append("elevation_unit")  # no argument declares a DEM's vertical unit; the file's label is used
        return args, ["slope-from-dem"], untranslated, notes
    return args, None, ["operation"], notes


def _inspect_arguments(args: dict) -> dict:
    out = dict(args)
    for key in ("vertical_sources", "support_sources"):
        if key in out:
            out[key] = [inspect_dataset(path) for path in out[key]]
    for key in ("reference_input", "dem"):
        if key in out:
            out[key] = inspect_dataset(out[key])
    return out


def _contract(paths, requirement, args):
    if requirement is None:
        return None
    profiles = [name for name in requirement if "." not in name]
    checks = [name for name in requirement if "." in name]
    if profiles and not checks:
        return profile_contract(paths, profiles, args)
    group = {"paths": paths, "checks": checks, "parameters": {k: v for k, v in args.items() if v is not None}}
    if profiles:
        group["profiles"] = profiles
    return {"schema": SCHEMA, "requirements": [group]}


def run_case(case: dict, base: Path, declared: bool) -> dict:
    output = str(base / case["output"])
    dataset = inspect_dataset(output)
    args, requirement, untranslated, notes = declare(case, base) if declared else ({}, None, [], [])
    results = run_checks([dataset], **_inspect_arguments(args))
    report = build_report(inputs=[input_record(output, "input", dataset["kind"])], results=results,
                          parameters=dict(args), contract=_contract([output], requirement, args))
    required = {row["check"] for row in report.get("verification", {}).get("requirements", [])}
    return {
        "grade": report["grade"],
        "verification_status": report.get("verification", {}).get("status"),
        "required_checks": sorted(required),
        "check_statuses": sorted({(c["id"], c["status"]) for c in report["checks"]}),
        "required_fail": any(c["status"] == "fail" for c in report["checks"] if c["id"] in required),
        "any_fail": any(c["status"] == "fail" for c in report["checks"]),
        "missing_bindings": sorted({b for r in report.get("verification", {}).get("requirements", [])
                                    for b in r.get("missing_bindings", [])}),
        "untranslated": untranslated,
        "notes": notes,
    }


def measure(generated: Path) -> dict:
    document = json.loads(CASES.read_text(encoding="utf-8"))
    cases = document["cases"] if isinstance(document, dict) else document
    rows = []
    for case in cases:
        rows.append({"id": case["id"], "family": case["family"], "kind": case["kind"],
                     "operation": case["declared"].get("operation"),
                     "declared": run_case(case, generated, True), "undeclared": run_case(case, generated, False)})
    return {"cases": rows, "summary": {mode: summarize(rows, mode) for mode in ("declared", "undeclared")}}


def summarize(rows: list[dict], mode: str) -> dict:
    wrong = [r for r in rows if r["kind"] == "wrong"]
    correct = [r for r in rows if r["kind"] == "correct"]
    grade = lambda r: r[mode]["grade"]  # noqa: E731
    decision = [r for r in rows if grade(r) == "decision-grade"]
    covered = [r for r in rows if r[mode]["required_checks"]]
    return {
        "wrong": len(wrong), "correct": len(correct),
        "detection_any_fail": sum(r[mode]["any_fail"] for r in wrong),
        "detection_required_fail": sum(r[mode]["required_fail"] for r in wrong),
        "false_assurance_wrong_decision_grade": sum(grade(r) == "decision-grade" for r in wrong),
        "decision_grade_total": len(decision),
        "wrong_among_decision_grade": sum(r["kind"] == "wrong" for r in decision),
        "correct_with_a_fail": sum(r[mode]["any_fail"] for r in correct),
        "correct_review_required": sum(grade(r) == "review-required" for r in correct),
        "correct_advisory": sum(grade(r) == "advisory-only" for r in correct),
        "correct_decision_grade": sum(grade(r) == "decision-grade" for r in correct),
        "correct_checks_passed": sum(grade(r) == "checks-passed" for r in correct),
        "wrong_checks_passed": sum(grade(r) == "checks-passed" for r in wrong),
        "with_declared_requirements": len(covered),
        "incomplete": sum(r[mode]["verification_status"] == "incomplete" for r in rows),
        "by_family": {family: {
            "wrong_detected": sum(r[mode]["any_fail"] for r in rows if r["family"] == family and r["kind"] == "wrong"),
            "wrong_decision_grade": sum(grade(r) == "decision-grade" for r in rows
                                        if r["family"] == family and r["kind"] == "wrong"),
            "correct_decision_grade": sum(grade(r) == "decision-grade" for r in rows
                                          if r["family"] == family and r["kind"] == "correct"),
            "correct_with_a_fail": sum(r[mode]["any_fail"] for r in rows
                                       if r["family"] == family and r["kind"] == "correct"),
        } for family in sorted({r["family"] for r in rows})},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("generated", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = measure(args.generated.resolve())
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
