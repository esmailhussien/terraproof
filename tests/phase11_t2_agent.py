#!/usr/bin/env python3
"""Phase 11 T2: do agents declare their pipeline in a project file, and does it catch their mistakes? Plans by default.

Three multi-deliverable pipelines on spent cached sources (Q0, S0b), "with" Terraproof only, four runs each:
12 invocations on OpenCode Go `opencode-go/mimo-v2.6-flash` (OpenCode 1.19.4), 1800 s per run (1200 s in attempt 1). The brief is
neutral and never mentions verification or a project file. The MCP server is wrapped to snapshot `outputs/`
and the project file before each verification call (tests/phase11_snapshot_server.py), so every verdict the
agent saw is scored against the oracle on the outputs as they were. Reported, as names and enums only:

- adoption: a valid project file at the end and at least one `verify_project` call on outputs;
- per call and deliverable: what the agent was shown, and the oracle on that call's snapshot;
- false assurance (oracle-wrong, shown `verified` or `decision-grade`), saves (oracle-wrong at a call that
  did not certify it, correct at the end), false alarms (oracle-correct, shown `failed`);
- each declared deliverable's goals and key bindings against the reference declaration;
- the registered reference project file, verified on the final outputs.

Committed before any T2 run (docs/plans/Terraproof_Phase11_PLAN.md registers the reading). Each oracle
recomputes the truth with numpy, rasterio and pyproj, never Terraproof; calibration repeats before any run.

    python tests/phase11_t2_agent.py --opencode-executable EXE --agent-python-with PY                 # plan
    python tests/phase11_t2_agent.py ... --work-root DIR --calibrate-only                            # no host
    python tests/phase11_t2_agent.py ... --work-root DIR --preflight-only                            # no model
    python tests/phase11_t2_agent.py ... --work-root DIR --approve-model-calls 12
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import numpy as np
import rasterio
from pyproj import Geod

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase8_p4 as p4  # noqa: E402  (adapter, raster helpers)
from agent_lift import ROOT, _json_lines, opencode_lift_command, opencode_trace, probe_opencode, run_contained, \
    shell_command  # noqa: E402

from terraproof import project as tp_project  # noqa: E402
from terraproof.evals.harness import _sanitize  # noqa: E402
from terraproof.evals.lift import (  # noqa: E402
    FLOAT_GRID, PREFLIGHT_FAILED, PREFLIGHT_ONLY, WITH, AgentRequest, LiftTask, _install, brief, classify_attempt,
    project_preflight, to_json,
)

RUNS, MODEL, HOST_VERSION, TIMEOUT = 4, p4.MODEL, p4.HOST_VERSION, 1800.0
WRAPPER = Path(__file__).resolve().parent / "phase11_snapshot_server.py"
CACHE = ROOT / ".terracache"
USABLE = [4, 5, 6, 11]
MASK = "single-band uint8 GeoTIFF on the grid of `scl.tif`, 1 where the pixel is usable and 0 where it is not"
CERTIFIED = ("verified", "decision-grade")
ADOPTION_BAR, SAVES_BAR, SAVE_RUNS_BAR = 6, 2, 2

TASKS = (
    {"task": LiftTask("t2-s2-pipeline", ("nir_dn.tif", "scl.tif", "scene_item.json"),
                      (("nir_reflectance.tif", f"surface reflectance, {FLOAT_GRID}"),
                       ("usable_mask.tif", MASK),
                       ("scene_summary.json", "JSON object with `usable_share`, the fraction of `scl.tif` cells "
                                              "that are usable (0 to 1), and `mean_nir_reflectance`, the mean "
                                              "surface reflectance of the valid NIR cells")), ()),
     "sources": {"nir_dn.tif": "q0/s2-v0/wa_B08.tif", "scl.tif": "q0/s2-v0/wa_SCL.tif",
                 "scene_item.json": "q0/s2-v0/item.json"},
     "prompt": "Prepare this Sentinel-2 L2A window for analysis. `nir_dn.tif` is a window of the scene's `nir` "
               "asset, `scl.tif` the matching window of its scene classification (`scl` asset), and "
               "`scene_item.json` the scene's STAC item from Earth Search. Vegetation, not-vegetated, water and "
               "snow/ice pixels are usable; every other class is not.",
     "reference": [
         {"name": "nir reflectance", "outputs": ["outputs/nir_reflectance.tif"], "goals": ["scaled-reflectance"],
          "reference_input": "inputs/nir_dn.tif", "decode_scale": 0.0001, "decode_offset": 0.0,
          "expect": "reflectance"},
         {"name": "usable mask", "outputs": ["outputs/usable_mask.tif"], "goals": ["qa-masked"],
          "qa_path": "inputs/scl.tif", "qa_kind": "keep-codes", "qa_keep_codes": USABLE,
          "output_form": "validity-mask"},
         {"name": "scene summary", "outputs": ["outputs/scene_summary.json"], "goals": ["summary-value"],
          "summaries": [{"key": "usable_share", "statistic": "fraction", "unit": "fraction",
                         "source": "inputs/scl.tif", "codes": USABLE},
                        {"key": "mean_nir_reflectance", "statistic": "mean", "source": "inputs/nir_dn.tif",
                         "scale": 0.0001, "offset": 0.0}]}]},
    {"task": LiftTask("t2-norway-terrain", ("norway_dem.tif",),
                      (("slope_deg.tif", f"terrain slope in degrees, {FLOAT_GRID}; edge cells may be nodata"),
                       ("elevation_ft.tif", f"elevation in international feet, {FLOAT_GRID}"),
                       ("terrain_summary.json", "JSON object with `mean_elevation_m` and `max_elevation_m`, the "
                                                "mean and maximum height of the window's cells in metres")), ()),
     "sources": {"norway_dem.tif": "s0b-seal-fetch/copdem/norway_win.tif"},
     "prompt": "Prepare terrain layers from this Copernicus DEM GLO-30 window in northern Norway. Heights are "
               "metres above EGM2008.",
     "reference": [
         {"name": "slope", "outputs": ["outputs/slope_deg.tif"], "goals": ["slope-from-dem"],
          "dem": "inputs/norway_dem.tif", "dem_vertical_unit": "metre", "slope_unit": "degrees"},
         {"name": "elevation in feet", "outputs": ["outputs/elevation_ft.tif"], "goals": ["vertical-units"],
          "vertical_operation": "convert", "vertical_sources": ["inputs/norway_dem.tif"],
          "vertical_source_units": ["metre"], "vertical_unit": "foot"},
         {"name": "terrain summary", "outputs": ["outputs/terrain_summary.json"], "goals": ["summary-value"],
          "summaries": [{"key": "mean_elevation_m", "statistic": "mean", "source": "inputs/norway_dem.tif"},
                        {"key": "max_elevation_m", "statistic": "max", "source": "inputs/norway_dem.tif"}]}]},
    {"task": LiftTask("t2-socal-coast", ("coast_dem.tif", "coast_dem.xml"),
                      (("elevation_ft.tif", f"elevation in international feet, {FLOAT_GRID}"),
                       ("coast_summary.json", "JSON object with `valid_cell_count`, how many cells hold a height, "
                                              "and `mean_elevation_m`, their mean height in metres")), ()),
     "sources": {"coast_dem.tif": "s0b-seal-fetch/usgs3dep/USGS_13_n33w118_win.tif",
                 "coast_dem.xml": "s0b-seal-fetch/usgs3dep/USGS_13_n33w118.xml"},
     "prompt": "Prepare this USGS 3DEP 1/3 arc-second elevation window of the southern California coast. "
               "`coast_dem.xml` is the tile's metadata.",
     "reference": [
         {"name": "elevation in feet", "outputs": ["outputs/elevation_ft.tif"],
          "goals": ["vertical-units", "nodata-support"],
          "vertical_operation": "convert", "vertical_sources": ["inputs/coast_dem.tif"],
          "vertical_source_units": ["metre"], "vertical_unit": "foot",
          "support_sources": ["inputs/coast_dem.tif"], "support_rule": "all"},
         {"name": "coast summary", "outputs": ["outputs/coast_summary.json"], "goals": ["summary-value"],
          "summaries": [{"key": "valid_cell_count", "statistic": "count", "source": "inputs/coast_dem.tif"},
                        {"key": "mean_elevation_m", "statistic": "mean", "source": "inputs/coast_dem.tif"}]}]},
)


# -- oracles: numpy, rasterio and pyproj only --------------------------------------------------------------


def _numbers(path: Path, keys: tuple[str, ...]) -> dict | str:
    if not path.is_file():
        return "missing"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        return {key: float(report[key]) for key in keys}
    except (ValueError, KeyError, TypeError):
        return "no numeric " + " and ".join(keys)


def _close(got: float, truth: float) -> bool:
    return abs(got - truth) <= 1e-3 * abs(truth) + 1e-3


def oracle_nir(inputs: Path, outputs: Path) -> dict:
    # Earth Search's sentinel-2-l2a stores DNs with the BOA offset already applied (earthsearch:boa_offset_applied,
    # although raster:bands still lists offset -0.1), so reflectance is DN x 1e-4; DN 0 is fill.
    dn, _valid, _ = p4._read(inputs / "nir_dn.tif")
    return p4._compare(outputs / "nir_reflectance.tif", inputs / "nir_dn.tif", dn * 1e-4, dn > 0, 1e-4)


def oracle_mask(inputs: Path, outputs: Path) -> dict:
    output = outputs / "usable_mask.tif"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    with rasterio.open(inputs / "scl.tif") as src, rasterio.open(output) as dst:
        if (dst.width, dst.height, dst.transform, dst.crs) != (src.width, src.height, src.transform, src.crs):
            return {"correct": False, "reason": "not on the scl grid"}
        keep = np.isin(src.read(1), USABLE)
        usable = dst.read(1) == 1
    errors = int(np.count_nonzero(usable != keep))
    return {"correct": errors == 0, "reason": "ok" if not errors else f"{errors} cells disagree", "mask_errors": errors}


def oracle_scene_summary(inputs: Path, outputs: Path) -> dict:
    got = _numbers(outputs / "scene_summary.json", ("usable_share", "mean_nir_reflectance"))
    if isinstance(got, str):
        return {"correct": False, "reason": got}
    with rasterio.open(inputs / "scl.tif") as src:
        scl = src.read(1)
    dn, _valid, _ = p4._read(inputs / "nir_dn.tif")
    share = float(np.isin(scl[scl != 0], USABLE).mean())
    mean = float((dn[dn > 0] * 1e-4).mean())
    ok = abs(got["usable_share"] - share) <= 1e-4 and abs(got["mean_nir_reflectance"] - mean) <= 1e-4
    return {"correct": ok, "reason": "ok" if ok else f"share {got['usable_share']:.6g} vs {share:.6g}, mean "
            f"{got['mean_nir_reflectance']:.6g} vs {mean:.6g}"}


def oracle_slope(inputs: Path, outputs: Path) -> dict:
    output = outputs / "slope_deg.tif"
    if not output.is_file():
        return {"correct": False, "reason": "missing"}
    z, valid, grid = p4._read(inputs / "norway_dem.tif")
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
    delivered = got[1:-1, 1:-1][interior]
    # Either standard stencil on true ground spacing is right; latitude ignored is far off at 69 N.
    median, p95 = min((float(np.median(d)), float(np.percentile(d, 95)))
                      for d in (np.abs(delivered - central[interior]), np.abs(delivered - horn[interior])))
    correct = median <= 0.2 and p95 <= 1.0
    return {"correct": correct, "reason": "ok" if correct else f"median {median:.3g} deg, p95 {p95:.3g} deg",
            "median_abs_diff_deg": median, "p95_abs_diff_deg": p95}


def _oracle_feet(dem: str):
    def oracle(inputs: Path, outputs: Path) -> dict:
        metres, valid, _ = p4._read(inputs / dem)  # the file's nodata is its fill; real zeros are heights
        return p4._compare(outputs / "elevation_ft.tif", inputs / dem, metres / 0.3048, valid, 1e-2)
    return oracle


def oracle_terrain_summary(inputs: Path, outputs: Path) -> dict:
    got = _numbers(outputs / "terrain_summary.json", ("mean_elevation_m", "max_elevation_m"))
    if isinstance(got, str):
        return {"correct": False, "reason": got}
    heights, valid, _ = p4._read(inputs / "norway_dem.tif")
    mean, top = float(heights[valid].mean()), float(heights[valid].max())
    ok = _close(got["mean_elevation_m"], mean) and _close(got["max_elevation_m"], top)
    return {"correct": ok, "reason": "ok" if ok else f"mean {got['mean_elevation_m']:.6g} vs {mean:.6g}, max "
            f"{got['max_elevation_m']:.6g} vs {top:.6g}"}


def oracle_coast_summary(inputs: Path, outputs: Path) -> dict:
    got = _numbers(outputs / "coast_summary.json", ("valid_cell_count", "mean_elevation_m"))
    if isinstance(got, str):
        return {"correct": False, "reason": got}
    heights, valid, _ = p4._read(inputs / "coast_dem.tif")
    count, mean = int(valid.sum()), float(heights[valid].mean())
    ok = got["valid_cell_count"] == count and _close(got["mean_elevation_m"], mean)
    return {"correct": ok, "reason": "ok" if ok else f"count {got['valid_cell_count']:.0f} vs {count}, mean "
            f"{got['mean_elevation_m']:.6g} vs {mean:.6g}"}


ORACLES = {
    "t2-s2-pipeline": {"nir_reflectance.tif": oracle_nir, "usable_mask.tif": oracle_mask,
                       "scene_summary.json": oracle_scene_summary},
    "t2-norway-terrain": {"slope_deg.tif": oracle_slope, "elevation_ft.tif": _oracle_feet("norway_dem.tif"),
                          "terrain_summary.json": oracle_terrain_summary},
    "t2-socal-coast": {"elevation_ft.tif": _oracle_feet("coast_dem.tif"), "coast_summary.json": oracle_coast_summary},
}


def score(task_id: str, inputs: Path, outputs: Path) -> dict:
    return {name: oracle(inputs, outputs) for name, oracle in ORACLES[task_id].items()}


# -- calibration: right outputs, and one wrong output per trap ------------------------------------------------


def _write_mask(reference: Path, path: Path, keep) -> None:
    with rasterio.open(reference) as src:
        profile = dict(src.profile, dtype="uint8", nodata=None, count=1)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(keep.astype("uint8"), 1)


def _central_slope(z, transform, lat_scaled: bool):
    """Slope in degrees by numpy.gradient: on WGS84 ground spacing, or with degrees as 111.32 km everywhere."""
    geod = Geod(ellps="WGS84")
    lat = transform[5] + (np.arange(z.shape[0]) + 0.5) * transform[4]
    if lat_scaled:
        dx = np.array([geod.inv(transform[2], la, transform[2] + transform[0], la)[2] for la in lat])[:, None]
        dy = abs(geod.inv(transform[2], lat[0], transform[2], lat[0] + transform[4])[2])
    else:
        dx, dy = abs(transform[0]) * 111320.0, abs(transform[4]) * 111320.0
    gy, gx = np.gradient(z)
    return np.degrees(np.arctan(np.hypot(gx / dx, gy / dy)))


def write_outputs(task_id: str, inputs: Path, outputs: Path, trap: str | None = None) -> None:
    """The right deliverables, with `trap` (a deliverable name) replaced by its registered mistake."""
    outputs.mkdir(parents=True, exist_ok=True)
    if task_id == "t2-s2-pipeline":
        dn, _v, _ = p4._read(inputs / "nir_dn.tif")
        with rasterio.open(inputs / "scl.tif") as src:
            scl = src.read(1)
        offset = -0.1 if trap in ("nir_reflectance.tif", "scene_summary.json") else 0.0  # offset applied twice
        codes = [2, *USABLE] if trap in ("usable_mask.tif", "scene_summary.json") else USABLE  # dark area kept
        p4._write_like(inputs / "nir_dn.tif", outputs / "nir_reflectance.tif", dn * 1e-4 + offset, dn > 0)
        _write_mask(inputs / "scl.tif", outputs / "usable_mask.tif", np.isin(scl, codes))
        (outputs / "scene_summary.json").write_text(json.dumps({
            "usable_share": float(np.isin(scl[scl != 0], codes).mean()),
            "mean_nir_reflectance": float((dn[dn > 0] * 1e-4 + offset).mean())}), encoding="utf-8")
    elif task_id == "t2-norway-terrain":
        z, valid, grid = p4._read(inputs / "norway_dem.tif")
        slope = _central_slope(z, grid[2], lat_scaled=trap != "slope_deg.tif")  # latitude ignored
        p4._write_like(inputs / "norway_dem.tif", outputs / "slope_deg.tif", slope, valid)
        feet = z if trap == "elevation_ft.tif" else z / 0.3048  # left in metres
        p4._write_like(inputs / "norway_dem.tif", outputs / "elevation_ft.tif", feet, valid)
        (outputs / "terrain_summary.json").write_text(json.dumps({
            "mean_elevation_m": float(z[valid].mean()), "max_elevation_m": float(z[valid].max())}), encoding="utf-8")
    else:
        z, valid, _ = p4._read(inputs / "coast_dem.tif")
        kept = valid & (z != 0) if trap in ("elevation_ft.tif", "coast_summary.json") else valid  # zeros dropped
        p4._write_like(inputs / "coast_dem.tif", outputs / "elevation_ft.tif", z / 0.3048, kept)
        (outputs / "coast_summary.json").write_text(json.dumps({
            "valid_cell_count": int(kept.sum()), "mean_elevation_m": float(z[kept].mean())}), encoding="utf-8")


TRAPS = {"t2-s2-pipeline": ("nir_reflectance.tif", "usable_mask.tif", "scene_summary.json"),
         "t2-norway-terrain": ("slope_deg.tif", "elevation_ft.tif"),
         "t2-socal-coast": ("elevation_ft.tif", "coast_summary.json")}


def write_reference(entry: dict, folder: Path) -> Path:
    path = folder / "terraproof.json"
    path.write_text(json.dumps({"schema": tp_project.SCHEMA, "deliverables": entry["reference"]}, indent=1),
                    encoding="utf-8")
    return path


LAYOUT = "raster.cog_layout"  # a heuristic layout screen; its warning alone keeps a correct raster at review


def reference_rows(path: Path) -> dict:
    """Each deliverable's status and non-pass findings under the reference declaration, by output file name."""
    return {Path(row["outputs"][0]).name: {"status": row["status"],
                                           "findings": [f"{f['check']}:{f['status']}" for f in row.get("findings", [])]}
            for row in tp_project.verify(path)["deliverables"]}


