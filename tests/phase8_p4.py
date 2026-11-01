#!/usr/bin/env python3
"""Phase 8 P4: what an agent with Terraproof does to verify its own real-data outputs. Plans by default.

Five tasks on windows of the P0 sources (not its sealed cases), "with" Terraproof only, two runs each:
10 invocations on OpenCode Go `opencode-go/mimo-v2.6-flash` (OpenCode 1.19.4), 900 s per run. The
brief is neutral: it asks for the deliverable, never for verification. Measured, not lift:

- whether the agent calls `propose_contract`, and whether its `run_checks` calls on the deliverable
  pass `profiles` or a `contract` (argument names only, never values);
- the share of runs whose last check of the deliverable had assessed coverage (a contract);
- false assurance: a deliverable the oracle rejects whose last check the agent saw as `decision-grade`.

Committed before any P4 run. Each oracle recomputes the truth from the inputs with numpy, rasterio and
pyproj, never Terraproof. Traces keep Phase 6's contamination labels; results are "contamination
screened", not evaluator-blind.

    python tests/phase8_p4.py CACHE_DIR --opencode-executable EXE --agent-python-with PY            # plan
    python tests/phase8_p4.py CACHE_DIR ... --work-root DIR --preflight-only                       # no model
    python tests/phase8_p4.py CACHE_DIR ... --work-root DIR --approve-model-calls 10
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import rasterio
from pyproj import Geod

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_lift  # noqa: E402
from agent_lift import (  # noqa: E402
    ROOT, OpenCodeHostAdapter, _json_lines, opencode_lift_command, opencode_trace, probe_opencode, run_contained,
    shell_command,
)

from terraproof.evals.harness import _sanitize  # noqa: E402
from terraproof.evals.lift import (  # noqa: E402
    FLOAT_GRID, PREFLIGHT_FAILED, PREFLIGHT_ONLY, WITH, AgentRequest, LiftTask, _install, brief, classify_attempt,
    project_preflight, to_json,
)

RUNS = 2
MODEL = "opencode-go/mimo-v2.6-flash"
HOST_VERSION = "1.19.4"
TIMEOUT = 900.0
GRADES = ("decision-grade", "checks-passed", "review-required", "advisory-only")
STATUSES = ("verified", "failed", "incomplete", "review-required")
S2 = "s2/S2B_32TMS_20250831_0_L2A.item.json"

TASKS = (
    {"task": LiftTask("p4-s2-blue-reflectance", ("blue_dn.tif", "scene_item.json"),
                      (("blue_reflectance.tif", f"surface reflectance, {FLOAT_GRID}"),), ()),
     "sources": {"blue_dn.tif": "s2/wa_B02.tif", "scene_item.json": S2},
     "prompt": "Convert this Sentinel-2 L2A blue-band window to surface reflectance. `blue_dn.tif` is a window of "
               "the scene's `blue` asset, and `scene_item.json` is the scene's STAC item from Earth Search."},
    {"task": LiftTask("p4-s2-swir-clear", ("swir_dn.tif", "scl.tif", "scene_item.json"),
                      (("swir_clear_reflectance.tif", f"SWIR surface reflectance of clear pixels, {FLOAT_GRID}"),),
                      ()),
     "sources": {"swir_dn.tif": "s2/wa_B11.tif", "scl.tif": "s2/wa_SCL.tif", "scene_item.json": S2},
     "prompt": "Make a clear-surface SWIR reflectance layer from this Sentinel-2 L2A window. `swir_dn.tif` is the "
               "scene's `swir16` asset and `scl.tif` its scene classification; `scene_item.json` is the STAC item. "
               "Keep pixels classified as vegetation, not vegetated, water or snow/ice; every other pixel, and "
               "any fill, must be nodata."},
    {"task": LiftTask("p4-kauai-feet", ("kauai_dem.tif", "kauai_dem.xml"),
                      (("kauai_elevation_ft.tif", f"elevation in international feet, {FLOAT_GRID}"),), ()),
     "sources": {"kauai_dem.tif": "usgs3dep/USGS_13_n22w159_win.tif", "kauai_dem.xml": "usgs3dep/USGS_13_n22w159.xml"},
     "prompt": "Convert this USGS 3DEP 1/3 arc-second elevation window of the Kauai coast to international feet. "
               "`kauai_dem.xml` is the tile's metadata."},
    {"task": LiftTask("p4-svalbard-slope", ("svalbard_dem.tif",),
                      (("slope_deg.tif", f"terrain slope in degrees, {FLOAT_GRID}; edge cells may be nodata"),), ()),
     "sources": {"svalbard_dem.tif": "copdem/n78e016_win.tif"},
     "prompt": "Compute terrain slope in degrees from this Copernicus DEM GLO-30 window in Svalbard. Heights are "
               "metres above EGM2008."},
    {"task": LiftTask("p4-iceland-area", ("countries.geojson",),
                      (("iceland_area.geojson", "GeoJSON holding Iceland's feature from countries.geojson with a "
                                                "numeric property `area_km2`, its area in square kilometres"),), ()),
     "sources": {"countries.geojson": "naturalearth/ne_110m_admin_0_countries.geojson"},
     "prompt": "From this Natural Earth countries file, deliver Iceland's boundary with its area in square "
               "kilometres."},
)


# -- oracles: numpy, rasterio and pyproj only --------------------------------------------------------------


def _read(path: Path):
    with rasterio.open(path) as src:
        data = src.read(1).astype("float64")
        valid = src.read_masks(1) > 0
        return data, valid & np.isfinite(data), (src.width, src.height, tuple(src.transform), src.crs)


def _compare(output: Path, reference: Path, expected, keep, atol: float) -> dict:
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    got, valid, grid = _read(output)
    if grid != _read(reference)[2]:
        return {"correct": False, "reason": "not on the input grid"}
    mask_errors = int(np.count_nonzero(valid != keep))
    both = valid & keep
    worst = float(np.max(np.abs(got[both] - expected[both]))) if both.any() else 0.0
    return {"correct": mask_errors == 0 and worst <= atol, "reason": "ok" if mask_errors == 0 and worst <= atol
            else f"{mask_errors} cells valid where they should not be (or the reverse); max |diff| {worst:.6g}",
            "mask_errors": mask_errors, "max_abs_diff": worst}


def oracle_blue(inputs: Path, outputs: Path) -> dict:
    # The window's stored values already include the BOA offset (the item's earthsearch:boa_offset_applied;
    # the darkest DN would decode negative with it), so reflectance is DN x 1e-4; DN 0 is fill.
    dn, _valid, _ = _read(inputs / "blue_dn.tif")
    return _compare(outputs / "blue_reflectance.tif", inputs / "blue_dn.tif", dn * 1e-4, dn > 0, 1e-4)


def oracle_swir(inputs: Path, outputs: Path) -> dict:
    dn, _valid, _ = _read(inputs / "swir_dn.tif")
    scl, _scl_valid, _ = _read(inputs / "scl.tif")
    keep = (dn > 0) & np.isin(scl, [4, 5, 6, 11])
    return _compare(outputs / "swir_clear_reflectance.tif", inputs / "swir_dn.tif", dn * 1e-4, keep, 1e-4)


def oracle_feet(inputs: Path, outputs: Path) -> dict:
    metres, valid, _ = _read(inputs / "kauai_dem.tif")  # the file's nodata (-999999) is its fill
    return _compare(outputs / "kauai_elevation_ft.tif", inputs / "kauai_dem.tif", metres / 0.3048, valid, 1e-2)


def oracle_slope(inputs: Path, outputs: Path) -> dict:
    output = outputs / "slope_deg.tif"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    z, valid, grid = _read(inputs / "svalbard_dem.tif")
    got, got_valid, got_grid = _read(output)
    if got_grid != grid:
        return {"correct": False, "reason": "not on the input grid"}
    transform = grid[2]
    geod = Geod(ellps="WGS84")
    rows = np.arange(z.shape[0])
    lat = transform[5] + (rows + 0.5) * transform[4]
    lon = transform[2]
    dx = np.array([geod.inv(lon, la, lon + transform[0], la)[2] for la in lat])
    dy = abs(geod.inv(lon, lat[0], lon, lat[0] + transform[4])[2])
    gx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx[1:-1, None])
    gy = (z[2:, 1:-1] - z[:-2, 1:-1]) / (2 * dy)
    expected = np.degrees(np.arctan(np.hypot(gx, gy)))
    interior = valid[1:-1, 1:-1] & got_valid[1:-1, 1:-1]
    if interior.sum() < 0.9 * interior.size:
        return {"correct": False, "reason": "most interior cells are nodata"}
    diff = np.abs(got[1:-1, 1:-1][interior] - expected[interior])
    median, p95 = float(np.median(diff)), float(np.percentile(diff, 95))
    # Horn and central differences agree within these bounds; degrees taken as lengths, or longitude not
    # scaled by latitude (x spacing 4.8x too long at 78 N), do not.
    correct = median <= 0.5 and p95 <= 3.0
    return {"correct": correct, "reason": "ok" if correct else f"median |diff| {median:.3g} deg, p95 {p95:.3g} deg",
            "median_abs_diff_deg": median, "p95_abs_diff_deg": p95}


def oracle_area(inputs: Path, outputs: Path) -> dict:
    output = outputs / "iceland_area.geojson"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    try:
        features = json.loads(output.read_text(encoding="utf-8"))["features"]
        value = float(features[0]["properties"]["area_km2"])
        geometry = features[0]["geometry"]
    except (ValueError, KeyError, IndexError, TypeError):
        return {"correct": False, "reason": "not a GeoJSON feature with a numeric area_km2"}
    source = json.loads((inputs / "countries.geojson").read_text(encoding="utf-8"))["features"]
    iceland = [f for f in source if f["properties"].get("NAME") == "Iceland"][0]["geometry"]
    geod = Geod(ellps="WGS84")
    polygons = [iceland["coordinates"]] if iceland["type"] == "Polygon" else iceland["coordinates"]
    truth = sum(abs(geod.polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])[0])
                * (1 if index == 0 else -1) for polygon in polygons for index, ring in enumerate(polygon)) / 1e6
    error = abs(value - truth) / truth
    same_shape = geometry.get("type") in ("Polygon", "MultiPolygon")
    correct = error <= 0.01 and same_shape
    return {"correct": correct, "reason": "ok" if correct else f"area_km2 {value:.6g} against {truth:.6g}",
            "relative_error": error}


ORACLES = {"p4-s2-blue-reflectance": oracle_blue, "p4-s2-swir-clear": oracle_swir, "p4-kauai-feet": oracle_feet,
           "p4-svalbard-slope": oracle_slope, "p4-iceland-area": oracle_area}


# -- verification labels from the host trace: names and enums only, never values -----------------------------


def _grade(text: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
        grade = payload.get("grade") or report.get("grade")
        status = (report.get("verification") or {}).get("status") if isinstance(report.get("verification"), dict) \
            else None
        return (grade if grade in GRADES else None), (status if status in STATUSES else None)
    found = re.search(r'"grade"\s*:\s*"(' + "|".join(GRADES) + ')"', str(text or ""))
    status = re.search(r'"verification"\s*:\s*\{[^{}]*?"status"\s*:\s*"(' + "|".join(STATUSES) + ')"', str(text or ""))
    return (found.group(1) if found else None), (status.group(1) if status else None)


def verification_calls(events, deliverables: tuple[str, ...]) -> list[dict]:
    calls = []
    for _stamp, event in events:
        if not isinstance(event, dict) or event.get("type") != "tool_use":
            continue
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        name = str(part.get("tool") or "")
        if not name.startswith("terraproof_"):
            continue
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        arguments = state.get("input") if isinstance(state.get("input"), dict) else {}
        paths = arguments.get("paths") if isinstance(arguments.get("paths"), list) else []
        grade, status = _grade(state.get("output"))
        calls.append({
            "tool": name.removeprefix("terraproof_"),
            "argument_names": sorted(str(key) for key in arguments),
            "profiles": sorted(p for p in (arguments.get("profiles") or []) if isinstance(p, str)
                               and re.fullmatch(r"[a-z-]{1,40}", p)),
            "contract": arguments.get("contract") is not None,
            "targets_deliverable": any(str(p).replace("\\", "/").rsplit("/", 1)[-1] in deliverables for p in paths),
            "grade": grade, "verification_status": status,
            "status": "failed" if state.get("status") == "error" else "completed",
        })
    return calls


class VerificationAdapter(OpenCodeHostAdapter):
    """The registered OpenCode adapter, keeping the verification labels of each run's trace."""

    def __init__(self, *args, deliverables: dict[str, tuple[str, ...]], **kwargs):
        super().__init__(*args, **kwargs)
        self.deliverables = deliverables
        self.last_calls: list[dict] = []

    def run(self, request: AgentRequest):
        command = opencode_lift_command(self.executable, request.project, self.model, self.variant)
        code, lines, _stderr, timed_out = run_contained(command, request.project, self._env(request.condition),
                                                        request.timeout_seconds)
        events, invalid = _json_lines(lines)
        result = opencode_trace(events, request.condition, (), timed_out=timed_out)
        if (code not in (0, None) or invalid) and result.status == "completed":
            result.status = "failed"
            result.turn["status"], result.turn["reason"] = "error", "nonzero host exit or invalid JSONL"
        self.last_calls = verification_calls(events, self.deliverables[request.task_id])
        return result

    def preflight(self, request: AgentRequest) -> dict:
        """The registered preflight, probing a P4 input; a vector-only task's read probe uses pyogrio."""
        inputs = {entry["task"].task_id: entry["task"].inputs for entry in TASKS}[request.task_id]
        raster = next((name for name in inputs if name.endswith(".tif")), None)
        original = agent_lift._probe_input
        agent_lift._probe_input = lambda _task_id: raster or inputs[0]
        try:
            checks = super().preflight(request)
        finally:
            agent_lift._probe_input = original
        if raster is None:
            env = self._env(request.condition)
            python = shutil.which("python", path=env["PATH"])
            script = ("import pathlib, pyogrio, sys; pyogrio.read_info(sys.argv[1]); print('READ-OK', flush=True); "
                      "p = pathlib.Path('outputs') / '.preflight-probe'; p.write_text('probe'); p.unlink(); "
                      "print('WRITE-OK')")
            probe = subprocess.run([python, "-c", script, str(Path("inputs") / inputs[0])], cwd=request.project,
                                   env=env, capture_output=True, text=True, timeout=120, check=False) if python else None
            # The registered probe stops at its raster read, so both of its later checks are replaced.
            checks["unsandboxed_read_inputs"] = bool(probe and "READ-OK" in probe.stdout)
            checks["unsandboxed_write_outputs"] = bool(probe and "WRITE-OK" in probe.stdout)
        return checks


