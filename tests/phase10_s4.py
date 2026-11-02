#!/usr/bin/env python3
"""Phase 10 S4.1: measure once on the sealed S0 real-data cases, in three configurations.

    python tests/phase10_s4.py CACHE_DIR DERIVED_DIR --out s4.json

CACHE_DIR is `evals/verification-heldout-s0/fetch.py`'s cache and DERIVED_DIR its `derive.py` output.
Committed before any S4.1 result was seen. Ground truth is each case's `kind`, confirmed by the bundle's
own oracle. The rules never read `kind`, `scenario`, `goal` or `oracle`: one rule per deliverable form,
from each case's `facts`, its sources, and the deliverable's own label. They were written from the bundle
README and a pooled view of the facts (keys, types, vocabularies; no ids or kinds), recorded in the plan.

- **declared**: what a careful user states.
  - validity mask: `qa-masked` with `output_form=validity-mask`, the facts' QA window as `qa_path`, its
    valid classes as keep codes, and the usable value.
  - slope raster (facts name a `source_dem`): `slope-from-dem` with that DEM, its vertical unit, and the
    slope unit the deliverable's label states (percent or degrees), else the facts' `slope_unit`.
  - other datasets: `scaled-reflectance` and `nodata-support` when the facts state the scale and that
    the offset is already applied; `vertical-units` and `nodata-support` when they state an elevation
    unit; otherwise a gap.
  - summary JSON: `summary-value` with one summary per expressible number in `report_numbers`. A number
    is expressible when its statistic maps; its key has no wildcard; its data names exactly one raw
    source file (never NDVI or a QA class); a reflectance number's source states its own scale; and
    its `mask` text is empty or a plain fill exclusion (the check always honours the source's nodata).
    `mask` text is never otherwise read. Other numbers stay undeclared, so the report can at best
    need review.
- **proposed**: the same profiles and the source paths (none for summaries); `propose_contract` fills
  the rest.
- **undeclared**: the output alone.

Acceptance, fixed in the plan, read per family in the declared configuration:
- S1 masks: every wrong mask fails a check, and at least half of the correct masks are decision-grade.
- S2 reprojected slopes: at least 80% of wrong ones fail ("4 of 5" in the plan; the set has 6 wrong, so
  5 of 6), and no correct one has a failing check.
- S3 reports: no declared number is not-run, every wrong report fails, and at least half of the correct
  reports are decision-grade.
Overall: zero false assurance in every configuration, zero false alarms within declared coverage, and no
metadata-filled binding that contradicts the declared value.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase7_v4 as v4  # noqa: E402  (shared contract and summary helpers)

from terraproof.checks import run_checks  # noqa: E402
from terraproof.evidence import build_report, input_record  # noqa: E402
from terraproof.evidence.contract import _missing_bindings, profiles as goal_profiles  # noqa: E402
from terraproof.evidence.propose import propose_contract  # noqa: E402
from terraproof.inspect import inspect_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "verification-heldout-s0" / "cases.json"
SOURCE_PATHS = ("reference_input", "dem", "vertical_sources", "support_sources", "qa_path", "qa_source")
UNITS = {"m": "metre", "metre": "metre"}
STATISTICS = {"mean": "mean", "mean_elevation_m": "mean", "maximum": "max", "max_elevation_m": "max",
              "minimum": "min", "min_elevation_m": "min", "count": "count", "sum": "sum", "area": "area",
              "length": "length", "share": "fraction"}
SUMMARY_UNITS = {"sq_km": "square_kilometre", "km": "kilometre", "fraction": "fraction", "percent": "percent"}
PLAIN_FILL = {"declared fill excluded", "declared fill 0 excluded", "declared fill -999999 excluded",
              "declared fill excluded, zeros kept"}
BANDS = {"blue": "B02", "green": "B03", "near-infrared": "B08"}
FAMILIES = {"qa_validity_masks": "S1", "reprojected_slopes": "S2", "multi_value_reports": "S3"}


def _cache_path(cache: Path, path: str) -> Path:
    return cache / path.removeprefix("cache/")


def _sources(case, cache: Path) -> list[Path]:
    return [_cache_path(cache, s["path"]) for s in case["sources"] if isinstance(s, dict) and isinstance(s.get("path"), str)]


def _same_grid(output: Path, rasters: list[Path]) -> Path | None:
    with rasterio.open(output) as dst:
        grid = (dst.width, dst.height, tuple(dst.transform), dst.crs)
    found = []
    for path in rasters:
        with rasterio.open(path) as src:
            if (src.width, src.height, tuple(src.transform), src.crs) == grid:
                found.append(path)
    return found[0] if len(found) == 1 else None


def _summary(key: str, spec: dict, sources: list[Path]):
    """One declared summary for an expressible report number, or None with the reason."""
    statistic = STATISTICS.get(spec.get("statistic"))
    data = str(spec.get("data", ""))
    if statistic is None:
        return None, "statistic not supported"
    if "[*]" in key:
        return None, "wildcard key"
    if "ndvi" in data.lower() or re.search(r"\bclass\b", data.lower()):  # not "classification"
        return None, "derived or class-restricted data"
    if spec.get("mask") not in (None, *PLAIN_FILL):
        return None, "selection the check cannot express"
    vectors = [p for p in sources if p.suffix in (".geojson", ".gpkg")]
    rasters = [p for p in sources if p.suffix == ".tif"]
    entry = {"key": key, "statistic": statistic}
    if statistic in ("area", "length") or (vectors and statistic == "count" and spec.get("unit") == "features"):
        if len(vectors) != 1:
            return None, "no single vector source"
        entry["source"] = str(vectors[0])
        first = data.split()[0] if data else ""
        if first[:1].isupper() and first not in ("Natural",):
            entry["feature"] = f"NAME={first}"
    else:
        lowered = data.lower()
        named = [p for p in rasters if any(word in lowered and code in p.name for word, code in BANDS.items())
                 or any(token in lowered and token in p.name.lower() for token in ("n22w159", "n31w091", "nepal"))
                 or ("window c" in lowered and p.name.startswith("wc_"))]
        chosen = named if named else (rasters if len(rasters) == 1 else [])
        if len(chosen) != 1:
            return None, "no single raster source"
        if spec.get("unit") == "reflectance":
            with rasterio.open(chosen[0]) as src:
                if src.scales[0] == 1.0 and src.offsets[0] == 0.0:
                    return None, "reflectance from a file that states no scale"
        entry["source"] = str(chosen[0])
    if statistic in ("area", "length", "fraction"):
        unit = SUMMARY_UNITS.get(spec.get("unit"))
        if unit is None:
            return None, "unit not supported"
        entry["unit"] = unit
    return entry, None


def declare(case: dict, cache: Path, derived: Path) -> dict:
    facts, output = case["facts"], derived / case["output"]["path"]
    form, label = case["deliverable_form"], case["output"].get("description", "").lower()
    sources = _sources(case, cache)
    rasters = [p for p in sources if p.suffix == ".tif"]
    plan = {"args": {}, "requirement": None, "stac": [], "gap": None, "form": form, "undeclared_numbers": {}}
    if form == "validity-mask":
        plan["args"] = dict(qa_path=str(_cache_path(cache, facts["pixel_qa_window"]["path"])), qa_kind="keep-codes",
                            qa_keep_codes=list(facts["pixel_qa_valid_classes"]), output_form="validity-mask",
                            output_valid_value=float(facts["mask_usable_value"]))
        plan["requirement"] = ["qa-masked"]
        return plan
    if form == "summary":
        entries = []
        for key, spec in (facts.get("report_numbers") or {}).items():
            entry, reason = _summary(key, spec, sources)
            if entry:
                entries.append(entry)
            else:
                plan["undeclared_numbers"][key] = reason
        if not entries:
            plan["gap"] = "no expressible report number"
            return plan
        plan["args"] = dict(summaries=entries)
        plan["requirement"] = ["summary-value"]
        return plan
    if "source_dem" in facts:
        unit = "percent" if "percent" in label else "degrees" if "degree" in label else facts.get("slope_unit")
        plan["args"] = dict(dem=str(_cache_path(cache, facts["source_dem"]["path"])),
                            dem_vertical_unit=UNITS[facts["elevation_unit"]],
                            slope_unit=None if unit == "degrees" else unit)
        plan["requirement"] = ["slope-from-dem"]
        return plan
    if "reflectance_scale" in facts:
        reference = _same_grid(output, rasters)
        if reference is None or not facts.get("reflectance_offset_applied_in_stored_values"):
            plan["gap"] = "reflectance without a same-grid source or an applied offset"
            return plan
        plan["args"] = dict(reference_input=str(reference), decode_scale=facts["reflectance_scale"],
                            decode_offset=0.0, processing_full_scan=True, expect="reflectance",
                            support_sources=[str(reference)], support_source_nodata=[float(facts["fill_value"])],
                            support_rule="all")
        plan["requirement"] = ["scaled-reflectance", "nodata-support"]
        return plan
    if "elevation_unit" in facts and rasters and "fill_value" in facts:
        unit = UNITS[facts["elevation_unit"]]
        plan["args"] = dict(vertical_operation="convert", vertical_sources=[str(rasters[0])],
                            vertical_source_units=[unit], vertical_unit=unit, support_sources=[str(rasters[0])],
                            support_source_nodata=[float(facts["fill_value"])], support_rule="all")
        plan["requirement"] = ["vertical-units", "nodata-support"]
        return plan
    plan["gap"] = "no rule"
    return plan


def _inspect_arguments(args: dict) -> dict:
    out = v4._inspect_arguments(args)
    if "summaries" in out:
        out["summaries"] = [dict(e, source=inspect_dataset(e["source"]),
                                 mask=inspect_dataset(e["mask"]) if e.get("mask") else None) for e in out["summaries"]]
    return out


def _required(requirement) -> list[str]:
    catalogue = goal_profiles()
    checks = sorted(set().union(*(set(catalogue[r]["checks"]) if r in catalogue else {r} for r in requirement)))
    return sorted({b for check in checks for b in _missing_bindings(check, {})} - {"processing_full_scan"})


def configure(plan: dict, mode: str, output: Path):
    if mode == "undeclared" or plan["requirement"] is None:
        return {}, None, None
    if mode == "declared":
        return plan["args"], plan["requirement"], None
    given = {k: v for k, v in plan["args"].items() if k in SOURCE_PATHS}
    names = [r for r in plan["requirement"] if r in goal_profiles()]
    proposal = propose_contract([str(output)], names, given, plan["stac"])
    return dict(proposal["contract"]["requirements"][0]["parameters"]), plan["requirement"], proposal


def run_case(case: dict, derived: Path, plan: dict, mode: str) -> dict:
    output = derived / case["output"]["path"]
    if not output.is_file():
        raise SystemExit(f"missing derived output {output}")
    args, requirement, proposal = configure(plan, mode, output)
    dataset = inspect_dataset(str(output))
    results = run_checks([dataset], **_inspect_arguments(args))
    report = build_report(inputs=[input_record(str(output), "input", dataset["kind"])], results=results,
                          parameters=dict(args), contract=v4._contract([str(output)], requirement, args))
    rows = report.get("verification", {}).get("requirements", [])
    required = {row["check"] for row in rows}
    summaries = [c for c in report["checks"] if c["id"] == "report.summary_value" and "summary_key" in c["evidence"]]
    row = {
        "grade": report["grade"],
        "verification_status": report.get("verification", {}).get("status"),
        "required_checks": sorted(required),
        "check_statuses": sorted({(c["id"], c["status"]) for c in report["checks"]}),
        "required_fail": any(c["status"] == "fail" for c in report["checks"] if c["id"] in required),
        "any_fail": any(c["status"] == "fail" for c in report["checks"]),
        "missing_bindings": sorted({b for r in rows for b in r.get("missing_bindings", [])}),
        "next_step": (report.get("next_step") or {}).get("profiles"),
        "declared_numbers_not_run": sorted(c["evidence"]["summary_key"] for c in summaries if c["status"] == "not-run"),
        "slope_comparison": next((c["evidence"].get("comparison", "same-grid") for c in report["checks"]
                                  if c["id"] == "terrain.slope_consistent"), None),
    }
    if proposal is not None:
        filled = [b for b in proposal["bindings"] if b["from"] == "metadata"]
        row["proposal"] = {
            "filled": {b["parameter"]: b["value"] for b in filled},
            "required": _required(requirement),
            "undeclared": sorted({u["parameter"] for u in proposal["undeclared"]}),
            "not_stated": sorted({n["parameter"] for n in proposal["not_stated"]}),
            "conflicts": sorted({c["parameter"] for c in proposal["conflicts"]}),
            "contradicting_truth": sorted(b["parameter"] for b in filled if b["parameter"] in plan["args"]
                                          and json.dumps(b["value"]) != json.dumps(plan["args"][b["parameter"]])),
        }
    return row


def acceptance(rows: list[dict]) -> dict:
    """The plan's per-direction acceptance, declared configuration, and the overall conditions."""
    def family(name, kind):
        return [r for r in rows if r["family"] == name and r["kind"] == kind]

    masks_wrong, masks_right = family("qa_validity_masks", "wrong"), family("qa_validity_masks", "correct")
    slopes_wrong, slopes_right = family("reprojected_slopes", "wrong"), family("reprojected_slopes", "correct")
    reports_wrong, reports_right = family("multi_value_reports", "wrong"), family("multi_value_reports", "correct")
    reports = reports_wrong + reports_right
    d = "declared"
    result = {
        "S1": {"wrong_failed": sum(r[d]["any_fail"] for r in masks_wrong), "wrong": len(masks_wrong),
               "correct_decision_grade": sum(r[d]["grade"] == "decision-grade" for r in masks_right),
               "correct": len(masks_right)},
        "S2": {"wrong_failed": sum(r[d]["any_fail"] for r in slopes_wrong), "wrong": len(slopes_wrong),
               "correct_with_a_fail": sum(r[d]["any_fail"] for r in slopes_right), "correct": len(slopes_right),
               "comparisons": sorted({r[d]["slope_comparison"] for r in slopes_wrong + slopes_right}, key=str)},
        "S3": {"declared_numbers_not_run": sum(len(r[d]["declared_numbers_not_run"]) for r in reports),
               "wrong_failed": sum(r[d]["any_fail"] for r in reports_wrong), "wrong": len(reports_wrong),
               "correct_decision_grade": sum(r[d]["grade"] == "decision-grade" for r in reports_right),
               "correct": len(reports_right)},
    }
    result["S1"]["met"] = (result["S1"]["wrong_failed"] == result["S1"]["wrong"]
                           and 2 * result["S1"]["correct_decision_grade"] >= result["S1"]["correct"])
    result["S2"]["met"] = (5 * result["S2"]["wrong_failed"] >= 4 * result["S2"]["wrong"]
                           and result["S2"]["correct_with_a_fail"] == 0)
    result["S3"]["met"] = (result["S3"]["declared_numbers_not_run"] == 0
                           and result["S3"]["wrong_failed"] == result["S3"]["wrong"]
                           and 2 * result["S3"]["correct_decision_grade"] >= result["S3"]["correct"])
    result["overall"] = {
        "false_assurance": {m: sum(r[m]["grade"] == "decision-grade" for r in rows if r["kind"] == "wrong")
                            for m in ("declared", "proposed", "undeclared")},
        "false_alarms_within_declared_coverage": sum(r[d]["required_fail"] for r in rows if r["kind"] == "correct"),
        "metadata_contradicting_truth": sum(len(r["proposed"].get("proposal", {}).get("contradicting_truth", []))
                                            for r in rows),
    }
    result["directions_met"] = sum(result[s]["met"] for s in ("S1", "S2", "S3"))
    return result


