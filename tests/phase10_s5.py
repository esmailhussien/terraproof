#!/usr/bin/env python3
"""Phase 10 S5: measure once on the sealed S0b real-data cases, in three configurations.

    python tests/phase10_s5.py CACHE_DIR DERIVED_DIR --out s5.json

CACHE_DIR is `evals/verification-heldout-s0b/fetch.py`'s cache and DERIVED_DIR its `derive.py` output.
Committed before any S5 result was seen. Ground truth is each case's `kind`, confirmed by the bundle's own
oracle. The rules never read `kind`, `scenario`, `goal`, `output` text or `oracle`: one rule per deliverable
form, from each case's `facts` and its sources' own metadata. They were written from the bundle README and a
pooled view of the facts (keys, types, vocabularies and report-number combinations; no ids or kinds),
recorded in the plan. The configurations, acceptance and reporting are S4.1's (`phase10_s4.py`).

- **declared**: what a careful user states.
  - validity mask: `qa-masked` with `output_form=validity-mask`, the facts' QA layer as `qa_path`, its
    usable classes as keep codes, and the usable value.
  - slope raster (facts name a `source_dem`): `slope-from-dem` with that DEM, its vertical unit, and the
    facts' slope unit. The target grid and resampling are not declared: the check tries every common way.
  - other datasets: S4.1's rules.
  - summary JSON: `summary-value` with one summary per expressible number in `report_numbers`:
    - vector file: `feature_count` as `count`, `area_geodesic` and `length_geodesic` as `area` and
      `length` in the stated unit, a named feature as `NAME=…`;
    - raster file, statistic `mean`, `maximum`, `minimum`, `count` or `share` (as `fraction`):
      - selection `all`: declared when no cell holds the file's nodata;
      - `not_value V`: declared when V is the file's nodata, which the check always excludes;
      - `equal V`: `codes=[V]`, when V is not the file's nodata;
      - `class_in C` on the file itself: `codes=C`, when C holds no nodata code;
    - a share over `all` cells: no mask (the check divides by all cells); over `valid` cells with a
      denominator mask `class_in D` on the same file: `codes=D`, the file as its own mask, `mask_codes=C`,
      when C is within D;
    - a stated decode: `scale` and `offset`.
    Not expressible, so left undeclared and the report can at best need review: NDVI, a selection joint
    across several files (`all_not_zero`), a QA selection on a layer on another grid, a mask file.
- **proposed**: the same profiles and the source paths (none for summaries); `propose_contract` fills
  the rest.
- **undeclared**: the output alone.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase10_s4 as s4  # noqa: E402  (configurations, acceptance and summaries as in S4.1)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "verification-heldout-s0b" / "cases.json"
UNITS = {"m": "metre"}
RASTER_STATISTICS = {"mean": "mean", "maximum": "max", "minimum": "min", "count": "count", "share": "fraction"}
VECTOR_STATISTICS = {"feature_count": "count", "area_geodesic": "area", "length_geodesic": "length"}
SUMMARY_UNITS = {"sq_km": "square_kilometre", "km": "kilometre", "fraction": "fraction"}


def _nodata(path: Path):
    with rasterio.open(path) as src:
        return src.nodata


def _holds(path: Path, value) -> bool:
    with rasterio.open(path) as src:
        return bool(np.any(src.read(1) == value))


def _summary(key: str, spec: dict, cache: Path):
    """One declared summary for an expressible report number, or None with the reason."""
    statistic, selection, file = spec.get("statistic"), spec.get("selection") or {}, spec.get("file") or {}
    if "[*]" in key or "*" in key:
        return None, "wildcard key"
    if set(file) - {"path", "feature"} or not isinstance(file.get("path"), str):
        return None, "derived from several files"
    source = s4._cache_path(cache, file["path"])
    entry = {"key": key, "source": str(source)}
    if source.suffix in (".geojson", ".gpkg"):
        if statistic not in VECTOR_STATISTICS or selection.get("type") not in (None, "all"):
            return None, "vector statistic or selection not supported"
        entry["statistic"] = VECTOR_STATISTICS[statistic]
        if file.get("feature"):
            entry["feature"] = f"NAME={file['feature']}"
        if entry["statistic"] != "count":
            if spec.get("unit") not in SUMMARY_UNITS:
                return None, "unit not supported"
            entry["unit"] = SUMMARY_UNITS[spec["unit"]]
        return entry, None
    if statistic not in RASTER_STATISTICS:
        return None, "statistic not supported"
    entry["statistic"] = RASTER_STATISTICS[statistic]
    nodata, kind = _nodata(source), selection.get("type")
    if set(selection) - {"type", "value", "classes"}:
        return None, "selection by another file"
    if kind == "all":
        if nodata is not None and _holds(source, nodata):
            return None, "selection includes the file's nodata"
    elif kind == "not_value":
        if nodata is None or float(selection["value"]) != float(nodata):
            return None, "excluded value is not the file's nodata"
    elif kind == "equal":
        if nodata is not None and float(selection["value"]) == float(nodata):
            return None, "selected value is the file's nodata"
        entry["codes"] = [int(selection["value"])]
    elif kind == "class_in":
        classes = [int(c) for c in selection["classes"]]
        if nodata is not None and float(nodata) in map(float, classes):
            return None, "selected classes include the file's nodata"
        entry["codes"] = classes
    else:
        return None, "selection not supported"
    if entry["statistic"] == "fraction":
        if spec.get("unit") not in SUMMARY_UNITS:
            return None, "unit not supported"
        entry["unit"] = SUMMARY_UNITS[spec["unit"]]
        denominator = spec.get("denominator")
        if denominator == "valid":
            mask = spec.get("denominator_mask") or {}
            if mask.get("type") != "class_in" or set(mask) - {"type", "classes"} or "codes" not in entry:
                return None, "denominator not supported"
            within = [int(c) for c in mask["classes"]]
            if not set(entry["codes"]) <= set(within):
                return None, "selected classes outside the denominator"
            entry.update(codes=within, mask=str(source), mask_codes=entry["codes"])
        elif denominator != "all":
            return None, "denominator not supported"
    decode = spec.get("decode")
    if decode:
        entry.update(scale=float(decode.get("scale", 1.0)), offset=float(decode.get("offset", 0.0)))
    return entry, None


def declare(case: dict, cache: Path, derived: Path) -> dict:
    facts, form = case["facts"], case["deliverable_form"]
    plan = {"args": {}, "requirement": None, "stac": [], "gap": None, "form": form, "undeclared_numbers": {}}
    if form == "validity-mask":
        plan["args"] = dict(qa_path=str(s4._cache_path(cache, facts["pixel_qa_layer"]["path"])), qa_kind="keep-codes",
                            qa_keep_codes=[int(c) for c in facts["pixel_qa_classes_usable"]],
                            output_form="validity-mask", output_valid_value=float(facts["mask_usable_value"]))
        plan["requirement"] = ["qa-masked"]
        return plan
    if form == "summary":
        entries = []
        for key, spec in (facts.get("report_numbers") or {}).items():
            entry, reason = _summary(key, spec, cache)
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
        unit = facts["slope_unit"]
        plan["args"] = dict(dem=str(s4._cache_path(cache, facts["source_dem"]["path"])),
                            dem_vertical_unit=UNITS[facts["elevation_unit"]],
                            slope_unit=None if unit == "degrees" else unit)
        plan["requirement"] = ["slope-from-dem"]
        return plan
    return s4.declare(case, cache, derived)


def measure(cache: Path, derived: Path, modes=("declared", "proposed", "undeclared")) -> dict:
    document = json.loads(CASES.read_text(encoding="utf-8"))
    cases = document["cases"] if isinstance(document, dict) else document
    rows = []
    for case in cases:
        plan = declare(case, cache, derived)
        row = {"id": case["id"], "family": case["family"], "kind": case["kind"], "form": plan["form"],
               "requirement": plan["requirement"], "gap": plan["gap"], "undeclared_numbers": plan["undeclared_numbers"],
               "declared_args": plan["args"]}
        for mode in modes:
            row[mode] = s4.run_case(case, derived, plan, mode)
        rows.append(row)
    return {"cases": rows, "acceptance": s4.acceptance(rows),
            "summary": {m: s4.summarize(rows, m) for m in modes}}


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
