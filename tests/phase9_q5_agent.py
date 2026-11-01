#!/usr/bin/env python3
"""Phase 9 Q5.2: does an agent with Terraproof declare its goal and avoid false assurance? Plans by default.

Five fresh tasks on the Q0 cache (sources no sealed Q0 case or P4 task delivered), "with" Terraproof only,
two runs each: 10 invocations on OpenCode Go `opencode-go/mimo-v2.6-flash` (OpenCode 1.19.4), 900 s per
run. The brief is neutral and never mentions verification. Reported, as names and enums only:

- whether `run_checks` returned a `next_step`, and whether the agent then called `propose_contract`;
- whether its checks of the deliverable carried `profiles` or a `contract`, and the last grade it saw;
- false assurance: a deliverable the oracle rejects whose last check the agent saw as `decision-grade`.
  Zero false assurance is required; nothing else has a threshold.

Committed before any Q5.2 run. Each oracle recomputes the truth with numpy, rasterio and pyproj, never
Terraproof, and is calibrated on a right and a wrong deliverable before any run.

    python tests/phase9_q5_agent.py CACHE_DIR --opencode-executable EXE --agent-python-with PY           # plan
    python tests/phase9_q5_agent.py CACHE_DIR ... --work-root DIR --preflight-only                      # no model
    python tests/phase9_q5_agent.py CACHE_DIR ... --work-root DIR --approve-model-calls 10
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import numpy as np
import rasterio
from pyproj import Geod

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase8_p4 as p4  # noqa: E402  (adapter, labels, raster helpers)
from agent_lift import ROOT, probe_opencode, shell_command  # noqa: E402

from terraproof.evals.harness import _sanitize  # noqa: E402
from terraproof.evals.lift import (  # noqa: E402
    FLOAT_GRID, PREFLIGHT_FAILED, PREFLIGHT_ONLY, WITH, AgentRequest, LiftTask, _install, brief, classify_attempt,
    project_preflight, to_json,
)

RUNS, MODEL, HOST_VERSION, TIMEOUT = 2, p4.MODEL, p4.HOST_VERSION, p4.TIMEOUT
GRADES = p4.GRADES
MASK = "single-band uint8 GeoTIFF on the input grid, 1 where the pixel is usable and 0 where it is not"

TASKS = (
    {"task": LiftTask("q5-c1-blue-reflectance", ("blue_dn.tif", "scene_item.json"),
                      (("blue_reflectance.tif", f"surface reflectance, {FLOAT_GRID}"),), ()),
     "sources": {"blue_dn.tif": "s2-c1/wa_B02.tif", "scene_item.json": "s2-c1/item.json"},
     "prompt": "Convert this Sentinel-2 L2A blue-band window to surface reflectance. `blue_dn.tif` is a window of "
               "the scene's `blue` asset, and `scene_item.json` is the scene's STAC item from Earth Search "
               "(collection sentinel-2-c1-l2a)."},
    {"task": LiftTask("q5-c1-clear-mask", ("scl.tif", "scene_item.json"),
                      (("clear_mask.tif", MASK),), ()),
     "sources": {"scl.tif": "s2-c1/wa_SCL.tif", "scene_item.json": "s2-c1/item.json"},
     "prompt": "Make a usable-pixel mask from this Sentinel-2 L2A scene classification window (`scl.tif`, the "
               "scene's `scl` asset; `scene_item.json` is its STAC item). Vegetation, not-vegetated, water and "
               "snow/ice pixels are usable; every other class, and no-data, is not."},
    {"task": LiftTask("q5-nepal-slope-percent", ("nepal_dem.tif",),
                      (("slope_percent.tif", f"terrain slope in percent, {FLOAT_GRID}; edge cells may be nodata"),),
                      ()),
     "sources": {"nepal_dem.tif": "copdem/n28e084_win.tif"},
     "prompt": "Compute terrain slope in percent from this Copernicus DEM GLO-30 window in Nepal. Heights are metres "
               "above EGM2008."},
    {"task": LiftTask("q5-kauai-summary", ("kauai_dem.tif", "kauai_dem.xml"),
                      (("elevation_summary.json", "JSON object with `mean_elevation_m`, the mean height of the "
                                                  "window's valid cells in metres, and `valid_cell_count`, how many "
                                                  "cells hold a height"),), ()),
     "sources": {"kauai_dem.tif": "usgs3dep/USGS_13_n22w159_win.tif", "kauai_dem.xml": "usgs3dep/USGS_13_n22w159.xml"},
     "prompt": "Summarise this USGS 3DEP 1/3 arc-second elevation window of the Kauai coast. `kauai_dem.xml` is the "
               "tile's metadata."},
    {"task": LiftTask("q5-switzerland-area", ("countries.geojson",),
                      (("switzerland_area.json", "JSON object with `area_km2`, Switzerland's area in square "
                                                 "kilometres"),), ()),
     "sources": {"countries.geojson": "naturalearth/ne_110m_admin_0_countries.geojson"},
     "prompt": "From this Natural Earth countries file, report Switzerland's area in square kilometres."},
)


# -- oracles: numpy, rasterio and pyproj only --------------------------------------------------------------


def oracle_blue(inputs: Path, outputs: Path) -> dict:
    # c1 stores ESA's raw DNs (no earthsearch:boa_offset_applied), so reflectance is (DN - 1000) x 1e-4; 0 is fill.
    dn, _valid, _ = p4._read(inputs / "blue_dn.tif")
    return p4._compare(outputs / "blue_reflectance.tif", inputs / "blue_dn.tif", (dn - 1000) * 1e-4, dn > 0, 1e-4)


def oracle_mask(inputs: Path, outputs: Path) -> dict:
    output = outputs / "clear_mask.tif"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    with rasterio.open(inputs / "scl.tif") as src, rasterio.open(output) as dst:
        if (dst.width, dst.height, dst.transform, dst.crs) != (src.width, src.height, src.transform, src.crs):
            return {"correct": False, "reason": "not on the input grid"}
        keep = np.isin(src.read(1), [4, 5, 6, 11])
        usable = dst.read(1) == 1
    errors = int(np.count_nonzero(usable != keep))
    return {"correct": errors == 0, "reason": "ok" if not errors else f"{errors} cells disagree", "mask_errors": errors}


def oracle_slope(inputs: Path, outputs: Path) -> dict:
    output = outputs / "slope_percent.tif"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    z, valid, grid = p4._read(inputs / "nepal_dem.tif")
    got, got_valid, got_grid = p4._read(output)
    if got_grid != grid:
        return {"correct": False, "reason": "not on the input grid"}
    transform, geod = grid[2], Geod(ellps="WGS84")
    lat = transform[5] + (np.arange(z.shape[0]) + 0.5) * transform[4]
    dx = np.array([geod.inv(transform[2], la, transform[2] + transform[0], la)[2] for la in lat])
    dy = abs(geod.inv(transform[2], lat[0], transform[2], lat[0] + transform[4])[2])
    gx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx[1:-1, None])
    gy = (z[2:, 1:-1] - z[:-2, 1:-1]) / (2 * dy)
    central = np.degrees(np.arctan(np.hypot(gx, gy)))
    horn = p4._horn_slope(z, transform, lat_scaled=True)[1:-1, 1:-1]
    interior = valid[1:-1, 1:-1] & got_valid[1:-1, 1:-1]
    if interior.sum() < 0.9 * interior.size:
        return {"correct": False, "reason": "most interior cells are nodata"}
    delivered = np.degrees(np.arctan(got[1:-1, 1:-1][interior] / 100.0))  # percent -> degrees
    # Either standard stencil on true ground spacing is right; latitude ignored is >= 1 degree off in median.
    median, p95 = min((float(np.median(d)), float(np.percentile(d, 95)))
                      for d in (np.abs(delivered - central[interior]), np.abs(delivered - horn[interior])))
    correct = median <= 0.2 and p95 <= 1.0
    return {"correct": correct, "reason": "ok" if correct else f"median {median:.3g} deg, p95 {p95:.3g} deg",
            "median_abs_diff_deg": median, "p95_abs_diff_deg": p95}


def oracle_summary(inputs: Path, outputs: Path) -> dict:
    output = outputs / "elevation_summary.json"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    try:
        report = json.loads(output.read_text(encoding="utf-8"))
        mean, count = float(report["mean_elevation_m"]), int(report["valid_cell_count"])
    except (ValueError, KeyError, TypeError):
        return {"correct": False, "reason": "no numeric mean_elevation_m and valid_cell_count"}
    heights, valid, _ = p4._read(inputs / "kauai_dem.tif")  # the file's nodata is its fill; real zeros count
    truth_mean, truth_count = float(heights[valid].mean()), int(valid.sum())
    correct = abs(mean - truth_mean) <= 1e-4 * abs(truth_mean) + 1e-3 and count == truth_count
    return {"correct": correct, "reason": "ok" if correct else f"mean {mean:.6g} vs {truth_mean:.6g}, count {count} "
            f"vs {truth_count}"}


def oracle_area(inputs: Path, outputs: Path) -> dict:
    output = outputs / "switzerland_area.json"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    try:
        value = float(json.loads(output.read_text(encoding="utf-8"))["area_km2"])
    except (ValueError, KeyError, TypeError):
        return {"correct": False, "reason": "no numeric area_km2"}
    from shapely.geometry import shape
    source = json.loads((inputs / "countries.geojson").read_text(encoding="utf-8"))["features"]
    geometry = shape([f for f in source if f["properties"].get("NAME") == "Switzerland"][0]["geometry"])
    truth = abs(Geod(ellps="WGS84").geometry_area_perimeter(geometry)[0]) / 1e6
    error = abs(value - truth) / truth
    return {"correct": error <= 0.01, "reason": "ok" if error <= 0.01 else f"{value:.6g} vs {truth:.6g}",
            "relative_error": error}


ORACLES = {"q5-c1-blue-reflectance": oracle_blue, "q5-c1-clear-mask": oracle_mask,
           "q5-nepal-slope-percent": oracle_slope, "q5-kauai-summary": oracle_summary,
           "q5-switzerland-area": oracle_area}


def calibrate(entry: dict, inputs: Path, root: Path) -> dict:
    """One right and one wrong deliverable per task; a task is eligible only if the oracle splits them."""
    task_id, verdicts = entry["task"].task_id, {}
    for label in ("right", "wrong"):
        outputs = root / label
        outputs.mkdir(parents=True)
        if task_id == "q5-c1-blue-reflectance":
            dn, _v, _ = p4._read(inputs / "blue_dn.tif")
            p4._write_like(inputs / "blue_dn.tif", outputs / "blue_reflectance.tif",
                           dn * 1e-4 if label == "wrong" else (dn - 1000) * 1e-4, dn > 0)  # wrong: offset missing
        elif task_id == "q5-c1-clear-mask":
            with rasterio.open(inputs / "scl.tif") as src:
                codes, profile = src.read(1), dict(src.profile, dtype="uint8", nodata=None, count=1)
            keep = np.isin(codes, [2, 4, 5, 6, 11] if label == "wrong" else [4, 5, 6, 11])  # wrong keeps dark areas
            with rasterio.open(outputs / "clear_mask.tif", "w", **profile) as dst:
                dst.write(keep.astype("uint8"), 1)
        elif task_id == "q5-nepal-slope-percent":
            z, valid, grid = p4._read(inputs / "nepal_dem.tif")
            degrees = p4._horn_slope(z, grid[2], lat_scaled=True)
            values = degrees if label == "wrong" else np.tan(np.radians(degrees)) * 100.0  # wrong: degrees as %
            p4._write_like(inputs / "nepal_dem.tif", outputs / "slope_percent.tif", values, valid)
        elif task_id == "q5-kauai-summary":
            heights, valid, _ = p4._read(inputs / "kauai_dem.tif")
            mean = float(heights.mean()) if label == "wrong" else float(heights[valid].mean())  # wrong: fill in
            (outputs / "elevation_summary.json").write_text(json.dumps(
                {"mean_elevation_m": mean, "valid_cell_count": int(valid.sum())}), encoding="utf-8")
        else:
            from shapely.geometry import shape
            source = json.loads((inputs / "countries.geojson").read_text(encoding="utf-8"))["features"]
            geometry = shape([f for f in source if f["properties"].get("NAME") == "Switzerland"][0]["geometry"])
            area = (geometry.area if label == "wrong"  # square degrees
                    else abs(Geod(ellps="WGS84").geometry_area_perimeter(geometry)[0]) / 1e6)
            (outputs / "switzerland_area.json").write_text(json.dumps({"area_km2": area}), encoding="utf-8")
        verdicts[label] = ORACLES[task_id](inputs, outputs)
    return {"task": task_id, "eligible": verdicts["right"]["correct"] and not verdicts["wrong"]["correct"],
            "right": verdicts["right"]["reason"], "wrong": verdicts["wrong"]["reason"]}


# -- behaviour and summary -----------------------------------------------------------------------------------


def behaviour(calls: list[dict]) -> dict:
    found = p4.behaviour(calls)
    offered = [i for i, c in enumerate(calls) if c["tool"] == "run_checks" and c.get("next_step_offered")]
    found["next_step_offered"] = bool(offered)
    found["followed_next_step"] = bool(offered) and any(c["tool"] == "propose_contract" for c in calls[offered[0]:])
    return found


def summarize(rows: list[dict]) -> dict:
    summary = p4.summarize(rows)
    ran = [r for r in rows if r.get("host_status") is not None]
    summary["next_step_offered"] = sum(r["behaviour"]["next_step_offered"] for r in ran)
    summary["followed_next_step"] = sum(r["behaviour"]["followed_next_step"] for r in ran)
    summary["zero_false_assurance"] = summary["false_assurance_wrong_seen_decision_grade"] == 0
    return summary


def run(adapter, cache: Path, work: Path, *, runs: int, preflight_only: bool, approved: int | None) -> dict:
    planned = len(TASKS) * runs
    if not preflight_only and approved != planned:
        raise SystemExit(f"approval {approved} does not equal the planned {planned} invocations; nothing started")
    calibration = []
    for entry in TASKS:
        inputs = work / "calibration" / entry["task"].task_id / "inputs"
        inputs.mkdir(parents=True)
        for name, relative in entry["sources"].items():
            shutil.copyfile(cache / relative, inputs / name)
        calibration.append(calibrate(entry, inputs, inputs.parent))
    if not all(item["eligible"] for item in calibration):
        raise SystemExit(f"oracle calibration failed; nothing started: {calibration}")
    rows, started = [], 0
    for run_index in range(runs):
        for entry in TASKS:
            task = entry["task"]
            project = work / f"{task.task_id}-{run_index}" / "project"
            (project / "inputs").mkdir(parents=True)
            (project / "outputs").mkdir()
            for name, relative in entry["sources"].items():
                shutil.copyfile(cache / relative, project / "inputs" / name)
            spec = SimpleNamespace(prompt=entry["prompt"])
            (project / "TASK.md").write_text(brief(task, spec), encoding="utf-8", newline="\n")
            code, skills = _install(project, "opencode", spec, adapter.agent_python_with)
            row = {"task": task.task_id, "run": run_index, "install_exit": code, "skills": skills}
            request = AgentRequest(task.task_id, WITH, run_index, project, brief(task, spec), TIMEOUT, None)
            checks = project_preflight(task, project, condition=WITH, agent="opencode", routed=skills)
            try:
                checks.update(adapter.preflight(request))
            except Exception as error:  # a broken probe must never fall through to a model call
                checks.update(adapter_preflight=False, adapter_preflight_error=type(error).__name__)
            ok = code == 0 and all(v for v in checks.values() if isinstance(v, bool))
            row["preflight"] = {"ok": ok, "checks": checks}
            if preflight_only or not ok:
                row["adapter_status"] = PREFLIGHT_ONLY if ok else PREFLIGHT_FAILED
                rows.append(row)
                continue
            started += 1
            if started > planned:  # pragma: no cover - guarded by the approval check
                raise SystemExit("approved invocation count exhausted")
            result = adapter.run(request)
            oracle = ORACLES[task.task_id](project / "inputs", project / "outputs")
            present = {name: (project / "outputs" / name).is_file() for name in task.deliverable_names}
            row.update(host_status=result.status, adapter_status=classify_attempt(result, present), oracle=oracle,
                       behaviour=behaviour(adapter.last_calls), verification_calls=adapter.last_calls,
                       agent={key: value for key, value in asdict(result).items() if key != "status"})
            rows.append(row)
    rows = _sanitize(rows, work)
    return {"schema": "terraproof.phase9.q5-agent/0.1", "model": MODEL, "host_version": HOST_VERSION,
            "calibration": calibration,
            "design": {"tasks": [e["task"].task_id for e in TASKS], "runs_per_task": runs,
                       "planned_invocations": planned, "started": started, "preflight_only": preflight_only,
                       "condition": WITH, "order": "every task once, then again"},
            "runs": rows, "summary": None if preflight_only else summarize(rows)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache", type=Path, help="the Q0 bundle's fetch.py cache")
    parser.add_argument("--opencode-executable", type=Path, required=True, help="native opencode.exe")
    parser.add_argument("--agent-python-with", type=Path, required=True, help="venv holding this branch's wheel")
    parser.add_argument("--work-root", type=Path, help="empty directory outside the checkout for the projects")
    parser.add_argument("--preflight-only", action="store_true", help="prepare and preflight every project; no agent")
    parser.add_argument("--approve-model-calls", type=int, metavar="N", help=f"explicit approval: N must be {RUNS * len(TASKS)}")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "phase9-q5-agent.json")
    args = parser.parse_args(argv)
    planned = RUNS * len(TASKS)
    base = ["python", "tests/phase9_q5_agent.py", str(args.cache), "--opencode-executable",
            str(args.opencode_executable), "--agent-python-with", str(args.agent_python_with),
            "--work-root", str(args.work_root or "WORK_DIR")]
    if args.approve_model_calls is None and not args.preflight_only:
        print(json.dumps({"status": "plan-only (no host started, no model called)", "condition": WITH,
                          "tasks": [e["task"].task_id for e in TASKS], "runs_per_task": RUNS,
                          "planned_model_invocations": planned, "model": MODEL, "host_version": HOST_VERSION,
                          "per_run_timeout_seconds": TIMEOUT,
                          "command_to_approve": shell_command(base + ["--approve-model-calls", str(planned)]),
                          "preflight_command": shell_command(base + ["--preflight-only"])}, indent=2, sort_keys=True))
        return 0
    if args.preflight_only and args.approve_model_calls is not None:
        parser.error("--preflight-only starts no agent; do not combine it with --approve-model-calls")
    work = (args.work_root or Path()).resolve()
    if args.work_root is None or ROOT.resolve() in work.parents or work == ROOT.resolve() or \
            (work.exists() and any(work.iterdir())):
        parser.error("--work-root must be an empty or new directory outside the checkout")
    executable, reason, version = probe_opencode(str(args.opencode_executable), MODEL)
    if executable is None or version.split()[1:2] != [HOST_VERSION]:
        print(json.dumps({"status": "unavailable", "model_called": False,
                          "reason": reason if executable is None else f"host is {version}, registered {HOST_VERSION}"}))
        return 1
    adapter = p4.VerificationAdapter(executable, MODEL, None, None, str(args.agent_python_with),
                                     deliverables={e["task"].task_id: e["task"].deliverable_names for e in TASKS},
                                     inputs={e["task"].task_id: e["task"].inputs for e in TASKS})
    work.mkdir(parents=True, exist_ok=True)
    report = run(adapter, args.cache.resolve(), work, runs=RUNS, preflight_only=args.preflight_only,
                 approved=args.approve_model_calls)
    report["host"] = {"name": "opencode", "version": version}
    out = args.out.with_name(args.out.stem + "-preflight" + args.out.suffix) if args.preflight_only else args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(report), encoding="utf-8", newline="\n")
    failed = [f"{r['task']}:{r['run']}" for r in report["runs"] if r["adapter_status"] == PREFLIGHT_FAILED]
    print(json.dumps({"status": "preflight complete" if args.preflight_only else "complete", "report": str(out),
                      "preflight_failures": failed, "started": report["design"]["started"],
                      "summary": report["summary"]}, indent=2, sort_keys=True, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
