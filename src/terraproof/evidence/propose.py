"""Draft verification contracts from explicit metadata; never applied automatically.

The caller names the goal profiles, the outputs and the sources it knows (the same bindings
`check` takes). A binding the profiles need that the caller did not give is filled only when
metadata states it explicitly: a band's unit label or nodata in the file itself, or `raster:bands`
scale, offset, nodata or unit in a local STAC Item asset that the caller ties to that file.
Nothing is inferred from names, value ranges or task text. A binding no metadata states stays
undeclared, and metadata that disagrees is reported as a conflict instead of choosing.
"""
from __future__ import annotations

import contextlib
import json
import math
from pathlib import Path

import rasterio

from terraproof._common import InputError
from terraproof.checks.vertical_units import unit_name
from terraproof.evidence.contract import (FILE_PARAMETERS, LIST_FILE_PARAMETERS, PARAMETERS, SUMMARY_FIELDS,
                                          _missing_bindings,
                                          profile_contract, profiles, recheck_arguments)

# Units terrain.slope_consistent accepts, by canonical unit; it has no fathom.
_DEM_UNITS = {"metre": "metre", "foot": "foot", "us-survey-foot": "us survey foot"}
# Command-line flags whose names are not the parameter name.
FLAGS = {"qa_path": "--qa", "qa_keep_codes": "--qa-keep-code", "stack": "--stack", "stack_weights": "--stack-weight",
         "stack_times": "--stack-time",
         "vertical_sources": "--vertical-source", "vertical_source_units": "--vertical-source-unit",
         "support_sources": "--support-source", "support_source_nodata": "--support-source-nodata"}
# Item properties stating that the band offset is already in the stored values (Earth Search
# sentinel-2-l2a); beside a non-zero raster:bands offset they are a conflict, never a choice.
OFFSET_APPLIED = ("earthsearch:boa_offset_applied",)
# Verification choices and goals no metadata can state.
_CALLER_ONLY = {"processing_full_scan": "a verification choice: pass it for a full-grid audit",
                "vertical_unit": "the output's intended unit is part of the goal",
                "vertical_operation": "how the output was made is part of the goal",
                "support_rule": "how sources combine is part of the goal",
                "qa_kind": "which QA rule applies is part of the goal",
                "qa_keep_codes": "which QA codes the quality rule accepts is part of the goal"}


def flag(parameter: str) -> str:
    if parameter.startswith("source_band:"):
        return "--band " + parameter.split(":", 1)[1] + "=PATH"
    return FLAGS.get(parameter, "--" + parameter.replace("_", "-"))


def parse_stac_binding(value: str) -> tuple[str, str, str]:
    """`FILE=ITEM.json#ASSET` ties a local file to one asset of a local STAC Item."""
    path, sep, rest = value.partition("=")
    item, hash_sep, asset = rest.rpartition("#")
    if not sep or not path or not hash_sep or not item or not asset:
        raise InputError(f"a STAC binding is FILE=ITEM.json#ASSET, got {value!r}")
    return path, item, asset