def passes(row: dict) -> bool:
    """Verified, or held at review only by the layout screen's warning."""
    return row["status"] == "verified" or (row["status"] == "review-required" and
                                           all(f == f"{LAYOUT}:warn" for f in row["findings"]))


def calibrate(entry: dict, root: Path, cache: Path) -> dict:
    """Right outputs: oracle-correct and reference-verified; each trap: oracle-wrong and reference-failed."""
    task_id, cases = entry["task"].task_id, {}
    for label in ("right", *TRAPS[task_id]):
        folder = root / task_id / label.replace(".", "_")
        _copy_inputs(entry, cache, folder / "inputs")
        write_outputs(task_id, folder / "inputs", folder / "outputs", None if label == "right" else label)
        oracle = score(task_id, folder / "inputs", folder / "outputs")
        rows = reference_rows(write_reference(entry, folder))
        if label == "right":
            ok = all(v["correct"] for v in oracle.values()) and all(passes(row) for row in rows.values())
        else:
            ok = not oracle[label]["correct"] and rows[label]["status"] == "failed"
        cases[label] = {"ok": ok, "oracle": {k: v["reason"] for k, v in oracle.items()}, "reference": rows}
    plan = tp_project.plan(root / task_id / "right" / "terraproof.json")
    return {"task": task_id, "eligible": all(c["ok"] for c in cases.values()) and plan["exit_code"] == 0,
            "plan_complete": plan["exit_code"] == 0, "cases": cases}


