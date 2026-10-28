"""Command-line interface for dataset inspection, evidence checks, preflight, manifests, and skill routing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from terraproof._common import InputError, jsonable
from terraproof._run_helpers import load_accuracy_samples, load_class_areas, verify_manifest_coverage
from terraproof.checks import run_checks
from terraproof.checks.index_formula import FORMULAS
from terraproof.checks.stack_reduction import REDUCTIONS as STACK_REDUCTIONS
from terraproof.checks.vertical_units import OPERATIONS as VERTICAL_OPERATIONS
from terraproof.checks.rs_processing import UNIT_CONVERSIONS
from terraproof.checks.base import FAIL, result
from terraproof.evidence import EXIT_CODES, build_report, input_record, render_markdown, to_json
from terraproof.evidence.contract import profile_contract
from terraproof.evidence.report import report_exit_code
from terraproof.inspect import inspect_dataset
from terraproof.preflight import run_preflight

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
        help=("run checks and write an evidence report (exit 0 decision-grade or checks-passed, 2 review, "
              "3 advisory; decision-grade needs a verification contract)"),
    )
    check_parser.add_argument("paths", nargs="+", metavar="PATH", help="input datasets")
    check_parser.add_argument(
        "--operation", choices=["buffer", "distance", "area", "length"],
        help="metric operation the data will be used for",
    )
    check_parser.add_argument("--compare-to", metavar="PATH", help="source for vector record counts or explicit --raster-identity")
    check_parser.add_argument("--resampling", metavar="METHOD", help="resampling method declared for the rasters")
    check_parser.add_argument("--categorical", action="store_true", help="rasters hold categorical codes")
    check_parser.add_argument(
        "--expect", choices=["reflectance", "index"], help="expected value range of the raster bands"
    )
    # Phase 4 processing-level check wiring.
    check_parser.add_argument("--reference-input", metavar="PATH", help="raw DN raster to compare against an output")
    check_parser.add_argument(
        "--encoding", choices=["s2-l2a", "landsat-c2-l2"], help="known product encoding for scale/offset checks"
    )
    check_parser.add_argument("--decode-scale", type=float, metavar="S",
                              help="declared scale of --reference-input DN (for example from a STAC item)")
    check_parser.add_argument("--decode-offset", type=float, metavar="O",
                              help="declared offset of --reference-input DN")
    check_parser.add_argument("--unit-conversion", choices=sorted(UNIT_CONVERSIONS),
                              help="declared unit change after decoding, for the scale check")
    check_parser.add_argument("--index-formula", choices=sorted(FORMULAS),
                              help="verify a spectral index from explicitly supplied calibrated source bands")
    check_parser.add_argument("--band", action="append", default=[], metavar="ROLE=PATH",
                              help="index source band by role (nir, red, green, blue, swir1, swir2, pre_nir, ...); repeatable")
    check_parser.add_argument("--stack", action="append", default=[], metavar="PATH",
                              help="ordered input layer for --stack-reduction; repeatable")
    check_parser.add_argument("--stack-reduction", choices=sorted(STACK_REDUCTIONS),
                              help="verify every output cell against this reduction of the --stack layers")
    check_parser.add_argument("--stack-weight", action="append", type=float, default=[], metavar="W",
                              help="one per --stack layer: hours for weighted-sum, decimal times for ols-slope")
    check_parser.add_argument("--stack-min-count", type=int, metavar="N",
                              help="minimum valid layers for a supported cell (default 1)")
    check_parser.add_argument("--band-number", action="append", default=[], metavar="ROLE=N",
                              help="1-based band of a multi-band --band source; repeatable")
    check_parser.add_argument("--nir", metavar="PATH", help="single-band NIR source; calibration comes from its scale/offset metadata")
    check_parser.add_argument("--red", metavar="PATH", help="single-band red source; calibration comes from its scale/offset metadata")
    check_parser.add_argument("--processing-full-scan", action="store_true",
                              help="verify every corresponding band/pixel for supplied calibration and QA relations")
    check_parser.add_argument("--dem", metavar="PATH", help="DEM a slope-in-degrees raster was derived from")
    check_parser.add_argument("--slope-method", choices=["central-difference"],
                              help="verify every slope value and complete stencil/edge mask from --dem")
    check_parser.add_argument("--raster-identity", action="store_true",
                              help="compare all valid raster samples, masks and grid metadata with --compare-to")
    check_parser.add_argument("--vertical-operation", choices=sorted(VERTICAL_OPERATIONS),
                              help="how the height output was made from --vertical-source: convert (one), difference (first minus second) "
                                   "or depth-below-level (one, with --vertical-level)")
    check_parser.add_argument("--vertical-source", action="append", default=[], metavar="PATH",
                              help="ordered source surface for --vertical-operation; repeatable")
    check_parser.add_argument("--vertical-source-unit", action="append", default=[], metavar="UNIT",
                              help="declared vertical unit of each --vertical-source (metre, foot, us-survey-foot); repeatable")
    check_parser.add_argument("--vertical-unit", metavar="UNIT", help="declared vertical unit of the output")
    check_parser.add_argument("--vertical-level", type=float, metavar="LEVEL",
                              help="level in the output unit for --vertical-operation depth-below-level")
    check_parser.add_argument("--support-source", action="append", default=[], metavar="PATH",
                              help="source raster whose valid cells define the output's support; repeatable")
    check_parser.add_argument("--support-source-nodata", action="append", default=[], metavar="VALUE",
                              help="declared fill value of each --support-source, or 'file' to use its own mask; repeatable")
    check_parser.add_argument("--support-rule", choices=["all", "any"],
                              help="output valid where all (or any) --support-source cells are valid")
    check_parser.add_argument("--qa", metavar="PATH", dest="qa_path", help="QA raster (SCL or Landsat QA_PIXEL)")
    check_parser.add_argument(
        "--qa-kind", choices=["s2-scl", "landsat-qa-pixel", "keep-codes"], help="kind of QA raster supplied with --qa"
    )
    check_parser.add_argument("--qa-keep-code", action="append", type=int, default=[], metavar="CODE",
                              help="QA code your quality rule accepts, for --qa-kind keep-codes (every other code "
                                   "must be nodata); repeatable; needs --processing-full-scan")
    check_parser.add_argument("--time-range", nargs=2, metavar=("START", "END"), help="ISO 8601 bounds for STAC items")
    check_parser.add_argument(
        "--sar-expect", choices=["sigma0-db", "sigma0-linear"], help="declared SAR backscatter scale"
    )
    check_parser.add_argument(
        "--accuracy-samples", metavar="JSON", help="JSON file of reference samples (map_class, ref_class, optional stratum_weight)"
    )
    check_parser.add_argument(
        "--class-areas", metavar="JSON", help="JSON object mapping map class to area for area-adjusted estimates"
    )
    check_parser.add_argument("--min-per-class", type=int, metavar="N", help="minimum reference samples per map class")
    check_parser.add_argument(
        "--estimates-requested", action="store_true", help="request area-adjusted class-area estimates"
    )
    # Phase 4 provenance wiring.
    check_parser.add_argument("--manifest", metavar="PATH", help="verify a run manifest and append provenance.reproducible")
    check_parser.add_argument(
        "--require-provenance", action="store_true", help="Decision-grade requires a verified manifest"
    )
    check_parser.add_argument("--format", choices=["json", "md"], default="json", help="report format")
    check_parser.add_argument("--lang", choices=["en", "ar"], default="en", help="language of the Markdown report")
    check_parser.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    check_parser.add_argument("--contract", metavar="FILE", help="explicit required checks, output paths and source/parameter bindings")
    check_parser.add_argument("--profile", action="append", default=[], metavar="NAME",
                              help="declared goal profile for every PATH, from routing/profiles.json; builds a contract "
                                   "from the arguments given (not with --contract); repeatable")

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="check a declared plan against real inputs before running it",
    )
    preflight_parser.add_argument("paths", nargs="+", metavar="PATH", help="input datasets the plan will use")
    preflight_parser.add_argument("--plan", required=True, metavar="FILE", help="JSON plan file")
    preflight_parser.add_argument("--format", choices=["json", "md"], default="json", help="report format")
    preflight_parser.add_argument("--lang", choices=["en", "ar"], default="en", help="language of the Markdown report")
    preflight_parser.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")

    route_parser = subparsers.add_parser("route", help="retrieve skill sections using task and dataset metadata")
    route_parser.add_argument("task", metavar="TASK", help="English or Arabic task description")
    route_parser.add_argument("--data", nargs="+", action="extend", default=[], metavar="PATH", help="local datasets to inspect")
    route_parser.add_argument("--top-k", type=int, default=5, metavar="N", help="maximum ranked skills")
    route_parser.add_argument("--mode", choices=["ranked", "candidates"], default="ranked", help="retrieval mode")
    route_parser.add_argument("--semantic", action="store_true", help="enable the optional local semantic retrieval pass")
    route_parser.add_argument("--format", choices=["json", "md"], default="json", help="guidance format")

    manifest_parser = subparsers.add_parser(
        "manifest", help="write or verify deterministic run manifests"
    )
    manifest_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="manifest subcommand and options (write or verify)"
    )

    evidence_parser = subparsers.add_parser('evidence', help='write or verify an unsigned evidence bundle')
    evidence_parser.add_argument('args', nargs=argparse.REMAINDER)

    return parser


def _load_json_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        plan = json.load(handle)
    if not isinstance(plan, dict):
        raise InputError(f"plan file must contain a JSON object: {path}")
    return plan


def _inspect_if_exists(path: str | None) -> dict | None:
    return inspect_dataset(path) if path else None


def _record_input(inputs: list, path: str | None, role: str, kind: str) -> None:
    if path and Path(path).is_file():
        inputs.append(input_record(path, role, kind))


def _cmd_inspect(args: argparse.Namespace) -> int:
    description = inspect_dataset(args.path)
    sys.stdout.write(json.dumps(jsonable(description), sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 0


def _role_pairs(values: list[str], flag: str) -> dict[str, str]:
    pairs = {}
    for value in values:
        role, sep, item = value.partition("=")
        if not sep or not role or not item:
            raise SystemExit(f"terraproof check: {flag} expects ROLE=VALUE, got {value!r}")
        pairs[role.strip()] = item
    return pairs


def _float_arg(value: str, flag: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise SystemExit(f"terraproof check: {flag} expects a number or 'file', got {value!r}") from None


def _cmd_check(args: argparse.Namespace) -> int:
    inspections = [inspect_dataset(path) for path in args.paths]
    compare = _inspect_if_exists(args.compare_to)
    reference_input = _inspect_if_exists(args.reference_input)
    dem = _inspect_if_exists(args.dem)
    nir = _inspect_if_exists(args.nir)
    red = _inspect_if_exists(args.red)
    band_paths = _role_pairs(args.band, "--band")
    band_numbers = {role: int(value) for role, value in _role_pairs(args.band_number, "--band-number").items()}
    index_bands = {role: dict(inspect_dataset(path), band=band_numbers.get(role)) for role, path in band_paths.items()}
    stack = [inspect_dataset(path) for path in args.stack]
    vertical_sources = [inspect_dataset(path) for path in args.vertical_source]
    support_sources = [inspect_dataset(path) for path in args.support_source]
    support_nodata = [None if value == "file" else _float_arg(value, "--support-source-nodata")
                      for value in args.support_source_nodata] or None

    inputs: list[dict] = [input_record(path, "input", ds["kind"]) for path, ds in zip(args.paths, inspections)]
    _record_input(inputs, args.compare_to, "compare-to", compare["kind"] if compare else "unknown")
    _record_input(inputs, args.reference_input, "reference-input", reference_input["kind"] if reference_input else "unknown")
    _record_input(inputs, args.dem, "dem", dem["kind"] if dem else "unknown")
    _record_input(inputs, args.nir, "nir", nir["kind"] if nir else "unknown")
    _record_input(inputs, args.red, "red", red["kind"] if red else "unknown")
    for role, path in band_paths.items():
        _record_input(inputs, path, "index-band", index_bands[role]["kind"])
    for path, layer in zip(args.stack, stack):
        _record_input(inputs, path, "stack-layer", layer["kind"])
    for path, layer in zip(args.vertical_source, vertical_sources):
        _record_input(inputs, path, "vertical-source", layer["kind"])
    for path, layer in zip(args.support_source, support_sources):
        _record_input(inputs, path, "support-source", layer["kind"])
    _record_input(inputs, args.qa_path, "qa", "raster")
    _record_input(inputs, args.accuracy_samples, "accuracy-samples", "accuracy-samples")
    _record_input(inputs, args.class_areas, "class-areas", "class-areas")
    _record_input(inputs, args.manifest, "manifest", "manifest")

    accuracy_samples = load_accuracy_samples(args.accuracy_samples) if args.accuracy_samples else None
    class_areas = load_class_areas(args.class_areas) if args.class_areas else None
    time_range = tuple(args.time_range) if args.time_range else None

    results = run_checks(
        inspections,
        compare_to=compare,
        operation=args.operation,
        resampling=args.resampling,
        categorical=args.categorical,
        expect=args.expect,
        reference_input=reference_input,
        encoding=args.encoding,
        decode_scale=args.decode_scale,
        decode_offset=args.decode_offset,
        unit_conversion=args.unit_conversion,
        qa_path=args.qa_path,
        qa_kind=args.qa_kind,
        qa_keep_codes=args.qa_keep_code or None,
        time_range=time_range,
        sar_expect=args.sar_expect,
        accuracy_samples=accuracy_samples,
        class_areas=class_areas,
        min_per_class=args.min_per_class,
        estimates_requested=args.estimates_requested,
        dem=dem,
        slope_method=args.slope_method,
        raster_identity=args.raster_identity,
        index_formula=args.index_formula,
        index_bands=index_bands or None,
        stack=stack or None,
        stack_reduction=args.stack_reduction,
        stack_weights=args.stack_weight or None,
        stack_min_count=args.stack_min_count,
        nir=nir,
        red=red,
        processing_full_scan=args.processing_full_scan,
        vertical_operation=args.vertical_operation,
        vertical_sources=vertical_sources or None,
        vertical_source_units=args.vertical_source_unit or None,
        vertical_unit=args.vertical_unit,
        vertical_level=args.vertical_level,
        support_sources=support_sources or None,
        support_source_nodata=support_nodata,
        support_rule=args.support_rule,
    )

    checked_paths = list(args.paths)
    for path in (args.compare_to, args.reference_input, args.dem, args.nir, args.red, *band_paths.values(), *args.stack,
                 *args.vertical_source, *args.support_source,
                 args.qa_path, args.accuracy_samples, args.class_areas):
        if path:
            checked_paths.append(path)

    if args.manifest:
        manifest_check = verify_manifest_coverage(args.manifest, checked_paths)
        results.append(manifest_check)
    elif args.require_provenance:
        results.append(
            result(
                "provenance.reproducible",
                FAIL,
                "Decision-grade requires a verified manifest, but none was supplied.",
                manifest=None,
            )
        )

    parameters = {
        "operation": args.operation,
        "compare_to": args.compare_to,
        "resampling": args.resampling,
        "categorical": args.categorical,
        "expect": args.expect,
        "reference_input": args.reference_input,
        "encoding": args.encoding,
        "decode_scale": args.decode_scale,
        "decode_offset": args.decode_offset,
        "unit_conversion": args.unit_conversion,
        "dem": args.dem,
        "slope_method": args.slope_method,
        "raster_identity": args.raster_identity,
        "index_formula": args.index_formula,
        "index_bands": {role: [path, band_numbers.get(role)] for role, path in band_paths.items()} or None,
        "stack": args.stack or None,
        "stack_reduction": args.stack_reduction,
        "stack_weights": args.stack_weight or None,
        "stack_min_count": args.stack_min_count,
        "nir": args.nir,
        "red": args.red,
        "processing_full_scan": args.processing_full_scan,
        "qa_path": args.qa_path,
        "qa_kind": args.qa_kind,
        "qa_keep_codes": args.qa_keep_code or None,
        "time_range": time_range,
        "sar_expect": args.sar_expect,
        "accuracy_samples": args.accuracy_samples,
        "class_areas": args.class_areas,
        "min_per_class": args.min_per_class,
        "estimates_requested": args.estimates_requested,
        "manifest": args.manifest,
        "require_provenance": args.require_provenance,
        "vertical_operation": args.vertical_operation,
        "vertical_sources": args.vertical_source or None,
        "vertical_source_units": args.vertical_source_unit or None,
        "vertical_unit": args.vertical_unit,
        "vertical_level": args.vertical_level,
        "support_sources": args.support_source or None,
        "support_source_nodata": support_nodata,
        "support_rule": args.support_rule,
    }
    if args.profile and args.contract:
        raise SystemExit("terraproof check: give --profile or --contract, not both")
    contract = profile_contract(args.paths, args.profile, parameters) if args.profile else args.contract
    report = build_report(inputs=inputs, results=results, parameters=parameters, contract=contract)
    text = to_json(report) if args.format == "json" else render_markdown(report, lang=args.lang)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return report_exit_code(report)


def _cmd_preflight(args: argparse.Namespace) -> int:
    inspections = [inspect_dataset(path) for path in args.paths]
    plan = _load_json_plan(args.plan)

    inputs = [input_record(path, "input", ds["kind"]) for path, ds in zip(args.paths, inspections)]
    inputs.append(input_record(args.plan, "plan", "plan"))

    results = run_preflight(inspections, plan)
    parameters = {"plan": args.plan, "plan_content": plan}
    report = build_report(inputs=inputs, results=results, parameters=parameters)
    text = to_json(report) if args.format == "json" else render_markdown(report, lang=args.lang)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return EXIT_CODES[report["grade"]]


def _cmd_route(args: argparse.Namespace) -> int:
    from terraproof.router import find_guidance, render_markdown as render_guidance

    result = find_guidance(
        args.task,
        data_paths=args.data,
        top_k=args.top_k,
        mode=args.mode,
        semantic=args.semantic,
    )
    text = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            if args.format == "json" else render_guidance(result))
    sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            return _cmd_inspect(args)
        if args.command == "route":
            return _cmd_route(args)
        if args.command == "preflight":
            return _cmd_preflight(args)
        if args.command == "manifest":
            from terraproof.provenance.__main__ import _run as _provenance_run
            return _provenance_run(args.args)
        if args.command == "evidence":
            from terraproof.evidence.bundle import main as evidence_main
            return evidence_main(args.args)
        return _cmd_check(args)
    except Exception as exc:  # CLI boundary: unreadable or unsupported input is a usage-level failure
        print(f"terraproof: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
