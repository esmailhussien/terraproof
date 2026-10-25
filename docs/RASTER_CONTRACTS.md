# Strict raster source contracts

Two explicit checks extend the existing screens without changing their default
behaviour. They run locally, read data without modifying it and expose the same
parameters/results through Python, CLI and MCP. No model API is needed.

## Central-difference slope

```bash
python -m terraproof check outputs/result.tif --dem inputs/elevation.tif --slope-method central-difference
```

Python `run_checks` takes an inspected DEM and `slope_method="central-difference"`.
MCP `run_checks` takes `dem` as a path with the same method value. This selects
`terrain.slope_formula`. With only `--dem`, the original
`terrain.slope_consistent` heuristic keeps its previous thresholds and scope.

The contract is a single floating band of physical degrees (output scale 1,
offset 0, unit absent or degrees) on exactly the DEM's CRS, affine and dimensions.
The DEM must have one real band on a projected, finite, unrotated grid at least
3 by 3. Its stored-value scale and offset and declared vertical length unit are
used; an absent vertical unit means the horizontal CRS unit. Metres,
international feet and US survey feet are supported with their declared aliases.

For every interior cell with a finite, valid centre and four direct neighbours:

```
gx = (right - left) * DEM_scale * vertical_to_horizontal / (2 * abs(pixel_width))
gy = (below - above) * DEM_scale * vertical_to_horizontal / (2 * abs(pixel_height))
slope_degrees = degrees(atan(hypot(gx, gy)))
```

The constant offset cancels from derivatives; subtracting stored values first
prevents a large offset erasing a real gradient. Calibrated values still must
be finite for valid source support. The outer image edge and any incomplete
stencil must be masked in the output. Every supported cell, including flat zero
slopes, must be present and match within `rtol=2e-6`, `atol=1e-6` degrees. There
is no sampled-cell or 95% agreement shortcut in this explicit mode.

A changed value, extra masking, unmasked edge/hole or non-finite valid output
fails. The check reports compared, mismatched, extra-masked and unsupported-output
cell counts. Unsupported source/method/units, unknown CRS, rotated/degenerate
grids, non-finite calibration, arithmetic overflow, DEM integers outside the
exact float64 range, unreadable data or no comparable stencil return not-run.
Output band encoding or exact grid mismatches fail.

Reads use at most 512 by 512 output windows and a one-cell DEM halo. Tile seams
are not artificial image edges. This is specifically the declared four-neighbour
central-difference method and nodata-edge policy; Horn/Zevenbergen-Thorne slopes,
geographic derivatives, other edge treatments and additional QA masks are outside
this contract. It does not establish that the supplied DEM or its units are true.

## Raster source identity

```bash
python -m terraproof check outputs/delivery.tif --compare-to inputs/analysis.tif --raster-identity
```

Python/MCP use `raster_identity=True` and `compare_to` (an inspected source in
Python, a path in MCP). This emits `raster.source_identity`; without the flag,
`compare_to` retains its vector-record-count behaviour. Explicit raster-only
identity does not emit an irrelevant vector-count not-run result.

The output must match the source's CRS, full affine, dimensions, band count,
dtypes, nodata, scales, offsets and band-unit metadata. Every band is read in
bounded 512 by 512 windows. Every validity-mask cell is compared, and all jointly
valid decoded stored samples must match exactly, without integer-to-float
conversion or a numeric tolerance. This catches late-window and later-band
changes, including one-unit differences above the float64 exact integer range.

Validity uses GDAL's nonzero-mask convention; zero-valued samples remain valid
when their mask says so. Matching valid NaNs compare equal, signed zeros compare
equal and matching infinities retain their sign. Two NaN nodata declarations
match. Payload under cells invalid in both rasters is intentionally not compared.
This is decoded valid-data identity, not byte-for-byte file identity or a claim
that the source values are scientifically usable. Real integer and floating
bands are supported; complex bands, missing operands/CRS, unusable grids,
non-finite calibration or zero jointly valid samples return not-run. Known
grid/band-metadata, value or validity differences fail.

Source files are declared by the caller. No source role or provenance is guessed
from a filename, and this check cannot establish that the chosen source is the
correct one for the task. Python callers supply inspected records consistently
with their paths; checks reopen actual rasters for the comparison.

## COG and grading limits

The COG plan requires both source identity and the existing layout/nodata/CRS
screens. Identity verifies full-resolution decoded data, masks and the stated
metadata. Layout still screens tiling, expected overview presence and JPEG
compression. Neither verifies full TIFF/IFD ordering, HTTP range access,
overview pixel values, every codec setting or every metadata tag. Full COG
conformance remains a separate validation step; it is not implied by source
identity or by the heuristic layout pass.

Source operands appear in CLI/MCP evidence inputs and must be covered by a
provenance manifest when supplied. The API harness's stronger bundled plans bind
these exact operands/options and current data snapshots. Missing/not-run/stale
requirements are unverified; current failures/warnings require review. Passing
all declared checks remains separate from independent complete task acceptance.

The new regressions reject an extra missing slope cell and an altered COG pixel
that the original screens could pass. The original benchmark recipes and
invocations still use those original checks: no historical result, frozen
experiment or published blind-spot count is rewritten. Offline tests establish
check behaviour, not model repair success or agent lift. No new paid run is
included in this release batch.

## Primary references

- [Rasterio nodata masks](https://rasterio.readthedocs.io/en/stable/topics/masks.html):
  per-band valid masks and sidecar-mask precedence. The checks use the effective
  masks returned by the reader, including external `.msk` data.
- [GDAL COG driver](https://gdal.org/en/stable/drivers/raster/cog.html):
  COG layout and generation are separate from decoded data identity; the driver
  documentation identifies dedicated conformance validation.

Implementation is original Terraproof code under the repository's MIT license;
no upstream implementation was copied. Attribution is recorded in
[`sources/SOURCES.md`](../sources/SOURCES.md).
