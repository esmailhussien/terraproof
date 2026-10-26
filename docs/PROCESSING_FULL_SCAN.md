# Exhaustive calibration and QA checks

Use the optional full scan for final checks of delivered calibration and cloud
masking. It reads every corresponding pixel in every band, using 256 by 256
windows to bound working memory. Runtime grows with raster size and band count.
The default remains the existing band-1, stride-8 screen.

```bash
python -m terraproof check decoded.tif --reference-input raw.tif --encoding s2-l2a --processing-full-scan
python -m terraproof check masked.tif --qa scl.tif --qa-kind s2-scl --processing-full-scan
```

Python and MCP `run_checks` accept `processing_full_scan=True`. Python takes an
inspected `reference_input`; MCP takes its path. Reports retain the option and
record scan scope, band count, compared/mismatched pixels and window size.
The option expands only `rs.scale_applied_once` and `rs.cloud_mask_applied`.
It does not make every other check exhaustive or certify an entire workflow.

## Calibration relation

Source/output dimensions, affine and declared CRS must agree, as must their band
counts. Bands correspond by index; selecting or reordering bands cannot be
inferred. Expected stored output is `source_stored * scale + offset`.
Use `s2-l2a` (0.0001, -0.1), `landsat-c2-l2` (0.0000275, -0.2), explicit
scale/offset parameters, or each source band's metadata. Selecting an encoding
overrides source metadata. An identity source metadata transform is a literal
identity relation, not evidence that the sensor needs no calibration.

Output scale/offset must be identity. Every jointly valid output sample must
match once-calibrated source within `abs(error) <= 1e-6 + 1e-4 * abs(expected)`.
A single mismatch fails; the default screen retains its 99% match threshold.
Unmasked nonfinite output or resurrected source-invalid pixels also fail.
Extra output masking is counted and allowed; its scientific appropriateness is
outside this check. An all-masked output cannot confirm calibration. Unsupported
types, integers outside the exact float64 range, overflow, missing grids or no
jointly valid samples return `not-run` rather than confirming correctness.

## Cloud/QA relation

QA must be one unscaled integer band on the same grid. Sentinel-2 SCL classes
3, 8, 9 and 10, or Landsat QA_PIXEL bits 1 through 4, must be masked/nodata or
NaN in **every output band**. Infinity does not count as masking. A single
unmasked flagged location fails. Missing QA or unsupported codes leave the
result `not-run` if no definite violation was found. An image with no flagged
locations cannot confirm that masking was performed.

This checks compliance with supplied QA, not cloud detection accuracy, dilation,
clear-pixel retention or the scientific choice of classes/bits.

## Reproducible offline scorecard

From a development checkout with the core Python dependencies:

```bash
PYTHONPATH=src python tests/checker_scorecard.py --work /new/outside-checkout/scorecard
```

Use process-local `$env:PYTHONPATH='src'` on PowerShell. The destination must not
already exist. No model or network request is made.

On 2026-10-26, the unchanged benchmark reproduced 33/33 tasks across 11 spec
files: 25 of 50 wrong controls rejected by product checks, 25 caught only by
independent oracles. Its old invocations do not enable the new option.

The **separate** new processing cohort contains five clean references and 13
single-pixel corruptions across two sensor encodings, per-band calibration
metadata and two QA formats. Independent scalar calculations confirm each
injected error. Both modes passed 5/5 clean controls; the sampled mode rejected
0/13 wrong controls and full scan rejected 13/13. Source hashes were unchanged.
These controls deliberately expose sparse-sampling gaps. They are not a random
sample, a field error-rate estimate, an agent-lift result or a revision of the
frozen benchmark. Other documented checker blind spots remain.
