# Run records and network options

Reference for [STAC and cloud access](../SKILL.md). Terraproof's own manifest
command and `provenance.reproducible` check are being added in Phase 4; until their
format is final, keep a run record like the one below and convert it later. It is
a pattern, not a Terraproof schema.

## Minimal run record

```json
{
  "core": {
    "stac_api": "https://earth-search.aws.element84.com/v1",
    "search": {
      "collections": ["sentinel-2-l2a"],
      "bbox": [13.30, 52.45, 13.50, 52.55],
      "datetime": "2024-06-01T00:00:00Z/2024-06-30T23:59:59Z",
      "query": {"eo:cloud_cover": {"lt": 20}}
    },
    "items": [
      {
        "collection": "sentinel-2-l2a",
        "id": "S2A_32UQD_20240629_0_L2A",
        "datetime": "2024-06-29T10:26:14.251000Z",
        "processing_version": "05.10",
        "assets": {
          "red": {
            "href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/32/U/QD/2024/6/S2A_32UQD_20240629_0_L2A/B04.tif",
            "scale": 0.0001, "offset": -0.1, "nodata": 0,
            "sha256": "<hash of the cached bytes>", "size": 0
          }
        }
      }
    ],
    "load": {"crs": "EPSG:32633", "resolution": 20, "groupby": "solar_day",
             "resampling": {"scl": "nearest", "*": "bilinear"}},
    "software": {"python": "3.x", "gdal": "x.y.z", "rasterio": "x.y.z",
                 "pystac-client": "x.y.z", "odc-stac": "x.y.z"},
    "outputs": [{"path": "outputs/ndvi_2024-06.tif", "sha256": "...", "size": 0}]
  },
  "context": {"created": "2026-10-21T00:00:00Z", "operator": "...", "root": "."}
}
```

The values above came from a real search when this skill was written
(`processing_version` was read from the deprecated `s2:processing_baseline`
because the item had no `processing:version`). Rules:

- `core` is deterministic: same inputs → same bytes. Timestamps, hostnames and
  absolute paths go in `context`; store paths relative to a declared root.
- Hrefs are **unsigned**. Strip signing query strings before recording, e.g.
  `href.split("?", 1)[0]` for Planetary Computer SAS URLs, and never store tokens
  or credentials.
- Hash the bytes actually analysed (a local copy), not the remote object.

```python
import hashlib
from pathlib import Path

def file_digest(path, chunk=1 << 20):
    h = hashlib.sha256()
    p = Path(path)
    with p.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return {"sha256": h.hexdigest(), "size": p.stat().st_size}
```

Write JSON with sorted keys (`json.dumps(core, sort_keys=True, indent=2)`) so the
core serialises identically across runs.

## GDAL network options

From the GDAL virtual-file-system and configuration documentation [S1, S2]:

| Option | Effect |
|---|---|
| `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` | No directory listing; drivers see only the opened file (no side-car probing). |
| `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif` | GDAL assumes only files with these extensions exist on the server. |
| `GDAL_HTTP_MAX_RETRY`, `GDAL_HTTP_RETRY_DELAY` | Retries (count, seconds) on HTTP 429, 502, 503, 504. |
| `CPL_VSIL_CURL_CHUNK_SIZE` | Range-request chunk size (16 KB default granularity; grows for sequential reads). |
| `CPL_VSIL_CURL_CACHE_SIZE` | Global in-memory LRU cache shared by `/vsicurl/` downloads (16 MB default). |
| `VSI_CACHE=TRUE`, `VSI_CACHE_SIZE` | Per-file RAM cache (25 MB default), discarded when the handle closes. |
| `AWS_REQUEST_PAYER=requester` | Access requester-pays S3 buckets via `/vsis3/` and accept charges. |
| `AWS_NO_SIGN_REQUEST=YES` | Disable request signing for public buckets. |

Set them with `rasterio.Env(...)` in Python or `--config KEY VALUE` / environment
variables for GDAL CLI tools. Credentials belong in the environment or a GDAL
configuration file's `[credentials]` section, never in code or manifests [S1].

## Sources

- [S1 — GDAL virtual file systems](https://gdal.org/en/stable/user/virtual_file_systems.html).
- [S2 — GDAL configuration options](https://gdal.org/en/stable/user/configoptions.html).