def summarize(rows: list[dict], mode: str) -> dict:
    summary = v4.summarize(rows, mode)
    summary["by_form"] = {form: {
        "cases": sum(r["form"] == form for r in rows),
        "with_requirement": sum(r["form"] == form and bool(r["requirement"]) for r in rows),
        "wrong_detected": sum(r["form"] == form and r["kind"] == "wrong" and r[mode]["any_fail"] for r in rows),
        "wrong": sum(r["form"] == form and r["kind"] == "wrong" for r in rows),
        "correct_decision_grade": sum(r["form"] == form and r["kind"] == "correct"
                                      and r[mode]["grade"] == "decision-grade" for r in rows),
    } for form in sorted({r["form"] for r in rows})}
    summary["coverage_gaps"] = {gap: sum(r["gap"] == gap for r in rows)
                                for gap in sorted({r["gap"] for r in rows if r["gap"]})}
    if mode == "declared":
        reasons = [reason for r in rows for reason in r["undeclared_numbers"].values()]
        summary["undeclared_report_numbers"] = {reason: reasons.count(reason) for reason in sorted(set(reasons))}
    if mode == "proposed":
        proposals = [r[mode]["proposal"] for r in rows if r[mode].get("proposal")]
        required = sum(len(p["required"]) for p in proposals)
        filled = sum(len(set(p["filled"]) & set(p["required"])) for p in proposals)
        summary["proposal"] = {
            "proposals": len(proposals), "required_bindings": required, "required_filled_from_metadata": filled,
            "metadata_fills": sorted({k for p in proposals for k in p["filled"]}),
            "conflicts": sorted({c for p in proposals for c in p["conflicts"]}),
            "contradicting_truth": sorted({(r["id"], c) for r in rows if r[mode].get("proposal")
                                           for c in r[mode]["proposal"]["contradicting_truth"]}),
        }
    if mode == "undeclared":
        summary["next_step_offered"] = sum(bool(r[mode]["next_step"]) for r in rows)
    return summary


def measure(cache: Path, derived: Path) -> dict:
    document = json.loads(CASES.read_text(encoding="utf-8"))
    cases = document["cases"] if isinstance(document, dict) else document
    rows = []
    for case in cases:
        plan = declare(case, cache, derived)
        row = {"id": case["id"], "family": case["family"], "kind": case["kind"], "form": plan["form"],
               "requirement": plan["requirement"], "gap": plan["gap"], "undeclared_numbers": plan["undeclared_numbers"],
               "declared_args": plan["args"]}
        for mode in ("declared", "proposed", "undeclared"):
            row[mode] = run_case(case, derived, plan, mode)
        rows.append(row)
    return {"cases": rows, "acceptance": acceptance(rows),
            "summary": {m: summarize(rows, m) for m in ("declared", "proposed", "undeclared")}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache", type=Path)
    parser.add_argument("derived", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = measure(args.cache.resolve(), args.derived.resolve())
    args.out.write_text(json.dumps(result, indent=2, default=list) + "\n", encoding="utf-8")
    print(json.dumps({"acceptance": result["acceptance"], "summary": result["summary"]}, indent=2, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
