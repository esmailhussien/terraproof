# Verification contracts and local evidence bundles

A contract declares what a single check invocation must establish. It binds
required check IDs to output paths and explicit source/parameter values. It does
not infer the user's task, run processing code or decide which scientific method
is appropriate. The contract belongs to the caller; retain its digest separately
and reuse it unchanged after a repair.

Tested starting points for four common workflows, and a CI example, are in
[Contract templates](CONTRACT_TEMPLATES.md).

## Declare the requirements

For example, save `contract.json` in a project containing `inputs/` and `outputs/`:

```json
{
  "schema": "terraproof.verification-contract/1",
  "requirements": [{
    "paths": ["outputs/ndvi.tif"],
    "checks": ["rs.index_formula"],
    "parameters": {
      "index_formula": "ndvi",
      "nir": "inputs/nir.tif",
      "red": "inputs/red.tif"
    }
  }]
}
```

```bash
python -m terraproof check outputs/ndvi.tif --index-formula ndvi --nir inputs/nir.tif --red inputs/red.tif --contract contract.json --out report.json
```

The actual arguments must supply the evidence and match the contract. Supplying
only `--contract` does not execute its parameters automatically: a range/metadata
screen cannot substitute for the missing source relation. Diagnostics identify
missing checks, missing bindings and parameter mismatches.

Python `build_report(..., contract=...)` and MCP `run_checks(..., contract=...)`
accept an inline object or a local JSON filename. File-relative paths resolve
against the contract's directory; inline paths resolve against the current working
directory. File contracts also retain the digest of the exact JSON bytes parsed,
so the bundle protects the original policy document as well as its canonical form.
JSON is limited to 64 KiB; duplicate keys, unknown IDs/parameters,
nonfinite JSON numbers and conflicting contexts are rejected. Each output must
be among the inspected primary paths. A pass on another file or an unscoped result
cannot satisfy a requirement. Multiple groups may share a consistent invocation
context. Different source contexts require separate contracts/reports.

Use ordinary run-check parameter names. The `bands`/`band_numbers` MCP aliases
normalize to `index_bands: {"role": ["path", 1]}`. Stack order and weights are
significant. Source-aware checks require explicit operand bindings; calibration
and QA contracts also declare `processing_full_scan` as true or false. Choosing
false explicitly retains the sampled scope; contract success is not an upgrade
to exhaustive coverage. Check evidence records tolerances and scope limitations.

## Declare a goal profile

A goal profile is shorthand for the checks a declared goal requires
(`routing/profiles.json`): `vertical-units`, `nodata-support`, `qa-masked`,
`scaled-reflectance`, `metric-operation` and `slope-from-dem`. Use `profiles`
in a requirement instead of, or as well as, `checks`. From the CLI,
`--profile NAME` builds the contract from the arguments you gave (MCP:
`profiles`):

```bash
python -m terraproof check outputs/change.tif --profile vertical-units   --vertical-operation difference   --vertical-source inputs/dem_2023.tif --vertical-source-unit metre   --vertical-source inputs/dem_2015.tif --vertical-source-unit foot   --vertical-unit metre
```

A profile never guesses its bindings. Without `--vertical-unit`, for example,
the requirement is `incomplete` and the diagnostics name what to declare.

### Propose a contract from metadata

`propose` drafts the contract for you (MCP: `propose_contract`). It takes the same
flags as `check`, for whatever you already know, and fills the bindings the profiles
still need only where metadata states them explicitly:

- a single-band source's unit label or nodata in the file itself;
- `raster:bands` scale, offset, nodata or unit of a local STAC Item asset that you tie
  to the file with `--stac FILE=ITEM.json#ASSET`. Files are never matched to assets by
  name.

```bash
python -m terraproof propose outputs/slope.tif --profile slope-from-dem --dem inputs/dem.tif   --stac inputs/dem.tif=inputs/item.json#dem --contract-out contract.json
```

Every filled binding carries its evidence (file, field, value). The rest is reported, never chosen:

- `undeclared`: bindings no metadata can state, such as the operation, the output's
  unit or the QA rule, each with the flag that supplies it;
- `not_stated`: bindings the metadata could have stated but did not;
- `conflicts`: a file and its STAC asset that disagree, or a STAC offset beside an item
  property saying the offset is already applied (`earthsearch:boa_offset_applied`, as in
  Earth Search Sentinel-2 L2A items);
- `unusable`: a stated value that is not a known unit or a finite number.

A bound value you passed is never replaced. A proposal is not coverage: review it,
then run its `check_command` (MCP: `run_checks` with `check_arguments` and the
contract). Its undeclared bindings keep the requirement `incomplete`.

- `raster.vertical_units` compares every cell with the declared `convert`,
  `difference` or `depth-below-level` (with `--vertical-level`, in the output
  unit) of the sources, done in metres and converted to the output unit. It also
  fails when the output band's unit label contradicts its declared unit. It does
  not cover vertical datum differences.
