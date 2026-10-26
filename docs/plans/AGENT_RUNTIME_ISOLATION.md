# Production runtime separation for agent evaluations

Status: offline admission hardening. No new inference run is authorized or implied.

The harder Antigravity study exposed an important confound: the treatment Python
could import the same `terraproof.evals` modules used by the private grader.
Four runs read those modules. Future opt-in runs now separate three roles:

| Role | Contents |
| --- | --- |
| Private harness/grader | Full source checkout, task recipes, oracles and host driver |
| Treatment compute/MCP Python | Dedicated dependency venv plus production modules, skills, routing and attribution assets only |
| Baseline compute Python | Separate dependency-only venv; no Terraproof package |

## Prepare and admit without a model

Create two new venvs outside the checkout, on neutral paths, with the same pinned
Python and geospatial dependency versions. Install the compute dependencies
(`numpy`, `rasterio`, `pyogrio`, `pyproj`, `shapely`) into both, and MCP dependencies
into the treatment environment. Freeze actual environment versions for a real
study. Do not use system-site-packages or an editable project install.

Then run from the private checkout:

```powershell
python tests/agent_runtime.py --target-python D:/study-envs/with/Scripts/python.exe
python tests/agent_lift.py --agent-host antigravity --antigravity-model <confirmed-id> `
  --task terrain-slope-map --runs 1 `
  --agent-python-with D:/study-envs/with/Scripts/python.exe `
  --agent-python-without D:/study-envs/without/Scripts/python.exe --preflight-only
```

The runtime preparation command copies a fixed production-module/asset allowlist
into the clean venv's site-packages. It excludes evaluator Python, task specs,
recipes and fixture/reference assets. It refuses an existing Terraproof install
and does not install packages, fetch code, read credentials or invoke a model.
It records an `agent-runtime.json` hash manifest beside the venv.

Before a real host is started, the driver verifies separate venvs, matching
compute metadata, baseline package absence, evaluator import/path absence and
exact production/runtime asset hashes against both the manifest and the current
checkout. Missing or failed admission returns `model_called: false`.
Plan-only commands remain available without configured runtimes.

The actual treatment tools and MCP process use the runtime interpreter. Installer
option `--mcp-python` writes its absolute path and `-I -m terraproof.mcp`, so
inherited PYTHONPATH and user-site fallback cannot silently select the grading
checkout. The agent environment also drops Python path/home/startup overrides.
The baseline interpreter remains dependency-only. Ordinary user installation and
the normal released wheel retain their existing defaults and evaluator CLI.

Runtimes are tied to their production hashes. A product/asset change requires a
fresh runtime environment. Do not rewrite an admitted runtime or its manifest to
make a later version appear to be the original experiment treatment.

## Limits that remain

This is **package/import and MCP runtime separation, not a security sandbox**.
Native Antigravity/Claude hosts can still access other filesystem locations or
the network if their host permissions permit it. A separate Python path alone
cannot prove that private grading sources elsewhere on the computer are
unreadable. A rigorous study still needs a supported host/container boundary
that exposes only the active task and approved production runtime, or an explicit
limited threat model with all forbidden reads rejected. No ACL, ownership or
integrity-label change is part of this implementation.

The Antigravity stream must now provide nonempty matching workspace evidence
before a SUCCESS can count as completed. Its real init shape was not preserved
by the earlier observer, so a future no-private-data fixture must confirm the
field mapping before relying on that host for a full study. An older stream
without this evidence will fail closed; do not invent a cwd from the requested
one. Native CLI probing, sign-in and invocation approval are otherwise unchanged.

Runtime admission happens before the run. It is not a lock preventing a host or
another process from changing files later. Snapshot/recheck and containment
remain necessary. Global skills are inspected for Terraproof content even under
renamed folders; this is a conservative contamination guard, not proof that
arbitrary global instructions cannot influence results.

## Statistical and historical integrity

The [Phase 5 plan](Terraproof_Phase5_PLAN.md) retains the frozen 7/18 versus 16/18
protocol result. Its primary task-cluster sign-flip p-value is 0.125. Secondary
run-level McNemar p=0.011719 does not replace it. Product-only introspection's
post-hoc reinterpretation is separately labelled (14/18 versus 16/18, primary
p=0.75, secondary p=0.625). Raw artifact acceptance is not restored as independent
performance for evaluator-exposed runs.

No frozen raw report, recording, pilot source, oracle or task fixture is edited.
The preparation helper and its tests are original Terraproof code under MIT.
