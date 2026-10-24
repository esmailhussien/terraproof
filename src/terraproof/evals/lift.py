"""Agent-lift harness: does an agent produce correct artifacts more often with Terraproof?

Each lift task reuses one executable benchmark task. The harness builds that task's
fixtures, copies only the declared **inputs** into a fresh agent project, and asks an agent
adapter to write the declared **deliverables**. The "without" project holds nothing else;
the "with" project additionally gets Terraproof through its own installer (router-selected
skills, agent instructions and the MCP server).

Scoring never re-implements a task. The task's existing recipe is run again in a private
scoring directory while the deliverable files it would write are replaced, at write time,
by the agent's files. The recipe's unmodified checks and independent oracle then grade the
agent's artifact exactly as they grade the reference solution. Before any agent run, a
calibration gate proves for every task that this substitution accepts the reference
solution, rejects every seeded-wrong output, rejects an echoed input and reports a missing
file, and that the inputs regenerate byte-identically.

The adapters shipped here are offline: `ScriptedAdapter` writes reference, seeded-wrong,
echoed or missing outputs, and `ReplayAdapter` replays recorded outputs. Neither calls a
model, so CI and the unit tests never spend anything. Real agent hosts live in the opt-in
`tests/agent_lift.py` driver, behind an explicit approval and a hard budget.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import random
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from statistics import NormalDist

from terraproof.evals import fixtures
from terraproof.evals.harness import CORRECT, _control_record, _sanitize
from terraproof.evals.specs import SpecError, TaskSpec, load_specs
from terraproof.evidence.grade import grade_for

SCHEMA = "terraproof.evals.lift/0.1"
WITHOUT = "without"
WITH = "with"
CONDITIONS = (WITHOUT, WITH)
ACCEPTED = "accepted"
REJECTED = "rejected"
MISSING = "missing"
ERROR = "error"
INVALID = "invalid"
NOT_RUN = "not_run"
MAX_DELIVERABLE_BYTES = 64 * 1024 * 1024
SIDECARS = (".aux.xml", ".ovr")
BOOTSTRAP_SEED = 20261024
BOOTSTRAP_RESAMPLES = 10_000
EXACT_SIGN_FLIP_MAX_TASKS = 20
FLOAT_GRID = "single-band float32 GeoTIFF on the input grid (same CRS, transform and shape), nodata -9999"
COUNT_GRID = "single-band uint8 GeoTIFF on the input grid, nodata 255"

LIMITATIONS = [
    "Only artifact-producing tasks whose recipe oracle reads the delivered file are eligible; prose, "
    "explanations and design reasoning in the agent's answer are not scored.",
    "Scoring sensitivity is exactly the recipe's: calibration proves each seeded-wrong output, an echoed input "
    "and a missing file are rejected, not that every conceivable wrong artifact is.",
    "A task's deliverable contract fixes file names, grid, dtype and nodata so a correct answer is gradable; "
    "it does not reveal the task's pitfall or the oracle's control values.",
    "The offline adapters prove the harness, not agent lift. Lift is measured only by an approved real-host run.",
]


class LiftError(ValueError):
    """An agent-lift run cannot start or its configuration is inconsistent."""


@dataclass(frozen=True)
class LiftTask:
    """An executable benchmark task re-posed as an agent task with file deliverables."""

    task_id: str
    inputs: tuple[str, ...]
    deliverables: tuple[tuple[str, str], ...]  # (file name, format contract)
    seeded: tuple[tuple[str, str], ...]  # (deliverable it replaces, seeded-wrong fixture file)

    @property
    def deliverable_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.deliverables)


# Selected by probing every recipe: these are the tasks whose inputs exist as files and
# whose correct-control oracle rejects each seeded-wrong deliverable once substituted.
LIFT_TASKS: tuple[LiftTask, ...] = (
    LiftTask(
        "indices-ndvi-physical-inputs",
        ("red_dn.tif", "nir_dn.tif"),
        (("ndvi.tif", f"NDVI, {FLOAT_GRID}"),),
        (("ndvi.tif", "ndvi_dn_ratio.tif"),),
    ),
    LiftTask(
        "raster-cog-delivery",
        ("analysis.tif",),
        (("delivery.tif", "analysis.tif delivered as a Cloud Optimized GeoTIFF with the same grid, dtype and nodata"),),
        (("delivery.tif", "delivery_lossy.tif"), ("delivery.tif", "delivery_striped.tif")),
    ),
    LiftTask(
        "raster-nodata-dtype-windowing",
        ("first_u16.tif", "second_u16.tif"),
        (("difference.tif", "first_u16.tif minus second_u16.tif, single-band floating-point GeoTIFF on the input "
                            "grid, nodata -9999"),),
        (("difference.tif", "difference_wrapped_u16.tif"),),
    ),
    LiftTask(
        "sar-db-linear-monthly-mean",
        ("vv_date1.tif", "vv_date2.tif", "vv_date3.tif"),
        (
            ("vv_monthly_mean_db.tif", f"monthly mean VV backscatter in dB, {FLOAT_GRID}"),
            ("vv_valid_dates.tif", f"per-pixel number of dates contributing to the mean, {COUNT_GRID}"),
        ),
        (("vv_monthly_mean_db.tif", "vv_monthly_mean_naive_db.tif"),),
    ),
    LiftTask(
        "satellite-landsat-qa-once",
        ("landsat_dn.tif", "qa_pixel.tif"),
        (("landsat_sr.tif", f"surface reflectance, {FLOAT_GRID}"),),
        (("landsat_sr.tif", "landsat_sr_double.tif"), ("landsat_sr.tif", "landsat_sr_clear_only.tif")),
    ),
    LiftTask(
        "satellite-s2-baseline-offset-mask",
        ("red_dn.tif", "nir_dn.tif", "scl.tif"),
        (
            ("sr_red.tif", f"red surface reflectance, {FLOAT_GRID}"),
            ("sr_nir.tif", f"NIR surface reflectance, {FLOAT_GRID}"),
        ),
        (("sr_red.tif", "sr_red_no_offset.tif"), ("sr_red.tif", "sr_red_unmasked.tif")),
    ),
    LiftTask(
        "satellite-seasonal-harmonized-composite",
        tuple(f"s2_date{index}_{band}.tif" for index in (1, 2, 3) for band in ("red", "nir")) + ("source-item.json",),
        (
            ("composite.tif", f"seasonal median red surface-reflectance composite of the dated red inputs, {FLOAT_GRID}"),
            ("composite_counts.tif", f"per-pixel count of valid observations used, {COUNT_GRID}"),
        ),
        (("composite.tif", "composite_cloudy.tif"), ("composite.tif", "composite_zero_filled.tif")),
    ),
    LiftTask(
        "stac-loader-double-decode",
        ("red_dn.tif", "source-item.json"),
        (("sr_red.tif", f"red surface reflectance, {FLOAT_GRID}"),),
        (("sr_red.tif", "sr_red_double.tif"), ("sr_red.tif", "sr_red_zero_valid.tif")),
    ),
    LiftTask(
        "ts-phenology-matched-difference",
        ("ndvi_2023-04.tif", "ndvi_2023-07.tif", "ndvi_2024-07.tif", "scl_2024.tif",
         "april-item.json", "july-2023-item.json", "july-2024-item.json"),
        (("difference_2023_2024.tif", f"2024 NDVI minus 2023 NDVI for the loss comparison, {FLOAT_GRID}"),),
        (("difference_2023_2024.tif", "difference_april_2024.tif"),
         ("difference_2023_2024.tif", "difference_unmasked.tif")),
    ),
)


# -- budget and adapters -----------------------------------------------------------------
@dataclass(frozen=True)
class Budget:
    """Hard limits; a run that could exceed them is never started."""

    max_runs: int | None = None
    per_run_usd: float | None = None
    total_usd: float | None = None
    timeout_seconds: float = 900.0


@dataclass(frozen=True)
class AgentRequest:
    """What an adapter is given: the project directory and the brief, nothing else."""

    task_id: str
    condition: str
    run_index: int
    project: Path
    brief: str
    timeout_seconds: float
    max_usd: float | None


@dataclass
class AgentResult:
    """What an adapter reports. Counts and labels only: never prompts, streams or paths."""

    status: str  # completed | failed | timeout
    cost_usd: float | None = 0.0
    tool_calls: int = 0
    terraproof_tool_calls: int = 0
    skill_reads: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    contamination: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


class Adapter:
    """Base class. `model_calls` adapters run only with an explicit opt-in and a budget."""

    name = "adapter"
    model_calls = False
    usd_capped = False

    def run(self, request: AgentRequest) -> AgentResult:  # pragma: no cover - interface
        raise NotImplementedError


SCRIPTED_BEHAVIOURS = ("reference", "seeded", "echo-input", "missing")


class ScriptedAdapter(Adapter):
    """Offline control agent: writes reference, seeded-wrong, echoed-input or no outputs.

    It regenerates the task's own fixtures in a private directory beside (never inside) the
    project, so it needs no privileged channel from the harness. `seeded` cycles through the
    task's seeded-wrong outputs by run index.
    """

    name = "scripted"

    def __init__(self, behaviours: dict[str, str]):
        unknown = {value for value in behaviours.values()} - set(SCRIPTED_BEHAVIOURS)
        if unknown or set(behaviours) != set(CONDITIONS):
            raise LiftError(f"scripted behaviours need both conditions from {SCRIPTED_BEHAVIOURS}")
        self.behaviours = dict(behaviours)

    def run(self, request: AgentRequest) -> AgentResult:
        task = lift_task(request.task_id)
        behaviour = self.behaviours[request.condition]
        outputs = request.project / "outputs"
        if behaviour == "missing":
            return AgentResult(status="completed")
        private = request.project.parent / "scripted-private"
        try:
            _generate(task, private)
            files = {name: private / name for name in task.deliverable_names}
            if behaviour == "seeded":
                target, wrong = task.seeded[request.run_index % len(task.seeded)]
                files[target] = private / wrong
            elif behaviour == "echo-input":
                files[task.deliverable_names[0]] = request.project / "inputs" / task.inputs[0]
            for name, source in files.items():
                shutil.copyfile(source, outputs / name)
        finally:
            shutil.rmtree(private, ignore_errors=True)
        return AgentResult(status="completed")


class ReplayAdapter(Adapter):
    """Replays recorded outputs from `<recordings>/<task>/<condition>/run-<k>/`.

    A recording holds `outputs/*` and an optional `result.json` with AgentResult fields, so a
    real run can be re-scored offline and deterministically after the fact.
    """

    name = "replay"

    def __init__(self, recordings: Path | str):
        self.recordings = Path(recordings)
        if not self.recordings.is_dir():
            raise LiftError(f"recordings directory not found: {self.recordings}")

    def run(self, request: AgentRequest) -> AgentResult:
        source = self.recordings / request.task_id / request.condition / f"run-{request.run_index}"
        if not source.is_dir():
            return AgentResult(status="failed", diagnostics=["no recording"])
        recorded = source / "outputs"
        if recorded.is_dir():
            for path in sorted(recorded.iterdir()):
                if path.is_file() and not path.is_symlink():
                    shutil.copyfile(path, request.project / "outputs" / path.name)
        result_path = source / "result.json"
        if not result_path.is_file():
            return AgentResult(status="completed", cost_usd=None)
        data = json.loads(result_path.read_text(encoding="utf-8"))
        allowed = set(AgentResult.__dataclass_fields__)
        return AgentResult(**{key: value for key, value in data.items() if key in allowed})


# -- tasks, fixtures and workspaces ------------------------------------------------------
def lift_task(task_id: str) -> LiftTask:
    for task in LIFT_TASKS:
        if task.task_id == task_id:
            return task
    raise LiftError(f"not an agent-lift task: {task_id!r}; choose from {[t.task_id for t in LIFT_TASKS]}")


def _registry():
    from terraproof.evals.recipes import REGISTRY

    return REGISTRY


def _generate(task: LiftTask, root: Path):
    root.mkdir(parents=True, exist_ok=True)
    return _registry()[task.task_id](root)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def brief(task: LiftTask, spec: TaskSpec) -> str:
    """The agent-facing task text: identical in both conditions, and free of oracle values."""
    lines = [
        "# Task",
        "",
        spec.prompt,
        "",
        "## Supplied files",
        "",
        "The input files are in `inputs/`: " + ", ".join(f"`{name}`" for name in task.inputs) + ".",
        "No other data is supplied and there is no network access. Work only inside this directory.",
        "",
        "## Required output",
        "",
        "Write these files to `outputs/`:",
        "",
    ]
    lines += [f"- `{name}`: {contract}." for name, contract in task.deliverables]
    lines += [
        "",
        "Parts of the request that the supplied files cannot support may be answered in prose. "
        "Finish with a short summary of what you did.",
        "",
    ]
    return "\n".join(lines)


def _install(project: Path, agent: str, spec: TaskSpec) -> tuple[int, list[str]]:
    """Install Terraproof exactly as a user would: router-selected skills plus the MCP server."""
    from terraproof.install import main as install_main, resolve_skill_names

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = install_main(["--agent", agent, "--task", spec.prompt, "--target", str(project), "--with-mcp"])
    return code, resolve_skill_names(None, spec.prompt) if code == 0 else []


def prepare_project(task: LiftTask, spec: TaskSpec, reference: Path, project: Path, *, condition: str, agent: str) -> dict:
    """Create an agent project with inputs, an empty outputs/ and TASK.md; install Terraproof for "with"."""
    if condition not in CONDITIONS:
        raise LiftError(f"unknown condition: {condition!r}")
    (project / "inputs").mkdir(parents=True)
    (project / "outputs").mkdir()
    for name in task.inputs:
        shutil.copyfile(reference / name, project / "inputs" / name)
    (project / "TASK.md").write_text(brief(task, spec), encoding="utf-8", newline="\n")
    installed = {"install_exit": None, "skills": []}
    if condition == WITH:
        code, skills = _install(project, agent, spec)
        installed = {"install_exit": code, "skills": skills}
    return installed


# -- scoring by substitution -------------------------------------------------------------
@contextlib.contextmanager
def _substitute(root: Path, mapping: dict[str, Path], hits: set[str]):
    """While a recipe runs, writes to the deliverable paths copy the agent's files instead."""
    from terraproof.evals import recipes
    from terraproof.evals.recipes import _util

    resolved_root = root.resolve()

    def wrap(writer):
        def substituted(path, *args, **kwargs):
            target = Path(path)
            try:
                relative = target.resolve().relative_to(resolved_root).as_posix()
            except ValueError:
                relative = None
            if relative not in mapping:
                return writer(path, *args, **kwargs)
            hits.add(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mapping[relative], target)
            for suffix in SIDECARS:
                sidecar = Path(str(mapping[relative]) + suffix)
                if sidecar.is_file() and not sidecar.is_symlink():
                    shutil.copyfile(sidecar, Path(str(target) + suffix))
            return str(target)

        return substituted

    modules = (fixtures, _util, *recipes._MODULES)
    names = [name for name in dir(fixtures) if name.startswith("write_")]
    originals = [(module, name, getattr(module, name)) for module in modules for name in names if hasattr(module, name)]
    replacements: dict[int, object] = {}
    for module, name, writer in originals:
        setattr(module, name, replacements.setdefault(id(writer), wrap(writer)))
    try:
        yield
    finally:
        for module, name, writer in originals:
            setattr(module, name, writer)