# -- calibration: each oracle must accept a right deliverable and reject a known mistake ---------------------


def _write_like(reference: Path, path: Path, values, keep) -> None:
    with rasterio.open(reference) as src:
        profile = dict(driver="GTiff", width=src.width, height=src.height, count=1, dtype="float32", crs=src.crs,
                       transform=src.transform, nodata=-9999.0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.where(keep, values, -9999.0).astype("float32"), 1)


def _horn_slope(z, transform, lat_scaled: bool):
    geod = Geod(ellps="WGS84")
    lat = transform[5] + (np.arange(z.shape[0]) + 0.5) * transform[4]
    dx = (np.array([geod.inv(transform[2], la, transform[2] + transform[0], la)[2] for la in lat])[:, None]
          if lat_scaled else abs(transform[0]) * 111320.0)
    dy = abs(transform[4]) * 111320.0 if not lat_scaled else abs(geod.inv(transform[2], lat[0], transform[2],
                                                                           lat[0] + transform[4])[2])
    p = np.pad(z, 1, mode="edge")
    gx = ((p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])) / (8 * dx)
    gy = ((p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])) / (8 * dy)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def calibrate(entry: dict, inputs: Path, root: Path) -> dict:
    """Write one right and one wrong deliverable and score both; a task is eligible only if they split."""
    task_id = entry["task"].task_id
    verdicts = {}
    for label in ("right", "wrong"):
        outputs = root / label
        outputs.mkdir(parents=True)
        if task_id == "p4-s2-blue-reflectance":
            dn, _v, _ = _read(inputs / "blue_dn.tif")
            _write_like(inputs / "blue_dn.tif", outputs / "blue_reflectance.tif",
                        dn * 1e-4 - (0.1 if label == "wrong" else 0.0), dn > 0)
        elif task_id == "p4-s2-swir-clear":
            dn, _v, _ = _read(inputs / "swir_dn.tif")
            scl, _s, _ = _read(inputs / "scl.tif")
            codes = [4, 5, 6, 7, 11] if label == "wrong" else [4, 5, 6, 11]  # wrong keeps low-probability cloud
            _write_like(inputs / "swir_dn.tif", outputs / "swir_clear_reflectance.tif", dn * 1e-4,
                        (dn > 0) & np.isin(scl, codes))
        elif task_id == "p4-kauai-feet":
            metres, valid, _ = _read(inputs / "kauai_dem.tif")
            _write_like(inputs / "kauai_dem.tif", outputs / "kauai_elevation_ft.tif",
                        metres if label == "wrong" else metres * 3.28084, valid)
        elif task_id == "p4-svalbard-slope":
            z, valid, grid = _read(inputs / "svalbard_dem.tif")
            _write_like(inputs / "svalbard_dem.tif", outputs / "slope_deg.tif",
                        _horn_slope(z, grid[2], lat_scaled=label == "right"), valid)
        else:
            source = json.loads((inputs / "countries.geojson").read_text(encoding="utf-8"))
            feature = [f for f in source["features"] if f["properties"].get("NAME") == "Iceland"][0]
            from shapely.geometry import shape
            planar = shape(feature["geometry"]).area  # square degrees, the classic mistake
            area = abs(Geod(ellps="WGS84").geometry_area_perimeter(shape(feature["geometry"]))[0]) / 1e6
            document = {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"NAME": "Iceland", "area_km2": planar if label == "wrong" else area},
                 "geometry": feature["geometry"]}]}
            (outputs / "iceland_area.geojson").write_text(json.dumps(document), encoding="utf-8")
        verdicts[label] = ORACLES[task_id](inputs, outputs)
    eligible = verdicts["right"]["correct"] and not verdicts["wrong"]["correct"]
    return {"task": task_id, "eligible": eligible,
            "right": verdicts["right"]["reason"], "wrong": verdicts["wrong"]["reason"]}


