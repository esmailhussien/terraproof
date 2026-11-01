#!/usr/bin/env python3
"""Phase 8 P3: measure once on the sealed real-data cases, in three configurations.

    python tests/phase8_p3.py CACHE_DIR DERIVED_DIR --out p3.json

CACHE_DIR is `evals/verification-heldout-real/fetch.py`'s cache and DERIVED_DIR its `derive.py` output.
Committed before any P3 result was seen. Ground truth is each case's `kind`, confirmed by the bundle's
own oracle; the rules below never read `kind`, and both members of a wrong/correct pair get the same rule.

- **declared**: what a careful user states, from each case's `facts`, goal and deliverable. A check is
  declared only where its meaning matches the deliverable. A 1/0 validity mask, a slope in percent or
  a JSON report has no check that verifies it, so it gets no requirement (recorded as a coverage gap),
  and a JSON report cannot be inspected at all.
- **proposed**: the same goal profiles and only the source paths (plus the STAC asset a band file came
  from); every other binding comes from `propose_contract`. Requirements named by check id, not by
  profile, get the source paths only.
- **undeclared**: the output alone, with no contract.

A metadata-filled binding contradicts the truth when it differs from the declared configuration's value
for the same parameter (the declared values come from the cases' facts). The fill share counts the
bindings the goal profiles require, except `processing_full_scan`, a verification choice rather than a
fact about the data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase7_v4 as v4  # noqa: E402  (shared contract, inspection and summary helpers)

from terraproof.checks import run_checks  # noqa: E402
from terraproof.evidence import build_report, input_record  # noqa: E402
from terraproof.evidence.contract import _missing_bindings, profiles as goal_profiles  # noqa: E402
from terraproof.evidence.propose import propose_contract  # noqa: E402
from terraproof.inspect import inspect_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "verification-heldout-real" / "cases.json"
# Parameters that name a source file: the proposed configuration keeps exactly these.
SOURCE_PATHS = ("reference_input", "dem", "vertical_sources", "support_sources", "buffer_source", "qa_path",
                "qa_source")
UNITS = {"m": "metre", "metre": "metre", "feet": "foot", "ft": "foot"}


def _paths(case, cache: Path):
    return [cache / s["path"].removeprefix("cache/") for s in case["sources"]]


def _same_grid(output: Path, sources: list[Path]) -> Path | None:
    """The single raster source on the output's grid: the band the output was made from."""
    with rasterio.open(output) as dst:
        grid = (dst.width, dst.height, tuple(dst.transform), dst.crs)
    found = []
    for path in sources:
        if path.suffix == ".tif":
            with rasterio.open(path) as src:
                if (src.width, src.height, tuple(src.transform), src.crs) == grid:
                    found.append(path)
    return found[0] if len(found) == 1 else None


def declare(case: dict, cache: Path, derived: Path) -> dict:
    """One rule per deliverable form. Returns args, requirement (profiles or check ids), stac, gap."""
    facts, output = case["facts"], derived / case["output"]["path"]
    description = case["output"]["description"].lower()
    sources = _paths(case, cache)
    rasters = [p for p in sources if p.suffix == ".tif"]
    plan = {"args": {}, "requirement": None, "stac": [], "gap": None}
    if output.suffix == ".json":
        plan["gap"] = "JSON report: not a dataset any check can inspect"
        return plan
    if "validity mask" in description:
        plan["gap"] = "1/0 validity mask: no check verifies a mask deliverable (checks read nodata, not 0)"
        return plan
    if output.suffix == ".geojson" and "boundary_source" in facts:
        props = json.loads(output.read_text(encoding="utf-8"))["features"][0]["properties"]
        source = [p for p in sources if p.suffix == ".geojson"][0]
        if "buffer_radius_km" in facts:
            plan["args"] = dict(metric_quantity="buffer", buffer_distance_m=facts["buffer_radius_km"] * 1000.0,
                                buffer_source=str(source))
        else:
            numeric = [k for k, v in props.items() if isinstance(v, (int, float))]
            name = numeric[0]
            quantity, unit = ("area", "square_kilometre") if name.endswith("sq_km") else ("length", "kilometre")
            plan["args"] = dict(metric_quantity=quantity, metric_property=name, metric_unit=unit)
        plan["requirement"] = ["metric-values"]
        return plan
    if "measured_quantity" in facts and "ndvi" in facts["measured_quantity"].lower():
        # NDVI from green and near-infrared: no index formula matches that pair, so only its range is stated.
        plan["args"] = dict(expect="index")
        plan["requirement"] = ["rs.index_range"]
        return plan
    if "reflectance_scale" in facts and "reflectance raster" in description:
        reference = _same_grid(output, rasters)
        offset = 0.0 if facts["reflectance_offset_applied_in_stored_values"] else facts["reflectance_offset_declared"]
        plan["args"] = dict(reference_input=str(reference), decode_scale=facts["reflectance_scale"],
                            decode_offset=offset, processing_full_scan=True, expect="reflectance",
                            support_sources=[str(reference)], support_source_nodata=[float(facts["fill_value"])],
                            support_rule="all")
        plan["requirement"] = ["scaled-reflectance", "nodata-support"]
        item = [p for p in sources if p.name.endswith(".item.json")][0]
        plan["stac"] = [f"{reference}={item}#{facts['band_common_name'].split()[0]}"]
        return plan
    if "elevation_unit" in facts and "slope" in description:
        if "slope-degrees" not in description:
            plan["gap"] = "slope in percent: terrain.slope_consistent verifies slope in degrees only"
            return plan
        plan["args"] = dict(dem=str(rasters[0]), dem_vertical_unit=UNITS[facts["elevation_unit"]])
        plan["requirement"] = ["slope-from-dem"]
        return plan
    if "elevation_unit" in facts:
        # The deliverable's claimed unit is stated in its goal, e.g. "the unit the deliverable claims (feet)".
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
    if "buffer_source" in out:
        out["buffer_source"] = inspect_dataset(out["buffer_source"])
    return out


