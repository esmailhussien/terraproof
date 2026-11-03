#!/usr/bin/env python3
"""Phase 11 T3: when an agent declares its pipeline and gets an output wrong, does `verify` catch it? Plans by default.

Seven headroom tasks where MiMo erred before (E4, R3), "with" Terraproof only, two runs each: 14 invocations on
OpenCode Go `opencode-go/mimo-v2.6-flash` (OpenCode 1.19.4), 1800 s per run. Each task has one deliverable,
`result.tif`, a registered oracle and seeded wrong outputs (`terraproof.evals.headroom`); the brief is the task's
registered one and never mentions verification or a project file. The host, install, snapshot wrapper and T2's
labels are reused (tests/phase11_t2_agent.py). Added: at every verification call, whether the declaration then
in the project file was faithful to the reference (its key bindings match) or a belief (they differ), and whether
the call failed it for contradicting its sources' metadata (`project.declaration`).

Registered in docs/plans/Terraproof_Phase11_PLAN.md section 7 before any run. The oracle is the task's own
(`score_outputs`'s `oracle_ok`), never Terraproof; calibration repeats before any run.

    python tests/phase11_t3_agent.py --opencode-executable EXE --agent-python-with PY                 # plan
    python tests/phase11_t3_agent.py ... --work-root DIR --calibrate-only                            # no host
    python tests/phase11_t3_agent.py ... --work-root DIR --preflight-only                            # no model
    python tests/phase11_t3_agent.py ... --work-root DIR --approve-model-calls 14
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase11_t2_agent as t2  # noqa: E402  (wrapper, adapter, labels)
from agent_lift import ROOT, probe_opencode, shell_command  # noqa: E402

from terraproof import project as tp_project  # noqa: E402
from terraproof.checks.vertical_units import unit_name  # noqa: E402
from terraproof.evals import lift  # noqa: E402
from terraproof.evals.harness import _sanitize  # noqa: E402
from terraproof.evals.lift import (  # noqa: E402
    PREFLIGHT_FAILED, PREFLIGHT_ONLY, WITH, AgentRequest, _install, brief, classify_attempt, project_preflight,
    to_json,
)

RUNS, MODEL, HOST_VERSION, TIMEOUT = 2, t2.MODEL, t2.HOST_VERSION, 1800.0
ADOPTION_BAR, SAVES_BAR, SAVE_RUNS_BAR = 7, 2, 2
RESULT = "result.tif"
LST_KEEP = [v for v in range(256) if v & 3 == 0 and (v >> 6) & 3 == 0]  # mandatory QA 00 and LST error 00


def _reference(**binding) -> list[dict]:
    return [dict(name="result", outputs=[f"outputs/{RESULT}"], **binding)]


TASKS = (
    {"task_id": "hr-flood-depth-feet", "reference": _reference(
        goals=["vertical-units"], vertical_operation="depth-below-level", vertical_sources=["inputs/dem.tif"],
        vertical_source_units=["foot"], vertical_unit="metre", vertical_level=12.0)},
    {"task_id": "hr-modis-lst-quality", "reference": _reference(
        goals=["qa-masked"], checks=["rs.scale_applied_once"], reference_input="inputs/LST_Day_1km.tif",
        decode_scale=0.02, decode_offset=0.0, unit_conversion="kelvin-to-celsius", processing_full_scan=True,
        qa_path="inputs/QC_Day.tif", qa_kind="keep-codes", qa_keep_codes=LST_KEEP)},
    {"task_id": "hr-landcover-change-fill", "reference": _reference(
        goals=["nodata-support"], support_sources=["inputs/landcover_2019.tif", "inputs/landcover_2023.tif"],
        support_source_nodata=[0, 0], support_rule="all")},
    {"task_id": "hr-reanalysis-air-temperature", "reference": _reference(
        checks=["rs.scale_applied_once"], reference_input="inputs/t2m.tif", decode_scale=0.0018,
        decode_offset=285.0, unit_conversion="kelvin-to-celsius", processing_full_scan=True)},
    {"task_id": "hr-s2-scl-red", "reference": _reference(
        goals=["qa-masked", "scaled-reflectance"], qa_path="inputs/SCL.tif", qa_kind="keep-codes",
        qa_keep_codes=[4, 5, 6], reference_input="inputs/B04.tif", decode_scale=0.0001, decode_offset=-0.1,
        expect="reflectance", processing_full_scan=True)},
    {"task_id": "hr-slope-geographic", "reference": _reference(goals=["slope-from-dem"], dem="inputs/dem.tif")},
    {"task_id": "hr-elevation-change-mixed-units", "reference": _reference(
        goals=["vertical-units"], vertical_operation="difference",
        vertical_sources=["inputs/dem_2023.tif", "inputs/dem_2015.tif"],
        vertical_source_units=["metre", "foot"], vertical_unit="metre")},
)
LIFT = {entry["task_id"]: lift.lift_task(entry["task_id"]) for entry in TASKS}
SPECS = lift._specs()
# The bindings a mistake on these tasks would change; a declaration is faithful when each the reference sets matches.
BINDINGS = ("decode_scale", "decode_offset", "unit_conversion", "qa_path", "qa_kind", "qa_keep_codes", "dem",
            "vertical_operation", "vertical_level", "vertical_sources", "vertical_source_units", "vertical_unit",
            "support_sources", "support_source_nodata", "support_rule")


# -- the oracle: the task's own, on the outputs as they are ----------------------------------------------------


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(task_id: str, inputs: Path, outputs: Path) -> dict:
    """{result.tif: correct, reason}: the registered oracle (`oracle_ok`), with the format contract reported apart."""
    task, spec = LIFT[task_id], SPECS[task_id]
    digests = {name: _digest(inputs / name) for name in task.inputs}
    with tempfile.TemporaryDirectory(prefix="tp-t3-") as scratch:
        record = lift.score_outputs(task, spec, outputs, Path(scratch) / "s", digests)
    correct = record["oracle_ok"] is True
    reason = ("missing" if not all(record["deliverables_present"].values()) else "ok" if correct else
              ",".join(record["failed_assertions"]) or record["verdict"])
    return {RESULT: {"correct": correct, "reason": reason, "contract_ok": record["contract_ok"]}}


# -- calibration: the reference passes the right output and fails every seeded one -----------------------------


def _inputs(task_id: str, generated: Path, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in LIFT[task_id].inputs:
        shutil.copyfile(generated / name, folder / name)


def calibrate(entry: dict, root: Path) -> dict:
    task_id = entry["task_id"]
    task, generated = LIFT[task_id], root / task_id / "generated"
    lift._generate(task, generated)
    cases = {}
    for label, source in (("right", RESULT), *((wrong, wrong) for _target, wrong in task.seeded)):
        folder = root / task_id / label.replace(".", "_")
        _inputs(task_id, generated, folder / "inputs")
        (folder / "outputs").mkdir(parents=True)
        shutil.copyfile(generated / source, folder / "outputs" / RESULT)
        oracle = score(task_id, folder / "inputs", folder / "outputs")[RESULT]
        row = t2.reference_rows(t2.write_reference(entry, folder))[RESULT]
        ok = (oracle["correct"] and t2.passes(row)) if label == "right" else \
            (not oracle["correct"] and row["status"] == "failed")
        cases[label] = {"ok": ok, "oracle": oracle["reason"], "reference": row}
    plan = tp_project.plan(root / task_id / "right" / "terraproof.json")
    complete = plan["exit_code"] == 0 and not any(r["conflicts"] for r in plan["deliverables"])
    return {"task": task_id, "eligible": all(c["ok"] for c in cases.values()) and complete,
            "plan_complete": complete, "cases": cases,
            "inputs": {name: _digest(generated / name) for name in task.inputs}}


# -- declarations at each call --------------------------------------------------------------------------------


def _checks(declaration: dict) -> set[str]:
    profiles = tp_project.profiles()
    goals = [g for g in declaration.get("goals") or [] if isinstance(g, str) and g in profiles]
    return {str(c) for c in declaration.get("checks") or []} | {c for g in goals for c in profiles[g]["checks"]}


def _same(a, b) -> bool:
    """T2's comparison, with path lists compared in order by file name and unit names by meaning (ft = foot)."""
    if isinstance(a, list) and isinstance(b, list) and all(isinstance(x, str) for x in a + b):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, str) and isinstance(b, str) and unit_name(a) is not None:
        return unit_name(a) == unit_name(b)
    return t2._same(a, b)