- `raster.nodata_support` requires the output to be valid exactly where its
  sources are valid under `--support-rule all` or `any`. A source's fill can be
  declared with `--support-source-nodata`, for example `0` when a product stores
  fill as zero without saying so in the file. Values where the sources hold only
  fill, and nodata where they hold valid values such as real zeros, both fail.

Other declarations that close a gap rather than guess one:

- `--qa-kind keep-codes --qa-keep-code N ...` with `--processing-full-scan`
  states which QA codes your quality rule accepts; every other code must be
  nodata in the output.
- `--decode-scale` and `--decode-offset` give a calibration the file lacks (for
  example one declared only in a STAC item), and `--unit-conversion
  kelvin-to-celsius` a unit change after decoding.
- `--dem` on a geographic DEM works when the DEM's vertical unit is known, from the
  file label or `--dem-vertical-unit`; the spacing is converted to metres on the
  ellipsoid for each row.
- `--metric-quantity area|length` with `--metric-property` and `--metric-unit`, or
  `--metric-quantity buffer` with `--buffer-distance-m` and `--buffer-source`,
  verifies delivered vector measurements geodesically in any CRS (profile
  `metric-values`). `crs.metric_operation` (profile `metric-operation`) is for data
  that is still to be measured.
- `--qa-source` names the band a keep-codes QA rule masks, so masking a code the
  rule keeps fails instead of only warning.
- Vertical operations also include `minus-level` (for example a constant geoid
  separation) and `depth-to-elevation`; `fathom` is a supported unit.
- `--categorical-source PATH` (`raster.categorical_codes`) requires every valid
  output cell to hold a class code that occurs in the class raster it came from, on
  any grid. Codes blended by bilinear, cubic or average resampling fail. A shifted
  or dropped class keeps every code valid and is not detected.
- `--sar-filter boxcar --sar-filter-size N --sar-filter-source PATH` with
  `--sar-expect` (`sar.filter_domain`) recomputes the speckle filter from the
  unfiltered source in linear power. A filter averaged in dB fails, and the report
  counts the cells that match the dB average. Only cells whose whole window is
  valid are compared.
- `--stack-window START END` with one `--stack-time START/END` per `--stack` layer
  (`rs.stack_window`) checks the output's time label. Layers must lie inside the
  window without overlapping. With `--stack-reduction weighted-sum`, they must also
  cover it without gaps, and each `--stack-weight` must equal its layer's hours.

Phase 9 declarations for real deliverables:

- `--output-form validity-mask` (with `--output-valid-value`, default 1) declares
  outputs as 1/0 masks. `rs.cloud_mask_applied` (always exhaustive for a declared
  mask) and `raster.nodata_support` then read every other value as invalid. A
  1/0 raster without the binding is still read as data.
- `--slope-unit percent` states a slope output in percent for `--dem` and
  `--slope-method`; it is converted to degrees before comparing. The default stays
  degrees. On a geographic DEM, `terrain.slope_consistent` accepts any common
  spacing model (WGS84, mean sphere, 111 320 m per degree) within 1%.
- `--summary-key KEY --summary-statistic STAT --summary-source PATH`
  (`report.summary_value`, profile `summary-value`) checks one number in a JSON
  report. It recomputes `mean`, `count`, `sum`, `min` or `max` over a raster's
  valid cells (with an optional `--summary-mask`), or `count`, `area` or `length` of
  vector features (with `--summary-unit` and an optional `--summary-feature
  FIELD=VALUE`), geodesically. A plain JSON object is now inspected as a report
  (its top-level keys only).
- Without a contract, a report whose arguments ran every check of a goal profile
  carries `next_step`: the profiles, and the `propose` / `propose_contract` call
  that would make them required. It is advisory and never changes the grade.

Phase 10 declarations:

- A declared validity mask fails `rs.cloud_mask_applied` where it marks a cell
  valid that the QA layer records as no observation: the QA file's nodata under
  any `--qa-kind`, and also SCL class 0 (`s2-scl`) or the QA_PIXEL fill bit
  (`landsat-qa-pixel`). Data outputs keep missing QA unverifiable.
- `terrain.slope_consistent` now compares a slope on another grid than its DEM
  (another CRS, resolution or origin) after resampling, instead of `not-run`. The
  reference is the DEM's slope made each common way: slope then warp, or warp then
  slope, with nearest, bilinear, cubic or average resampling, central differences
  or Horn, warped in the delivered unit. The delivered slope passes only when one
  way reproduces it cell by cell (95% of cells within 1%), and fails when one way
  reproduces a named mistake instead, including degrees and percent confused.
  Otherwise it fails only for a gross mistake: the declared reading's area-mean
  gradient lies outside the envelope correct resampling stays inside (set in Phase
  10 S2), and a mistake's lies within it with the DEM's pattern. The rest warns.
  The evidence says `comparison: resampled`.
