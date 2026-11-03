"""Command-line interface for dataset inspection, evidence checks, contract proposals, preflight, manifests, and skill routing."""

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

    # The bindings check takes; propose takes the same, so whatever the caller knows is declared once.
    bindings = _Parser(add_help=False)
    bindings.add_argument(
        "--operation", choices=["buffer", "distance", "area", "length"],
        help="metric operation the data will be used for",
    )
    bindings.add_argument("--compare-to", metavar="PATH", help="source for vector record counts or explicit --raster-identity")
    bindings.add_argument("--resampling", metavar="METHOD", help="resampling method declared for the rasters")
    bindings.add_argument("--categorical", action="store_true", help="rasters hold categorical codes")
    bindings.add_argument("--categorical-source", metavar="PATH",
                          help="class raster the output was resampled from; every output code must occur in it")
    bindings.add_argument(
        "--expect", choices=["reflectance", "index"], help="expected value range of the raster bands"
    )
    # Phase 4 processing-level check wiring.
    bindings.add_argument("--reference-input", metavar="PATH", help="raw DN raster to compare against an output")
    bindings.add_argument(
        "--encoding", choices=["s2-l2a", "landsat-c2-l2"],
        help="known product encoding for scale/offset checks; s2-l2a also needs --decode-offset (0 or -0.1)"
    )
    bindings.add_argument("--decode-scale", type=float, metavar="S",
                              help="declared scale of --reference-input DN (for example from a STAC item)")
    bindings.add_argument("--decode-offset", type=float, metavar="O",
                              help="declared offset of --reference-input DN")
    bindings.add_argument("--unit-conversion", choices=sorted(UNIT_CONVERSIONS),
                              help="declared unit change after decoding, for the scale check")
    bindings.add_argument("--index-formula", choices=sorted(FORMULAS),
                              help="verify a spectral index from explicitly supplied calibrated source bands")
    bindings.add_argument("--band", action="append", default=[], metavar="ROLE=PATH",
                              help="index source band by role (nir, red, green, blue, swir1, swir2, pre_nir, ...); repeatable")
    bindings.add_argument("--stack", action="append", default=[], metavar="PATH",
                              help="ordered input layer for --stack-reduction; repeatable")
    bindings.add_argument("--stack-reduction", choices=sorted(STACK_REDUCTIONS),
                              help="verify every output cell against this reduction of the --stack layers")
    bindings.add_argument("--stack-weight", action="append", type=float, default=[], metavar="W",
                              help="one per --stack layer: hours for weighted-sum, decimal times for ols-slope")
    bindings.add_argument("--stack-min-count", type=int, metavar="N",
                              help="minimum valid layers for a supported cell (default 1)")
    bindings.add_argument("--stack-time", action="append", default=[], metavar="START/END",
                          help="ISO 8601 interval each --stack layer covers, in order; repeatable")
    bindings.add_argument("--stack-window", nargs=2, metavar=("START", "END"),
                          help="time window the output is labelled with; checked against --stack-time")
    bindings.add_argument("--band-number", action="append", default=[], metavar="ROLE=N",
                              help="1-based band of a multi-band --band source; repeatable")
    bindings.add_argument("--nir", metavar="PATH", help="single-band NIR source; calibration comes from its scale/offset metadata")
    bindings.add_argument("--red", metavar="PATH", help="single-band red source; calibration comes from its scale/offset metadata")
    bindings.add_argument("--processing-full-scan", action="store_true",
                              help="verify every corresponding band/pixel for supplied calibration and QA relations")
    bindings.add_argument("--dem", metavar="PATH", help="DEM a slope-in-degrees raster was derived from")
    bindings.add_argument("--dem-vertical-unit", metavar="UNIT",
                              help="declared vertical unit of --dem when its file has no label (metre, foot, ...)")
    bindings.add_argument("--metric-quantity", choices=["area", "length", "buffer"],
                              help="verify delivered vector measurements geodesically, in any CRS")
    bindings.add_argument("--metric-property", metavar="FIELD", help="feature property holding the area or length")
    bindings.add_argument("--metric-unit", metavar="UNIT",
                              help="unit of --metric-property (square_metre, hectare, square_kilometre, metre, kilometre)")
    bindings.add_argument("--buffer-distance-m", type=float, metavar="METRES", help="declared ground buffer distance")
    bindings.add_argument("--buffer-source", metavar="PATH", help="vector the output buffers")
    bindings.add_argument("--slope-method", choices=["central-difference"],
                              help="verify every slope value and complete stencil/edge mask from --dem")
    bindings.add_argument("--raster-identity", action="store_true",
                              help="compare all valid raster samples, masks and grid metadata with --compare-to")
    bindings.add_argument("--vertical-operation", choices=sorted(VERTICAL_OPERATIONS),
                              help="how the height output was made from --vertical-source: convert (one), difference (first minus second) "
                                   "or depth-below-level (one, with --vertical-level)")
    bindings.add_argument("--vertical-source", action="append", default=[], metavar="PATH",
                              help="ordered source surface for --vertical-operation; repeatable")
    bindings.add_argument("--vertical-source-unit", action="append", default=[], metavar="UNIT",
                              help="declared vertical unit of each --vertical-source (metre, foot, us-survey-foot); repeatable")
    bindings.add_argument("--vertical-unit", metavar="UNIT", help="declared vertical unit of the output")
    bindings.add_argument("--vertical-level", type=float, metavar="LEVEL",
                              help="level in the output unit for --vertical-operation depth-below-level")
    bindings.add_argument("--support-source", action="append", default=[], metavar="PATH",
                              help="source raster whose valid cells define the output's support; repeatable")
    bindings.add_argument("--support-source-nodata", action="append", default=[], metavar="VALUE",
                              help="declared fill value of each --support-source, or 'file' to use its own mask; repeatable")
    bindings.add_argument("--support-rule", choices=["all", "any"],
                              help="output valid where all (or any) --support-source cells are valid")
    bindings.add_argument("--qa", metavar="PATH", dest="qa_path", help="QA raster (SCL or Landsat QA_PIXEL)")
    bindings.add_argument(
        "--qa-kind", choices=["s2-scl", "landsat-qa-pixel", "keep-codes"], help="kind of QA raster supplied with --qa"
    )
    bindings.add_argument("--qa-source", metavar="PATH",
                              help="source band the QA rule masks; tells over-masking from source gaps for keep-codes")
    bindings.add_argument("--qa-keep-code", action="append", type=int, default=[], metavar="CODE",
                              help="QA code your quality rule accepts, for --qa-kind keep-codes (every other code "
                                   "must be nodata); repeatable; needs --processing-full-scan")
    bindings.add_argument("--time-range", nargs=2, metavar=("START", "END"), help="ISO 8601 bounds for STAC items")
    bindings.add_argument(
        "--sar-expect", choices=["sigma0-db", "sigma0-linear"], help="declared SAR backscatter scale"
    )
    bindings.add_argument("--output-form", choices=["validity-mask"],
                          help="the outputs are validity masks: only --output-valid-value counts as valid")
    bindings.add_argument("--output-valid-value", type=float, metavar="V",
                          help="value meaning valid in a validity-mask output (default 1)")
    bindings.add_argument("--slope-unit", choices=["degrees", "percent"],
                          help="unit of a slope output checked with --dem (default degrees)")
    bindings.add_argument("--summary-key", metavar="KEY", help="JSON key (dots for nesting) holding a delivered number")
    bindings.add_argument("--summary-statistic",
                          choices=["mean", "count", "sum", "min", "max", "fraction", "area", "length"],
                          help="statistic the --summary-key number reports, recomputed from --summary-source")
    bindings.add_argument("--summary-source", metavar="PATH", help="raster or vector the summary was computed from")
    bindings.add_argument("--summary-unit", metavar="UNIT",
                          help="unit of a fraction (fraction, percent), area or length summary "
                               "(square_kilometre, hectare, metre, kilometre, ...)")
    bindings.add_argument("--summary-feature", metavar="FIELD=VALUE", help="vector features the summary covers")
    bindings.add_argument("--summary-mask", metavar="PATH",
                          help="validity mask (1 = include) on the raster source's grid")
    bindings.add_argument("--summary", action="append", default=[],
                          metavar="key=K,statistic=S,source=PATH[,unit=U][,codes=C;C][,mask=PATH,...]",
                          help="one declared report number; repeat for each number a report holds")
    bindings.add_argument("--sar-filter", choices=["boxcar"],
                          help="speckle filter applied to --sar-filter-source; recomputed in linear power")
    bindings.add_argument("--sar-filter-size", type=int, metavar="N", help="odd window size of --sar-filter")
    bindings.add_argument("--sar-filter-source", metavar="PATH",
                          help="unfiltered backscatter, in the --sar-expect domain, on the output's grid")
    bindings.add_argument(
        "--accuracy-samples", metavar="JSON", help="JSON file of reference samples (map_class, ref_class, optional stratum_weight)"
    )
    bindings.add_argument(
        "--class-areas", metavar="JSON", help="JSON object mapping map class to area for area-adjusted estimates"
    )
    bindings.add_argument("--min-per-class", type=int, metavar="N", help="minimum reference samples per map class")
    bindings.add_argument(
        "--estimates-requested", action="store_true", help="request area-adjusted class-area estimates"
    )
    # Phase 4 provenance wiring.
    bindings.add_argument("--manifest", metavar="PATH", help="verify a run manifest and append provenance.reproducible")
    bindings.add_argument(
        "--require-provenance", action="store_true", help="Decision-grade requires a verified manifest"
    )
    check_parser = subparsers.add_parser(
        "check", parents=[bindings],
        help=("run checks and write an evidence report (exit 0 decision-grade or checks-passed, 2 review, "
              "3 advisory; decision-grade needs a verification contract)"),
    )
    check_parser.add_argument("paths", nargs="+", metavar="PATH", help="input datasets")
    check_parser.add_argument("--format", choices=["json", "md"], default="json", help="report format")
    check_parser.add_argument("--lang", choices=["en", "ar"], default="en", help="language of the Markdown report")
    check_parser.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    check_parser.add_argument("--contract", metavar="FILE", help="explicit required checks, output paths and source/parameter bindings")
    check_parser.add_argument("--profile", action="append", default=[], metavar="NAME",
                              help="declared goal profile for every PATH, from routing/profiles.json; builds a contract "
                                   "from the arguments given (not with --contract); repeatable")

    propose_parser = subparsers.add_parser(
        "propose", parents=[bindings],
        help="draft a verification contract for goal profiles from the bindings given and explicit metadata",
    )
    propose_parser.add_argument("paths", nargs="+", metavar="PATH", help="outputs the contract covers")
    propose_parser.add_argument("--profile", action="append", required=True, metavar="NAME",
                                help="declared goal profile, from routing/profiles.json; repeatable")
    propose_parser.add_argument("--stac", action="append", default=[], metavar="FILE=ITEM#ASSET",
                                help="ties a source FILE to ASSET of a local STAC Item, whose raster:bands scale, "
                                     "offset, nodata and unit then count as that file's metadata; repeatable")
    propose_parser.add_argument("--out", metavar="FILE", help="write the proposal to FILE instead of stdout")
    propose_parser.add_argument("--contract-out", metavar="FILE",
                                help="also write the draft contract alone, ready for check --contract")

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

    workflow_parser = subparsers.add_parser('workflow', help='plan, run and verify a scientific workflow')
    workflow_parser.add_argument('args', nargs=argparse.REMAINDER)

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


