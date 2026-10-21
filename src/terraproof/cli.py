"""Command-line interface: `python -m terraproof inspect PATH` and `python -m terraproof check PATH ...`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from terraproof._common import jsonable
from terraproof.checks import run_checks
from terraproof.evidence import EXIT_CODES, build_report, input_record, render_markdown, to_json
from terraproof.inspect import inspect_dataset

EXIT_USAGE = 1


class _Parser(argparse.ArgumentParser):
    """Exit with status 1 on usage errors, as the Terraproof CLI contract requires."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="terraproof", description="Inspect geospatial datasets and run evidence-graded checks.")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_Parser, metavar="COMMAND")

    inspect_parser = subparsers.add_parser("inspect", help="inspect one dataset and print JSON")
    inspect_parser.add_argument("path", metavar="PATH", help="vector, raster, or local STAC Item file")

    check_parser = subparsers.add_parser(
        "check",
        help="run checks and write an evidence report (exit 0 decision-grade, 2 review, 3 advisory)",
    )
    check_parser.add_argument("paths", nargs="+", metavar="PATH", help="input datasets")
    check_parser.add_argument(
        "--operation", choices=["buffer", "distance", "area", "length"],
        help="metric operation the data will be used for",
    )
    check_parser.add_argument("--compare-to", metavar="PATH", help="input dataset to compare record counts with")
    check_parser.add_argument("--resampling", metavar="METHOD", help="resampling method declared for the rasters")
    check_parser.add_argument("--categorical", action="store_true", help="rasters hold categorical codes")
    check_parser.add_argument(
        "--expect", choices=["reflectance", "index"], help="expected value range of the raster bands"
    )
    check_parser.add_argument("--format", choices=["json", "md"], default="json", help="report format")
    check_parser.add_argument("--lang", choices=["en", "ar"], default="en", help="language of the Markdown report")
    check_parser.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    return parser


def _cmd_inspect(args: argparse.Namespace) -> int:
    description = inspect_dataset(args.path)
    sys.stdout.write(json.dumps(jsonable(description), sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    inspections = [inspect_dataset(path) for path in args.paths]
    compare = inspect_dataset(args.compare_to) if args.compare_to else None

    inputs = [input_record(path, "input", ds["kind"]) for path, ds in zip(args.paths, inspections)]
    if compare is not None:
        inputs.append(input_record(args.compare_to, "compare-to", compare["kind"]))

    results = run_checks(
        inspections,
        compare_to=compare,
        operation=args.operation,
        resampling=args.resampling,
        categorical=args.categorical,
        expect=args.expect,
    )
    parameters = {
        "operation": args.operation,
        "compare_to": args.compare_to,
        "resampling": args.resampling,
        "categorical": args.categorical,
        "expect": args.expect,
    }
    report = build_report(inputs=inputs, results=results, parameters=parameters)
    text = to_json(report) if args.format == "json" else render_markdown(report, lang=args.lang)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return EXIT_CODES[report["grade"]]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            return _cmd_inspect(args)
        return _cmd_check(args)
    except Exception as exc:  # CLI boundary: unreadable or unsupported input is a usage-level failure
        print(f"terraproof: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
