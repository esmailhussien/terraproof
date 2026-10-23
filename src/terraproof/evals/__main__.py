"""`python -m terraproof.evals run`: execute the benchmark task specs against generated fixtures."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from terraproof.evals.harness import run_benchmark, to_json
from terraproof.evals.specs import SpecError, repo_root

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.keep:
        cache = repo_root() / ".terracache" / "evals-kept"
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
