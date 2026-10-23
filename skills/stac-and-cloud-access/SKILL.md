---
name: stac-and-cloud-access
description: Search STAC APIs reproducibly and read cloud-hosted rasters lazily, covering collections/bbox/intersects/datetime/query/filter parameters, item and asset provenance, signed URLs and requester-pays buckets, COG and Zarr windowed reads through HTTP range requests and GDAL /vsicurl/, loader scale/offset behaviour, caching and pinning item ids in a run manifest; use when finding, loading or recording satellite data from STAC catalogs or object storage.
license: MIT
---

# STAC search and cloud-native access

## Search with explicit, reproducible parameters

STAC API Item Search (`GET /search` required, `POST` recommended) returns an
ItemCollection (GeoJSON FeatureCollection of Items). Core parameters [S1]:

| Parameter | Meaning and pitfalls |
|---|---|
| `collections` | Collection ids; always set it so results are not cross-collection by accident. |
| `bbox` | `[min lon, min lat, max lon, max lat]` in WGS 84 (CRS84); 2D or 3D. |
| `intersects` | One GeoJSON geometry. **Only one of `bbox` or `intersects`**; both is a 400 error. |
| `datetime` | RFC 3339 instant or interval with `/`; `..` for open ends. Item times are UTC [S2]. |
| `ids` | Exact Item ids — the way to re-fetch a pinned set. |
| `limit` | Page size suggestion only; servers may return fewer and paginate via `next` links. |