def _deliverable_ok(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_DELIVERABLE_BYTES


def score_outputs(task: LiftTask, spec: TaskSpec, outputs: Path, scoring_root: Path, input_digests: dict[str, str]) -> dict:
    """Grade the agent's deliverables with the task's own checks and independent oracle."""
    present = {name: _deliverable_ok(outputs / name) for name in task.deliverable_names}
    record = {"deliverables_present": present, "verdict": MISSING, "accepted": False, "checks_ok": None,
              "oracle_ok": None, "caught_by": [], "mismatched_checks": [], "unexpected_failures": [],
              "failed_assertions": [], "evidence_grade": None, "error": None}
    if not all(present.values()):
        return record
    hits: set[str] = set()
    try:
        with _substitute(scoring_root, {name: outputs / name for name in task.deliverable_names}, hits):
            recipe = _generate(task, scoring_root)
    except Exception as error:  # an unreadable or malformed artifact is a failed answer, not a crash
        record.update(verdict=ERROR, error=type(error).__name__)
        return record
    if hits != set(task.deliverable_names):
        record.update(verdict=INVALID, error="a deliverable was not substituted into the recipe")
        return record
    drift = sorted(name for name, digest in input_digests.items() if _digest(scoring_root / name) != digest)
    if drift:
        record.update(verdict=INVALID, error=f"fixture inputs regenerated differently: {drift}")
        return record
    control = recipe.correct
    if control.kind != CORRECT:  # pragma: no cover - guarded by TaskRecipe
        raise LiftError("recipe correct control is not marked correct")
    results = [result for step in control.steps for result in step.results]
    graded = _control_record(control, spec.expected_checks, scoring_root, grade_for(results))
    accepted = graded["verdict"] == "accepted"
    caught = []
    if not graded["checks_ok"]:
        caught.append("checks")
    if not graded["oracle_ok"]:
        caught.append("oracle")
    record.update(
        verdict=ACCEPTED if accepted else REJECTED,
        accepted=accepted,
        checks_ok=graded["checks_ok"],
        oracle_ok=graded["oracle_ok"],
        caught_by=caught,
        mismatched_checks=graded["mismatched_checks"],
        unexpected_failures=graded["unexpected_failures"],
        failed_assertions=[a["name"] for a in graded["oracle"]["assertions"] if not a["passed"]],
        evidence_grade=graded["evidence_grade"],
    )
    return record


# -- calibration -------------------------------------------------------------------------
def _calibrate_task(task: LiftTask, spec: TaskSpec, root: Path) -> dict:
    reference = root / "reference"
    _generate(task, reference)
    again = root / "regenerated"
    _generate(task, again)
    digests = {name: _digest(reference / name) for name in task.inputs}
    deterministic = all(_digest(again / name) == digest for name, digest in digests.items())

    def score(label: str, files: dict[str, Path]) -> dict:
        outputs = root / label / "outputs"
        outputs.mkdir(parents=True)
        for name, source in files.items():
            shutil.copyfile(source, outputs / name)
        return score_outputs(task, spec, outputs, root / label / "scoring", digests)

    reference_files = {name: reference / name for name in task.deliverable_names}
    cases = [{"case": "reference", "expected": ACCEPTED, **_brief_score(score("reference", reference_files))}]
    for index, (target, wrong) in enumerate(task.seeded):
        files = dict(reference_files, **{target: reference / wrong})
        cases.append({"case": f"seeded:{wrong}", "expected": REJECTED, **_brief_score(score(f"seeded-{index}", files))})
    echo = dict(reference_files, **{task.deliverable_names[0]: reference / task.inputs[0]})
    cases.append({"case": f"echo-input:{task.inputs[0]}", "expected": "not accepted", **_brief_score(score("echo", echo))})
    cases.append({"case": "missing", "expected": MISSING, **_brief_score(score("missing", {}))})
    passed = [
        case["verdict"] == case["expected"] if case["expected"] != "not accepted" else not case["accepted"]
        for case in cases
    ]
    return {"task": task.task_id, "inputs_deterministic": deterministic, "cases": cases,
            "eligible": deterministic and all(passed)}


def _brief_score(record: dict) -> dict:
    return {key: record[key] for key in ("verdict", "accepted", "caught_by", "error")}


def calibrate(task_ids: list[str] | None = None, *, work_root: Path | str | None = None, keep: bool = False) -> dict:
    """Prove that substitution scoring accepts references and rejects seeded/echoed/missing outputs."""
    tasks = _select(task_ids)
    specs = _specs()
    with _workspace(work_root, keep, "calibrate") as base:
        records = [_calibrate_task(task, specs[task.task_id], base / task.task_id) for task in tasks]
    return {"tasks": records, "eligible": all(record["eligible"] for record in records)}


# -- running and statistics --------------------------------------------------------------
def _specs() -> dict[str, TaskSpec]:
    return {spec.id: spec for spec in load_specs()}


def _select(task_ids: list[str] | None) -> list[LiftTask]:
    if not task_ids:
        return list(LIFT_TASKS)
    seen = []
    for task_id in task_ids:
        task = lift_task(task_id)
        if task not in seen:
            seen.append(task)
    return sorted(seen, key=lambda item: item.task_id)


@contextlib.contextmanager
def _workspace(work_root: Path | str | None, keep: bool, label: str):
    if work_root is not None:
        base = Path(work_root)
        base.mkdir(parents=True, exist_ok=True)
        yield base
        return
    cache = Path.cwd() / ".terracache" / "lift"
    cache.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix=f"terraproof-lift-{label}-", dir=cache))
    try:
        yield base
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)