- On a projected grid whose point scale factor strays more than 1% from 1 (Web
  Mercator away from the equator, polar stereographic), slope is measured in
  ground metres cell by cell, and projected units taken as ground lengths is a
  named mistake. UTM and other grids within 1% keep nominal spacing. Heights in
  metres converted to feet over metre spacing is a named mistake on every grid.
- A declared validity mask passes `raster.nodata_declared`: its form already
  says that every value but the valid one is invalid.
- `--summary key=K,statistic=S,source=PATH[,unit=U][,feature=FIELD=VALUE][,mask=PATH]`
  (repeatable; MCP `summaries`, a list of objects) declares every number a report
  holds, one `report.summary_value` result each. Keys may index lists
  (`bands.0.mean`). On a raster source, `codes=C;C` keeps cells holding those
  class codes, `mask_codes=C;C` names the mask values to include (default 1, so
  a QA layer can be the mask), and `scale=`/`offset=` decode a band whose file
  states no calibration (a different one in the file is a conflict, `not-run`). `--summary-statistic fraction` is the share of the source's
  valid cells the mask marks 1, or of all cells that are valid without a mask,
  with `unit` `fraction` or `percent`. A number matches within the statistic's
  tolerance or within rounding to the decimals it is written with. Numbers no
  summary declares are listed in `coverage.unchecked_numbers`, never judged, and
  a warning names them, so such a report needs review rather than being
  decision-grade.

`geometry.winding` warns rather than fails (Phase 8). RFC 7946 binds GeoJSON
writers to the right-hand rule but tells parsers not to reject other rings, and
ring order changes no coordinate, area or topology. The warning still keeps a
contract from decision-grade.

## Read both outcomes

Every report (schema `terraproof.evidence/0.2`) has a `coverage` block:
`assessed` is true only with a contract, and `not_checked` lists catalogue checks
that apply to the checked inputs but did not run, with the parameters that enable
them. Without a contract, passing checks grade `checks-passed` (exit 0), never
`decision-grade`. With a contract the report adds:

- `verification`: canonical contract, SHA-256, per-output/check coverage and scan
  scope, missing/mismatched bindings, status and effective grade.
- `diagnostics`: observed messages/evidence and bounded next actions. Recheck
  suggestions use MCP-compatible arguments and identify the unchanged contract
  digest. Supply the original contract again; suggestions do not replace it.

With a contract, the report's `grade` is `verification.grade`, and the CLI/MCP
exit code follows it: missing/not-run requirements or failures produce advisory/3,
warnings produce review/2, and complete passing evidence produces decision/0.
Other observed failures/warnings remain material. (In `terraproof.evidence/0.1`
reports, `grade` described only the checks that ran and graded them
decision-grade when all passed; evidence bundles of either version still verify.) JSON and
English/Arabic Markdown display the contract outcome separately. A missing
requirement is not silently omitted and an automatic patch is never applied.

This does not verify that a caller chose all scientifically necessary requirements,
the correct band roles, a suitable CRS or trustworthy source data. It verifies
the declared contract against the observations in this invocation.

## Bind and verify the report

The existing provenance manifest remains available. An additional unsigned bundle
binds a JSON report, its contract and its recorded input/output hashes:

```bash
python -m terraproof evidence write report.json --root . --out evidence.json
python -m terraproof evidence verify evidence.json
python -m terraproof evidence verify evidence.json --expected-report-sha256 DIGEST_RETAINED_SEPARATELY
```

Use `--root` for the report's original working directory if recorded data paths
are relative. Bundles retain absolute local paths and are not portable archives.
Python exposes `build_bundle(report, root=...)` and `verify_bundle(bundle,
expected_report_sha256=...)` in `terraproof.evidence.bundle`.

Writing refuses data changed since the report and refuses overwriting recorded
data or the source report. Verification recomputes report/contract consistency,
file hashes and known companion membership. It detects changed, missing or newly
created masks and common Shapefile companions. Known companions include `.msk`,
`.aux.xml`, `.ovr`, GeoPackage WAL/SHM and common Shapefile component suffixes.
VRT external dependencies are unsupported and refused.
Contract reports capture companion hashes as well. A legacy report without that
snapshot cannot be bundled when companions exist; rerun it with a contract.
Other external execution or data dependencies are not claimed to be captured. Hashing reads file bytes;
it is not zero-I/O verification or a filesystem lock.

A self-contained hash is not a signature. A party able to replace the whole
bundle can recompute it; an externally retained trusted report digest provides
an independent comparison anchor. Bundle verification proves content binding,
not source authenticity, that processing actually ran, professional accreditation
or scientific correctness. A failed/incomplete report can have an intact bundle:
inspect its verification outcome as well as bundle integrity.
