---
name: crs-and-units
description: Choose and verify coordinate reference systems, coordinate order, datum transformations, and measurement units for vector or raster analysis; use before distance, length, area, buffering, reprojection, or work across projection boundaries.
---

# CRS and units

## Choose a measurement CRS

Start from the dataset CRS, full AOI, required accuracy, and intended measurement.
A projected CRS is not automatically a good measurement CRS.

- For compact local distance/buffer work, consider an appropriate UTM zone or an
  authoritative local projected CRS whose area of use contains the AOI.
- UTM is conformal, with 60 generally 6-degree longitude zones [S1]. It preserves
  local angles, not exact distances or areas everywhere. Inspect distortion over
  the whole AOI; a centroid-based zone estimate is only a candidate.
- For regional area totals, prefer a suitable equal-area projection (for example
  Albers or Lambert azimuthal equal-area). Conformal projections prioritize local
  shape/angles instead; neither property guarantees the other [S2].
- For large, multi-zone, or polar AOIs, consider a regional/polar projection or
  ellipsoidal geodesic calculation. Do not force every AOI into one UTM zone.
- Do not choose Web Mercator merely because it displays the basemap. Projection
  scale distortion must fit the measurement error budget.

Use [GeoPandas](../geopandas/SKILL.md) for vector API details and
[GDAL](../gdal/SKILL.md) for raster/vector reprojection commands.
General implementation rules live in [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), and [security](../../instructions/security.md).

## Look up EPSG definitions and units

Use `projinfo EPSG:4326` to inspect the authoritative axes, units, datum and area
of use [S3]. Use the PROJ CRS Explorer linked in [S3] or query the local EPSG
catalog through pyproj; prefer an authority ID or WKT over a lossy PROJ string.
Do not assign a guessed EPSG code based only on coordinate magnitude.

This example estimates a UTM candidate for a compact, non-crossing AOI. Review
its area of use and distortion before accepting it:

```python
import geopandas as gpd
from pyproj import CRS

gdf = gpd.read_file("local_aoi.gpkg", engine="pyogrio")
if gdf.crs is None:
    raise ValueError("Obtain the source CRS from the data provider")
try:
    candidate = gdf.estimate_utm_crs()
except RuntimeError as exc:
    # GeoPandas raises when no UTM candidate exists, e.g. for polar or multi-zone AOIs.
    # Choose a regional or polar projection whose area of use contains the AOI instead.
    raise ValueError("No UTM candidate: select an appropriate regional or polar CRS") from exc
crs = CRS(candidate)
print(crs.to_authority(), crs.area_of_use)
print([(a.name, a.unit_name, a.unit_conversion_factor) for a in crs.axis_info])
```

`set_crs()` labels existing coordinates; `to_crs()` changes coordinates. Assign
metadata only when the actual source definition is known. Geographic horizontal
coordinates are angular. Projected horizontal units can be metres, feet, or other
units; inspect each relevant axis instead of assuming that projected means metres.

## Resolve axis order explicitly

EPSG:4326 defines latitude then longitude [S3]. GIS coordinate arrays commonly
use longitude then latitude. RFC 7946 GeoJSON uses WGS 84 longitude, latitude in
decimal degrees, equivalent to OGC:CRS84 [S4]; the axis convention is part of the
interface contract, not evidence that coordinates should be swapped blindly.

For explicit pyproj arrays in GIS order, use `always_xy=True`:

```python
from pyproj import Transformer

def project_lonlat(lon, lat, target_crs):
    transform = Transformer.from_crs(
        "EPSG:4326", target_crs, always_xy=True, allow_ballpark=False
    )
    return transform.transform(lon, lat, errcheck=True)
```

Use a known control point inside the AOI to test position, axis order, and units.
A forward/inverse round trip alone cannot reveal consistently swapped axes or a
wrong but reversible CRS assignment.

## Inspect datum transformations and grids

Reprojection can include a datum transformation, not just a projection change.
Choose the operation for the AOI and required accuracy, inspect unavailable grids,
and reject an unjustified ballpark fallback. With known `source_crs`, `target_crs`,
and geographic AOI bounds supplied by the caller [S5]:

```python
from pyproj import network
from pyproj.aoi import AreaOfInterest
from pyproj.transformer import TransformerGroup

def transformation_candidates(source_crs, target_crs, geographic_bounds):
    network.set_network_enabled(False)
    group = TransformerGroup(
        source_crs, target_crs, always_xy=True,
        area_of_interest=AreaOfInterest(*geographic_bounds),
        allow_ballpark=False,
    )
    for operation in group.unavailable_operations:
        print(operation.name, [(g.short_name, g.available) for g in operation.grids])
    if not group.best_available or not group.transformers:
        raise RuntimeError("Required transformation unavailable; resolve grids first")
    for transform in group.transformers:
        print(transform.description, transform.accuracy, transform.area_of_use)
    return group.transformers  # Select against the task's accuracy requirement.
```

