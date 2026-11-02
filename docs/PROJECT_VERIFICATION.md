# Project verification

A pipeline delivers several outputs: a mask, a slope, a report. Each output is meant to be something specific.

**The project file** (`terraproof.toml`, or `terraproof.json`) states that once, next to the pipeline:
- each deliverable's outputs;
- the goal it must meet;
- the sources and parameters that pin it down.

**`terraproof verify`** checks every deliverable against its declaration in one run. Its exit code can gate CI.

Nothing is inferred from file names, task text or folder layout. A deliverable is decision-grade only when every check its goal requires ran with the declared bindings and passed.

## The file

```toml
schema = "terraproof.project/1"

[[deliverables]]
name = "usable-pixel mask"          # unique; used by --only and in report file names
outputs = ["out/mask.tif"]          # one or more outputs this declaration covers
goals = ["qa-masked"]               # goal profiles; or `checks = ["rs.cloud_mask_applied"]`
qa_path = "data/SCL_20m.tif"        # bindings: same names as run_checks / verification contracts
qa_kind = "keep-codes"
qa_keep_codes = [4, 5, 6, 7, 11]
output_form = "validity-mask"

[[deliverables]]
name = "slope"
outputs = ["out/slope_utm.tif"]
goals = ["slope-from-dem"]
dem = "data/dem.tif"
dem_vertical_unit = "metre"
slope_unit = "percent"

[[deliverables]]
name = "area report"
outputs = ["out/report.json"]
goals = ["summary-value"]

[[deliverables.summaries]]
key = "per_class.0.share"
statistic = "fraction"
unit = "fraction"
source = "data/SCL_20m.tif"
codes = [4, 5, 6, 7, 11]
mask = "data/SCL_20m.tif"
mask_codes = [6]

[[deliverables.summaries]]
key = "country.area_km2"
statistic = "area"
unit = "square_kilometre"
source = "data/countries.geojson"
feature = "NAME=New Zealand"
```

**Paths.** Relative paths resolve against the file's own folder, never the current directory.

**Goals.** The goal profiles are:

| Goal | Required checks |
| --- | --- |
| `qa-masked` | `rs.cloud_mask_applied` |
| `slope-from-dem` | `terrain.slope_consistent` |
| `summary-value` | `report.summary_value` |
| `scaled-reflectance` | `rs.reflectance_range`, `rs.scale_applied_once` |
| `vertical-units` | `raster.vertical_units` |
| `nodata-support` | `raster.nodata_support` |
| `metric-operation` | `crs.metric_operation` |
| `metric-values` | `geometry.metric_values` |

**Checks.** `checks` names check ids directly.

**Bindings.** Bindings are the parameters of `run_checks`. Index bands are given as `bands` (role to path) and `band_numbers`. An unknown name is an error, never ignored.

**TOML and JSON.** Reading TOML needs Python 3.11 or later. On 3.10, write `terraproof.json`:

```json
{"schema": "terraproof.project/1", "deliverables": [{"name": "...", "outputs": ["..."], "goals": ["..."]}]}
```

## Commands

```bash
python -m terraproof verify [FILE]          # default: terraproof.toml, then terraproof.json, here
python -m terraproof verify --plan          # run nothing; list required checks and missing bindings
python -m terraproof verify --only slope    # one deliverable (repeatable)
python -m terraproof verify --format json   # machine-readable summary
python -m terraproof verify --reports out/terraproof   # also write each full JSON evidence report
```

**`verify`.** It prints one line per deliverable, with its status and grade, and the findings of every check that did not pass:
- **Statuses:** verified, failed, review-required, incomplete, missing output, or error.
- **Exit code:** the worst deliverable's: `0` verified, `2` review required, `3` failed, incomplete or missing, and `1` for an invalid project file.

**`--plan`.** It needs no outputs. It exits `0` when every declaration has the bindings its checks require, and `3` otherwise, naming them (for example `dem` or `summaries[0].unit`).

**Agents.** Through MCP, the same runs are `verify_project` (`plan=true` for the plan). An agent can write the file when a task starts, before producing anything, check it with `plan=true`, and verify the finished outputs before it reports the task as done.

## In CI

```yaml
# .github/workflows/terraproof.yml
name: terraproof
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install terraproof
      - run: python your_pipeline.py          # produce the outputs the file declares
      - run: python -m terraproof verify --reports terraproof-reports
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: terraproof-reports
          path: terraproof-reports
```

A step fails when any deliverable fails or cannot be verified. To fail only on failures, not on warnings, treat exit `2` as success in your own script.

## Limits

- **The declaration is the requirement.** `verify` checks outputs against what the file says they are meant to be. A wrong declaration is checked faithfully.
- **Undeclared report numbers.** In a report, numbers the file does not declare are listed, never judged, and keep the report at review.
- **One deliverable's checks share one invocation.** Outputs that need different bindings (two masks from different QA layers) are separate deliverables.
