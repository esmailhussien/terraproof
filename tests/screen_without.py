#!/usr/bin/env python3
"""Phase 6 E4: the registered "without"-only screen. Prints a plan by default; model calls are opt-in.

E3 fixed the screen as the 24 `headroom-confirmation` tasks, "without" only, twice per task: 48
invocations on OpenCode Go `opencode-go/mimo-v2.6-flash` (OpenCode 1.19.4), 900 s per run.
`tests/agent_lift.py` schedules with/without pairs, so it cannot run this screen. This script reuses
its OpenCode adapter and the frozen `terraproof.evals.lift` preparation, preflight, brief and scoring
unchanged, and replaces only the schedule: one condition, run index outer, task order inner.

    python tests/screen_without.py --opencode-executable OPENCODE --agent-python-without PY
    python tests/screen_without.py ... --preflight-only
    python tests/screen_without.py ... --approve-model-calls 48

The full report is sealed evidence for after E6 (or a recorded E5 stop). Before then, read only the
printed screen summary: per-task accept, merit-rejection and unresolved counts, and the E5 status.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_lift import ROOT, OpenCodeHostAdapter, probe_opencode, shell_command  # noqa: E402

from terraproof.evals.harness import _sanitize  # noqa: E402
from terraproof.evals.lift import (  # noqa: E402
    ACCEPTED, ERROR, NOT_RUN, PREFLIGHT_FAILED, PREFLIGHT_ONLY, REJECTED, SCHEMA, WITHOUT, Adapter, AgentRequest,
    Budget, LiftError, LiftTask, _calibrate_task, _digest, _record, _select, _specs, _workspace, brief,
    classify_attempt, prepare_project, project_preflight, score_outputs, to_json,
)

COHORT = "headroom-confirmation"
RUNS = 2
MODEL = "opencode-go/mimo-v2.6-flash"
HOST_VERSION = "1.19.4"
TIMEOUT = 900.0
MIN_RETAINED = 8
STOP_STATEMENT = ("On MiMo-V2.6-Flash, this cohort leaves insufficient headroom to measure improvement "
                  "under the registered protocol.")


def screen_schedule(tasks: list[LiftTask], runs: int) -> list[tuple[int, LiftTask]]:
    """Deterministic order: every task once, then every task again."""
    return [(run_index, task) for run_index in range(runs) for task in tasks]


def classify(run: dict) -> str:
    """`accepted`, `merit` (a baseline failure on its own deliverables) or `unresolved`.

    A merit rejection needs a completed, uncontaminated host run whose delivered artifact was scored
    and rejected, or could not be read. Contamination, host failure or timeout, no deliverable,
    preflight, install or fixture failures leave the run unresolved: they are not headroom.
    """
    if run.get("accepted"):
        return ACCEPTED
    clean = run.get("host_status") == "completed" and not (run.get("agent") or {}).get("contamination")
    if clean and run.get("verdict") in (REJECTED, ERROR):
        return "merit"
    return "unresolved"


def _reason(run: dict) -> str:
    if (run.get("agent") or {}).get("contamination"):
        return "contamination"
    if run.get("host_status") not in (None, "completed"):
        return f"host-{run['host_status']}"
    return str(run.get("adapter_status") if run.get("verdict") == NOT_RUN else run.get("verdict"))


def screen_summary(task_reports: list[dict], *, minimum: int = MIN_RETAINED) -> dict:
    """E5's go/no-go from accept/reject counts and validity only.

    A task is retained with at least one merit rejection, resolved-not-retained when every run was
    accepted, and otherwise unresolved. Unresolved tasks pause the decision unless even all of them
    could not reach the minimum.
    """
    per_task = []
    for task in task_reports:
        kinds = [classify(run) for run in task["runs"]]
        unresolved = [_reason(run) for run, kind in zip(task["runs"], kinds) if kind == "unresolved"]
        per_task.append({"task": task["id"], "runs": len(kinds), "accepted": kinds.count(ACCEPTED),
                         "merit_rejections": kinds.count("merit"), "unresolved": sorted(unresolved)})
    retained = [item["task"] for item in per_task if item["merit_rejections"]]
    open_tasks = [item["task"] for item in per_task if not item["merit_rejections"] and item["unresolved"]]
    if len(retained) >= minimum:
        status = "go"
    elif len(retained) + len(open_tasks) < minimum:
        status = "stop"
    else:
        status = "paused: unresolved screening coverage"
    return {
        "retained_tasks": retained,
        "retained": len(retained),
        "unresolved_tasks": open_tasks,
        "minimum": minimum,
        "status": status,
        **({"statement": STOP_STATEMENT} if status == "stop" else {}),
        "per_task": per_task,
    }


def run_screen(adapter: Adapter, tasks: list[LiftTask], *, runs: int, budget: Budget, work_root: Path,
               allow_model_calls: bool = False, preflight_only: bool = False,
               recordings_out: Path | None = None) -> dict:
    """`run_lift`'s per-run steps for the "without" condition only, under a hard run budget."""
    planned = len(tasks) * runs
    if not preflight_only:
        if adapter.model_calls and not allow_model_calls:
            raise LiftError(f"adapter {adapter.name!r} calls a model; it needs an explicit opt-in")
        if budget.max_runs is None or planned > budget.max_runs:
            raise LiftError(f"{planned} planned agent runs exceed the approved maximum of {budget.max_runs}")
    specs = _specs()
    started = 0
    records: dict[str, list[dict]] = {task.task_id: [] for task in tasks}
    with _workspace(work_root, False, "screen") as base:
        calibration = {"tasks": [_calibrate_task(task, specs[task.task_id], base / "calibration" / task.task_id)
                                 for task in tasks]}
        calibration["eligible"] = all(item["eligible"] for item in calibration["tasks"])
        if not calibration["eligible"]:
            failing = [item["task"] for item in calibration["tasks"] if not item["eligible"]]
            raise LiftError(f"calibration failed; scoring is not trustworthy for: {failing}")
        references = {task.task_id: base / "inputs" / task.task_id for task in tasks}
        for task in tasks:
            references[task.task_id].mkdir(parents=True)
            for name in task.inputs:
                shutil.copyfile(base / "calibration" / task.task_id / "reference" / name,
                                references[task.task_id] / name)
        shutil.rmtree(base / "calibration", ignore_errors=True)
        digests = {task.task_id: {name: _digest(references[task.task_id] / name) for name in task.inputs}
                   for task in tasks}
        for sequence, (run_index, task) in enumerate(screen_schedule(tasks, runs), start=1):
            record = {"run": run_index, "condition": WITHOUT}
            run_dir = base / "runs" / f"{sequence:03d}"
            project = run_dir / "project"
            installed = prepare_project(task, specs[task.task_id], references[task.task_id], project,
                                        condition=WITHOUT, agent="opencode")
            if installed["install_exit"] not in (None, 0):
                record.update(adapter_status="install_failed", verdict=NOT_RUN, accepted=False)
                records[task.task_id].append(record)
                continue
            request = AgentRequest(task.task_id, WITHOUT, run_index, project, brief(task, specs[task.task_id]),
                                   budget.timeout_seconds, budget.per_run_usd)
            checks = project_preflight(task, project, condition=WITHOUT, agent="opencode", routed=[])
            try:
                checks.update(adapter.preflight(request))
            except Exception as error:  # a broken probe must never fall through to a model call
                checks["adapter_preflight"] = False
                checks["adapter_preflight_error"] = type(error).__name__
            preflight_ok = all(value for value in checks.values() if isinstance(value, bool))
            record["preflight"] = {"ok": preflight_ok, "checks": checks}
            if preflight_only or not preflight_ok:
                record.update(adapter_status=PREFLIGHT_ONLY if preflight_ok else PREFLIGHT_FAILED,
                              verdict=NOT_RUN, accepted=False)
                records[task.task_id].append(record)
                shutil.rmtree(run_dir, ignore_errors=True)
                continue
            if started >= budget.max_runs:  # pragma: no cover - guarded by the planned count above
                raise LiftError("approved run budget exhausted")
            started += 1
            result = adapter.run(request)
            score = score_outputs(task, specs[task.task_id], project / "outputs", run_dir / "scoring",
                                  digests[task.task_id])
            if result.contamination:
                score.update(accepted_before_contamination=score["accepted"],
                             contamination_forced_rejection=score["accepted"],
                             accepted=False, verdict=REJECTED if score["verdict"] == ACCEPTED else score["verdict"])
            record.update(adapter_status=classify_attempt(result, score["deliverables_present"]),
                          host_status=result.status, treatment_used=None, **score,
                          agent={key: value for key, value in asdict(result).items() if key != "status"})
            records[task.task_id].append(record)
            if recordings_out is not None:
                _record(Path(recordings_out), task, WITHOUT, run_index, project / "outputs", result)
            shutil.rmtree(run_dir, ignore_errors=True)
    task_reports = [{"id": task.task_id, "inputs": list(task.inputs),
                     "runs": _sanitize(sorted(records[task.task_id], key=lambda r: r["run"]), Path(base))}
                    for task in tasks]
    return {
        "schema": SCHEMA,
        "command": "python tests/screen_without.py",
        "adapter": {"name": adapter.name, "model_calls": adapter.model_calls},
        "agent_format": "opencode",
        "design": {"conditions": [WITHOUT], "cohort": COHORT, "tasks": len(tasks), "runs_per_task": runs,
                   "planned_agent_runs": planned, "started_agent_runs": started, "preflight_only": preflight_only,
                   "order": "without only; every task in cohort order, then again"},
        "budget": {**asdict(budget), "spent_usd": 0.0},
        "calibration": calibration,
        "tasks": task_reports,
        "screen": screen_summary(task_reports),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--opencode-executable", type=Path, required=True, help="native opencode.exe")
    parser.add_argument("--agent-python-without", type=Path, required=True, help="dependency-only Python")
    parser.add_argument("--preflight-only", action="store_true",
                        help="prepare every project and run the no-model host preflight; start no agent")
    parser.add_argument("--approve-model-calls", type=int, metavar="N", help=f"explicit approval: N must be {RUNS * 24}")
    parser.add_argument("--out", type=Path, default=ROOT / ".terracache" / "e4-screen.json")
    parser.add_argument("--recordings", type=Path, default=ROOT / ".terracache" / "e4-screen-rec")
    args = parser.parse_args(argv)
    tasks = _select(None, COHORT)
    planned = len(tasks) * RUNS
    approve = ["python", "tests/screen_without.py", "--opencode-executable", str(args.opencode_executable),
               "--agent-python-without", str(args.agent_python_without), "--approve-model-calls", str(planned)]
    if args.approve_model_calls is None and not args.preflight_only:
        print(json.dumps({"status": "plan-only (no host started, no model called)", "cohort": COHORT,
                          "condition": WITHOUT, "runs_per_task": RUNS, "planned_model_invocations": planned,
                          "model": MODEL, "host_version": HOST_VERSION, "per_run_timeout_seconds": TIMEOUT,
                          "command_to_approve": shell_command(approve),
                          "preflight_command": shell_command(approve[:-2] + ["--preflight-only"])},
                         indent=2, sort_keys=True))
        return 0
    if args.preflight_only and args.approve_model_calls is not None:
        parser.error("--preflight-only starts no agent; do not combine it with --approve-model-calls")
    if args.approve_model_calls is not None and args.approve_model_calls != planned:
        parser.error(f"--approve-model-calls {args.approve_model_calls} does not equal the planned "
                     f"{planned} invocations; nothing was started")
    executable, reason, version = probe_opencode(str(args.opencode_executable), MODEL)
    if executable is None or version.split()[1:2] != [HOST_VERSION]:
        print(json.dumps({"status": "unavailable", "model_called": False,
                          "reason": reason if executable is None else f"host is {version}, registered {HOST_VERSION}"}))
        return 1
    adapter = OpenCodeHostAdapter(executable, MODEL, None, str(args.agent_python_without), None)
    work = Path(tempfile.mkdtemp(prefix="paired-run-")).resolve()
    if ROOT.resolve() in work.parents:
        shutil.rmtree(work, ignore_errors=True)
        print(json.dumps({"status": "refused", "reason": "work directory inside the checkout"}))
        return 1
    try:
        report = run_screen(adapter, tasks, runs=RUNS,
                            budget=Budget(max_runs=None if args.preflight_only else planned, timeout_seconds=TIMEOUT),
                            work_root=work, allow_model_calls=not args.preflight_only,
                            preflight_only=args.preflight_only,
                            recordings_out=None if args.preflight_only else args.recordings)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    report["command"] = shell_command(approve[:-2] + ["--preflight-only"]) if args.preflight_only else shell_command(approve)
    report["host"] = {"name": "opencode", "version": version}
    out = args.out.with_name(args.out.stem + "-preflight" + args.out.suffix) if args.preflight_only else args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(report), encoding="utf-8", newline="\n")
    failed = [f"{task['id']}:{run['run']}" for task in report["tasks"] for run in task["runs"]
              if run["adapter_status"] == PREFLIGHT_FAILED]
    screen = report["screen"]
    print(json.dumps({"status": "preflight complete" if args.preflight_only else "complete", "report": str(out),
                      "host_version": version, "preflight_failures": failed,
                      "started_agent_runs": report["design"]["started_agent_runs"],
                      **({} if args.preflight_only else {"screen": {key: screen[key] for key in screen
                                                                    if key != "per_task"},
                                                         "per_task": screen["per_task"]})},
                     indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