Unknown accuracy is not zero error. Record the selected pipeline, PROJ/database
versions and grid names. If a required grid is unavailable, obtain it through an
approved installation process and rerun the selection. A horizontal transform does
not by itself establish vertical datum or coordinate-epoch correctness.

## Compute area, length, and buffers with honest units

For planar GeoPandas/Shapely operations, length/distance/buffer parameters use CRS
units and area uses squared CRS units. Transform all operands into the chosen CRS
before analysis. In a foot-based CRS, convert requested metric tolerances before
buffering; for areas, square the linear conversion factor. Do not label an area
as square metres just because the CRS is projected.

For a compact AOI with an already reviewed metre-based `measurement_crs`:

```python
import geopandas as gpd
from pyproj import CRS

def measure_parcels(input_path, measurement_crs):
    gdf = gpd.read_file(input_path, engine="pyogrio")
    target = CRS(measurement_crs)
    if gdf.crs is None or not target.is_projected:
        raise ValueError("Defined source and reviewed projected target required")
    if any(a.unit_name != "metre" for a in target.axis_info[:2]):
        raise ValueError("This example requires metre-based horizontal axes")
    projected = gdf.to_crs(target)
    projected["area_m2"] = projected.geometry.area
    projected["perimeter_m"] = projected.geometry.length
    return projected
```

For survey-grade work, a projected grid distance is not the elevation-dependent
ground distance: the difference depends on the projection scale factor and surface
height, so state which distance a result reports.

Geodesic area/distance is an alternative when appropriate: use pyproj `Geod` on
geographic coordinates with explicit ellipsoid and ring orientation [S6]. A
geodesic calculation does not make a planar buffer in degrees correct.

## Handle antimeridian and polar data

Do not infer crossing extent by a naive longitude minimum/maximum. A GeoJSON
antimeridian bbox may have west longitude greater than east longitude. RFC 7946
recommends cutting crossing geometries so no part crosses the antimeridian [S4].

Before transforming, establish the intended side of the globe and edge model;
split/unwrap crossing parts, densify when the edge approximation requires it,
and validate the transformed geometry. A generic vertex-only transform is not
an automatic geodesic densifier. Near poles, choose a suitable polar projection
or geodesic method and inspect its area of use. Check ring orientation, enclosed
region and extent on a globe as well as a flat map.

## Verify with Terraproof

Run with an installed Python core and replace these example paths with real local
datasets. Checks are selected by inputs/options, not by a check-id CLI argument:

```bash
python -m terraproof check parcels_projected.gpkg --operation area --format md --lang en --out crs-report.md
python -m terraproof check roads_projected.gpkg parcels_projected.gpkg --operation distance
python -m terraproof check parcels_geographic.gpkg --operation buffer
```

`crs.defined` checks presence, not whether the label is true. `crs.consistent`
compares multiple positional datasets with the first; it does not reproject them.
`crs.metric_operation` fails for a geographic or geocentric CRS with the declared
operation. It passes only a projected horizontal CRS (including a compound CRS whose
horizontal part is projected) in metre- **or foot-based** units, and warns when the
units cannot be confirmed. The last command
is an intentional negative preflight, not a recipe for a geographic buffer.

Projection distortion, unit conversion in your arithmetic, axis order, control
point accuracy, grid availability, datum/epoch correctness, antimeridian handling,
and geodesic algorithms are **not checked automatically yet**. A pass is not a
survey-accuracy claim. See [verification](../verification/SKILL.md).

## Sources

- [S1 — PROJ UTM](https://proj.org/en/stable/operations/projections/utm.html): conformal classification, 60 zones, generally 6-degree width.
- [S2 — PROJ Albers](https://proj.org/en/stable/operations/projections/aea.html), [Lambert azimuthal equal-area](https://proj.org/en/stable/operations/projections/laea.html), and [Lambert conformal conic](https://proj.org/en/stable/operations/projections/lcc.html): projection properties.
- [S3 — PROJ FAQ](https://proj.org/en/stable/faq.html): EPSG:4326 latitude/longitude axes, CRS lookup, WKT and authority definitions.
- [S4 — RFC 7946](https://www.rfc-editor.org/rfc/rfc7946): sections 3.1.1, 3.1.9, 4 and 5 cover coordinate order, degrees, antimeridian and poles.
- [S5 — pyproj advanced examples](https://pyproj4.github.io/pyproj/stable/advanced_examples.html): TransformerGroup, missing grids and AOI selection.
- [S6 — pyproj Geod](https://pyproj4.github.io/pyproj/stable/api/geod.html): ellipsoidal distance/area and signed ring areas.
- [GeoPandas projections](https://geopandas.org/en/stable/docs/user_guide/projections.html): CRS assignment versus transformation and geographic boundary limitations.
