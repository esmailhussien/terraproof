# NDVI source/output contract

```bash
python -m terraproof check ndvi.tif --index-formula ndvi --nir nir.tif --red red.tif --format json
```

Python: `run_checks([inspect_dataset(output)], index_formula="ndvi", nir=inspect_dataset(nir), red=inspect_dataset(red))`.
MCP: `run_checks(paths=[output], index_formula="ndvi", nir=nir, red=red)`.

The caller explicitly declares the NIR/red roles. Each of the three single-band
rasters must have a CRS and identical dimensions and supported north-up affine
grids. The check uses physical values `stored * scale + offset` from each file's
own metadata (including encoded output). Metadata defaults 1/0 mean the stored
values are already physical; calibration and sensor-band identity are trusted,
not independently recovered or inferred from names. Unsupported grids, complex
bands, missing operands or unknown formula return **not-run**.

Every cell is read in bounded 512-by-512 windows, not sampled. On finite, jointly
valid source support with `abs(NIR+red) > 1e-12`, expected NDVI is
`(NIR-red)/(NIR+red)`. A compared value agrees within `1e-6 + 1e-5 * abs(expected)`.
Any disagreement or unmasked output without finite supported sources **fails**.
Unmasked NaN/Inf output also fails. Extra output masking **warns**, because it may
be intentional QA filtering whose policy these operands do not establish. With
no comparable valid output cell the check is **not-run**, never a vacuous pass.
This is one declared formula; it does not validate EVI, NDWI, temporal aggregation,
sensor provenance, scientific fitness, or an external QA policy.

CLI and MCP include red/NIR paths and hashes in the evidence inputs, record the
formula and paths in parameters, and require the source files in any supplied
provenance manifest. This verifies the recorded files, not the truth of their
calibration metadata. The read-only check does not modify files.

Existing benchmark specs, recipes, oracles and frozen sets remain unchanged.
Their baseline remains 33/33, zero false passes, 25 wrong controls rejected by
checks and 25 detected only by the oracle. The new contract has separate numeric,
mask, window, legitimate-extra-mask, provenance and CLI/MCP parity tests; it does
not retroactively close an old invocation's missing-input blind spot.