def declaration_row(entry: dict, declared: list[dict]) -> dict:
    """result.tif's declaration against the reference: declared, checks covering the reference's, key bindings."""
    reference = entry["reference"][0]
    match = next((d for d in declared if any(Path(str(o)).name == RESULT for o in d.get("outputs") or [])), None)
    if match is None:
        return {"declared": False}
    row = {"declared": True, "goals_cover_reference": _checks(reference) <= _checks(match),
           "checks_named_directly": bool(match.get("checks"))}
    for key in BINDINGS:
        if key in reference:
            row[key] = "absent" if key not in match else "match" if _same(match[key], reference[key]) else "differs"
    return row


def faithful(row: dict) -> bool:
    """Declared, with checks covering the reference's and every key binding the reference sets matching."""
    return bool(row.get("declared")) and bool(row.get("goals_cover_reference")) and \
        all(value == "match" for key, value in row.items() if key in BINDINGS)


def declarations(entry: dict, snapshots: Path) -> list[dict]:
    """For each snapshot, in call order: the project file then present, and whether it was faithful."""
    found = []
    for folder in sorted(snapshots.iterdir()) if snapshots.is_dir() else []:
        state, declared = t2.read_project_file(folder)
        row = declaration_row(entry, declared)
        found.append({"project_file": state, "faithful": faithful(row), "bindings": row})
    return found