def _copy_inputs(entry: dict, cache: Path, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, relative in entry["sources"].items():
        shutil.copyfile(cache / relative, folder / name)


def source_hashes(cache: Path) -> dict:
    return {relative: hashlib.sha256((cache / relative).read_bytes()).hexdigest()
            for entry in TASKS for relative in entry["sources"].values()}


# -- the agent's declarations against the reference -----------------------------------------------------------


BINDINGS = ("decode_scale", "decode_offset", "encoding", "qa_path", "qa_keep_codes", "output_form", "dem",
            "dem_vertical_unit", "slope_unit", "vertical_source_units", "vertical_unit", "support_rule")
SUMMARY_FIELDS = ("statistic", "codes", "scale", "offset", "unit")


def read_project_file(folder: Path) -> tuple[str, list[dict]]:
    """('valid' | 'invalid' | 'none', raw deliverables) for the project file in `folder`."""
    path = next((folder / name for name in tp_project.FILENAMES if (folder / name).is_file()), None)
    if path is None:
        return "none", []
    try:
        tp_project.load_project(path)
        state = "valid"
    except Exception:
        state = "invalid"
    try:
        if path.suffix == ".toml":
            import tomllib
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
        deliverables = raw.get("deliverables") if isinstance(raw, dict) else None
        return state, [d for d in deliverables or [] if isinstance(d, dict)]
    except Exception:
        return "invalid", []


def _same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        try:
            return sorted(a) == sorted(b)
        except TypeError:
            return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= 1e-12
    if isinstance(a, str) and isinstance(b, str):
        return a.replace("\\", "/").rsplit("/", 1)[-1].lower() == b.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return a == b


def faithfulness(entry: dict, declared: list[dict]) -> dict:
    """Per required deliverable: declared or not, goals covering the reference's, and key bindings compared."""
    found = {}
    for reference in entry["reference"]:
        name = Path(reference["outputs"][0]).name
        match = next((d for d in declared if any(Path(str(o)).name == name for o in d.get("outputs") or [])), None)
        if match is None:
            found[name] = {"declared": False}
            continue
        goals = set(match.get("goals") or [])
        row = {"declared": True, "goals_cover_reference": set(reference["goals"]) <= goals,
               "checks_named_directly": bool(match.get("checks"))}
        for key in BINDINGS:
            if key in reference:
                row[key] = "absent" if key not in match else ("match" if _same(match[key], reference[key])
                                                              else "differs")
        if "summaries" in reference:
            given = {s.get("key"): s for s in match.get("summaries") or [] if isinstance(s, dict)}
            for summary in reference["summaries"]:
                other = given.get(summary["key"])
                row[f"summary:{summary['key']}"] = "absent" if other is None else (
                    "match" if all(_same(other.get(f), summary.get(f)) for f in SUMMARY_FIELDS if f in summary)
                    else "differs")
        found[name] = row
    return found


# -- snapshots: every verdict the agent saw, scored on the outputs as they were -------------------------------


def read_snapshots(task_id: str, inputs: Path, snapshots: Path, deliverables: tuple[str, ...]) -> list[dict]:
    calls = []
    for folder in sorted(snapshots.iterdir()) if snapshots.is_dir() else []:
        record_path = folder / "call.json"
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {"outcome": "lost"}
        shown = {}
        if record.get("tool") == "verify_project":
            for row in record.get("deliverables") or []:
                for name in row.get("outputs") or []:
                    if name in deliverables:
                        shown[name] = {"status": row.get("status"), "grade": row.get("grade"),
                                       "findings": row.get("findings") or []}
        elif record.get("tool") == "run_checks":
            paths = (record.get("arguments") or {}).get("paths") or []
            for path in paths:
                name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
                if name in deliverables:
                    shown[name] = {"status": record.get("verification_status"), "grade": record.get("grade")}
        oracle = score(task_id, inputs, folder / "outputs") if shown else {}
        arguments = record.get("arguments") or {}
        calls.append({"tool": record.get("tool"), "outcome": record.get("outcome"), "error": record.get("error"),
                      "declared": bool(arguments.get("profiles") or arguments.get("contract")),
                      "shown": shown,
                      "oracle": {name: oracle[name]["correct"] for name in shown}})
    return calls


def _certified(shown: dict) -> bool:
    return shown.get("status") == "verified" or shown.get("grade") == "decision-grade"


def _flagged(shown: dict) -> bool:
    """A required check failed: the call told the agent this deliverable is wrong."""
    return shown.get("status") == "failed"


def outcomes(calls: list[dict], final: dict) -> dict:
    """Per deliverable: certified-wrong at any call, saves (flagged `failed`, correct at the end), false alarms."""
    per = {}
    for name, verdict in final.items():
        seen = [(c["shown"][name], c["oracle"][name]) for c in calls if name in c.get("shown", {})]
        last = seen[-1][0] if seen else None
        per[name] = {
            "final_correct": verdict["correct"],
            "calls": len(seen),
            "certified_wrong_at_a_call": sum(_certified(s) and not ok for s, ok in seen),
            "wrong_at_a_call": sum(not ok for _s, ok in seen),
            "wrong_flagged_at_a_call": sum(not ok and _flagged(s) for s, ok in seen),
            "wrong_unflagged_at_a_call": sum(not ok and not _flagged(s) and not _certified(s) for s, ok in seen),
            "false_alarm_calls": sum(ok and _flagged(s) for s, ok in seen),
            "saved": verdict["correct"] and any(not ok and _flagged(s) for s, ok in seen),
            "last_status": last.get("status") if last else None,
            "last_grade": last.get("grade") if last else None,
            "final_false_assurance": (not verdict["correct"]) and bool(last and _certified(last)),
            "shipped_wrong_flagged": (not verdict["correct"]) and bool(last) and _flagged(last),
            "shipped_wrong_unflagged": (not verdict["correct"]) and bool(last) and not _flagged(last)
                                       and not _certified(last),
            "shipped_wrong_unchecked": (not verdict["correct"]) and not last,
        }
    return per


def trace_labels(events) -> dict:
    """Order of verification calls from the host trace: tool names and the `plan` flag only."""
    sequence = []
    for _stamp, event in events:
        part = event.get("part") if isinstance(event, dict) and event.get("type") == "tool_use" else None
        if not isinstance(part, dict) or not str(part.get("tool") or "").startswith("terraproof_"):
            continue
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        arguments = state.get("input") if isinstance(state.get("input"), dict) else {}
        sequence.append((str(part["tool"]).removeprefix("terraproof_"), arguments.get("plan") is True))
    verifies = [plan for tool, plan in sequence if tool == "verify_project"]
    return {"tools": [tool for tool, _ in sequence], "verify_project_calls": len(verifies),
            "verify_project_plan_calls": sum(verifies),
            "plan_before_first_verify": bool(verifies) and verifies[0] is True}


class SnapshotAdapter(p4.VerificationAdapter):
    """The P4/Q5.2 adapter, also keeping the trace's verification order."""

    def run(self, request: AgentRequest):
        command = opencode_lift_command(self.executable, request.project, self.model, self.variant)
        code, lines, _stderr, timed_out = run_contained(command, request.project, self._env(request.condition),
                                                        request.timeout_seconds)
        events, invalid = _json_lines(lines)
        result = opencode_trace(events, request.condition, (), timed_out=timed_out)
        if (code not in (0, None) or invalid) and result.status == "completed":
            result.status = "failed"
            result.turn["status"], result.turn["reason"] = "error", "nonzero host exit or invalid JSONL"
        self.last_calls = p4.verification_calls(events, self.deliverables[request.task_id])
        self.last_trace = trace_labels(events)
        self.last_lines = [line for _stamp, line in lines]
        return result


# -- the wrapped server must serve exactly what the stock server serves ---------------------------------------


async def _served(command: str, args: list[str], cwd: Path, timeout: float, env: dict | None) -> dict:
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command=command, args=args, cwd=str(cwd),
                                   env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(env or {})})
    async with Client(params, raise_exceptions=False, read_timeout_seconds=timeout) as client:
        tools = sorted((t.model_dump(mode="json") for t in (await client.list_tools()).tools),
                       key=lambda t: t["name"])
        return {"instructions": client.instructions, "tools": tools}


