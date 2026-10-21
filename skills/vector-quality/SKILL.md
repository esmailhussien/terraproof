---
name: vector-quality
description: Audit and repair vector geometry and attribute quality while preserving feature identity and analytical scope; use before overlays, joins, measurement, coverage analysis, or GeoJSON export when invalid, missing, mixed, duplicate, or topologically inconsistent features could silently change results.
---

# Vector quality

## Inventory geometry and attribute states

Read the intended layer and retain a stable feature key. Count null geometries,
empty geometries, invalid non-null geometries, and geometry types separately.
Missing geometry (`None`) is not an empty geometry; an empty geometry may be
valid but unusable for the requested operation. Count attribute nulls independently.

```python
import geopandas as gpd
import shapely

gdf = gpd.read_file("parcels.gpkg", engine="pyogrio")
g = gdf.geometry
present = g.notna()
print({
    "records": len(gdf),
    "null_geometry": int((~present).sum()),
    "empty_geometry": int(g.is_empty.sum()),
    "invalid_geometry": int((present & ~g.is_valid).sum()),
    "types": g.geom_type.value_counts(dropna=False).to_dict(),
    "attribute_nulls": gdf.drop(columns=g.name).isna().sum().to_dict(),
})
reasons = shapely.is_valid_reason(g.array)
```

Distinguish Polygon from MultiPolygon even when both are acceptable polygonal
outputs. Inspect GeometryCollection members explicitly: a collection can hide
lower-dimensional remnants. A consistent type family is not proof of the
requested exact type, multipart policy, or dimensionality.

Use [GeoPandas](../geopandas/SKILL.md) for I/O and operation APIs, and
[CRS and units](../crs-and-units/SKILL.md) for metric tolerances. Follow the shared
[engineering](../../instructions/engineering.md), [simplicity](../../instructions/simplicity.md),
and [security](../../instructions/security.md) guidance rather than duplicating it.

## Check validity before choosing a repair

OGC Simple Features polygon rules concern the represented region, not just a
closed coordinate list [S1]. Rings must be closed and simple; ring boundaries
must not cross. Holes must lie within their shell and polygon interiors must be
connected. MultiPolygon interiors must not overlap. Boundary-touch cases require
the actual OGC rules, not a blanket rule that all touching is invalid.

Use Shapely `is_valid` and `is_valid_reason` to diagnose individual features.
Planar topology ignores Z coordinates, so these checks do not audit elevation or M values.
A self-crossing LineString can be valid but non-simple; use `is_simple` when
network rules require no self-intersections. Feature validity alone does not
check whether adjacent cadastral polygons overlap or leave gaps.

Choose a repair based on intended geometry semantics, not simply whichever
method makes `is_valid` return true [S2]:

- `make_valid` linework repair preserves input edges/vertices but may produce
  complex multipart output or a GeometryCollection.
- Structure repair reasons from shells and holes; it assumes their input roles
  are correct. Check that the installed Shapely/GEOS supports the requested method.
- Collapsed rings can become lines/points or empties. Removing them is a scope
  decision, not a neutral cleanup. Do not substitute `buffer(0)` as a universal
  repair or assume it preserves the original region.

Minimal repair audit (default `make_valid` avoids version-specific method options):

```python
import geopandas as gpd
import shapely

original = gpd.read_file("parcels.gpkg", engine="pyogrio")
repaired = original.copy()
needs_repair = original.geometry.notna() & ~original.geometry.is_valid
repaired.loc[needs_repair, original.geometry.name] = shapely.make_valid(
    original.geometry.loc[needs_repair].array
)
print(original.geometry.geom_type.value_counts(dropna=False))
print(repaired.geometry.geom_type.value_counts(dropna=False))
print("empty_after", int(repaired.geometry.is_empty.sum()))
# Review changed regions and types before exporting repaired to a new dataset.
```

Keep a before/after repair ledger keyed by feature ID. Compare type, parts,
empty/null state, and region changes in a justified measurement CRS; invalid
input areas are not a trustworthy ground truth. Export only after deciding how
to retain or quarantine lower-dimensional components. Do not silently explode
or drop them to meet a file format's schema. Audit whether Z and M values survive
repair and export, since repair and format conversion can drop or alter them.

## Detect duplicate geometries without deleting legitimate records

Define duplication first: identical coordinate encoding, normalized structural
equality, or topological equality are different questions. Normalized WKB is a
useful candidate key, but topologically equal polygons with different vertex
segmentation can still have different encodings. Use Shapely `equals` on candidate
pairs for region equality [S3], with a spatial index for large layers.

Separate duplicate IDs, duplicate geometry, and duplicate full records. Two records
may share geometry legitimately (for example, different observations or rights).
Inspect attributes and ownership rules before deduplicating; record retained IDs
and every removal. Precision rounding is not an automatic duplicate detector.

## Audit coverage topology: gaps, overlaps, and slivers

For a polygon coverage, validate individual inputs first and work in a suitable
shared CRS. Define the expected coverage boundary and legitimate holes before
labelling missing area a gap.

- Use spatial-index candidate pairs, then intersect polygon interiors; positive
  intersection area indicates overlap, while shared edges alone are not overlap.
  Exclude a feature paired with itself and count each pair once.
