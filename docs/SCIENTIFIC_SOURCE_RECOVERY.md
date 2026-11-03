# Scientific source selection and recovery

Status: experimental local extension of the [scientific workflow core](SCIENTIFIC_WORKFLOWS.md), not a published release. One supported catalog route: public Microsoft Planetary Computer `landsat-c2-l2`, native USGS Landsat 8/9 Collection 2 L2SP Surface Temperature.

The purpose is to recover a suitable **source for an approved type of study**, not automatically change a measurement or certify a catalog thumbnail. Source search, explicit selection/acquisition and native scientific approval are separate steps. No model or new dependency is required.

## Workflow

Create an unapproved source request, preserving the intended quantity, AOI, date interval, QA flags, usable threshold and full-AOI default:

```powershell
python -m terraproof workflow source-init source-request.json --aoi study_area.kmz --start 2023-07-01 --end 2023-07-31 --reject-qa-bits 0 1 2 3 4 5 7 --min-valid-fraction 0.6 --max-scene-cloud 100
python -m terraproof workflow discover source-request.json --out alternatives
```

`source-init` only writes a draft. `discover` reads public catalog metadata and writes `report.html`, `report.json` and frozen page snapshots. It downloads no pixels, approves nothing and processes no raster. Review the HTML alternatives and rejection reasons; scene cloud percentage does not predict usable AOI coverage.

Choose an **eligible** item and the actual report digest, not the placeholders below:

```powershell
python -m terraproof workflow acquire alternatives/report.json --item SELECTED_ITEM_ID --expect-digest REVIEWED_REPORT_DIGEST --out source-bundle
python -m terraproof workflow plan source-bundle/workflow.json
```

Acquisition downloads exactly that item's original MTL TXT, ST_B10, QA_PIXEL and ST_QA. It rechecks native product identity, MTL associations, sensor/date and existing admission rules. It writes an **unapproved** `/2` workflow and native-data plan. Catalog geometry can disagree with actual source coverage; an unresolved native plan stays unresolved. No alternative is silently substituted.

Review the new plan and its actual `spec_digest` before approving/running:

```powershell
python -m terraproof workflow approve source-bundle/workflow.json --out approval.json --reviewer "Study reviewer" --expect-digest NATIVE_PLAN_SPEC_DIGEST
python -m terraproof workflow run approval.json --out result
```

The source report digest binds the catalog selection; the native plan digest and input records bind scientific execution. They are distinct unsigned consistency boundaries, not authenticated approval. The same APIs are available as `from terraproof.workflows import discover, acquire`; existing `plan/approve/execute/verify/repair` remain the analytical core.

## Request and ranking

```json
{
  "schema": "terraproof.source-request/1",
  "id": "Acquisition-time surface temperature",
  "intent": {
    "quantity": "land-surface-temperature",
    "unit": "degree_Celsius",
    "aoi": "study_area.kmz",
    "acquired_between": ["2023-07-01", "2023-07-31"],
    "reject_qa_bits": [0, 1, 2, 3, 4, 5, 7],
    "min_valid_fraction": 0.6,
    "scene_coverage": "full-aoi"
  },
  "search": {"max_scene_cloud": 100, "max_download_bytes": 536870912}
}
```

Intent validation is shared with local native admission. `scene_coverage` defaults to `full-aoi`; explicitly `allow-partial` or CLI `--allow-partial` permits a partial proposal but does not weaken usable QA coverage. Paths resolve against the request file. The scene-cloud limit is explicit; the download cap defaults to 512 MiB and can be lowered.

Eligible proposals require Landsat 8/9 L2SP, an acquisition date within the inclusive UTC interval, valid cloud metadata below the declared maximum, a valid overlapping catalog polygon, the requested full footprint unless partial is explicit, and four supported unsigned native asset URLs. Bounding-box intersection alone is insufficient. Antimeridian footprints remain unsupported.

Ordering is deterministic: eligible candidates first, lowest reported scene cloud, latest acquisition, then item ID. Catalog footprint fractions are calculated in the longitude/latitude plane for metadata screening, not geodesic area or native usable coverage. All eligibility and ranking reasons are retained; ranking is not scientific approval or a guarantee that the first scene is good.

## Bounded access and lineage

- Fixed public catalog/storage endpoints; no account credentials, subscription keys, arbitrary URL adapter or provider plugin framework.
- At most five pages of up to 100 items, each at most 8 MiB. Incomplete/failed pagination cannot be selected. Conflicting duplicate IDs are not silently resolved. A large request must be narrowed explicitly.
- Original metadata is retained except signed/credential-bearing **asset** URLs are redacted and rejected. Download access tokens remain transient, are not stored/printed, and are omitted from errors. Redirects are refused.
- Complete native downloads are streamed under the reviewed aggregate cap, with sizes and SHA-256. Early EOF, budget overrun and access errors retain partial/failure evidence. Existing output directories are refused; there is no automatic resume or fallback.
- Changed request/AOI/recognized sidecars, altered catalog pages or an unreviewed report digest prevent acquisition. Native input/sidecar identity is subsequently bound by the existing approval. This is not a filesystem lock or protection against someone permitted to rewrite all trusted evidence.
- `source-package.json` records the chosen item, candidate metadata, source report/digest/page hashes, request/input identities, unsigned URLs, downloaded hashes and the new draft path. No source metadata or scientific parameters are rewritten to gain admission.

## Scientific limits

Different candidate dates inside the requested interval are **different observations**. Selecting one is not correcting the original observation, calculating a period mean, composing a mosaic or improving absolute physical accuracy. A study requiring a specific day must declare that day; a study requiring temporal composition needs a separate method.

If no eligible single scene exists, or the downloaded scene has insufficient usable observations, retain unresolved/incomplete. New source selection remains explicit. Do not widen dates, relax QA, allow partial delivery, invent missing values or mix dates as repair. Native numeric correctness still does not validate atmosphere, emissivity, QA truth or study interpretation. Independent scientific review remains a release gate.

Catalog/access and scientific references are recorded in [sources/SOURCES.md](../sources/SOURCES.md#scientific-workflow-core-native-landsat-surface-temperature). Live development evidence is recorded separately from frozen agent experiments.