def served(command: str, args: list[str], cwd: Path, timeout: float = 60, env: dict | None = None) -> dict | None:
    try:
        return asyncio.run(asyncio.wait_for(_served(command, args, cwd, timeout, env), timeout))
    except Exception:
        return None


def wrap_config(project: Path, wrapper: Path, snapshots: Path) -> tuple[str, list[str]]:
    """Point the installed server entry at the wrapper; returns the stock command for the identity check."""
    config = project / "opencode.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    entry = data["mcp"]["terraproof"]
    stock = list(entry["command"])
    entry["command"] = [stock[0], "-I", str(wrapper), str(snapshots), str(project)]
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return stock[0], stock[1:]


def identity_checks(project: Path, stock: tuple[str, list[str]], wrapper: Path, snapshots: Path) -> dict:
    expected = served(stock[0], stock[1], project)
    wrapped = served(stock[0], ["-I", str(wrapper), str(snapshots), str(project)], project)
    return {"wrapper_serves_stock_tools": bool(expected) and bool(wrapped) and expected == wrapped,
            "wrapper_outside_project": project.resolve() not in wrapper.resolve().parents,
            "snapshots_outside_project": project.resolve() not in snapshots.resolve().parents,
            "no_snapshot_before_run": not snapshots.exists() or not any(snapshots.iterdir())}


