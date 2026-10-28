# Contract templates for four common workflows

These are starting points for a [verification contract](VERIFICATION_CONTRACTS.md).
Copy one next to your project's `inputs/` and `outputs/`, change the paths and
parameters to match **your own declared goal and data**, and run it with the
check arguments shown. A template does not choose your method: if you did not
declare nearest-neighbour resampling or an NDVI from named bands, do not copy
that requirement in.

Each template is tested in `tests/python/test_contract_templates.py` on generated
data with three cases: a valid output, an intentional defect and missing evidence.

| Template | Valid output | Intentional defect | Missing evidence |
|---|---|---|---|
| [vector-metric-area](contract-templates/vector-metric-area.json) | exit 0, `verified` | a dropped record: exit 2, `review-required` | no `--compare-to`: exit 3, `incomplete` |
| [raster-categorical-grid](contract-templates/raster-categorical-grid.json) | exit 0, `verified` | a half-pixel grid shift: exit 3, `failed` | no `--resampling`/`--categorical`: exit 3, `incomplete` |
| [index-ndvi](contract-templates/index-ndvi.json) | exit 0, `verified` | swapped bands: exit 3, `failed` | no `--nir`/`--red`: exit 3, `incomplete` |
| [stack-median](contract-templates/stack-median.json) | exit 0, `verified` | a mean instead of the median: exit 3, `failed` | no `--stack`: exit 3, `incomplete` |

The arguments must supply what the contract declares. Passing only `--contract`
does not run its parameters for you, and a missing binding is reported, never skipped.

## 1. Vector: CRS, geometry and record count for an area calculation

```bash
python -m terraproof check outputs/parcels_area.gpkg --operation area --compare-to inputs/parcels.gpkg --contract vector-metric-area.json --out report.json
```

Scope: the CRS is defined and suits an area operation, geometries are valid and
the output keeps the source's record count. It does **not** check the computed
area values. A changed record count is a warning, not a failure, because a
filter may be intended; the run needs review.

## 2. Raster: grid, declared categorical resampling and nodata

```bash
python -m terraproof check outputs/landcover_aligned.tif inputs/reference_grid.tif --resampling nearest --categorical --contract raster-categorical-grid.json --out report.json
```

Scope: the output declares nodata and sits on the reference grid, and the
declared resampling suits categorical codes. A declared method is not proof of
the operation that actually ran.

## 3. A calibrated index from named source bands

```bash
python -m terraproof check outputs/ndvi.tif --index-formula ndvi --nir inputs/nir.tif --red inputs/red.tif --contract index-ndvi.json --out report.json
```

Scope: every output cell is recomputed from the named bands. The other formulas
(`nbr`, `dnbr`, `ndwi`, `mndwi`, `ndmi`, `savi`, `evi`) use `--band ROLE=PATH`
and `index_bands` instead of `nir`/`red`.

## 4. A temporal reduction of ordered sources

```bash
python -m terraproof check outputs/median.tif --stack-reduction median --stack inputs/t1.tif --stack inputs/t2.tif --stack inputs/t3.tif --contract stack-median.json --out report.json
```

Scope: every output cell is recomputed from the stack in its declared order.
`weighted-sum` and `ols-slope` also need one `--stack-weight` per layer in the
contract and the arguments.

## Warnings outside the contract still count

The exit code uses the contract's grade, but other observed failures and warnings
remain material. For example, an untiled GeoTIFF triggers a COG layout warning
and exits 2 even when the contract is `verified`. Fix the warning or review it;
do not drop it from the run.

## Use it in ordinary CI

This GitHub Actions job runs one contract, uploads the evidence whether it passes
or fails, and fails the job on a missing or failed requirement. The commands are
the ones the template tests run; the workflow file itself is an example and is
not run in this repository.

```yaml
name: verify-outputs
on: [push]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install terraproof
      - name: Check the NDVI output against its source bands
        run: |
          python -m terraproof check outputs/ndvi.tif --index-formula ndvi \
            --nir inputs/nir.tif --red inputs/red.tif \
            --contract contracts/index-ndvi.json --out report.json
      - name: Bind the report to the data
        if: always()
        run: python -m terraproof evidence write report.json --root . --out evidence.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: terraproof-evidence
          path: |
            report.json
            evidence.json
```

The check step fails the job with exit 3 when a requirement is missing or failed,
and with exit 2 when a result needs review. To fail only on exit 3, wrap the
command and test its code. Uploading `report.json` keeps the failure visible.
`evidence write` refuses to bind data that changed after the report.