def _stac_band(item_path: str, asset_key: str) -> tuple[dict, dict, dict] | None:
    """The single band an asset describes, from STAC 1.0 `raster:bands` or STAC 1.1 `bands`, with the field each
    fact came from, and the item's properties. A fill the band does not state may come from the one
    `classification:classes` entry marked `nodata`."""
    try:
        data = json.loads(Path(item_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InputError(f"cannot read STAC Item {item_path} ({type(error).__name__})") from error
    if not isinstance(data, dict) or data.get("type") != "Feature" or "stac_version" not in data:
        raise InputError(f"not a STAC Item: {item_path}")
    asset = (data.get("assets") or {}).get(asset_key)
    if not isinstance(asset, dict):
        raise InputError(f"STAC Item {item_path} has no asset {asset_key!r}")
    facts, fields = {"scale": None, "offset": None, "nodata": None, "unit": None}, {}
    for key, prefix in (("raster:bands", ""), ("bands", "raster:")):
        bands = asset.get(key)
        if isinstance(bands, list) and len(bands) == 1 and isinstance(bands[0], dict):
            band = bands[0]
            facts = {"scale": band.get(prefix + "scale"), "offset": band.get(prefix + "offset"),
                     "nodata": band.get("nodata"), "unit": band.get("unit")}
            fields = dict.fromkeys(facts, f"assets.{asset_key}.{key}[0]")
            break
    classes = asset.get("classification:classes")
    fills = [c.get("value") for c in classes if isinstance(c, dict) and c.get("nodata") is True] \
        if isinstance(classes, list) else []
    if facts["nodata"] is None and len(fills) == 1:
        facts["nodata"], fields["nodata"] = fills[0], f"assets.{asset_key}.classification:classes"
    if not fields:
        return None
    return facts, fields, data.get("properties") or {}


def _statements(path: str, stac: dict, fact: str) -> list[dict]:
    """Every explicit statement of one fact about a single-band source: its file, then its STAC asset."""
    found = []
    try:
        src = rasterio.open(path)
    except rasterio.errors.RasterioIOError:
        src = None  # not a raster: no file statements
    with src or contextlib.nullcontext():
        if src is not None and src.count == 1:
            if fact == "unit" and (src.units[0] or "").strip():
                found.append({"file": path, "field": "band 1 unit", "value": src.units[0].strip()})
            if fact == "nodata" and src.nodata is not None:
                found.append({"file": path, "field": "band 1 nodata", "value": src.nodata})
            # rasterio reports scale 1 and offset 0 when a file states none, so only other values are statements.
            if fact == "scale" and src.scales[0] != 1.0:
                found.append({"file": path, "field": "band 1 scale", "value": src.scales[0]})
            if fact == "offset" and src.offsets[0] != 0.0:
                found.append({"file": path, "field": "band 1 offset", "value": src.offsets[0]})
    key = Path(path).resolve()
    if key in stac:
        item, asset = stac[key]
        band = _stac_band(item, asset)
        if band is not None and band[0][fact] is not None:
            field = band[1][fact] + ("" if band[1][fact].endswith("classification:classes") else f".{fact}")
            found.append({"file": str(Path(item).resolve()), "field": field, "value": band[0][fact]})
            if fact == "offset" and band[0][fact] != 0:
                # An item that also says the offset is already applied leaves no offset to decode with.
                found += [{"file": str(Path(item).resolve()), "field": f"properties.{flag}", "value": True,
                           "means": 0.0} for flag in OFFSET_APPLIED if band[2].get(flag) is True]
    return found


def _agreed(statements: list[dict], normalise):
    """(value, None) when every statement agrees, (None, reason) otherwise; nothing stated gives (None, None)."""
    if not statements:
        return None, None
    values = {json.dumps(normalise(s.get("means", s["value"]))) for s in statements}
    if "null" in values:
        return None, "stated value is not usable"
    if len(values) > 1:
        return None, "conflict"
    return normalise(statements[0]["value"]), None


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _dem_unit(value):
    return _DEM_UNITS.get(unit_name(value))


def _absolute(given: dict) -> dict:
    """Local paths made absolute, so a saved contract resolves from any folder."""
    for key in FILE_PARAMETERS:
        if isinstance(given.get(key), str):
            given[key] = str(Path(given[key]).resolve())
    for key in LIST_FILE_PARAMETERS:
        if isinstance(given.get(key), list):
            given[key] = [str(Path(path).resolve()) for path in given[key]]
    if isinstance(given.get("index_bands"), dict):
        given["index_bands"] = {role: [str(Path(pair[0]).resolve()), pair[1]] for role, pair in given["index_bands"].items()}
    return given


def command_flags(arguments: dict) -> list[str]:
    """Command-line flags for run_checks-style arguments (`paths` and `profiles` excluded)."""
    argv = []
    for key, value in sorted(arguments.items()):
        if key in ("paths", "profiles") or value is None or value is False:
            continue
        if key == "bands":
            argv += [part for role, path in sorted(value.items()) for part in ("--band", f"{role}={path}")]
        elif key == "band_numbers":
            argv += [part for role, n in sorted(value.items()) for part in ("--band-number", f"{role}={n}")]
        elif value is True:
            argv.append(flag(key))
        elif key in ("time_range", "stack_window"):
            argv += [flag(key), *map(str, value)]
        elif key == "summaries":
            argv += [part for entry in value for part in ("--summary", ",".join(
                f"{name}=" + (";".join(map(str, entry[name])) if isinstance(entry[name], list) else str(entry[name]))
                for name in SUMMARY_FIELDS if entry.get(name) is not None))]
        elif isinstance(value, list):
            argv += [part for item in value for part in (flag(key), "file" if item is None else str(item))]
        else:
            argv += [flag(key), str(value)]
    return argv


def check_command(arguments: dict, contract: str = "CONTRACT.json") -> list[str]:
    """The `check` command line for run_checks-style arguments and a saved contract."""
    return ["python", "-m", "terraproof", "check", *arguments["paths"], "--contract", contract,
            *command_flags(arguments)]


ITEM_SIZE_LIMIT = 5_000_000  # bytes; a larger JSON file is not read as a candidate STAC Item


def local_stac_links(folders) -> dict:
    """Local files tied to the STAC Item assets that point at them: every Item among the `.json` files directly in
    `folders` whose asset `href` resolves to an existing local file. The href is the Item's own explicit link."""
    links = {}
    for folder in sorted({Path(f).resolve() for f in folders}):
        for item in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                if item.stat().st_size > ITEM_SIZE_LIMIT:
                    continue
                data = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or data.get("type") != "Feature" or "stac_version" not in data:
                continue
            for key, asset in sorted((data.get("assets") or {}).items()):
                href = asset.get("href") if isinstance(asset, dict) else None
                if isinstance(href, str) and href and "://" not in href:
                    target = (item.parent / href).resolve()
                    if target.is_file():
                        links.setdefault(target, (str(item), key))
    return links


def _same_number(declared, stated) -> bool:
    return declared is not None and math.isclose(declared, stated, rel_tol=1e-9, abs_tol=1e-12)


def declaration_conflicts(values: dict, stac: dict) -> list[dict]:
    """Declared bindings that explicit metadata about their own sources contradicts.

    Compared: a DEM's vertical unit, the decode scale and offset of the reference input, each vertical source's
    unit, and each support source's fill. A fact no metadata states, or that metadata states in disagreeing
    ways, is not compared. A support source with no declared fill conflicts with a fill only its STAC Item states,
    since the file's own mask would then miss it."""
    found = []

    def compare(parameter, declared, source, fact, normalise, same):
        if not isinstance(source, str):
            return
        statements = _statements(source, stac, fact)
        value, problem = _agreed(statements, normalise)
        if value is not None and not problem and not same(normalise(declared), value):
            found.append({"parameter": parameter, "declared": declared, "source": source, "statements": statements})

    equal = lambda a, b: a == b  # noqa: E731
    if values.get("dem_vertical_unit") is not None:
        compare("dem_vertical_unit", values["dem_vertical_unit"], values.get("dem"), "unit", _dem_unit, equal)
    for parameter, fact in (("decode_scale", "scale"), ("decode_offset", "offset")):
        if values.get(parameter) is not None:
            compare(parameter, values[parameter], values.get("reference_input"), fact, _number, _same_number)
    sources = values.get("vertical_sources") or []
    for source, unit in zip(sources, values.get("vertical_source_units") or []):
        compare("vertical_source_units", unit, source, "unit", unit_name, equal)
    fills = values.get("support_source_nodata") or []
    for index, source in enumerate(values.get("support_sources") or []):
        declared = fills[index] if index < len(fills) else None
        if declared is not None:
            compare("support_source_nodata", declared, source, "nodata", _number, _same_number)
            continue
        statements = _statements(source, stac, "nodata")
        if statements and not any(s["file"] == source for s in statements):  # the file's own mask lacks this fill
            value, problem = _agreed(statements, _number)
            if value is not None and not problem:
                found.append({"parameter": "support_source_nodata", "declared": None, "source": source,
                              "statements": statements})
    return found


# Sources whose decode a declaration states elsewhere (in each summary), so a stated scale needs no decode check.
_OWN_DECODE = ("summary_source", "summary_mask", "summaries", "qa_path", "qa_source")


def undeclared_decodes(values: dict, stac: dict, checks) -> list[dict]:
    """Declared sources whose metadata states a decode (scale other than 1, or offset other than 0) that no declared
    check applies: `rs.scale_applied_once` covers only its `reference_input`. Advisory: an output need not carry
    its source's decoded values, but when it does, an undeclared decode is never checked."""
    covered = values.get("reference_input") if "rs.scale_applied_once" in set(checks) else None
    sources = [v for k, v in values.items() if k in FILE_PARAMETERS and k not in _OWN_DECODE and isinstance(v, str)]
    sources += [p for k in LIST_FILE_PARAMETERS for p in values.get(k) or [] if isinstance(p, str)]
    found = []
    for source in dict.fromkeys(sources):
        if source == covered:
            continue
        stated = {}
        for fact, default in (("scale", 1.0), ("offset", 0.0)):
            value, problem = _agreed(_statements(source, stac, fact), _number)
            if value is not None and not problem and value != default:
                stated[fact] = value
        if stated:
            found.append({"source": source, **stated})
    return found


def propose_contract(paths: list[str], names: list[str], arguments: dict, stac: list[str] | None = None) -> dict:
    """A draft contract for the named goal profiles, with the evidence for every binding it filled."""
    if not names:
        raise InputError("name at least one goal profile")
    if not paths:
        raise InputError("name at least one output")
    catalogue = profiles()
    unknown = sorted(set(names) - set(catalogue))
    if unknown:
        raise InputError("unknown goal profile: " + ", ".join(unknown))
    checks = sorted(set().union(*(catalogue[name]["checks"] for name in names)))
    stac_map = {}
    for value in stac or []:
        path, item, asset = parse_stac_binding(value)
        stac_map[Path(path).resolve()] = (item, asset)
    if set(arguments) - PARAMETERS:
        raise InputError("unknown verification parameter: " + ", ".join(sorted(set(arguments) - PARAMETERS)))
    given = _absolute({key: value for key, value in arguments.items() if value not in (None, False, [], {})})
    bindings = [{"parameter": key, "value": given[key], "from": "caller"} for key in sorted(given)]
    conflicts, unusable, not_stated = [], [], []

    def stated(parameter, source, fact, normalise):
        """One source's agreed value of a fact, or None (recording a conflict, an unusable or no statement)."""
        statements = _statements(source, stac_map, fact)
        if not statements:
            not_stated.append({"parameter": parameter, "source": source})
        value, problem = _agreed(statements, normalise)
        if problem:
            (conflicts if problem == "conflict" else unusable).append(
                {"parameter": parameter, "source": source, "statements": statements})
            return None, statements, True
        return value, statements, False

    def fill(parameter, value, evidence):
        given[parameter] = value
        bindings.append({"parameter": parameter, "value": value, "from": "metadata", "evidence": evidence})

    if "scaled-reflectance" in names and "expect" not in given:
        # The profile's own goal: surface reflectance.
        given["expect"] = "reflectance"
        bindings.append({"parameter": "expect", "value": "reflectance", "from": "profile"})
    singles = []
    if "terrain.slope_consistent" in checks and given.get("dem"):
        singles.append(("dem_vertical_unit", given["dem"], "unit", _dem_unit))
    if "rs.scale_applied_once" in checks and given.get("reference_input"):
        singles += [("decode_scale", given["reference_input"], "scale", _number),
                    ("decode_offset", given["reference_input"], "offset", _number)]
    for parameter, source, fact, normalise in singles:
        if parameter not in given:
            value, statements, problem = stated(parameter, source, fact, normalise)
            if value is not None:
                fill(parameter, value, statements)
    if ("raster.vertical_units" in checks and given.get("vertical_sources")
            and "vertical_source_units" not in given):
        units, evidence = [], []
        for source in given["vertical_sources"]:
            value, statements, problem = stated("vertical_source_units", source, "unit", unit_name)
            units.append(value)
            evidence += statements
        if None not in units:
            fill("vertical_source_units", units, evidence)
    if ("raster.nodata_support" in checks and given.get("support_sources")
            and "support_source_nodata" not in given):
        # A source whose file states its fill keeps its own mask (None); a fill only STAC states is declared.
        fills, evidence, problems = [], [], False
        for source in given["support_sources"]:
            value, statements, problem = stated("support_source_nodata", source, "nodata", _number)
            problems |= problem
            in_file = any(s["file"] == source for s in statements)
            fills.append(None if in_file else value)
            evidence += statements
        if not problems and any(v is not None for v in fills):
            fill("support_source_nodata", fills, evidence)

    contract = profile_contract([str(Path(p).resolve()) for p in paths], names, given)
    undeclared = []
    for check in checks:
        for parameter in _missing_bindings(check, given):
            undeclared.append({"parameter": parameter, "check": check, "supply_with": flag(parameter),
                               **({"why": _CALLER_ONLY[parameter]} if parameter in _CALLER_ONLY else {})})
    arguments = recheck_arguments(contract["requirements"][0])
    return {"status": "proposed", "profiles": sorted(set(names)), "contract": contract,
            "bindings": sorted(bindings, key=lambda b: b["parameter"]), "undeclared": undeclared,
            "conflicts": conflicts, "unusable": unusable, "not_stated": not_stated,
            "check_arguments": arguments, "check_command": check_command(arguments),
            "note": "A proposal is not coverage. Review it, then run check with this contract and these "
                    "arguments; undeclared bindings keep the requirement incomplete."}