# -- summary and the registered reading ---------------------------------------------------------------------


def summarize(rows: list[dict]) -> dict:
    ran = [r for r in rows if r.get("host_status") is not None]
    every = [(r, name, d) for r in ran for name, d in r["deliverables"].items()]
    adopted = [r for r in ran if r["adopted"]]
    saves = [(r["task"], r["run"], name) for r, name, d in every if d["saved"]]
    false_any = sum(d["certified_wrong_at_a_call"] > 0 for _r, _n, d in every)
    false_final = sum(d["final_false_assurance"] for _r, _n, d in every)
    wrong_snapshots = sum(d["wrong_at_a_call"] for _r, _n, d in every)
    summary = {
        "runs_started": len(ran), "completed": sum(r["host_status"] == "completed" for r in ran),
        "contamination_labelled": sum(bool(r["agent"]["contamination"]) for r in ran),
        "project_file": {state: sum(r["project_file"] == state for r in ran) for state in ("valid", "invalid", "none")},
        "adopted": len(adopted),
        "plan_before_first_verify": sum(r["trace"]["plan_before_first_verify"] for r in ran),
        "deliverables": len(every),
        "declared_in_project_file": sum(r["faithfulness"][n]["declared"] for r, n, _d in every),
        "goals_cover_reference": sum(bool(r["faithfulness"][n].get("goals_cover_reference")) for r, n, _d in every),
        "final_correct": sum(d["final_correct"] for _r, _n, d in every),
        "checked_at_least_once": sum(d["calls"] > 0 for _r, _n, d in every),
        "wrong_snapshots": wrong_snapshots,
        "wrong_snapshots_flagged": sum(d["wrong_flagged_at_a_call"] for _r, _n, d in every),
        "wrong_snapshots_unflagged": sum(d["wrong_unflagged_at_a_call"] for _r, _n, d in every),
        "saves": len(saves), "save_runs": len({(t, run) for t, run, _ in saves}),
        "false_assurance_any_call": false_any, "false_assurance_final": false_final,
        "false_alarm_calls": sum(d["false_alarm_calls"] for _r, _n, d in every),
        "shipped_wrong_flagged": sum(d["shipped_wrong_flagged"] for _r, _n, d in every),
        "shipped_wrong_unflagged": sum(d["shipped_wrong_unflagged"] for _r, _n, d in every),
        "shipped_wrong_unchecked": sum(d["shipped_wrong_unchecked"] for _r, _n, d in every),
        "reference_agrees_with_oracle": sum(passes(r["reference_final"][n]) == d["final_correct"]
                                            for r, n, d in every if n in r["reference_final"]),
        "by_task": {task: {"runs": sum(r["task"] == task for r in ran),
                           "adopted": sum(r["adopted"] for r in ran if r["task"] == task),
                           "final_correct": sum(d["final_correct"] for r, _n, d in every if r["task"] == task),
                           "deliverables": sum(r["task"] == task for r, _n, _d in every)}
                    for task in sorted({r["task"] for r in ran})},
    }
    summary["reading"] = reading(summary)
    return summary