def schedule(tasks: list[LiftTask], runs: int) -> list[tuple[int, LiftTask, tuple[str, str]]]:
    """Deterministic paired order: both conditions of a pair run back to back, alternating first."""
    order = []
    for run_index in range(runs):
        for task_index, task in enumerate(tasks):
            pair = CONDITIONS if (task_index + run_index) % 2 == 0 else CONDITIONS[::-1]
            order.append((run_index, task, pair))
    return order


def planned_calls(task_count: int, runs: int) -> int:
    return task_count * runs * len(CONDITIONS)


def _check_budget(adapter: Adapter, budget: Budget, planned: int, allow_model_calls: bool) -> None:
    if adapter.model_calls and not allow_model_calls:
        raise LiftError(f"adapter {adapter.name!r} calls a model; it needs an explicit opt-in")
    if budget.max_runs is not None and planned > budget.max_runs:
        raise LiftError(f"{planned} planned agent runs exceed the approved maximum of {budget.max_runs}")
    if not adapter.model_calls:
        return
    if budget.max_runs is None or budget.timeout_seconds <= 0:
        raise LiftError("model-calling runs need an approved run count and a positive per-run timeout")
    if adapter.usd_capped and (budget.per_run_usd is None or budget.total_usd is None):
        raise LiftError("a USD-billed adapter needs both a per-run and a total USD cap")


