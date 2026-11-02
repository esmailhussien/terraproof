"""Project verification: declare every deliverable of a pipeline once, in a file, and check them all in one run.

A project file (`terraproof.toml` or `terraproof.json`) lists deliverables. Each names its `outputs`, the goal
profiles (`goals`) or check ids (`checks`) they must meet, and its bindings under the names `run_checks` and
verification contracts use. Relative paths resolve against the file's folder. `verify` runs each deliverable
through `check` with its declaration as the contract, so each is graded on declared coverage. `plan` runs
nothing: it reports what each declaration still lacks, so the file can be written before any output exists.
Before the file exists, `plan` returns the guide to writing it: every goal with its checks and required
bindings, every binding's meaning (from the `check` command's own help), and a template.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from terraproof._common import InputError
from terraproof.evidence.contract import (FILE_PARAMETERS, LIST_FILE_PARAMETERS, PARAMETERS, SCHEMA as CONTRACT_SCHEMA,
                                          _missing_bindings, load_contract, profiles)
from terraproof.evidence.grade import ADVISORY, EXIT_CODES

SCHEMA = "terraproof.project/1"
FILENAMES = ("terraproof.toml", "terraproof.json")
RESERVED = ("name", "outputs", "goals", "checks")
BINDINGS = PARAMETERS | {"bands", "band_numbers"}
LABELS = {"verified": "PASS", "failed": "FAIL", "review-required": "REVIEW", "incomplete": "INCOMPLETE",
          "missing-output": "MISSING", "error": "ERROR"}
MESSAGE_LENGTH = 240


def find(path=None) -> Path:
    """The project file given, or the first of FILENAMES in the current folder."""
    if path:
        return Path(path)
    for name in FILENAMES:
        if Path(name).is_file():
            return Path(name)
    raise InputError("no project file: give its path or create " + " or ".join(FILENAMES)
                     + " (the plan describes the format before the file exists)")


def _read(path: Path) -> dict:
    raw = path.read_bytes()
    if path.suffix == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError:
            raise InputError("reading TOML needs Python 3.11 or later; use terraproof.json") from None
        return tomllib.loads(raw.decode("utf-8"))
    return json.loads(raw)


def _absolute(value, base: Path):
    return str((base / value).resolve()) if isinstance(value, str) and value else value


def _resolve(bindings: dict, base: Path) -> dict:
    """Bindings with every file path made absolute against the project folder."""
    out = dict(bindings)
    if isinstance(out.get("index_bands"), dict):
        pairs = out.pop("index_bands")
        out["bands"] = {role: pair[0] for role, pair in pairs.items() if isinstance(pair, list) and pair}
        out["band_numbers"] = {role: pair[1] for role, pair in pairs.items()
                               if isinstance(pair, list) and len(pair) == 2 and pair[1] is not None}
    for key in FILE_PARAMETERS & set(out):
        out[key] = _absolute(out[key], base)
    for key in LIST_FILE_PARAMETERS:
        if isinstance(out.get(key), list):
            out[key] = [_absolute(p, base) for p in out[key]]
    if isinstance(out.get("bands"), dict):
        out["bands"] = {role: _absolute(p, base) for role, p in out["bands"].items()}
    if isinstance(out.get("summaries"), list):
        out["summaries"] = [{k: (_absolute(v, base) if k in ("source", "mask") else v) for k, v in e.items()}
                            if isinstance(e, dict) else e for e in out["summaries"]]
    return out


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _arguments(name: str, outputs: list[str], bindings: dict):
    """Parsed `check` arguments for a declaration, so its values are typed exactly as the CLI types them."""
    from terraproof.cli import build_parser
    from terraproof.evidence.propose import command_flags

    argv = ["check", *outputs, *command_flags(bindings)]
    try:
        return build_parser().parse_args(argv)
    except SystemExit:
        raise InputError(f"{name}: a binding has an invalid value (see the usage above)") from None


def load_project(path=None) -> tuple[Path, list[dict]]:
    """The project file and its deliverables, each with its parsed arguments and verification contract."""
    from terraproof.cli import _binding_parameters

    path = find(path).resolve()
    try:
        document = _read(path)
    except (OSError, ValueError, UnicodeDecodeError) as error:
        raise InputError(f"cannot read project file {path} ({error})") from error
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or set(document) - {"schema", "deliverables"}:
        raise InputError(f'a project file holds schema = "{SCHEMA}" and a list of deliverables')
    entries = document.get("deliverables")
    if not isinstance(entries, list) or not entries:
        raise InputError("a project file lists at least one deliverable")
    base, known_goals = path.parent, profiles()
    deliverables, names = [], set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InputError(f"deliverables[{index}] is not a table")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise InputError(f"deliverables[{index}] needs a name no other deliverable has")
        names.add(name)
        if not _strings(entry.get("outputs")) or not entry["outputs"]:
            raise InputError(f"{name}: list its outputs (paths)")
        goals, checks = entry.get("goals", []), entry.get("checks", [])
        if not isinstance(goals, list) or not isinstance(checks, list) or not (goals or checks):
            raise InputError(f"{name}: declare goals (goal profiles) or checks (check ids)")
        unknown = sorted(set(map(str, goals)) - set(known_goals))
        if unknown:
            raise InputError(f"{name}: unknown goal {', '.join(unknown)}; goals are {', '.join(sorted(known_goals))}")
        bindings = {k: v for k, v in entry.items() if k not in RESERVED}
        unknown = sorted(set(bindings) - BINDINGS)
        if unknown:
            raise InputError(f"{name}: unknown binding {', '.join(unknown)}")
        outputs = [_absolute(p, base) for p in entry["outputs"]]
        args = _arguments(name, outputs, _resolve(bindings, base))
        # The contract binds what the CLI parsed, as `check --profile` does, so declared and actual values agree.
        bound = {k: v for k, v in _binding_parameters(args).items() if v is not None and k in PARAMETERS}
        requirement = {"paths": outputs, "parameters": bound}
        if goals:
            requirement["profiles"] = sorted(set(goals))
        if checks:
            requirement["checks"] = sorted(set(checks))
        try:
            contract = load_contract({"schema": CONTRACT_SCHEMA, "requirements": [requirement]})
        except InputError as error:
            raise InputError(f"{name}: {error}") from None
        group = contract["requirements"][0]
        args.contract = contract
        deliverables.append({"name": name, "outputs": outputs, "goals": sorted(set(goals)), "checks": group["checks"],
                             "missing_bindings": sorted({b for c in group["checks"]
                                                         for b in _missing_bindings(c, group["parameters"])}),
                             "args": args, "contract": contract})
    return path, deliverables


def _select(deliverables: list[dict], only) -> list[dict]:
    if not only:
        return deliverables
    unknown = sorted(set(only) - {d["name"] for d in deliverables})
    if unknown:
        raise InputError("no deliverable named " + ", ".join(unknown))
    return [d for d in deliverables if d["name"] in only]


def _relative(path: str, base: Path) -> str:
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:  # another drive
        return path


def _paths(deliverable: dict) -> list[str]:
    """Every absolute path a deliverable names, longest first, so messages can show them relative."""
    found = list(deliverable["outputs"])

    def walk(value):
        if isinstance(value, str) and os.path.isabs(value):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(vars(deliverable["args"]))
    return sorted(set(found), key=len, reverse=True)


def _short(message: str, base: Path, paths=()) -> str:
    for path in paths:
        relative = _relative(path, base)
        message = message.replace(path, relative).replace(os.path.normcase(path), relative)
    message = message.replace(str(base) + os.sep, "")
    return message if len(message) <= MESSAGE_LENGTH else message[:MESSAGE_LENGTH - 1] + "…"


TEMPLATE = f'''schema = "{SCHEMA}"

[[deliverables]]
name = "parcel-areas"
outputs = ["outputs/parcels.gpkg"]
goals = ["metric-values"]
metric_quantity = "area"
metric_property = "area_ha"
metric_unit = "hectare"

[[deliverables]]
name = "report"
outputs = ["outputs/report.json"]
goals = ["summary-value"]
summaries = [{{key = "parcel_count", statistic = "count", source = "outputs/parcels.gpkg"}}]
'''


def _value(action) -> str:
    if action.nargs == 0:
        return "true"
    kind = {float: "number", int: "integer"}.get(action.type, "string")
    return f"list of {kind}s" if type(action).__name__ == "_AppendAction" else kind


def guide() -> dict:
    """How to write a project file: each goal's checks and required bindings, and every binding's meaning."""
    from terraproof.cli import build_parser
    from terraproof.evidence.contract import SUMMARY_FIELDS
    from terraproof.evidence.propose import flag

    parser = build_parser()
    check = next(a for a in parser._subparsers._group_actions if a.choices).choices["check"]
    options = {s: a for a in check._actions for s in a.option_strings}
    special = {"bands": "--band", "band_numbers": "--band-number", "summaries": "--summary"}
    flags = {name: special.get(name, flag(name)) for name in BINDINGS if special.get(name, flag(name)) in options}
    names = {f: name for name, f in flags.items()}

    def text(help_text: str) -> str:  # the check command's help, with its flags named as project-file bindings
        return re.sub(r"--[a-z0-9-]+", lambda m: names.get(m.group(0), m.group(0)), help_text or "")

    bindings = {}
    for name, f in sorted(flags.items()):
        action = options[f]
        entry = {"value": _value(action), "meaning": text(action.help)}
        if action.choices:
            entry["choices"] = list(action.choices)
        bindings[name] = entry
    bindings["bands"]["value"] = "table of role = path"
    bindings["band_numbers"]["value"] = "table of role = band number"
    bindings["summaries"]["value"] = "list of tables with " + ", ".join(SUMMARY_FIELDS)
    bindings["index_bands"] = {"value": "table of role = [path, band number]",
                               "meaning": "bands and band_numbers in one table"}
    goals = {name: {"description": entry.get("description", ""), "checks": entry["checks"],
                    "required_bindings": sorted({b for c in entry["checks"] for b in _missing_bindings(c, {})})}
             for name, entry in sorted(profiles().items())}
    return {"project": None, "mode": "guide", "deliverables": [], "exit_code": EXIT_CODES[ADVISORY],
            "files": list(FILENAMES), "schema": SCHEMA,
            "deliverable_keys": {"name": "unique name", "outputs": "list of output paths, relative to the file",
                                 "goals": "goal names (below)", "checks": "check ids, instead of or with goals"},
            "goals": goals, "bindings": bindings, "template": TEMPLATE,
            "json": "terraproof.json holds the same keys as one JSON object (needed on Python 3.10)",
            "next": "write the file, then plan again: it lists each declaration's still-missing bindings"}


def plan(path=None, only=None) -> dict:
    """What each declaration requires and still lacks; no check runs and outputs need not exist yet."""
    try:
        if not find(path).is_file():
            return guide()
    except InputError:
        return guide()
    project, deliverables = load_project(path)
    base = project.parent
    rows = [{"name": d["name"], "outputs": [_relative(p, base) for p in d["outputs"]],
             "outputs_present": [Path(p).exists() for p in d["outputs"]], "goals": d["goals"], "checks": d["checks"],
             "missing_bindings": d["missing_bindings"], "ready": not d["missing_bindings"]}
            for d in _select(deliverables, only)]
    return {"project": str(project), "mode": "plan", "deliverables": rows,
            "exit_code": 0 if all(r["ready"] for r in rows) else EXIT_CODES[ADVISORY]}


def verify(path=None, only=None, reports_dir=None) -> dict:
    """Check every deliverable against its declaration; the exit code is the worst deliverable's."""
    from terraproof.cli import check_report
    from terraproof.evidence import to_json
    from terraproof.evidence.report import report_exit_code

    project, deliverables = load_project(path)
    base = project.parent
    rows = []
    for d in _select(deliverables, only):
        row = {"name": d["name"], "outputs": [_relative(p, base) for p in d["outputs"]], "goals": d["goals"],
               "checks": d["checks"], "missing_bindings": d["missing_bindings"], "findings": []}
        absent = [p for p in d["outputs"] if not Path(p).exists()]
        if absent:
            row.update(status="missing-output", grade=ADVISORY, exit_code=EXIT_CODES[ADVISORY],
                       findings=[{"check": None, "status": "missing", "message": "output not found: " + _relative(p, base)}
                                 for p in absent])
            rows.append(row)
            continue
        try:
            report = check_report(d["args"])
        except Exception as error:  # one unreadable deliverable is a finding, not the end of the run
            row.update(status="error", grade=ADVISORY, exit_code=EXIT_CODES[ADVISORY],
                       findings=[{"check": None, "status": "error", "message": _short(str(error), base, _paths(d))}])
            rows.append(row)
            continue
        row.update(status=report["verification"]["status"], grade=report["grade"], exit_code=report_exit_code(report),
                   findings=[{"check": c["id"], "status": c["status"], "message": _short(c["message"], base, _paths(d))}
                             for c in report["checks"] if c["status"] != "pass"])
        if reports_dir:
            target = Path(reports_dir)
            target.mkdir(parents=True, exist_ok=True)
            out = target / ("".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in d["name"]) + ".json")
            out.write_text(to_json(report), encoding="utf-8", newline="\n")
            row["report"] = str(out)
        rows.append(row)
    return {"project": str(project), "mode": "verify", "deliverables": rows,
            "exit_code": max(r["exit_code"] for r in rows)}