SUMMARY_SYNTAX = ("key=K,statistic=S,source=PATH[,unit=U][,feature=FIELD=VALUE][,mask=PATH][,codes=C;C]"
                  "[,mask_codes=C;C][,scale=X][,offset=X]")


def _summary_entries(values: list[str]) -> list[dict]:
    """One declared summary per --summary; code lists are separated by semicolons."""
    from terraproof.evidence.contract import SUMMARY_FIELDS
    entries = []
    for value in values:
        entry = {}
        for part in value.split(","):
            name, sep, item = part.partition("=")
            name = name.strip()
            if not sep or name not in SUMMARY_FIELDS or not item or name in entry:
                raise SystemExit(f"terraproof: --summary expects {SUMMARY_SYNTAX}, got {value!r}")
            try:
                entry[name] = ([int(code) for code in item.split(";")] if name in ("codes", "mask_codes")
                               else float(item) if name in ("scale", "offset") else item)
            except ValueError:
                raise SystemExit(f"terraproof: --summary {name} must be numeric, got {item!r}") from None
        entries.append(entry)
    return entries


def _binding_parameters(args: argparse.Namespace) -> dict:
    """The declared bindings, keyed as verification-contract parameters."""
    band_paths = _role_pairs(args.band, "--band")
    band_numbers = {role: int(value) for role, value in _role_pairs(args.band_number, "--band-number").items()}
    support_nodata = [None if value == "file" else _float_arg(value, "--support-source-nodata")
                      for value in args.support_source_nodata] or None
    time_range = tuple(args.time_range) if args.time_range else None
    return {
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
        "dem_vertical_unit": args.dem_vertical_unit,
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
        "qa_source": args.qa_source,
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
        "metric_quantity": args.metric_quantity,
        "metric_property": args.metric_property,
        "metric_unit": args.metric_unit,
        "buffer_distance_m": args.buffer_distance_m,
        "buffer_source": args.buffer_source,
        "categorical_source": args.categorical_source,
        "sar_filter": args.sar_filter,
        "sar_filter_size": args.sar_filter_size,
        "sar_filter_source": args.sar_filter_source,
        "stack_times": args.stack_time or None,
        "stack_window": args.stack_window,
        "output_form": args.output_form,
        "output_valid_value": args.output_valid_value,
        "slope_unit": args.slope_unit,
        "summary_key": args.summary_key,
        "summary_statistic": args.summary_statistic,
        "summary_source": args.summary_source,
        "summary_unit": args.summary_unit,
        "summary_feature": args.summary_feature,
        "summary_mask": args.summary_mask,
        "summaries": _summary_entries(args.summary) or None,
    }


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
    buffer_source = _inspect_if_exists(args.buffer_source)
    categorical_source = _inspect_if_exists(args.categorical_source)
    sar_filter_source = _inspect_if_exists(args.sar_filter_source)
    summary_source = _inspect_if_exists(args.summary_source)
    summary_mask = _inspect_if_exists(args.summary_mask)
    summary_entries = _summary_entries(args.summary)
    summaries = [dict(entry, source=_inspect_if_exists(entry.get("source")), mask=_inspect_if_exists(entry.get("mask")))
                 for entry in summary_entries]
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
    _record_input(inputs, args.qa_source, "qa-source", "raster")
    _record_input(inputs, args.buffer_source, "buffer-source", buffer_source["kind"] if buffer_source else "unknown")
    _record_input(inputs, args.categorical_source, "categorical-source",
                  categorical_source["kind"] if categorical_source else "unknown")
    _record_input(inputs, args.sar_filter_source, "sar-filter-source",
                  sar_filter_source["kind"] if sar_filter_source else "unknown")
    _record_input(inputs, args.summary_source, "summary-source", summary_source["kind"] if summary_source else "unknown")
    _record_input(inputs, args.summary_mask, "summary-mask", summary_mask["kind"] if summary_mask else "unknown")
    for declared, entry in zip(summary_entries, summaries):
        for field, role in (("source", "summary-source"), ("mask", "summary-mask")):
            if entry[field] is not None and not any(r["path"] == declared[field] and r["role"] == role for r in inputs):
                _record_input(inputs, declared[field], role, entry[field]["kind"])
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
        qa_source=args.qa_source,
        time_range=time_range,
        sar_expect=args.sar_expect,
        accuracy_samples=accuracy_samples,
        class_areas=class_areas,
        min_per_class=args.min_per_class,
        estimates_requested=args.estimates_requested,
        dem=dem,
        dem_vertical_unit=args.dem_vertical_unit,
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
        metric_quantity=args.metric_quantity,
        metric_property=args.metric_property,
        metric_unit=args.metric_unit,
        buffer_distance_m=args.buffer_distance_m,
        buffer_source=buffer_source,
        categorical_source=categorical_source,
        sar_filter=args.sar_filter,
        sar_filter_size=args.sar_filter_size,
        sar_filter_source=sar_filter_source,
        stack_times=args.stack_time or None,
        stack_window=args.stack_window,
        output_form=args.output_form,
        output_valid_value=args.output_valid_value,
        slope_unit=args.slope_unit,
        summary_key=args.summary_key,
        summary_statistic=args.summary_statistic,
        summary_source=summary_source,
        summary_unit=args.summary_unit,
        summary_feature=args.summary_feature,
        summary_mask=summary_mask,
        summaries=summaries or None,
    )

    checked_paths = list(args.paths) + [e[f] for e in summary_entries for f in ("source", "mask") if e.get(f)]
    for path in (args.compare_to, args.reference_input, args.dem, args.nir, args.red, *band_paths.values(), *args.stack,
                 *args.vertical_source, *args.support_source, args.qa_source, args.buffer_source,
                 args.categorical_source, args.sar_filter_source, args.summary_source, args.summary_mask,
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

    parameters = _binding_parameters(args)
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


def _cmd_propose(args: argparse.Namespace) -> int:
    from terraproof.evidence.propose import check_command, propose_contract

    proposal = propose_contract(args.paths, args.profile, _binding_parameters(args), args.stac)
    if args.contract_out:
        Path(args.contract_out).write_text(json.dumps(proposal["contract"], sort_keys=True, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")
        proposal["check_command"] = check_command(proposal["check_arguments"], str(Path(args.contract_out).resolve()))
    text = json.dumps(jsonable(proposal), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


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
        if args.command == 'workflow':
            from terraproof.workflows.__main__ import main as workflow_main
            return workflow_main(args.args)
        if args.command == "route":
            return _cmd_route(args)
        if args.command == "preflight":
            return _cmd_preflight(args)
        if args.command == "propose":
            return _cmd_propose(args)
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