def run_lift(
    adapter: Adapter,
    *,
    task_ids: list[str] | None = None,
    runs: int = 1,
    agent: str = "codex",
    budget: Budget = Budget(),
    work_root: Path | str | None = None,
    keep: bool = False,
    allow_model_calls: bool = False,
    recordings_out: Path | str | None = None,
) -> dict:
    """Run the paired with/without experiment and return a deterministic JSON report."""
    if runs < 1:
        raise LiftError("runs must be at least 1")
    tasks = _select(task_ids)
    specs = _specs()
    planned = planned_calls(len(tasks), runs)
    _check_budget(adapter, budget, planned, allow_model_calls)
    spent = 0.0
    started = 0
    records: dict[str, list[dict]] = {task.task_id: [] for task in tasks}
    routed: dict[str, list[str]] = {}
    with _workspace(work_root, keep, "run") as base:
        calibration = {"tasks": [_calibrate_task(task, specs[task.task_id], base / "calibration" / task.task_id)
                                 for task in tasks]}
        calibration["eligible"] = all(item["eligible"] for item in calibration["tasks"])
        if not calibration["eligible"]:
            failing = [item["task"] for item in calibration["tasks"] if not item["eligible"]]
            raise LiftError(f"calibration failed; scoring is not trustworthy for: {failing}")
        # Keep only the calibrated inputs. No reference or seeded-wrong artifact stays on disk
        # while an agent runs; scoring regenerates the recipe after the agent has finished.
        references = {task.task_id: base / "inputs" / task.task_id for task in tasks}
        for task in tasks:
            references[task.task_id].mkdir(parents=True)
            for name in task.inputs:
                shutil.copyfile(base / "calibration" / task.task_id / "reference" / name,
                                references[task.task_id] / name)
        shutil.rmtree(base / "calibration", ignore_errors=True)
        digests = {task.task_id: {name: _digest(references[task.task_id] / name) for name in task.inputs}
                   for task in tasks}
        stopped = None
        for run_index, task, pair in schedule(tasks, runs):
            pair_cost = 2 * budget.per_run_usd if budget.per_run_usd is not None else 0.0
            if stopped is None and budget.total_usd is not None and spent + pair_cost > budget.total_usd + 1e-9:
                stopped = "total USD budget would be exceeded"
            for condition in pair:
                record = {"run": run_index, "condition": condition}
                if stopped:
                    record.update(adapter_status=NOT_RUN, verdict=NOT_RUN, accepted=False, reason=stopped)
                    records[task.task_id].append(record)
                    continue
                run_dir = base / "runs" / task.task_id / f"run-{run_index}" / condition
                project = run_dir / "project"
                installed = prepare_project(task, specs[task.task_id], references[task.task_id], project,
                                            condition=condition, agent=agent)
                if condition == WITH:
                    routed[task.task_id] = installed["skills"]
                if installed["install_exit"] not in (None, 0):
                    record.update(adapter_status="install_failed", verdict=NOT_RUN, accepted=False)
                    records[task.task_id].append(record)
                    continue
                request = AgentRequest(task.task_id, condition, run_index, project, brief(task, specs[task.task_id]),
                                       budget.timeout_seconds, budget.per_run_usd)
                started += 1
                result = adapter.run(request)
                cost = result.cost_usd if result.cost_usd is not None else (budget.per_run_usd or 0.0)
                spent += cost
                score = score_outputs(task, specs[task.task_id], project / "outputs", run_dir / "scoring",
                                      digests[task.task_id])
                if result.contamination:
                    score.update(accepted=False, verdict=REJECTED if score["verdict"] == ACCEPTED else score["verdict"])
                record.update(adapter_status=result.status, **score,
                              agent={key: value for key, value in asdict(result).items() if key != "status"})
                records[task.task_id].append(record)
                if recordings_out is not None:
                    _record(Path(recordings_out), task, condition, run_index, project / "outputs", result)
                if not keep:
                    # A later agent must not find this run's project, outputs or scoring tree.
                    shutil.rmtree(run_dir, ignore_errors=True)
                if budget.total_usd is not None and spent > budget.total_usd + 1e-9:
                    stopped = "total USD budget exhausted"
    task_reports = [
        {"id": task.task_id, "skill": specs[task.task_id].skill, "inputs": list(task.inputs),
         "deliverables": [{"file": name, "contract": contract} for name, contract in task.deliverables],
         "routed_skills": routed.get(task.task_id, []),
         "runs": _sanitize(sorted(records[task.task_id], key=lambda r: (r["run"], r["condition"])), Path(base))}
        for task in tasks
    ]
    return {
        "schema": SCHEMA,
        "command": "python -m terraproof.evals lift",
        "adapter": {"name": adapter.name, "model_calls": adapter.model_calls},
        "agent_format": agent,
        "design": {"conditions": list(CONDITIONS), "tasks": len(tasks), "runs_per_condition": runs,
                   "planned_agent_runs": planned, "started_agent_runs": started,
                   "order": "paired, back to back, first condition alternating by task and run",
                   "treatment": "python -m terraproof.install --task <spec prompt> --with-mcp"},
        "budget": {**asdict(budget), "spent_usd": round(spent, 6)},
        "calibration": calibration,
        "tasks": task_reports,
        "summary": summarize(task_reports),
        "limitations": LIMITATIONS,
    }