def reading(summary: dict) -> str:
    """Section 4 of the Phase 11 plan, applied as registered."""
    if summary["false_assurance_any_call"] or summary["false_assurance_final"]:
        return "false assurance: fix its route first; no push"
    if summary["adopted"] < ADOPTION_BAR:
        return "adoption not met: instructions or install are the bottleneck; no push"
    if summary["saves"] >= SAVES_BAR and summary["save_runs"] >= SAVE_RUNS_BAR:
        return "adoption and value met with zero false assurance: push, PR, prepare 0.13.0"
    if summary["wrong_snapshots"] < 2:
        return "adoption met, fewer than 2 wrong snapshots: tasks too easy; inconclusive; no push"
    return "adoption met, wrong snapshots not flagged or not fixed: record the gap; no push"


# -- run ---------------------------------------------------------------------------------------------------


def run(adapter, cache: Path, work: Path, *, runs: int, mode: str, approved: int | None,
        checkpoint=None) -> dict:
    """`checkpoint(report)` is called after every agent run, so a later failure keeps the runs before it."""
    planned = len(TASKS) * runs
    if mode == "run" and approved != planned:
        raise SystemExit(f"approval {approved} does not equal the planned {planned} invocations; nothing started")
    calibration = [calibrate(entry, work / "calibration", cache) for entry in TASKS]
    report = {"schema": "terraproof.phase11.t2-agent/0.1", "model": MODEL, "host_version": HOST_VERSION,
              "sources": source_hashes(cache), "calibration": calibration,
              "design": {"tasks": [e["task"].task_id for e in TASKS], "runs_per_task": runs,
                         "planned_invocations": planned, "mode": mode, "condition": WITH,
                         "per_run_timeout_seconds": TIMEOUT, "order": "every task once, then again",
                         "bars": {"adoption": ADOPTION_BAR, "saves": SAVES_BAR, "save_runs": SAVE_RUNS_BAR}},
              "runs": [], "summary": None}
    if not all(item["eligible"] for item in calibration):
        raise SystemExit(f"calibration failed; nothing started: {json.dumps(calibration, indent=1)}")
    if mode == "calibrate":
        return report
    wrapper = work / "server" / WRAPPER.name
    wrapper.parent.mkdir(parents=True)
    shutil.copyfile(WRAPPER, wrapper)
    rows, started = [], 0
    for run_index in range(runs):
        for entry in TASKS:
            task = entry["task"]
            base = work / f"{task.task_id}-{run_index}"
            project, snapshots = base / "project", base / "snapshots"
            _copy_inputs(entry, cache, project / "inputs")
            (project / "outputs").mkdir()
            spec = SimpleNamespace(prompt=entry["prompt"])
            (project / "TASK.md").write_text(brief(task, spec), encoding="utf-8", newline="\n")
            code, skills = _install(project, "opencode", spec, adapter.agent_python_with)
            row = {"task": task.task_id, "run": run_index, "install_exit": code, "skills": skills}
            request = AgentRequest(task.task_id, WITH, run_index, project, brief(task, spec), TIMEOUT, None)
            checks = project_preflight(task, project, condition=WITH, agent="opencode", routed=skills)
            try:
                checks.update(adapter.preflight(request))  # the registered checks, on the stock install
                stock = wrap_config(project, wrapper, snapshots)
                checks.update(identity_checks(project, stock, wrapper, snapshots))
            except Exception as error:  # a broken probe must never fall through to a model call
                checks.update(adapter_preflight=False, adapter_preflight_error=type(error).__name__)
            ok = code == 0 and all(v for v in checks.values() if isinstance(v, bool))
            row["preflight"] = {"ok": ok, "checks": checks}
            if mode == "preflight" or not ok:
                row["adapter_status"] = PREFLIGHT_ONLY if ok else PREFLIGHT_FAILED
                rows.append(row)
                continue
            started += 1
            if started > planned:  # pragma: no cover - guarded by the approval check
                raise SystemExit("approved invocation count exhausted")
            result = adapter.run(request)
            # The raw host stream stays outside the project and out of the report (names and enums only there).
            (base / "trace.jsonl").write_text("".join(getattr(adapter, "last_lines", [])), encoding="utf-8")
            deliverables = task.deliverable_names
            final = score(task.task_id, project / "inputs", project / "outputs")
            calls = read_snapshots(task.task_id, project / "inputs", snapshots, deliverables)
            state, declared = read_project_file(project)
            (base / "reference").mkdir()
            reference = write_reference(entry, base / "reference")
            shutil.copytree(project / "inputs", base / "reference" / "inputs")
            shutil.copytree(project / "outputs", base / "reference" / "outputs")
            present = {name: (project / "outputs" / name).is_file() for name in deliverables}
            row.update(host_status=result.status, adapter_status=classify_attempt(result, present),
                       project_file=state, trace=adapter.last_trace,
                       adopted=state == "valid" and any(c["tool"] == "verify_project" and c["shown"] for c in calls),
                       faithfulness=faithfulness(entry, declared),
                       deliverables=outcomes(calls, final),
                       oracle={name: v["reason"] for name, v in final.items()},
                       calls=calls, reference_final=reference_rows(reference),
                       verification_calls=adapter.last_calls,
                       agent={key: value for key, value in asdict(result).items() if key != "status"})
            rows.append(row)
            if checkpoint:
                checkpoint(dict(report, runs=_sanitize(rows, work), design=dict(report["design"], started=started)))
    report["runs"] = _sanitize(rows, work)
    report["design"]["started"] = started
    report["summary"] = summarize(rows) if mode == "run" else None
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=CACHE, help="folder holding the q0/ and s0b-seal-fetch/ caches")
    parser.add_argument("--opencode-executable", type=Path, required=True, help="native opencode.exe")
    parser.add_argument("--agent-python-with", type=Path, required=True, help="venv holding this branch's wheel")
    parser.add_argument("--work-root", type=Path, help="empty directory outside the checkout for the projects")
    parser.add_argument("--calibrate-only", action="store_true", help="oracles and reference only; no host")
    parser.add_argument("--preflight-only", action="store_true", help="prepare and preflight every project; no agent")
    parser.add_argument("--approve-model-calls", type=int, metavar="N", help=f"explicit approval: N must be {RUNS * len(TASKS)}")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "phase11-t2-agent.json")
    args = parser.parse_args(argv)
    planned = RUNS * len(TASKS)
    base = ["python", "tests/phase11_t2_agent.py", "--opencode-executable", str(args.opencode_executable),
            "--agent-python-with", str(args.agent_python_with), "--work-root", str(args.work_root or "WORK_DIR")]
    modes = [args.calibrate_only, args.preflight_only, args.approve_model_calls is not None]
    if sum(modes) > 1:
        parser.error("give one of --calibrate-only, --preflight-only and --approve-model-calls")
    if not any(modes):
        print(json.dumps({"status": "plan-only (no host started, no model called)", "condition": WITH,
                          "tasks": [e["task"].task_id for e in TASKS], "runs_per_task": RUNS,
                          "planned_model_invocations": planned, "model": MODEL, "host_version": HOST_VERSION,
                          "per_run_timeout_seconds": TIMEOUT,
                          "command_to_approve": shell_command(base + ["--approve-model-calls", str(planned)]),
                          "preflight_command": shell_command(base + ["--preflight-only"]),
                          "calibration_command": shell_command(base + ["--calibrate-only"])},
                         indent=2, sort_keys=True))
        return 0
    mode = "calibrate" if args.calibrate_only else "preflight" if args.preflight_only else "run"
    work = (args.work_root or Path()).resolve()
    if args.work_root is None or ROOT.resolve() in work.parents or work == ROOT.resolve() or \
            (work.exists() and any(work.iterdir())):
        parser.error("--work-root must be an empty or new directory outside the checkout")
    adapter, version = None, None
    if mode != "calibrate":
        executable, reason, version = probe_opencode(str(args.opencode_executable), MODEL)
        if executable is None or version.split()[1:2] != [HOST_VERSION]:
            print(json.dumps({"status": "unavailable", "model_called": False,
                              "reason": reason if executable is None else f"host is {version}, registered {HOST_VERSION}"}))
            return 1
        adapter = SnapshotAdapter(executable, MODEL, None, None, str(args.agent_python_with),
                                  deliverables={e["task"].task_id: e["task"].deliverable_names for e in TASKS},
                                  inputs={e["task"].task_id: e["task"].inputs for e in TASKS})
    work.mkdir(parents=True, exist_ok=True)
    out = args.out if mode == "run" else args.out.with_name(f"{args.out.stem}-{mode}{args.out.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    host = {"name": "opencode", "version": version}

    def write(report: dict) -> None:
        out.write_text(to_json(dict(report, host=host)), encoding="utf-8", newline="\n")

    report = run(adapter, args.cache.resolve(), work, runs=RUNS, mode=mode, approved=args.approve_model_calls,
                 checkpoint=lambda partial: write(dict(partial, status="partial")))
    report["host"] = host
    write(report)
    failed = [f"{r['task']}:{r['run']}" for r in report["runs"] if r.get("adapter_status") == PREFLIGHT_FAILED]
    print(json.dumps({"status": f"{mode} complete", "report": str(out), "preflight_failures": failed,
                      "started": report["design"].get("started", 0), "summary": report["summary"]},
                     indent=2, sort_keys=True, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