# -- run and summarize ---------------------------------------------------------------------------------------


def behaviour(calls: list[dict]) -> dict:
    on_deliverable = [c for c in calls if c["tool"] == "run_checks" and c["targets_deliverable"]
                      and c["status"] == "completed"]
    last = on_deliverable[-1] if on_deliverable else None
    return {
        "terraproof_calls": len(calls),
        "called_propose_contract": any(c["tool"] == "propose_contract" for c in calls),
        "checked_deliverable": bool(on_deliverable),
        "declared_on_deliverable": any(c["profiles"] or c["contract"] for c in on_deliverable),
        "last_grade": last["grade"] if last else None,
        "last_coverage_assessed": bool(last and (last["profiles"] or last["contract"])),
        "last_verification_status": last["verification_status"] if last else None,
    }


def summarize(rows: list[dict]) -> dict:
    ran = [r for r in rows if r.get("host_status") is not None]
    clean = [r for r in ran if not r["agent"]["contamination"]]
    count = lambda key, pool: sum(bool(r["behaviour"][key]) for r in pool)  # noqa: E731
    wrong = [r for r in ran if not r["oracle"]["correct"]]
    return {
        "runs_started": len(ran), "completed": sum(r["host_status"] == "completed" for r in ran),
        "contamination_labelled": len(ran) - len(clean),
        "deliverable_correct": sum(r["oracle"]["correct"] for r in ran),
        "called_propose_contract": count("called_propose_contract", ran),
        "checked_deliverable": count("checked_deliverable", ran),
        "declared_on_deliverable": count("declared_on_deliverable", ran),
        "last_check_coverage_assessed": count("last_coverage_assessed", ran),
        "last_grade": {grade: sum(r["behaviour"]["last_grade"] == grade for r in ran) for grade in (*GRADES, None)},
        "false_assurance_wrong_seen_decision_grade": sum(r["behaviour"]["last_grade"] == "decision-grade"
                                                         for r in wrong),
        "wrong_seen_checks_passed": sum(r["behaviour"]["last_grade"] == "checks-passed" for r in wrong),
        "by_task": {task: {"runs": sum(r["task"] == task for r in ran),
                           "correct": sum(r["oracle"]["correct"] for r in ran if r["task"] == task),
                           "checked": sum(r["behaviour"]["checked_deliverable"] for r in ran if r["task"] == task),
                           "declared": sum(r["behaviour"]["declared_on_deliverable"] for r in ran
                                           if r["task"] == task)}
                    for task in sorted({r["task"] for r in ran})},
    }


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
    return {"schema": "terraproof.phase8.p4/0.1", "model": MODEL, "host_version": HOST_VERSION,
            "calibration": calibration,
            "design": {"tasks": [e["task"].task_id for e in TASKS], "runs_per_task": runs,
                       "planned_invocations": planned, "started": started, "preflight_only": preflight_only,
                       "condition": WITH, "order": "every task once, then again"},
            "runs": rows, "summary": None if preflight_only else summarize(rows)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache", type=Path, help="the real-data bundle's fetch.py cache")
    parser.add_argument("--opencode-executable", type=Path, required=True, help="native opencode.exe")
    parser.add_argument("--agent-python-with", type=Path, required=True, help="venv holding this branch's wheel")
    parser.add_argument("--work-root", type=Path, help="empty directory outside the checkout for the projects")
    parser.add_argument("--preflight-only", action="store_true", help="prepare and preflight every project; no agent")
    parser.add_argument("--approve-model-calls", type=int, metavar="N", help=f"explicit approval: N must be {RUNS * len(TASKS)}")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "phase8-p4.json")
    args = parser.parse_args(argv)
    planned = RUNS * len(TASKS)
    base = ["python", "tests/phase8_p4.py", str(args.cache), "--opencode-executable", str(args.opencode_executable),
            "--agent-python-with", str(args.agent_python_with), "--work-root", str(args.work_root or "WORK_DIR")]
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
    adapter = VerificationAdapter(executable, MODEL, None, None, str(args.agent_python_with),
                                  deliverables={e["task"].task_id: e["task"].deliverable_names for e in TASKS})
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