def wrong_snapshots(calls: list[dict]) -> list[dict]:
    """Every call that showed a wrong result.tif: what it said, and the declaration it judged."""
    rows = []
    for index, call in enumerate(calls):
        shown, ok = call["shown"].get(RESULT), call["oracle"].get(RESULT)
        if shown is None or ok:
            continue
        # the wrapper records findings as "check:status"
        findings = [str(f.get("check")) if isinstance(f, dict) else str(f).rsplit(":", 1)[0]
                    for f in shown.get("findings") or []]
        rows.append({"call": index, "tool": call["tool"], "status": shown.get("status"), "grade": shown.get("grade"),
                     "flagged": t2._flagged(shown), "certified": t2._certified(shown),
                     "by_declaration_conflict": tp_project.DECLARATION in findings,
                     "declaration": call.get("declaration", {}).get("project_file"),
                     "faithful": bool(call.get("declaration", {}).get("faithful"))})
    return rows


# -- summary and the registered reading ---------------------------------------------------------------------


def summarize(rows: list[dict]) -> dict:
    summary = t2.summarize(rows)
    ran = [r for r in rows if r.get("host_status") is not None]
    wrong = [w for r in ran for w in r["wrong_snapshots"]]
    finals = [r for r in ran if not r["deliverables"][RESULT]["final_correct"]]
    summary.update(
        wrong_snapshots_by_kind={
            "flagged_by_checks": sum(w["flagged"] and not w["by_declaration_conflict"] for w in wrong),
            "flagged_by_declaration_conflict": sum(w["flagged"] and w["by_declaration_conflict"] for w in wrong),
            "certified_faithful": sum(w["certified"] and w["faithful"] for w in wrong),
            "certified_belief": sum(w["certified"] and not w["faithful"] for w in wrong),
            "unflagged_faithful": sum(not w["flagged"] and not w["certified"] and w["faithful"] for w in wrong),
            "unflagged_belief": sum(not w["flagged"] and not w["certified"] and not w["faithful"] for w in wrong)},
        false_assurance_faithful=sum(w["certified"] and w["faithful"] for w in wrong)
        + sum(r["deliverables"][RESULT]["final_false_assurance"] and r["final_declaration_faithful"] for r in finals),
        false_assurance_belief=sum(w["certified"] and not w["faithful"] for w in wrong),
        final_contract_ok=sum(bool(r["contract_ok"]) for r in ran))
    summary["reading"] = reading(summary)
    return summary