def render(summary: dict) -> str:
    """A short plain-text table for terminals and CI logs."""
    if summary["mode"] == "guide":
        lines = [f"terraproof verify --plan: no project file yet; write {' or '.join(summary['files'])}",
                 "goals (required bindings):"]
        lines += [f"  {name:<19} {', '.join(g['required_bindings'])}" for name, g in summary["goals"].items()]
        lines += ["every binding, with its meaning: --format json", "template:", summary["template"].rstrip()]
        return "\n".join(lines) + "\n"
    rows = summary["deliverables"]
    lines = [f"terraproof {summary['mode']}: {summary['project']} ({len(rows)} deliverable{'s' * (len(rows) != 1)})"]
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        if summary["mode"] == "plan":
            label = "READY" if r["ready"] else "INCOMPLETE"
            present = sum(r["outputs_present"])
            lines.append(f"  {label:<10}  {r['name']:<{width}}  {', '.join(r['checks'])}"
                         f"  ({present}/{len(r['outputs'])} outputs present)")
        else:
            lines.append(f"  {LABELS.get(r['status'], r['status'].upper()):<10}  {r['grade']:<15}  "
                         f"{r['name']:<{width}}  {', '.join(r['outputs'])}")
            for f in r["findings"]:
                lines.append(f"              {(f['check'] or '') + ' ' if f['check'] else ''}{f['status']}: {f['message']}")
        if r["missing_bindings"]:
            lines.append(f"              missing bindings: {', '.join(r['missing_bindings'])}")
    if summary["mode"] == "plan":
        ready = sum(r["ready"] for r in rows)
        lines.append(f"{ready} of {len(rows)} declarations complete")
    else:
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        lines.append(", ".join(f"{n} {status}" for status, n in sorted(counts.items())) + f"; exit {summary['exit_code']}")
    return "\n".join(lines) + "\n"