def _required_bindings(requirement, args) -> list[str]:
    if not requirement:
        return []
    catalogue = goal_profiles()
    checks = sorted(set().union(*(set(catalogue[r]["checks"]) if r in catalogue else {r} for r in requirement)))
    return sorted({b for check in checks for b in _missing_bindings(check, {})} - {"processing_full_scan"})


def configure(plan: dict, mode: str, output: Path) -> tuple[dict, list | None, dict | None]:
    if mode == "undeclared" or plan["requirement"] is None:
        return {}, None, None
    if mode == "declared":
        return plan["args"], plan["requirement"], None
    given = {k: v for k, v in plan["args"].items() if k in SOURCE_PATHS}
    names = [r for r in plan["requirement"] if r in goal_profiles()]
    if not names:
        return given, plan["requirement"], None
    proposal = propose_contract([str(output)], names, given, plan["stac"])
    args = dict(proposal["contract"]["requirements"][0]["parameters"])
    return args, plan["requirement"], proposal


def run_case(case: dict, cache: Path, derived: Path, plan: dict, mode: str) -> dict:
    output = derived / case["output"]["path"]
    if output.suffix == ".json":
        return {"grade": None, "not_checkable": plan["gap"], "required_checks": [], "any_fail": False,
                "required_fail": False, "verification_status": None}
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
        "gap": plan["gap"],
    }
    if proposal is not None:
        filled = [b for b in proposal["bindings"] if b["from"] != "caller"]
        row["proposal"] = {
            "filled": {b["parameter"]: b["value"] for b in filled},
            "evidence": {b["parameter"]: b.get("evidence") for b in filled},
            "undeclared": sorted({u["parameter"] for u in proposal["undeclared"]}),
            "not_stated": sorted({n["parameter"] for n in proposal["not_stated"]}),
            "conflicts": sorted({c["parameter"] for c in proposal["conflicts"]}),
            "unusable": sorted({u["parameter"] for u in proposal["unusable"]}),
            "required": _required_bindings(requirement, args),
            "contradicting_truth": sorted(p for p, v in ((b["parameter"], b["value"]) for b in filled
                                                          if b["from"] == "metadata")
                                          if p in plan["args"] and json.dumps(v) != json.dumps(plan["args"][p])),
        }
    return row


def summarize(rows: list[dict], mode: str) -> dict:
    checkable = [r for r in rows if r[mode]["grade"] is not None]
    summary = v4.summarize(checkable, mode)
    summary["not_checkable"] = len(rows) - len(checkable)
    summary["coverage_gaps"] = {gap: sum(r["gap"] == gap for r in rows) for gap in sorted({r["gap"] for r in rows
                                                                                          if r["gap"]})}
    summary["cases_with_a_gap"] = sum(bool(r["gap"]) for r in rows)
    if mode == "proposed":
        proposals = [r[mode]["proposal"] for r in rows if r[mode].get("proposal")]
        required = sum(len(p["required"]) for p in proposals)
        filled = sum(len(set(p["filled"]) & set(p["required"])) for p in proposals)
        summary["proposal"] = {
            "proposals": len(proposals), "required_bindings": required,
            "required_filled_from_metadata": filled,
            "fill_share": round(filled / required, 4) if required else None,
            "undeclared": sorted({u for p in proposals for u in p["undeclared"]}),
            "not_stated": sorted({u for p in proposals for u in p["not_stated"]}),
            "conflicts": sorted({u for p in proposals for u in p["conflicts"]}),
            "contradicting_truth": sorted({(r["id"], c) for r in rows if r[mode].get("proposal")
                                           for c in r[mode]["proposal"]["contradicting_truth"]}),
        }
    return summary


def measure(cache: Path, derived: Path) -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        plan = declare(case, cache, derived)
        row = {"id": case["id"], "family": case["family"], "kind": case["kind"],
               "requirement": plan["requirement"], "gap": plan["gap"]}
        for mode in ("declared", "proposed", "undeclared"):
            row[mode] = run_case(case, cache, derived, plan, mode)
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
