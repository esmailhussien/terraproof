#!/usr/bin/env python3
"""Phase 9 Q5.1: measure once on the sealed Q0 real-data cases, in three configurations.

    python tests/phase9_q5.py CACHE_DIR DERIVED_DIR --out q5.json

CACHE_DIR is `evals/verification-heldout-q0/fetch.py`'s cache and DERIVED_DIR its `derive.py` output.
Committed before any Q5.1 result was seen. Ground truth is each case's `kind`, confirmed by the bundle's
own oracle. The rules never read `kind`: one rule per deliverable form, from each case's `facts`, goal
and the deliverable's own label.

- **declared**: what a careful user states.
  - validity mask: `qa-masked` with `output_form=validity-mask`, the facts' valid classes as keep
    codes, and the usable value. `nodata-support` is not declared: a QA mask invalidates valid
    clouds by design.
  - slope raster: `slope-from-dem` with the facts' vertical unit and the slope unit its label
    states (percent or degrees).
  - summary JSON: `summary-value` with the facts' key and statistic. A compound "X and Y" checks the
    first; a vector summary filters the named feature. Facts that state no key leave a gap.
  - reflectance raster: `scaled-reflectance` and `nodata-support`, with offset 0 when the stored
    values already include it, else the declared offset.
  - elevation raster: `vertical-units` and `nodata-support`, with the unit the goal claims.
  - NDVI map: `rs.index_range` with `expect=index`.
- **proposed**: the same profiles, the source paths, and each band file's STAC asset;
  `propose_contract` fills the rest.
- **undeclared**: the output alone.

A metadata-filled binding contradicts the truth when it differs from the declared value for the same
parameter. The fill share counts required coverage bindings, except `processing_full_scan`.
"""
from __future__ import annotations

import argparse
import json
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
CASES = ROOT / "evals" / "verification-heldout-q0" / "cases.json"
SOURCE_PATHS = ("reference_input", "dem", "vertical_sources", "support_sources", "qa_path", "qa_source",
                "summary_source", "summary_mask")
UNITS = {"m": "metre", "metre": "metre"}
STATISTICS = (("mean", "mean"), ("count", "count"), ("maximum", "max"), ("minimum", "min"), ("sum", "sum"),
              ("area", "area"), ("length", "length"))
AREA_UNITS = {"sq_km": "square_kilometre", "km": "kilometre"}


def _sources(case, cache: Path) -> list[Path]:
    return [cache / s["path"].removeprefix("cache/") for s in case["sources"]
            if isinstance(s, dict) and isinstance(s.get("path"), str)]


def _same_grid(output: Path, rasters: list[Path]) -> Path | None:
    with rasterio.open(output) as dst:
        grid = (dst.width, dst.height, tuple(dst.transform), dst.crs)
    found = []
    for path in rasters:
        with rasterio.open(path) as src:
            if (src.width, src.height, tuple(src.transform), src.crs) == grid:
                found.append(path)
    return found[0] if len(found) == 1 else None


def declare(case: dict, cache: Path, derived: Path) -> dict:
    facts, output = case["facts"], derived / case["output"]["path"]
    form, label = case["deliverable_form"], case["output"].get("description", "").lower()
    sources = _sources(case, cache)
    rasters = [p for p in sources if p.suffix == ".tif"]
    plan = {"args": {}, "requirement": None, "stac": [], "gap": None, "form": form}
    if form == "validity-mask":
        qa = [p for p in rasters if "SCL" in p.name]
        plan["args"] = dict(qa_path=str(qa[0]), qa_kind="keep-codes", qa_keep_codes=list(facts["pixel_qa_valid_classes"]),
                            output_form="validity-mask", output_valid_value=float(facts["mask_usable_value"]))
        plan["requirement"] = ["qa-masked"]
        return plan
    if form == "summary":
        if "summary_key" not in facts or "summary_statistic" not in facts:
            plan["gap"] = "summary whose facts state no key or statistic"
            return plan
        key = facts["summary_key"].split(" and ")[0].strip()
        words = facts["summary_statistic"].split(" and ")[0].split()  # whole words: "country" is not "count"
        statistic = next((s for word, s in STATISTICS if word in words), None)
        vector = [p for p in sources if p.suffix in (".geojson", ".gpkg")]
        if vector:
            name = facts["summary_data"].split()[0]
            plan["args"] = dict(summary_key=key, summary_statistic=statistic, summary_source=str(vector[0]),
                                summary_feature=f"NAME={name}",
                                summary_unit=AREA_UNITS.get(facts.get("measured_quantity_units")))
        else:
            plan["args"] = dict(summary_key=key, summary_statistic=statistic, summary_source=str(rasters[0]))
        plan["requirement"] = ["summary-value"]
        return plan
    if "slope" in label or "slope" in str(facts.get("measured_property", "")):
        unit = "percent" if "percent" in label else "degrees"  # the unit the deliverable's label claims
        plan["args"] = dict(dem=str(rasters[0]), dem_vertical_unit=UNITS[facts["elevation_unit"]], slope_unit=unit)
        plan["requirement"] = ["slope-from-dem"]
        return plan
    if "measured_quantity" in facts and "ndvi" in facts["measured_quantity"].lower():
        plan["args"] = dict(expect="index")
        plan["requirement"] = ["rs.index_range"]
        return plan
    if "reflectance_scale" in facts:
        reference = _same_grid(output, rasters)
        offset = 0.0 if facts["reflectance_offset_applied_in_stored_values"] else facts["reflectance_offset_declared"]
        plan["args"] = dict(reference_input=str(reference), decode_scale=facts["reflectance_scale"],
                            decode_offset=offset, processing_full_scan=True, expect="reflectance",
                            support_sources=[str(reference)], support_source_nodata=[float(facts["fill_value"])],
                            support_rule="all")
        plan["requirement"] = ["scaled-reflectance", "nodata-support"]
        item = [p for p in sources if p.name == "item.json"][0]
        asset = facts["band_common_name"].split()[0]
        if asset in (json.loads(item.read_text(encoding="utf-8")).get("assets") or {}):
            plan["stac"] = [f"{reference}={item}#{asset}"]
        return plan
    if "elevation_unit" in facts:
        claimed = "foot" if "(feet)" in case["goal"] else UNITS[facts["elevation_unit"]]
        plan["args"] = dict(vertical_operation="convert", vertical_sources=[str(rasters[0])],
                            vertical_source_units=[UNITS[facts["elevation_unit"]]], vertical_unit=claimed,
                            support_sources=[str(rasters[0])], support_source_nodata=[float(facts["fill_value"])],
                            support_rule="all")
        plan["requirement"] = ["vertical-units", "nodata-support"]
        return plan
    plan["gap"] = "no rule"
    return plan


