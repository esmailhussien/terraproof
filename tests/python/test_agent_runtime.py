"""Admission to production-only runtimes; no models, network or package installs."""
import json
import os
from pathlib import Path
import sys
import venv

import pytest

from test_api_agent import driver
import agent_runtime
from terraproof.install import main as install
from terraproof.evals import lift


def python_in(root):
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


@pytest.fixture(scope="module")
def runtimes(tmp_path_factory):
    root = tmp_path_factory.mktemp("compute-envs")
    with_env, without_env = root / "a", root / "b"
    for env in (with_env, without_env):
        venv.EnvBuilder(with_pip=False).create(env)
    with_python, without_python = python_in(with_env), python_in(without_env)
    result = agent_runtime.prepare(with_python)
    assert result["prepared"] and result["model_calls"] == 0
    return with_python, without_python


def test_prepared_runtime_has_product_and_no_evaluators_or_reference_assets(runtimes):
    with_python, without_python = runtimes
    info = agent_runtime.inspect_python(with_python)
    baseline = agent_runtime.inspect_python(without_python)
    assert info["runtime_local"] and not info["evaluators_visible"]
    assert baseline["package"] is None and not baseline["evaluators_visible"]
    package = Path(info["package"])
    assert agent_runtime.file_hashes(package) == agent_runtime.expected_files()
    assert not (package/"evals").exists() and not (package/"data/evals").exists()
    assert (package/"mcp/server.py").is_file() and (package/"data/routing/registry.json").is_file()
    assert (package/"data/LICENSE").read_bytes() == (agent_runtime.ROOT/"LICENSE").read_bytes()
    with pytest.raises(ValueError, match="clean separate"):
        agent_runtime.prepare(with_python)


def test_pair_refuses_missing_dependencies_even_when_evaluators_are_absent(runtimes):
    result = agent_runtime.validate_pair(*runtimes)
    assert result["runtime_only_product"] and result["evaluator_imports_absent"]
    assert result["separate_runtime_pythons"] and result["without_product"]
    assert not result["matching_compute_dependencies"]  # these test venvs intentionally have no dependencies
    assert not all(agent_runtime.validate_pair(None, None).values())


def test_preparation_refuses_inherited_system_packages(tmp_path):
    environment = tmp_path/"inherited-env"
    venv.EnvBuilder(with_pip=False, system_site_packages=True).create(environment)
    with pytest.raises(ValueError, match="clean separate"):
        agent_runtime.prepare(python_in(environment))


def test_pair_accepts_matching_compute_metadata_and_refuses_an_added_oracle(runtimes, monkeypatch):
    original = agent_runtime.inspect_python
    def metadata(python):
        info = original(python)
        info["dependencies"] = dict.fromkeys(agent_runtime.DEPENDENCIES, "test-version")
        return info
    monkeypatch.setattr(agent_runtime, "inspect_python", metadata)
    assert all(agent_runtime.validate_pair(*runtimes).values())
    info = original(runtimes[0])
    package = Path(info["package"])
    oracle = package/"evals.py"
    try:
        oracle.write_text("# unexpected evaluator", encoding="utf-8")
        checks = agent_runtime.validate_pair(*runtimes)
        assert not checks["runtime_only_product"] and not checks["evaluator_imports_absent"]
    finally:
        oracle.unlink(missing_ok=True)


def test_runtime_env_selects_each_python_and_drops_checkout_fallbacks(runtimes, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(agent_runtime.ROOT/"src"))
    monkeypatch.setenv("PYTHONHOME", "unexpected")
    for condition, python in ((lift.WITH, runtimes[0]), (lift.WITHOUT, runtimes[1])):
        env = driver.host_env(condition, str(runtimes[1]), str(runtimes[0]))
        assert env["PATH"].split(os.pathsep)[0] == str(python.parent)
        assert "PYTHONPATH" not in env and "PYTHONHOME" not in env
        assert env["PYTHONNOUSERSITE"] == "1"


def test_explicit_installer_mcp_command_uses_isolated_runtime_python(tmp_path, runtimes):
    assert install(["--agent", "antigravity", "--skills", "gdal", "--target", str(tmp_path),
                    "--with-mcp", "--mcp-python", str(runtimes[0])]) == 0
    entry = json.loads((tmp_path/".agents/mcp_config.json").read_text())["mcpServers"]["terraproof"]
    assert entry == {"command": str(runtimes[0]), "args": ["-I", "-m", "terraproof.mcp"]}
    config = driver.codex_mcp_value(lift.WITH, str(runtimes[0]))
    assert json.dumps(str(runtimes[0])) in config and '["-I", "-m", "terraproof.mcp"]' in config


@pytest.mark.parametrize("extra", [["--mcp-python", "relative/python"],
                                    ["--with-mcp", "--mcp-python", "relative/python"]])
def test_installer_refuses_invalid_runtime_selection(tmp_path, extra):
    assert install(["--agent", "antigravity", "--skills", "gdal", "--target", str(tmp_path), *extra]) == 1
    assert not list(tmp_path.iterdir())


def test_driver_refuses_host_start_without_verified_runtime_pair(monkeypatch, capsys):
    monkeypatch.setattr(driver, "probe_antigravity", lambda *a: ("agy.exe", "ok", "test"))
    monkeypatch.setattr(driver, "run_lift", lambda *a, **k: pytest.fail("host run started before runtime admission"))
    assert driver.main(["--agent-host", "antigravity", "--antigravity-model", "m", "--runs", "1",
                        "--task", "terrain-slope-map", "--approve-model-calls", "2"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "runtime isolation failed" and result["model_called"] is False


def test_lift_registration_uses_runtime_without_exposing_harness_python(tmp_path, runtimes):
    task = lift.lift_task("terrain-slope-map")
    reference = tmp_path/"reference"
    lift._generate(task, reference)
    spec = lift._specs()[task.task_id]
    project = tmp_path/"project"
    installed = lift.prepare_project(task, spec, reference, project, condition=lift.WITH,
                                     agent="antigravity", mcp_python=str(runtimes[0]))
    assert installed["install_exit"] == 0
    config = (project/".agents/mcp_config.json").read_text()
    assert json.dumps(str(runtimes[0])) in config
    assert json.dumps(sys.executable) not in config
