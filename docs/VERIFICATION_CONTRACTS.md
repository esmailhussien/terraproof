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

- `raster.vertical_units` compares every cell with the declared `convert` or
  `difference` of the sources, done in metres and converted to the output unit.
  It also fails when the output band's unit label contradicts its declared unit.
  It does not cover vertical datum differences, or depths from a constant water
  level.
- `raster.nodata_support` requires the output to be valid exactly where its
  sources are valid under `--support-rule all` or `any`. A source's fill can be
  declared with `--support-source-nodata`, for example `0` when a product stores
  fill as zero without saying so in the file. Values where the sources hold only
  fill, and nodata where they hold valid values such as real zeros, both fail.

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
