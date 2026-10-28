"""The Terraproof MCP server: read-only tools over stdio.

The server exposes the same inspectors, checks, evidence report, skill sections, and
router that the command line uses, so an agent gets identical results whichever way
it calls them. It never writes files and never uses the network.

The official Python SDK's current stable line is 2.x, which serves both protocol
revisions; `FastMCP` was renamed to `MCPServer` in that release
(https://py.sdk.modelcontextprotocol.io/whats-new/#fastmcp-is-now-mcpserver).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from terraproof import __version__
from terraproof._common import InputError, jsonable
from terraproof._run_helpers import load_accuracy_samples, load_class_areas, verify_manifest_coverage
from terraproof.checks import run_checks as _run_checks
from terraproof.checks.base import FAIL, result
from terraproof.evidence import EXIT_CODES, build_report, input_record, render_markdown, to_json
from terraproof.inspect import inspect_dataset as _inspect_dataset
from terraproof.mcp.skills import SectionError, list_skills as _list_skills, load_section as _load_section
from terraproof.preflight import run_preflight as _run_preflight

LANGUAGES = ("en", "ar")

INSTRUCTIONS = (
    "Terraproof provides evidence-graded geospatial checks. Before you claim a mapping or "
    "remote-sensing result is correct, call `run_checks` on the outputs and report the grade. "
    "Call `inspect_dataset` on unfamiliar inputs, `find_guidance` at the start of a task to "
    "retrieve the relevant skill sections, and `load_section` to read one of those sections in "
    "full; installed skill files are not automatically loaded by every host. Use `preflight` "
    "to validate a declared plan against the real inputs before spending compute. For derived "
    "outputs, supply the relevant source operands and options to `run_checks`; inspection or "
    "a plausible value range alone does not verify the derivation. For NDVI, use "
    "`index_formula=\"ndvi\"`, `nir` and `red` on the saved output; for NBR, dNBR, NDWI, MNDWI, "
    "NDMI, SAVI or EVI pass `bands` by role (and `band_numbers` for multi-band sources). For "
    "composites, accumulations and trends pass the ordered input layers as `stack` with "
    "`stack_reduction` (and `stack_weights` for hours or times). Respect each band's scale "
    "and offset, source nodata masks and undefined denominators; valid zero values remain "
    "data. Review extra output masking against the task's QA policy. Read individual check "
    "statuses and limitations: warn and not-run do not establish correctness. Correct failed "
    "requirements and rerun checks after changes, or report what remains unresolved. All "
    "tools are read-only: they never modify your data."
)

mcp = MCPServer(name="terraproof", version=__version__, instructions=INSTRUCTIONS)


def _router() -> Any:
    """Import the router lazily: routing is optional for inspecting and checking."""
    try:
        from terraproof.router import find_guidance
    except Exception as exc:  # any import failure of the optional router package
        raise ToolError(
            "The Terraproof router is unavailable in this installation, so find_guidance cannot "
            f"rank skills ({exc}). Use `list_skills` and `load_section` instead."
        ) from exc
    return find_guidance


@mcp.tool()
def inspect_dataset(path: str) -> dict[str, Any]:
    """Inspect one local dataset and return its profile.

    Call this first on any vector, raster, or STAC Item file whose contents you have not
    seen: the result gives the CRS, units, extent, schema or bands, nodata, dtype,
    resolution, feature or pixel counts, and scale/offset that every later decision
    depends on. It reads local files only; it does not fetch URLs.
    """
    try:
        return jsonable(_inspect_dataset(path))
    except Exception as exc:  # tool boundary: a bad path is a message for the agent, not a crash
        raise ToolError(f"cannot inspect {path!r}: {exc}") from exc


@mcp.tool()
def run_checks(
    paths: list[str],
    operation: str | None = None,
    compare_to: str | None = None,
    resampling: str | None = None,
    categorical: bool = False,
    expect: str | None = None,
    reference_input: str | None = None,
    encoding: str | None = None,
    qa_path: str | None = None,
    qa_kind: str | None = None,
    time_range: list[str] | None = None,
    sar_expect: str | None = None,
    accuracy_samples: dict | list | str | None = None,
    class_areas: dict | str | None = None,
    min_per_class: int | None = None,
    estimates_requested: bool = False,
    dem: str | None = None,
    slope_method: str | None = None,
    raster_identity: bool = False,
    index_formula: str | None = None,
    nir: str | None = None,
    red: str | None = None,
    bands: dict[str, str] | None = None,
    band_numbers: dict[str, int] | None = None,
    stack: list[str] | None = None,
    stack_reduction: str | None = None,
    stack_weights: list[float] | None = None,
    stack_min_count: int | None = None,
    processing_full_scan: bool = False,
    manifest: str | None = None,
    require_provenance: bool = False,
    vertical_operation: str | None = None,
    vertical_sources: list[str] | None = None,
    vertical_source_units: list[str] | None = None,
    vertical_unit: str | None = None,
    support_sources: list[str] | None = None,
    support_source_nodata: list[float | None] | None = None,
    support_rule: str | None = None,
    contract: dict | str | None = None,
    profiles: list[str] | None = None,
    lang: str = "en",
) -> dict[str, Any]:
    """Run Terraproof's deterministic evidence checks and return the grade and report.

    Call this before you claim a geospatial result is correct. The grade is decision-grade only
    when a declared `contract` was fully verified; without one, passing checks give checks-passed,
    which does not show the output is fit for a decision. Otherwise it needs review or is advisory
    only. Read `report.coverage.not_checked` for applicable checks that did not run. Pass the
    outputs you produced, plus the inputs they came from, so CRS, geometry, scope, raster,
    and remote-sensing checks can run. `operation` is the metric operation the data will be
    used for (buffer, distance, area, length); `compare_to` is a source for vector record
    counts or explicit raster identity; `resampling` is the method declared for the rasters and `categorical` says
    they hold class codes; `expect` is the value range the bands should hold (reflectance or
    index). Phase 4 options include `reference_input`/`encoding` for scale/offset checks,
    `qa_path`/`qa_kind` for cloud-mask checks, `time_range` for temporal coverage.
    For final calibration/QA audits, set `processing_full_scan=True`: this checks
    every corresponding band and pixel in bounded windows; the default remains
    a sampled screen. This option does not expand other checks' scope.
    Use `sar_expect` for SAR domain checks, and `accuracy_samples`/`class_areas` for accuracy
    assessment. `dem` is the DEM a slope-in-degrees output was derived from; it checks the
    slope against the DEM's vertical unit and pixel spacing. Explicit
    `slope_method="central-difference"` instead verifies all values and the complete
    stencil/edge mask. `raster_identity=True` with `compare_to` compares all valid
    samples, masks and grid/band metadata; COG layout remains a separate screen. `index_formula="ndvi"` with
    single-band `nir` and `red` verifies calibrated NDVI values and source support; extra
    output masking warns because its QA policy is not supplied. `manifest` verifies a run manifest and appends `provenance.reproducible`;
    `require_provenance` prevents Decision-grade when no manifest is supplied. `lang`
    selects the Markdown language (en or ar). Results match `python -m terraproof check`.
    `vertical_operation` (convert or difference) with ordered `vertical_sources`, one
    declared unit each in `vertical_source_units`, and the output's `vertical_unit` checks
    height values for mixed or mislabelled units. `support_sources` with `support_rule`
    (all or any), and optionally each source's declared fill in `support_source_nodata`,
    checks that the output is valid exactly where its sources are. `profiles` names declared
    goal profiles (routing/profiles.json) required on every path, bound to the arguments
    given; a binding a profile needs but you did not give leaves it incomplete.
    Supply `contract` as a verification-contract object or local JSON path to require
    specific checks on specific outputs with declared source/parameter bindings.
    Read `report.verification` and `report.diagnostics`: missing required evidence
    prevents contract success even when every check that ran passes. Recheck the same
    contract after correcting a new output; no patch is applied by this tool.
    """
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
        raise ToolError("paths must be a non-empty list of file paths")
    if lang not in LANGUAGES:
        raise ToolError(f"unsupported language: {lang!r}; use one of {', '.join(LANGUAGES)}")
    try:
        inspections = [_inspect_dataset(path) for path in paths]
        compare = _inspect_dataset(compare_to) if compare_to else None
        reference = _inspect_dataset(reference_input) if reference_input else None
        dem_dataset = _inspect_dataset(dem) if dem else None
        nir_dataset = _inspect_dataset(nir) if nir else None
        red_dataset = _inspect_dataset(red) if red else None
        index_bands = {role: dict(_inspect_dataset(path), band=(band_numbers or {}).get(role))
                       for role, path in (bands or {}).items()}
        stack_layers = [_inspect_dataset(path) for path in stack or []]
        vertical_layers = [_inspect_dataset(path) for path in vertical_sources or []]
        support_layers = [_inspect_dataset(path) for path in support_sources or []]

        inputs = [input_record(path, "input", dataset["kind"]) for path, dataset in zip(paths, inspections)]
        if compare is not None:
            inputs.append(input_record(compare_to, "compare-to", compare["kind"]))
        if reference is not None:
            inputs.append(input_record(reference_input, "reference-input", reference["kind"]))
        if dem_dataset is not None:
            inputs.append(input_record(dem, "dem", dem_dataset["kind"]))
        if nir_dataset is not None:
            inputs.append(input_record(nir, "nir", nir_dataset["kind"]))
        if red_dataset is not None:
            inputs.append(input_record(red, "red", red_dataset["kind"]))
        for role, path in (bands or {}).items():
            inputs.append(input_record(path, "index-band", index_bands[role]["kind"]))
        for path, layer in zip(stack or [], stack_layers):
            inputs.append(input_record(path, "stack-layer", layer["kind"]))
        for path, layer in zip(vertical_sources or [], vertical_layers):
            inputs.append(input_record(path, "vertical-source", layer["kind"]))
        for path, layer in zip(support_sources or [], support_layers):
            inputs.append(input_record(path, "support-source", layer["kind"]))
        if qa_path and Path(qa_path).is_file():
            inputs.append(input_record(qa_path, "qa", "raster"))
        if isinstance(accuracy_samples, str) and Path(accuracy_samples).is_file():
            inputs.append(input_record(accuracy_samples, "accuracy-samples", "accuracy-samples"))
        if isinstance(class_areas, str) and Path(class_areas).is_file():
            inputs.append(input_record(class_areas, "class-areas", "class-areas"))
        if manifest and Path(manifest).is_file():
            inputs.append(input_record(manifest, "manifest", "manifest"))

        samples = load_accuracy_samples(accuracy_samples) if accuracy_samples is not None else None
        areas = load_class_areas(class_areas) if class_areas is not None else None
        time_tuple = tuple(time_range) if time_range else None

        results = _run_checks(
            inspections,
            compare_to=compare,
            operation=operation,
            resampling=resampling,
            categorical=categorical,
            expect=expect,
            reference_input=reference,
            encoding=encoding,
            qa_path=qa_path,
            qa_kind=qa_kind,
            time_range=time_tuple,
            sar_expect=sar_expect,
            accuracy_samples=samples,
            class_areas=areas,
            min_per_class=min_per_class,
            estimates_requested=estimates_requested,
            dem=dem_dataset,
            slope_method=slope_method,
            raster_identity=raster_identity,
            index_formula=index_formula,
            index_bands=index_bands or None,
            stack=stack_layers or None,
            stack_reduction=stack_reduction,
            stack_weights=stack_weights,
            stack_min_count=stack_min_count,
            nir=nir_dataset,
            red=red_dataset,
            processing_full_scan=processing_full_scan,
            vertical_operation=vertical_operation,
            vertical_sources=vertical_layers or None,
            vertical_source_units=vertical_source_units or None,
            vertical_unit=vertical_unit,
            support_sources=support_layers or None,
            support_source_nodata=support_source_nodata or None,
            support_rule=support_rule,
        )

        checked_paths = list(paths)
        for path in (compare_to, reference_input, dem, nir, red, *(bands or {}).values(), *(stack or []),
                     *(vertical_sources or []), *(support_sources or []), qa_path, accuracy_samples,
                     class_areas):
            if isinstance(path, str):
                checked_paths.append(path)

        if manifest:
            manifest_check = verify_manifest_coverage(manifest, checked_paths)
            results.append(manifest_check)
        elif require_provenance:
            results.append(
                result(
                    "provenance.reproducible",
                    "fail",
                    "Decision-grade requires a verified manifest, but none was supplied.",
                    manifest=None,
                )
            )
    except Exception as exc:  # tool boundary: unreadable inputs are a message for the agent
        raise ToolError(f"cannot check {paths!r}: {exc}") from exc

    parameters = {
        "operation": operation,
        "compare_to": compare_to,
        "resampling": resampling,
        "categorical": categorical,
        "expect": expect,
        "reference_input": reference_input,
        "encoding": encoding,
        "dem": dem,
        "slope_method": slope_method,
        "raster_identity": raster_identity,
        "index_formula": index_formula,
        "index_bands": {role: [path, (band_numbers or {}).get(role)] for role, path in (bands or {}).items()} or None,
        "stack": stack or None,
        "stack_reduction": stack_reduction,
        "stack_weights": stack_weights,
        "stack_min_count": stack_min_count,
        "nir": nir,
        "red": red,
        "processing_full_scan": processing_full_scan,
        "qa_path": qa_path,
        "qa_kind": qa_kind,
        "time_range": time_tuple,
        "sar_expect": sar_expect,
        "accuracy_samples": accuracy_samples,
        "class_areas": class_areas,
        "min_per_class": min_per_class,
        "estimates_requested": estimates_requested,
        "manifest": manifest,
        "require_provenance": require_provenance,
        "vertical_operation": vertical_operation,
        "vertical_sources": vertical_sources or None,
        "vertical_source_units": vertical_source_units or None,
        "vertical_unit": vertical_unit,
        "support_sources": support_sources or None,
        "support_source_nodata": support_source_nodata or None,
        "support_rule": support_rule,
    }
    try:
        if profiles and contract is not None:
            raise ValueError("give profiles or contract, not both")
        if profiles:
            from terraproof.evidence.contract import profile_contract
            contract = profile_contract(paths, profiles, parameters)
        report = build_report(inputs=inputs, results=results, parameters=parameters, contract=contract)
    except (OSError, ValueError, TypeError) as exc:
        raise ToolError(f"cannot evaluate verification contract: {exc}") from exc
    from terraproof.evidence.report import report_exit_code
    return {
        "grade": report["grade"],
        "exit_code": report_exit_code(report),
        "report": json.loads(to_json(report)),
        "markdown": render_markdown(report, lang=lang),
    }


@mcp.tool()
def preflight(
    paths: list[str],
    plan: dict | str,
    lang: str = "en",
) -> dict[str, Any]:
    """Check a declared processing plan against real inputs before running it.

    Pass the datasets the plan will use and either a plan dict or the path to a JSON plan
    file. Returns the same evidence-graded report format as `run_checks`, with check ids
    prefixed `preflight.*`. This is the MCP equivalent of
    `python -m terraproof preflight PATH... --plan FILE`.
    """
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
        raise ToolError("paths must be a non-empty list of file paths")
    if lang not in LANGUAGES:
        raise ToolError(f"unsupported language: {lang!r}; use one of {', '.join(LANGUAGES)}")
    try:
        inspections = [_inspect_dataset(path) for path in paths]
        if isinstance(plan, str):
            plan_path = plan
            with open(plan_path, encoding="utf-8") as handle:
                plan_data = json.load(handle)
            if not isinstance(plan_data, dict):
                raise InputError(f"plan file must contain a JSON object: {plan_path}")
        elif isinstance(plan, dict):
            plan_path = "(supplied dict)"
            plan_data = plan
        else:
            raise InputError("plan must be a dict or a file path")

        inputs = [input_record(path, "input", dataset["kind"]) for path, dataset in zip(paths, inspections)]
        if Path(plan_path).is_file():
            inputs.append(input_record(plan_path, "plan", "plan"))

        results = _run_preflight(inspections, plan_data)
        parameters = {"plan": plan_path, "plan_content": plan_data}
        report = build_report(inputs=inputs, results=results, parameters=parameters)
    except Exception as exc:
        raise ToolError(f"cannot run preflight: {exc}") from exc

    return {
        "grade": report["grade"],
        "exit_code": EXIT_CODES[report["grade"]],
        "report": json.loads(to_json(report)),
        "markdown": render_markdown(report, lang=lang),
    }


@mcp.tool()
def list_skills() -> list[dict]:
    """List the Terraproof skills you can load, with their sections and checks.

    Call this when you need to know which guidance exists before choosing one, or when
    the router is unavailable. Each entry gives the skill name, its layer, a one-sentence
    explanation, the id and title of every section, and the check ids the skill bears on.
    Follow up with `load_section` to read a section.
    """
    try:
        return _list_skills()
    except Exception as exc:
        raise ToolError(f"cannot read the skill registry: {exc}") from exc


@mcp.tool()
def load_section(skill: str, section_id: str) -> dict[str, Any]:
    """Load one skill section's Markdown text.

    Call this after `find_guidance` or `list_skills` names a section you need, instead of
    reading a whole SKILL.md. Unknown skills and sections are rejected, and a section may
    only resolve to a file inside its own skill directory.
    """
    try:
        return _load_section(skill, section_id)
    except SectionError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        raise ToolError(f"cannot load {skill!r}/{section_id!r}: {exc}") from exc


@mcp.tool()
def find_guidance(
    task: str,
    data_paths: list[str] | None = None,
    top_k: int = 5,
    mode: str = "ranked",
    semantic: bool = False,
) -> dict[str, Any]:
    """Rank the skill sections that fit a mapping or remote-sensing task.

    Call this at the start of a task, with the datasets you will work on, to get the few
    sections worth reading instead of the whole catalogue. `data_paths` are local datasets
    that are inspected to steer retrieval; `top_k` caps the number of ranked skills. Use
    `mode=candidates` for a recall-oriented list the host model can re-rank, and
    `semantic=true` to enable the optional local semantic retrieval pass. This is the same
    retrieval `python -m terraproof route` performs.
    """
    find_guidance_fn = _router()
    try:
        return jsonable(find_guidance_fn(task, data_paths=list(data_paths or []), top_k=top_k, mode=mode, semantic=semantic))
    except Exception as exc:  # tool boundary: an empty task or unreadable dataset
        raise ToolError(f"cannot route {task!r}: {exc}") from exc
