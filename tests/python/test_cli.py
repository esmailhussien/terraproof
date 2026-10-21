"""CLI tests: exit codes, usage errors, inspect JSON, and deterministic output files."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from shapely.geometry import Polygon

from terraproof.cli import main


def square(x: float, y: float, size: float = 10.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def test_exit_codes_for_decision_review_and_advisory(make_vector):
    clean = make_vector("clean.gpkg", [square(500000, 5000000)])
    empty = make_vector("empty.gpkg", [square(500000, 5000000), Polygon()])
    geographic = make_vector("lonlat.gpkg", [square(30.0, 30.0, 0.01)], crs="EPSG:4326")

    assert main(["check", clean, "--operation", "area"]) == 0
    assert main(["check", empty]) == 2
    assert main(["check", geographic, "--operation", "buffer"]) == 3


def test_missing_file_exits_1_with_message(tmp_path, capsys):
    missing = str(tmp_path / "missing.gpkg")

    assert main(["check", missing]) == 1
    assert "file not found" in capsys.readouterr().err


def test_unknown_option_is_a_usage_error(make_vector):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    with pytest.raises(SystemExit) as excinfo:
        main(["check", path, "--no-such-option"])

    assert excinfo.value.code == 1


def test_inspect_prints_valid_json(make_vector, capsys):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])

    assert main(["inspect", path]) == 0

    description = json.loads(capsys.readouterr().out)
    assert description["kind"] == "vector"
    assert description["crs"]["epsg"] == 32636


def test_help_exits_0_for_both_commands():
    for argv in (["--help"], ["check", "--help"]):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code == 0


def test_module_entry_point_help_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "terraproof", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "inspect" in completed.stdout and "check" in completed.stdout


def test_repeated_check_writes_byte_identical_files(make_vector, tmp_path):
    path = make_vector("parcels.gpkg", [square(500000, 5000000), square(500100, 5000100)])
    first_out = tmp_path / "run1.json"
    second_out = tmp_path / "run2.json"

    assert main(["check", path, "--operation", "area", "--out", str(first_out)]) == 0
    assert main(["check", path, "--operation", "area", "--out", str(second_out)]) == 0

    assert first_out.read_bytes() == second_out.read_bytes()


def test_markdown_out_file_is_written_as_utf8(make_vector, tmp_path):
    path = make_vector("clean.gpkg", [square(500000, 5000000)])
    out = tmp_path / "report_ar.md"

    assert main(["check", path, "--operation", "area", "--format", "md", "--lang", "ar", "--out", str(out)]) == 0

    text = out.read_text(encoding="utf-8")
    assert "جاهز للقرار" in text
    assert "`crs.defined`" in text