Property filtering is an **extension**: the Query extension (`query`, operators
`eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `startsWith`, `endsWith`, `contains`, `in`)
[S3] or the recommended Filter extension (`filter`, `filter-lang` = `cql2-text` or
`cql2-json`) [S4]. Check conformance before relying on either; a server that does
not implement one may ignore or reject it.

```python
import pystac_client

client = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
if not client.conforms_to("QUERY"):
    raise RuntimeError("server does not advertise the Query extension")
search = client.search(
    collections=["sentinel-2-l2a"],
    bbox=[13.30, 52.45, 13.50, 52.55],
    datetime="2024-06-01T00:00:00Z/2024-06-30T23:59:59Z",
    query={"eo:cloud_cover": {"lt": 20}},
    max_items=200,                      # client-side cap across pages
)
items = list(search.items())
```

`Client.search` defaults to `POST`; `max_items` caps total items, `limit` is the
per-page hint; `filter` defaults to `cql2-json` for dict input [S5]. When run in
October 2026 this endpoint advertised Query but not Filter, so a `filter=` search
only warned. An AOI can return items from several UTM zones/tiles; plan a common
output CRS. Dataset discovery and licensing are covered by
[geospatial data discovery](../geospatial-data-discovery/SKILL.md). Shared rules:
[engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Record item and asset provenance

An Item requires `id`, `geometry`, `bbox` (when geometry is not null),
`properties.datetime` (or `null` with `start_datetime`/`end_datetime`), `links`
and `assets`; ids are unique within a Collection, so record **collection + id**
[S2]. For each input keep:

- STAC API root URL, collection id, item id, `datetime`, self link;
- asset key and **unsigned** `href`, media type and roles;
- processing version: `processing:version` (e.g. a Sentinel processing
  baseline) [S6], or the deprecated `s2:processing_baseline` still used by some
  catalogs [S7];
- encoding metadata: raster extension `scale`/`offset`/`nodata` (`raster:bands`
  in v1.x, `raster:scale`/`raster:offset` in v2.0) [S8];
- the exact search parameters and the date the search ran.

Catalogs change (reprocessing, new baselines, removed items). A search re-run
later can return different items; the pinned ids cannot silently change.
Re-fetch with `client.search(collections=[...], ids=[...])`. A manifest pattern
is in [references/run-manifest.md](references/run-manifest.md).

## Signed URLs and requester-pays storage

- **Signed URLs (SAS):** Microsoft Planetary Computer assets need signing,
  e.g. `Client.open(url, modifier=planetary_computer.sign_inplace)` or
  `planetary_computer.sign(item)`; tokens expire and signed items gain an
  `msft:expiry` property [S9]. Sign at read time; never store signed URLs or
  tokens in manifests, logs or reports ([security](../../instructions/security.md)).
- **Requester pays:** the reader pays for access and transfer. Example:
  `s3://usgs-landsat/collection02/` is a requester-pays bucket [S10]. GDAL needs
  credentials plus `AWS_REQUEST_PAYER=requester`; `AWS_NO_SIGN_REQUEST=YES`
  disables signing for public buckets [S11]. Estimate transfer before bulk reads.

## Read COG windows with HTTP range requests

`/vsicurl/` reads remote files piece-wise with HTTP range requests, chunked and
cached in memory; `/vsicurl_streaming/` does not use range requests; a plain URL
without `/vsi` uses the HTTP driver, which downloads the whole file [S11]. COGs
are tiled with overviews and an internal tile index, which is what makes partial
reads efficient [S11]. Rasterio opens `https://` hrefs through GDAL.

```python
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

aoi = (13.30, 52.45, 13.50, 52.55)            # lon/lat
href = items[0].assets["red"].href            # unsigned public COG here
with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                  CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
    with rasterio.open(href) as src:
        bounds = transform_bounds("EPSG:4326", src.crs, *aoi)
        window = from_bounds(*bounds, transform=src.transform)
        window = window.round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, src.width, src.height))
        dn = src.read(1, window=window, masked=True)   # stored values
        transform = src.window_transform(window)
```

`GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` stops directory listing and side-car
probing; `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` limits which files GDAL assumes exist
[S12]. CLI equivalents: `gdalinfo /vsicurl/https://.../B04.tif`, and
`gdal_translate -projwin_srs EPSG:4326 -projwin ...` for a subset. Retries
(`GDAL_HTTP_MAX_RETRY`, `GDAL_HTTP_RETRY_DELAY`) and cache sizes are in
[references/run-manifest.md](references/run-manifest.md#gdal-network-options).
Windows/blocks and COG creation: [raster processing](../raster-processing/SKILL.md).

## Know what your loader decodes

In the example above (Earth Search Sentinel-2 L2A, October 2026) the STAC asset
declared `scale 0.0001, offset -0.1, nodata 0`, while the GeoTIFF reported
identity scale/offset: `rasterio.read()` returns raw DN [S8]. Loaders differ:

- `odc.stac.load(...)` returned raw `uint16` DN with `nodata` 0 in the same test;
  decode afterwards, exactly once.
- `stackstac.stack(...)` defaults to `rescale=True`, applying `raster:bands`
  scale/offset, with `dtype=float64` and NaN fill [S13]; do not decode again.
- `xarray.open_zarr(...)` defaults to `mask_and_scale=True` (CF decoding) and
  lazy Dask chunks when Dask is installed [S14].

Decoding rules and sensor offsets: [satellite preprocessing](../satellite-preprocessing/SKILL.md).

## Load many items as a lazy cube

```python
import odc.stac

ds = odc.stac.load(
    items, bands=["red", "nir", "scl"],
    crs="EPSG:32633", resolution=20,            # explicit output grid
    bbox=[13.30, 52.45, 13.50, 52.55],
    groupby="solar_day",                        # merge same-pass tiles
    chunks={"x": 2048, "y": 2048},              # Dask-backed, nothing read yet
)
```

`groupby="solar_day"` places items from the same solar day in one time slice;
by default overlapping pixels are filled from the first valid item in a
deterministic time/id order; `patch_url` can sign hrefs (e.g. `planetary_computer.sign`)
[S15]. Set `resampling` per band, e.g. nearest for categorical `scl` [S15]. In
the test above, 4 tile-items became 2 dates. Record `crs`, `resolution`,
`groupby`, `resampling` and library versions with the outputs.

## Cache and pin for reproducibility

GDAL's `/vsicurl/` cache is in-process memory only [S11]; it is not a
reproducibility mechanism. For results that must be re-verified:

1. Pin collection + item ids and asset keys; store unsigned hrefs.
2. Copy the exact bytes you analysed to a local or bucket cache and record
   SHA-256 and size; verify hashes before reuse.
3. Record processing versions, encoding metadata, loader parameters, library and
   GDAL versions, and the search parameters.
4. Keep timestamps and machine paths outside the hashed part of a manifest.

## Verify with Terraproof

```bash
python -m terraproof check source-item.json
python -m terraproof check subset_red.tif --expect reflectance
```

`stac.provenance` checks Item time and a projection code, not full lineage,
licences or calibration. Raster outputs get `crs.defined`, `crs.consistent`,
`raster.nodata_declared`, `raster.grid_alignment`, `raster.cog_layout`, and
`rs.reflectance_range` with `--expect reflectance` (only after decoding).

Use `--manifest run.json --require-provenance` for `provenance.reproducible`
(re-hashes manifest inputs/outputs; warns on tool-version drift, fails on content
drift). Add `--time-range START END` for `rs.temporal_scope` on source Items.
For `rs.scale_applied_once`, compare a decoded raster with its raw source using
`--reference-input RAW.tif --encoding s2-l2a` or `landsat-c2-l2`; the sampled
output is compared with DN × scale + offset under that declared encoding.

**Not checked automatically:** whether the search returned the right items,
whether pinned items still exist upstream, licence compliance and transfer
costs. Manifest credential guards reject known secret-bearing paths/URLs, but
do not audit every application log or prevent all signed-URL leakage.

## Sources

- [S1 — STAC API Item Search](https://github.com/radiantearth/stac-api-spec/blob/main/item-search/README.md): parameters, bbox/intersects exclusivity, datetime syntax, limit and pagination.
- [S2 — STAC Item specification](https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md): required fields, id uniqueness, UTC datetime.
- [S3 — STAC API Query extension](https://github.com/stac-api-extensions/query): `query` syntax and operators.
- [S4 — STAC API Filter extension](https://github.com/stac-api-extensions/filter): `filter`, `filter-lang`, CQL2 text/JSON, queryables.
- [S5 — pystac-client `Client`](https://github.com/stac-utils/pystac-client/blob/main/pystac_client/client.py): `open(modifier=...)`, `search()` parameters and defaults, `conforms_to`.
- [S6 — STAC processing extension](https://github.com/stac-extensions/processing): `processing:version` (e.g. Sentinel processing baseline), `processing:software`, lineage links.
- [S7 — STAC Sentinel-2 extension](https://github.com/stac-extensions/sentinel-2): `s2:processing_baseline` deprecated in favour of `processing:version`.
- [S8 — STAC raster extension](https://github.com/stac-extensions/raster): scale/offset semantics; Earth Search behaviour observed by a live query and rasterio read (October 2026).
- [S9 — Planetary Computer SDK](https://github.com/microsoft/planetary-computer-sdk-for-python): `sign`, `sign_inplace`, token expiry and `msft:expiry`.
- [S10 — Registry of Open Data on AWS, USGS Landsat](https://registry.opendata.aws/usgs-landsat/): `usgs-landsat` bucket `RequesterPays: True`.
- [S11 — GDAL virtual file systems](https://gdal.org/en/stable/user/virtual_file_systems.html): `/vsicurl/` range requests, chunking/cache, `/vsis3/`, `AWS_REQUEST_PAYER`, `AWS_NO_SIGN_REQUEST`, retries, cloud-friendly TIFF layout.
- [S12 — GDAL configuration options](https://gdal.org/en/stable/user/configoptions.html): `GDAL_DISABLE_READDIR_ON_OPEN`, `CPL_VSIL_CURL_ALLOWED_EXTENSIONS`.
- [S13 — stackstac `stack()`](https://github.com/gjoseph92/stackstac/blob/main/stackstac/stack.py): `rescale=True`, `dtype`, `fill_value`, `resampling` defaults.
- [S14 — xarray `open_zarr`](https://github.com/pydata/xarray/blob/main/xarray/backends/zarr.py): `chunks` and `mask_and_scale` defaults.
- [S15 — odc-stac `load`](https://odc-stac.readthedocs.io/en/latest/_api/odc.stac.load.html): `groupby`, `chunks`, `crs`, `resolution`, `bbox`, `resampling`, `patch_url`, fuse behaviour.