def reading(summary: dict) -> str:
    """Section 7 of the Phase 11 plan, applied as registered."""
    if summary["false_assurance_faithful"]:
        return "false assurance on a faithful declaration: a check gap; fix it first; no push"
    if summary["adopted"] < ADOPTION_BAR:
        return "adoption not met: instructions or install are the bottleneck; no push"
    belief = summary["false_assurance_belief"]
    note = f"; {belief} wrong call(s) certified on belief declarations, reported" if belief else ""
    if summary["saves"] >= SAVES_BAR and summary["save_runs"] >= SAVE_RUNS_BAR:
        return "adoption and value met, no false assurance on faithful declarations" + note
    if summary["wrong_snapshots"] < 2:
        return "adoption met, fewer than 2 wrong snapshots: tasks too easy; inconclusive; no push" + note
    return "adoption met, wrong snapshots not flagged or not fixed: record the gap; no push" + note


# -- run ---------------------------------------------------------------------------------------------------


def run(adapter, work: Path, *, runs: int, mode: str, approved: int | None, checkpoint=None) -> dict:
    """`checkpoint(report)` is called after every agent run, so a later failure keeps the runs before it."""
    planned = len(TASKS) * runs
    if mode == "run" and approved != planned:
        raise SystemExit(f"approval {approved} does not equal the planned {planned} invocations; nothing started")
    calibration = [calibrate(entry, work / "calibration") for entry in TASKS]
    report = {"schema": "terraproof.phase11.t3-agent/0.1", "model": MODEL, "host_version": HOST_VERSION,
              "calibration": calibration,
              "design": {"tasks": [e["task_id"] for e in TASKS], "runs_per_task": runs,
                         "planned_invocations": planned, "mode": mode, "condition": WITH,
                         "per_run_timeout_seconds": TIMEOUT, "order": "every task once, then again",
                         "bars": {"adoption": ADOPTION_BAR, "saves": SAVES_BAR, "save_runs": SAVE_RUNS_BAR}},
              "runs": [], "summary": None}
    if not all(item["eligible"] for item in calibration):
        raise SystemExit(f"calibration failed; nothing started: {json.dumps(calibration, indent=1)}")
    if mode == "calibrate":
        return report
    wrapper = work / "server" / t2.WRAPPER.name
    wrapper.parent.mkdir(parents=True)
    shutil.copyfile(t2.WRAPPER, wrapper)
    rows, started = [], 0
    for run_index in range(runs):
        for entry in TASKS:
            task_id = entry["task_id"]
            task, spec = LIFT[task_id], SPECS[task_id]
            base = work / f"{task_id}-{run_index}"
            project, snapshots = base / "project", base / "snapshots"
            _inputs(task_id, work / "calibration" / task_id / "generated", project / "inputs")
            (project / "outputs").mkdir()
            (project / "TASK.md").write_text(brief(task, spec), encoding="utf-8", newline="\n")
            code, skills = _install(project, "opencode", spec, adapter.agent_python_with)
            row = {"task": task_id, "run": run_index, "install_exit": code, "skills": skills}
            request = AgentRequest(task_id, WITH, run_index, project, brief(task, spec), TIMEOUT, None)
            checks = project_preflight(task, project, condition=WITH, agent="opencode", routed=skills)
            try:
                checks.update(adapter.preflight(request))  # the registered checks, on the stock install
                stock = t2.wrap_config(project, wrapper, snapshots)
                checks.update(t2.identity_checks(project, stock, wrapper, snapshots))
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
            (base / "trace.jsonl").write_text("".join(getattr(adapter, "last_lines", [])), encoding="utf-8")
            final = score(task_id, project / "inputs", project / "outputs")
            calls = t2.read_snapshots(task_id, project / "inputs", snapshots, task.deliverable_names, scorer=score)
            for call, declaration in zip(calls, declarations(entry, snapshots)):
                call["declaration"] = declaration
            state, declared = t2.read_project_file(project)
            ending = {RESULT: declaration_row(entry, declared)}
            (base / "reference").mkdir()
            reference = t2.write_reference(entry, base / "reference")
            shutil.copytree(project / "inputs", base / "reference" / "inputs")
            shutil.copytree(project / "outputs", base / "reference" / "outputs")
            present = {name: (project / "outputs" / name).is_file() for name in task.deliverable_names}
            row.update(host_status=result.status, adapter_status=classify_attempt(result, present),
                       project_file=state, trace=adapter.last_trace,
                       adopted=state == "valid" and any(c["tool"] == "verify_project" and c["shown"] for c in calls),
                       faithfulness=ending, final_declaration_faithful=faithful(ending[RESULT]),
                       deliverables=t2.outcomes(calls, final),
                       oracle={name: v["reason"] for name, v in final.items()},
                       contract_ok=final[RESULT]["contract_ok"],
                       calls=calls, wrong_snapshots=wrong_snapshots(calls),
                       reference_final=t2.reference_rows(reference),
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
    parser.add_argument("--opencode-executable", type=Path, required=True, help="native opencode.exe")
    parser.add_argument("--agent-python-with", type=Path, required=True, help="venv holding this branch's wheel")
    parser.add_argument("--work-root", type=Path, help="empty directory outside the checkout for the projects")
    parser.add_argument("--calibrate-only", action="store_true", help="oracles and reference only; no host")
    parser.add_argument("--preflight-only", action="store_true", help="prepare and preflight every project; no agent")
    parser.add_argument("--approve-model-calls", type=int, metavar="N", help=f"explicit approval: N must be {RUNS * len(TASKS)}")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "phase11-t3-agent.json")
    args = parser.parse_args(argv)
    planned = RUNS * len(TASKS)
    base = ["python", "tests/phase11_t3_agent.py", "--opencode-executable", str(args.opencode_executable),
            "--agent-python-with", str(args.agent_python_with), "--work-root", str(args.work_root or "WORK_DIR")]
    modes = [args.calibrate_only, args.preflight_only, args.approve_model_calls is not None]
    if sum(modes) > 1:
        parser.error("give one of --calibrate-only, --preflight-only and --approve-model-calls")
    if not any(modes):
        print(json.dumps({"status": "plan-only (no host started, no model called)", "condition": WITH,
                          "tasks": [e["task_id"] for e in TASKS], "runs_per_task": RUNS,
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
        adapter = t2.SnapshotAdapter(executable, MODEL, None, None, str(args.agent_python_with),
                                     deliverables={tid: task.deliverable_names for tid, task in LIFT.items()},
                                     inputs={tid: task.inputs for tid, task in LIFT.items()})
    work.mkdir(parents=True, exist_ok=True)
    out = args.out if mode == "run" else args.out.with_name(f"{args.out.stem}-{mode}{args.out.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    host = {"name": "opencode", "version": version}

    def write(report: dict) -> None:
        out.write_text(to_json(dict(report, host=host)), encoding="utf-8", newline="\n")

    report = run(adapter, work, runs=RUNS, mode=mode, approved=args.approve_model_calls,
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