- Compare the union with the expected coverage boundary. Boundary minus union
  identifies uncovered regions; union minus boundary identifies excess coverage.
  The summed feature area versus union area is a useful overlap diagnostic, not
  a map of each error or a substitute for pairwise inspection.
- Inspect narrow fragments generated by overlay. Set any sliver review threshold
  from source accuracy and analytical purpose, not an arbitrary deletion cutoff.
- With a supporting Shapely version, `coverage_is_valid` and
  `coverage_invalid_edges` help assess edge-matched, non-overlapping coverage.
  Gaps may still be permitted by a coverage validator; check the intended boundary
  explicitly [S4].

A valid union can conceal invalid relationships between the original records.
Do not fix a parcel coverage by dissolving away the ownership boundaries.

## Choose precision and snapping deliberately

Precision grids and snapping tolerances are in coordinate units. Choose a grid
from the source accuracy and task tolerance after selecting a suitable CRS.
`shapely.set_precision` may remove repeated vertices, collapse narrow polygons,
or return empties [S5]. `shapely.snap` uses heuristics and does not guarantee valid
output. Validate again and compare feature scope and area after either operation.

Use a shared precision policy for overlay operands, but keep the original
coordinates. Coordinate decimal places do not establish positional accuracy.
Do not snap all layers to a basemap simply because the basemap looks cleaner.

## Preserve records through null handling and joins

Audit required attribute nulls, blank strings and duplicate join keys separately.
For a many-parcels-to-one-owner join, reject null keys or explicitly route them to
an unmatched group before merging. A left join with `validate="many_to_one"` and
`indicator=True` can detect multiplied keys and unmatched records. Pandas may
match null keys to each other, unlike usual SQL null semantics [S6].

Track stable IDs as well as counts: an output can lose one record and duplicate
another while preserving total row count. Report unmatched left/right keys,
null-induced exclusions and one-to-many expansion. An intentional inner join or
`dropna` needs an explicit excluded-record ledger. A spatial join's boundary
predicate and duplicate matches need separate review; see
[GeoPandas API guidance](../geopandas/SKILL.md#core-api-decisions).

## Export GeoJSON winding correctly

RFC 7946 requires WGS 84 longitude/latitude coordinates in decimal degrees and
right-hand winding: exterior rings counterclockwise, holes clockwise. A linear
ring has at least four positions and identical first/last positions [S7]. Winding
is not an OGC validity substitute. Readers should tolerate older opposite-wound
polygons, but producers should emit the RFC convention.

Use the GDAL GeoJSON driver's RFC mode after reviewing geometry quality:

```bash
ogr2ogr -f GeoJSON -t_srs EPSG:4326 -lco RFC7946=YES parcels.geojson parcels_reviewed.gpkg
```

Reopen and inspect the output rings, types, stable IDs and scope. RFC mode handles
antimeridian splitting, but precision reduction at export can still affect tiny
features. Do not export projected metre coordinates under a GeoJSON CRS label.

## Verify with Terraproof

Use an installed Python core and substitute real local datasets:

```bash
python -m terraproof check parcels.gpkg --format md --lang en --out vector-input-report.md
python -m terraproof check repaired.gpkg --compare-to parcels.gpkg
python -m terraproof check joined.gpkg --compare-to repaired.gpkg
```

`geometry.valid` fails for invalid geometries. `geometry.non_empty` **warns** on
nulls or empties. `geometry.type_consistent` warns across type families, but
Polygon plus MultiPolygon is considered consistent. `scope.record_count` warns
on changed counts; it does not prove stable-ID preservation or join correctness.
`crs.defined` verifies CRS presence only.

Duplicate geometries, coverage gaps/overlaps/slivers, GeoJSON winding, precision
loss, attribute nulls, join-key/cardinality semantics, and repair fidelity are
**not checked automatically yet**. Add explicit audits for those requirements;
see [verification](../verification/SKILL.md).

## Sources

- [S1 — OGC Simple Feature Access, Part 1, 06-103r4](https://docs.ogc.org/is/06-103r4/06-103r4.pdf): sections 6.1.11 and 6.1.14 define polygon/MultiPolygon validity; simplicity and topology definitions are in the common architecture.
- [S2 — Shapely make_valid](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html): linework/structure semantics and collapsed components.
- [S3 — Shapely equals](https://shapely.readthedocs.io/en/stable/reference/shapely.equals.html): topological equality independent of vertex ordering.
- [S4 — Shapely coverage_is_valid](https://shapely.readthedocs.io/en/stable/reference/shapely.coverage_is_valid.html): edge matching, overlap and gap-width semantics.
- [S5 — Shapely set_precision](https://shapely.readthedocs.io/en/stable/reference/shapely.set_precision.html) and [snap](https://shapely.readthedocs.io/en/stable/reference/shapely.snap.html): collapse and validity caveats.
- [S6 — pandas merge](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.merge.html): validation, indicator and null-key matching.
- [S7 — RFC 7946](https://www.rfc-editor.org/rfc/rfc7946): sections 3.1.6 and 4 specify four-position closed rings, winding and coordinates.
- [GDAL GeoJSON driver](https://gdal.org/en/stable/drivers/vector/geojson.html): RFC7946 layer creation option and export behavior.
