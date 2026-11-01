"""Phase 8 P1: contract proposals bind only what the caller gives or metadata states explicitly."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from terraproof._common import InputError
from terraproof.cli import main
from terraproof.evidence.contract import load_contract, path_key
from terraproof.evidence.propose import parse_stac_binding, propose_contract

UTM = "EPSG:32636"
SHAPE = (16, 16)


def _label(path, unit):
    with rasterio.open(path, "r+") as dataset:
        dataset.units = (unit,)
    return path


def _item(tmp_path, name="item.json", **band):
    path = tmp_path / name
    path.write_text(json.dumps({"type": "Feature", "stac_version": "1.0.0", "id": "x", "properties": {},
                                "assets": {"data": {"href": "https://example.invalid/data.tif",
                                                    "raster:bands": [band]}}}), encoding="utf-8")
    return str(path)


def _binding(proposal, parameter):
    found = [b for b in proposal["bindings"] if b["parameter"] == parameter]
    return found[0] if found else None


def _params(proposal):
    return proposal["contract"]["requirements"][0]["parameters"]


@pytest.fixture
def surface(make_raster):
    return make_raster("surface.tif", np.random.default_rng(1).uniform(100, 200, SHAPE).astype("float32"))


def test_file_unit_label_fills_the_dem_unit_with_its_evidence(make_raster, surface):
    _label(surface, "m")
    proposal = propose_contract([surface], ["slope-from-dem"], {"dem": surface})
    binding = _binding(proposal, "dem_vertical_unit")
    assert proposal["status"] == "proposed"
    assert binding["value"] == "metre" and binding["from"] == "metadata"
    assert binding["evidence"] == [{"file": str(Path(surface).resolve()), "field": "band 1 unit", "value": "m"}]
    assert _params(proposal)["dem_vertical_unit"] == "metre"


def test_no_label_leaves_the_unit_unstated_whatever_the_file_is_called(make_raster):
    dem = make_raster("dem_in_feet.tif", np.ones(SHAPE, dtype="float32"))
    proposal = propose_contract([dem], ["slope-from-dem"], {"dem": dem})
    assert _binding(proposal, "dem_vertical_unit") is None
    assert "dem_vertical_unit" not in _params(proposal)
    assert proposal["not_stated"] == [{"parameter": "dem_vertical_unit", "source": str(Path(dem).resolve())}]


def test_stac_unit_fills_what_the_file_lacks(tmp_path, surface):
    item = _item(tmp_path, unit="ft")
    proposal = propose_contract([surface], ["slope-from-dem"], {"dem": surface}, [f"{surface}={item}#data"])
    binding = _binding(proposal, "dem_vertical_unit")
    assert binding["value"] == "foot"
    assert binding["evidence"][0]["field"] == "assets.data.raster:bands[0].unit"


def test_file_and_stac_disagreeing_is_a_conflict_not_a_choice(tmp_path, surface):
    _label(surface, "m")
    item = _item(tmp_path, unit="ft")
    proposal = propose_contract([surface], ["slope-from-dem"], {"dem": surface}, [f"{surface}={item}#data"])
    assert _binding(proposal, "dem_vertical_unit") is None
    assert [c["parameter"] for c in proposal["conflicts"]] == ["dem_vertical_unit"]
    assert {s["value"] for s in proposal["conflicts"][0]["statements"]} == {"m", "ft"}


def test_an_unknown_unit_label_is_unusable_not_guessed(surface):
    _label(surface, "degrees")
    proposal = propose_contract([surface], ["slope-from-dem"], {"dem": surface})
    assert _binding(proposal, "dem_vertical_unit") is None
    assert [u["parameter"] for u in proposal["unusable"]] == ["dem_vertical_unit"]


def test_a_caller_binding_is_never_replaced_by_metadata(surface):
    _label(surface, "m")
    proposal = propose_contract([surface], ["slope-from-dem"], {"dem": surface, "dem_vertical_unit": "foot"})
    assert _binding(proposal, "dem_vertical_unit") == {"parameter": "dem_vertical_unit", "value": "foot",
                                                       "from": "caller"}


def test_vertical_source_units_need_every_source_stated(make_raster, surface):
    other = make_raster("other.tif", np.ones(SHAPE, dtype="float32"))
    _label(surface, "metre")
    given = {"vertical_sources": [surface, other], "vertical_operation": "difference"}
    partial = propose_contract([surface], ["vertical-units"], given)
    assert _binding(partial, "vertical_source_units") is None
    _label(other, "US survey foot")
    full = propose_contract([surface], ["vertical-units"], given)
    assert _binding(full, "vertical_source_units")["value"] == ["metre", "us-survey-foot"]
    undeclared = {u["parameter"]: u for u in full["undeclared"]}
    assert set(undeclared) == {"vertical_unit"} and undeclared["vertical_unit"]["supply_with"] == "--vertical-unit"
    assert "goal" in undeclared["vertical_unit"]["why"]


def test_goal_bindings_are_listed_with_their_flags(surface):
    proposal = propose_contract([surface], ["vertical-units", "qa-masked"], {})
    flags = {u["parameter"]: u["supply_with"] for u in proposal["undeclared"]}
    assert flags["vertical_sources"] == "--vertical-source" and flags["qa_path"] == "--qa"
    assert flags["vertical_operation"] == "--vertical-operation" and flags["qa_kind"] == "--qa-kind"
    assert flags["processing_full_scan"] == "--processing-full-scan"


def test_stac_scale_and_offset_fill_the_decode(tmp_path, make_raster):
    raw = make_raster("raw.tif", np.full(SHAPE, 2500, dtype="uint16"), nodata=0)
    item = _item(tmp_path, scale=0.0001, offset=-0.1, nodata=0)
    proposal = propose_contract([raw], ["scaled-reflectance"], {"reference_input": raw}, [f"{raw}={item}#data"])
    assert _binding(proposal, "decode_scale")["value"] == 0.0001
    assert _binding(proposal, "decode_offset")["value"] == -0.1
    assert _binding(proposal, "expect") == {"parameter": "expect", "value": "reflectance", "from": "profile"}
    assert [u["parameter"] for u in proposal["undeclared"]] == ["processing_full_scan"]


def test_file_scale_against_stac_scale_is_a_conflict(tmp_path, make_raster):
    raw = make_raster("raw.tif", np.full(SHAPE, 2500, dtype="uint16"), scale=0.0002, offset=0.0)
    item = _item(tmp_path, scale=0.0001)
    proposal = propose_contract([raw], ["scaled-reflectance"], {"reference_input": raw}, [f"{raw}={item}#data"])
    assert _binding(proposal, "decode_scale") is None
    assert [c["parameter"] for c in proposal["conflicts"]] == ["decode_scale"]


def test_support_fill_only_stac_states_is_declared(tmp_path, make_raster):
    in_file = make_raster("in_file.tif", np.ones(SHAPE, dtype="float32"), nodata=-9999.0)
    stac_only = make_raster("stac_only.tif", np.ones(SHAPE, dtype="float32"), nodata=None)
    item = _item(tmp_path, nodata=-32768)
    given = {"support_sources": [in_file, stac_only], "support_rule": "all"}
    proposal = propose_contract([in_file], ["nodata-support"], given, [f"{stac_only}={item}#data"])
    assert _binding(proposal, "support_source_nodata")["value"] == [None, -32768.0]
    without = propose_contract([in_file], ["nodata-support"], given)
    assert _binding(without, "support_source_nodata") is None


def test_proposals_are_deterministic_and_relocatable(tmp_path, surface):
    _label(surface, "m")
    first = propose_contract([surface], ["slope-from-dem"], {"dem": surface})
    assert json.dumps(first, sort_keys=True) == json.dumps(propose_contract([surface], ["slope-from-dem"],
                                                                           {"dem": surface}), sort_keys=True)
    saved = tmp_path / "elsewhere" / "contract.json"
    saved.parent.mkdir()
    saved.write_text(json.dumps(first["contract"]), encoding="utf-8")
    assert load_contract(str(saved))["requirements"][0]["parameters"]["dem"] == path_key(surface, Path.cwd())


def test_bad_input_is_refused(surface):
    with pytest.raises(InputError, match="unknown goal profile"):
        propose_contract([surface], ["slope"], {})
    with pytest.raises(InputError, match="unknown verification parameter"):
        propose_contract([surface], ["slope-from-dem"], {"dem_unit": "m"})
    with pytest.raises(InputError, match="FILE=ITEM.json#ASSET"):
        parse_stac_binding("dem.tif=item.json")


def test_cli_proposal_runs_to_a_verified_contract(make_raster, tmp_path, capsys):
    feet = np.random.default_rng(3).uniform(300, 600, SHAPE).astype("float32")
    source = _label(make_raster("source_ft.tif", feet), "ft")
    output = make_raster("output_m.tif", (feet * 0.3048).astype("float32"))
    contract = tmp_path / "contract.json"
    assert main(["propose", output, "--profile", "vertical-units", "--vertical-source", source,
                 "--vertical-operation", "convert", "--vertical-unit", "metre", "--contract-out", str(contract)]) == 0
    proposal = json.loads(capsys.readouterr().out)
    assert _binding(proposal, "vertical_source_units")["value"] == ["foot"] and proposal["undeclared"] == []
    command = proposal["check_command"]
    assert command[:4] == ["python", "-m", "terraproof", "check"] and str(contract.resolve()) in command
    assert main(command[3:] + ["--out", str(tmp_path / "report.json")]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["grade"] == "decision-grade" and report["verification"]["status"] == "verified"


def test_cli_requires_a_profile(surface):
    with pytest.raises(SystemExit) as stopped:
        main(["propose", surface])
    assert stopped.value.code == 1
