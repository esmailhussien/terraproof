#!/usr/bin/env python3
"""Phase 7 V4b: measure the fixed configuration once on the sealed V0b cases.

    python tests/phase7_v4b.py GENERATED_DIR --out v4b.json

GENERATED_DIR is the output of `evals/verification-heldout-v0b/generate.py`. Each case's `declared`
block becomes Terraproof arguments by one rule per declared `operation` (`declare` below), committed
before any V4b result was seen. A fact the declaration does not state is never supplied: in
particular, a height whose vertical unit is not declared gets no unit, so its requirement is
incomplete rather than assumed. `pass_through_verification` cases declare no requirement. Every case
also runs undeclared. Ground truth is each case's `kind`, confirmed by the held-out oracle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase7_v4 as v4  # noqa: E402  (shared contract, inspection and summary helpers)

from terraproof.checks import run_checks  # noqa: E402
from terraproof.evidence import build_report, input_record  # noqa: E402
from terraproof.inspect import inspect_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "verification-heldout-v0b" / "cases.json"


def declare(case: dict, base: Path) -> tuple[dict, list | None, list[str], list[str]]:
    d = case["declared"]
    op = d.get("operation")
    primary = str(base / d["primary_source"])
    untranslated: list[str] = []
    notes: list[str] = []
    if op in ("polygon_area_calculation", "geodesic_length_calculation"):
        quantity = "area" if op == "polygon_area_calculation" else "length"
        return (dict(metric_quantity=quantity, metric_property=d["metric_property_name"], metric_unit=d["metric_unit"]),
                ["metric-values"], untranslated, notes)
    if op == "line_buffer_generation":
        return (dict(metric_quantity="buffer", buffer_distance_m=d["buffer_distance_m"], buffer_source=primary),
                ["metric-values"], untranslated, notes)
    if op in ("qa_class_masking", "qa_bitmask_filtering"):
        qa = base / d["qa_layer"]
        if "valid_qa_classes" in d:
            keep = list(d["valid_qa_classes"])
        else:
            mask = sum(1 << bit for bit in d["invalid_bit_indices"])
            keep = [code for code in v4._codes(qa) if not code & mask]
            notes.append("keep codes derived from the declared invalid bits and the QA layer's codes")
        return (dict(qa_path=str(qa), qa_kind="keep-codes", qa_keep_codes=keep, qa_source=primary,
                     processing_full_scan=True), ["qa-masked"], untranslated, notes)
    if op == "terrain_slope_calculation":
        return dict(dem=primary, dem_vertical_unit=d["declared_vertical_unit"]), ["slope-from-dem"], untranslated, notes
    if op in ("geoid_height_correction", "sounding_to_elevation", "unit_conversion"):
        unit = d.get("target_vertical_unit")
        source_unit = d.get("source_vertical_unit")
        if op == "geoid_height_correction" and "secondary_source" in d:
            args = dict(vertical_operation="difference", vertical_sources=[primary, str(base / d["secondary_source"])])
            units = [source_unit, source_unit]  # the geoid grid's unit is not declared separately either
        elif op == "geoid_height_correction":
            args = dict(vertical_operation="minus-level", vertical_sources=[primary],
                        vertical_level=d["geoid_undulation_m"])
            units = [source_unit]
            untranslated.append("geoid_undulation_m unit (metres by name) applies only if the heights are metres")
        elif op == "sounding_to_elevation":
            args = dict(vertical_operation="depth-to-elevation", vertical_sources=[primary])
            units = [source_unit]
        else:
            args = dict(vertical_operation="convert", vertical_sources=[primary])
            units = [source_unit]
            untranslated.append("conversion_factor")  # implied by the declared units
        if all(units):
            args["vertical_source_units"] = units
        else:
            untranslated.append("source vertical unit (not declared)")
        if unit:
            args["vertical_unit"] = unit
        else:
            untranslated.append("target vertical unit (not declared)")
        return args, ["vertical-units"], untranslated, notes
    if op == "nodata_handling":
        return (dict(support_sources=[primary], support_source_nodata=[d["fill_value"]], support_rule="all"),
                ["nodata-support"], untranslated, notes)
    if op == "scale_and_offset_unpacking":
        args = dict(reference_input=primary, decode_scale=d["scale_factor"], decode_offset=d["add_offset"],
                    processing_full_scan=True)
        if d.get("physical_quantity") == "surface_reflectance":
            args["expect"] = "reflectance"
            return args, ["scaled-reflectance"], untranslated, notes
        return args, ["rs.scale_applied_once"], untranslated, notes
    if op == "pass_through_verification":
        return {}, None, [], ["no requirement declared"]
    return {}, None, ["operation"], notes


def _inspect_arguments(args: dict) -> dict:
    out = v4._inspect_arguments(args)
    if "buffer_source" in out:
        out["buffer_source"] = inspect_dataset(out["buffer_source"])
    return out


def run_case(case: dict, base: Path, declared: bool) -> dict:
    output = str(base / case["output"])
    dataset = inspect_dataset(output)
    args, requirement, untranslated, notes = declare(case, base) if declared else ({}, None, [], [])
    results = run_checks([dataset], **_inspect_arguments(args))
    report = build_report(inputs=[input_record(output, "input", dataset["kind"])], results=results,
                          parameters=dict(args), contract=v4._contract([output], requirement, args))
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
    rows = [{"id": case["id"], "family": case["family"], "kind": case["kind"],
             "operation": case["declared"].get("operation"),
             "declared": run_case(case, generated, True), "undeclared": run_case(case, generated, False)}
            for case in cases]
    return {"cases": rows, "summary": {mode: v4.summarize(rows, mode) for mode in ("declared", "undeclared")}}


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
