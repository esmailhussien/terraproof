"""`python -m terraproof.evals run|lift`: the benchmark task specs and the offline agent-lift harness."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from terraproof.evals.harness import run_benchmark, to_json
from terraproof.evals.lift import (
    COHORTS, DEFAULT_COHORT, SCRIPTED_BEHAVIOURS, LiftError, ReplayAdapter, ScriptedAdapter, calibrate, run_lift,
)
from terraproof.evals.lift import to_json as lift_to_json
from terraproof.evals.specs import SpecError

EXIT_USAGE = 2


class _Parser(argparse.ArgumentParser):
    """Report usage errors as exit status 2, distinct from a benchmark failure (1)."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m terraproof.evals", description="Run the Terraproof benchmark task specs.")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_Parser, metavar="COMMAND")
    run_parser = subparsers.add_parser(
        "run",
        help="run every task recipe and print the JSON report (exit 0 all passed, 1 failures)",
    )
    run_parser.add_argument("--specs", metavar="DIR", help="directory of task spec JSON files (default: evals/tasks)")
    run_parser.add_argument(
        "--only",
        action="append",
        metavar="TASK_ID",
        help="run only this task id (repeatable; diagnostic use, not a full pass)",
    )
    run_parser.add_argument("--out", metavar="FILE", help="write the JSON report to FILE instead of stdout")
    run_parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the generated fixtures in the temporary run directory (path is printed to stderr)",
    )
    lift_parser = subparsers.add_parser(
        "lift",
        help="run the paired with/without agent-lift harness with an OFFLINE adapter (never calls a model)",
    )
    lift_parser.add_argument("--adapter", choices=["scripted", "replay"], default="scripted",
                             help="scripted control agent (default) or replay of recorded outputs")
    lift_parser.add_argument("--with-behaviour", choices=SCRIPTED_BEHAVIOURS, default="reference",
                             help="scripted output in the with condition (default: reference)")
    lift_parser.add_argument("--without-behaviour", choices=SCRIPTED_BEHAVIOURS, default="seeded",
                             help="scripted output in the without condition (default: seeded)")
    lift_parser.add_argument("--recordings", metavar="DIR", help="recorded outputs for --adapter replay")
    lift_parser.add_argument("--task", action="append", metavar="TASK_ID", help="lift task id (repeatable; not with --cohort)")
    lift_parser.add_argument("--cohort", choices=sorted(COHORTS),
                             help=f"task cohort (runs default to {DEFAULT_COHORT}; --calibrate-only defaults to every task)")
    lift_parser.add_argument("--runs", type=int, default=1, help="runs per condition and task (default 1)")
    lift_parser.add_argument("--agent", default="codex", help="installer agent format for the with condition")
    lift_parser.add_argument("--calibrate-only", action="store_true", help="run only the scoring calibration gate")
    lift_parser.add_argument("--out", metavar="FILE", help="write the JSON report to FILE instead of stdout")
    return parser


def _lift(args) -> int:
    if args.task and args.cohort:
        print("terraproof.evals: error: --task and --cohort select tasks in different ways; give one of them",
              file=sys.stderr)
        return EXIT_USAGE
    if args.calibrate_only:
        cohort_ids = [task.task_id for task in COHORTS[args.cohort]] if args.cohort else None
        report = calibrate(args.task or cohort_ids)
        code = 0 if report["eligible"] else 1
    else:
        if args.adapter == "replay":
            if not args.recordings:
                print("terraproof.evals: error: --adapter replay needs --recordings DIR", file=sys.stderr)
                return EXIT_USAGE
            adapter = ReplayAdapter(args.recordings)
        else:
            adapter = ScriptedAdapter({"with": args.with_behaviour, "without": args.without_behaviour})
        report = run_lift(adapter, task_ids=args.task, cohort=args.cohort or DEFAULT_COHORT, runs=args.runs,
                          agent=args.agent)
        code = 0
        summary = report["summary"]
        print(
            "terraproof.evals lift: "
            f"{summary['complete_pairs']} pairs, pass rate with {summary['pass_rate']['with']}, "
            f"without {summary['pass_rate']['without']}, adapter {report['adapter']['name']} (no model calls)",
            file=sys.stderr,
        )
    text = lift_to_json(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "lift":
        try:
            return _lift(args)
        except (LiftError, SpecError) as error:
            print(f"terraproof.evals: error: {error}", file=sys.stderr)
            return EXIT_USAGE
    if args.keep:
        cache = Path.cwd() / ".terracache" / "evals-kept"
        cache.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(prefix="terraproof-evals-", dir=cache))
    else:
        work_root = None
    try:
        report = run_benchmark(spec_dir=args.specs, only=args.only, work_root=work_root, keep=args.keep)
    except SpecError as error:
        print(f"terraproof.evals: error: {error}", file=sys.stderr)
        return EXIT_USAGE
    if work_root is not None:
        print(f"terraproof.evals: fixtures kept at {work_root}", file=sys.stderr)
    text = to_json(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    summary = report["summary"]
    print(
        "terraproof.evals: "
        f"{summary['tasks']} tasks, {summary['tasks_passed']} passed, {summary['tasks_failed']} failed, "
        f"{summary['tasks_unrunnable']} unrunnable, {summary['false_passes']} false passes, "
        f"{summary['wrong_controls_checker_blind_spots']} checker blind spots, "
        f"{summary['checks_exercised'].__len__()} check ids exercised",
        file=sys.stderr,
    )
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