def _inspect_arguments(args: dict) -> dict:
    out = v4._inspect_arguments(args)
    for key in ("summary_source", "summary_mask"):
        if key in out:
            out[key] = inspect_dataset(out[key])
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
    if not names:
        return given, plan["requirement"], None
    proposal = propose_contract([str(output)], names, given, plan["stac"])
    return dict(proposal["contract"]["requirements"][0]["parameters"]), plan["requirement"], proposal


def run_case(case: dict, derived: Path, plan: dict, mode: str) -> dict:
    output = derived / case["output"]["path"]
    args, requirement, proposal = configure(plan, mode, output)
    dataset = inspect_dataset(str(output))
    results = run_checks([dataset], **_inspect_arguments(args))
    report = build_report(inputs=[input_record(str(output), "input", dataset["kind"])], results=results,
                          parameters=dict(args), contract=v4._contract([str(output)], requirement, args))
    required = {row["check"] for row in report.get("verification", {}).get("requirements", [])}
    row = {
        "grade": report["grade"],
        "verification_status": report.get("verification", {}).get("status"),
        "required_checks": sorted(required),
        "check_statuses": sorted({(c["id"], c["status"]) for c in report["checks"]}),
        "required_fail": any(c["status"] == "fail" for c in report["checks"] if c["id"] in required),
        "any_fail": any(c["status"] == "fail" for c in report["checks"]),
        "missing_bindings": sorted({b for r in report.get("verification", {}).get("requirements", [])
                                    for b in r.get("missing_bindings", [])}),
        "next_step": (report.get("next_step") or {}).get("profiles"),
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


def summarize(rows: list[dict], mode: str) -> dict:
    summary = v4.summarize(rows, mode)
    forms = sorted({r["form"] for r in rows})
    summary["by_form"] = {form: {
        "cases": sum(r["form"] == form for r in rows),
        "with_requirement": sum(r["form"] == form and bool(r["requirement"]) for r in rows),
        "wrong_detected": sum(r["form"] == form and r["kind"] == "wrong" and r[mode]["any_fail"] for r in rows),
        "wrong": sum(r["form"] == form and r["kind"] == "wrong" for r in rows),
        "correct_decision_grade": sum(r["form"] == form and r["kind"] == "correct"
                                      and r[mode]["grade"] == "decision-grade" for r in rows),
    } for form in forms}
    summary["coverage_gaps"] = {gap: sum(r["gap"] == gap for r in rows)
                                for gap in sorted({r["gap"] for r in rows if r["gap"]})}
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
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        plan = declare(case, cache, derived)
        row = {"id": case["id"], "family": case["family"], "kind": case["kind"], "form": plan["form"],
               "requirement": plan["requirement"], "gap": plan["gap"]}
        for mode in ("declared", "proposed", "undeclared"):
            row[mode] = run_case(case, derived, plan, mode)
        rows.append(row)
    return {"cases": rows, "summary": {m: summarize(rows, m) for m in ("declared", "proposed", "undeclared")}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache", type=Path)
    parser.add_argument("derived", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = measure(args.cache.resolve(), args.derived.resolve())
    args.out.write_text(json.dumps(result, indent=2, default=list) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