def _record(root: Path, task: LiftTask, condition: str, run_index: int, outputs: Path, result: AgentResult) -> None:
    target = root / task.task_id / condition / f"run-{run_index}"
    (target / "outputs").mkdir(parents=True, exist_ok=True)
    for name in task.deliverable_names:
        if _deliverable_ok(outputs / name):
            shutil.copyfile(outputs / name, target / "outputs" / name)
    (target / "result.json").write_text(json.dumps(asdict(result), sort_keys=True, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")


def _round(value):
    return None if value is None else round(float(value), 6)


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: a binomial test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def sign_flip_p(differences: list[float]) -> float | None:
    """Exact two-sided randomization p-value for the mean task-level difference."""
    if not differences or len(differences) > EXACT_SIGN_FLIP_MAX_TASKS:
        return None
    observed = abs(sum(differences))
    extreme = sum(
        1 for signs in product((1, -1), repeat=len(differences))
        if abs(sum(sign * value for sign, value in zip(signs, differences))) >= observed - 1e-12
    )
    return extreme / 2 ** len(differences)


def bootstrap_ci(differences: list[float], *, seed: int = BOOTSTRAP_SEED, resamples: int = BOOTSTRAP_RESAMPLES,
                 level: float = 0.95) -> list[float] | None:
    """Percentile CI of the mean task-level difference; tasks are resampled (cluster bootstrap)."""
    if len(differences) < 2:
        return None
    rng = random.Random(seed)
    count = len(differences)
    means = sorted(
        sum(differences[int(rng.random() * count)] for _ in range(count)) / count for _ in range(resamples)
    )
    low = means[int(math.floor((1 - level) / 2 * resamples))]
    high = means[min(resamples - 1, int(math.ceil((1 + level) / 2 * resamples)) - 1)]
    return [low, high]


def mcnemar_mde(pairs: int, discordance: float, *, alpha: float = 0.05, power: float = 0.8) -> float | None:
    """Smallest paired difference detectable with McNemar's test (Connor 1987 approximation)."""
    if pairs <= 0 or not 0 < discordance <= 1:
        return None
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)

    def required(delta: float) -> float:
        return (z_alpha * math.sqrt(discordance) + z_beta * math.sqrt(max(0.0, discordance - delta**2))) ** 2 / delta**2

    low, high = 1e-6, math.sqrt(discordance)
    if required(high) > pairs:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        if required(middle) > pairs:
            low = middle
        else:
            high = middle
    return high


def summarize(task_reports: list[dict]) -> dict:
    """Paired statistics; the task is the unit of the primary analysis."""
    b = c = both = neither = 0
    differences = []
    per_task = []
    rates = {WITH: [0, 0], WITHOUT: [0, 0]}
    secondary = {condition: {"rejected_by_checks": 0, "rejected_by_oracle_only": 0, "missing_or_error": 0,
                             "contaminated": 0, "tool_calls": 0, "terraproof_tool_calls": 0, "skill_reads": 0,
                             "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
                 for condition in CONDITIONS}
    incomplete = 0
    for task in task_reports:
        by_run: dict[int, dict[str, dict]] = {}
        for run in task["runs"]:
            by_run.setdefault(run["run"], {})[run["condition"]] = run
            stats = secondary[run["condition"]]
            if run["verdict"] == REJECTED and "checks" in run.get("caught_by", []):
                stats["rejected_by_checks"] += 1
            elif run["verdict"] == REJECTED and run.get("caught_by") == ["oracle"]:
                stats["rejected_by_oracle_only"] += 1
            elif run["verdict"] in (MISSING, ERROR, INVALID):
                stats["missing_or_error"] += 1
            agent = run.get("agent", {})
            stats["contaminated"] += bool(agent.get("contamination"))
            for key in ("tool_calls", "terraproof_tool_calls", "skill_reads", "input_tokens", "output_tokens"):
                stats[key] += int(agent.get(key) or 0)
            stats["cost_usd"] += float(agent.get("cost_usd") or 0.0)
        task_with = task_without = pairs = 0
        for run in by_run.values():
            if set(run) != set(CONDITIONS) or any(item["verdict"] == NOT_RUN for item in run.values()):
                incomplete += 1
                continue
            pairs += 1
            outcome_with, outcome_without = run[WITH]["accepted"], run[WITHOUT]["accepted"]
            task_with += outcome_with
            task_without += outcome_without
            b += outcome_with and not outcome_without
            c += outcome_without and not outcome_with
            both += outcome_with and outcome_without
            neither += not outcome_with and not outcome_without
        rates[WITH][0] += task_with
        rates[WITHOUT][0] += task_without
        rates[WITH][1] += pairs
        rates[WITHOUT][1] += pairs
        difference = (task_with - task_without) / pairs if pairs else None
        if difference is not None:
            differences.append(difference)
        per_task.append({"task": task["id"], "pairs": pairs, "accepted_with": task_with,
                         "accepted_without": task_without, "difference": _round(difference)})
    pairs_total = b + c + both + neither
    mean_difference = sum(differences) / len(differences) if differences else None
    ci = bootstrap_ci(differences)
    discordance = (b + c) / pairs_total if pairs_total else None
    return {
        "primary_metric": "oracle-and-check acceptance of the agent's final deliverables (per run, binary)",
        "complete_pairs": pairs_total,
        "incomplete_pairs": incomplete,
        "pass_rate": {condition: _round(rates[condition][0] / rates[condition][1]) if rates[condition][1] else None
                      for condition in CONDITIONS},
        "mean_task_difference": _round(mean_difference),
        "mean_task_difference_ci95": [_round(value) for value in ci] if ci else None,
        "ci_method": f"task-cluster percentile bootstrap, {BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}",
        "sign_flip_p": _round(sign_flip_p(differences)),
        "mcnemar": {"with_only": b, "without_only": c, "both": both, "neither": neither,
                    "exact_p": _round(exact_mcnemar(b, c))},
        "observed_discordance": _round(discordance),
        "mde_at_observed_discordance": _round(mcnemar_mde(pairs_total, discordance)) if discordance else None,
        "per_task": per_task,
        "secondary": {condition: {key: _round(value) if isinstance(value, float) else value
                                  for key, value in stats.items()}
                      for condition, stats in secondary.items()},
    }


def to_json(report: dict) -> str:
    from terraproof._common import jsonable

    return json.dumps(jsonable(report), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


__all__ = [
    "AgentRequest", "AgentResult", "Adapter", "Budget", "LIFT_TASKS", "LiftError", "LiftTask", "ReplayAdapter",
    "ScriptedAdapter", "SpecError", "brief", "calibrate", "exact_mcnemar", "mcnemar_mde", "planned_calls",
    "prepare_project", "run_lift", "schedule", "score_outputs", "sign_flip_p", "summarize", "to_json",
]
