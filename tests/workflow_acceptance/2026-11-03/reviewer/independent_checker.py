"""Prior-criteria native oracle. No product imports or implementation inspection.

Run with ../installed/Scripts/python.exe -I independent_checker.py.
Reads frozen artifacts; writes only reviewer/independent-evidence.json.
"""
from pathlib import Path
import json, hashlib, math, re, datetime
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.features import geometry_mask
from pyproj import Transformer
from shapely.geometry import shape, mapping, Polygon, box
from shapely.ops import transform as geom_transform
from shapely import contains_xy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
E = {"checker": "standalone rasterio/numpy/pyproj/shapely; no terraproof imports",
     "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
     "checks": [], "cases": {}, "variants": {}}

def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def check(label, passed, detail=None):
    row = {"check": label, "passed": bool(passed)}
    if detail is not None:
        row["detail"] = detail
    E["checks"].append(row)

def near(label, actual, expected, tol):
    ok = actual is None and expected is None
    if actual is not None and expected is not None:
        ok = abs(actual - expected) <= tol
    check(label, ok, {"actual": actual, "expected": expected, "tolerance": tol})

def geometry(data):
    if data["type"] == "FeatureCollection":
        assert len(data["features"]) == 1
        data = data["features"][0]
    if data["type"] == "Feature":
        data = data["geometry"]
    return shape(data)

def densify(poly, step):
    coords = list(poly.exterior.coords)
    out = []
    for a, b in zip(coords, coords[1:]):
        n = max(1, math.ceil(max(abs(b[0]-a[0]), abs(b[1]-a[1])) / step))
        out.extend((a[0]+(b[0]-a[0])*i/n, a[1]+(b[1]-a[1])*i/n) for i in range(n))
    return Polygon(out + [out[0]])

def native_polygon(geo, ds, step=0.0001):
    tr = Transformer.from_crs(4326, ds.crs, always_xy=True)
    return geom_transform(tr.transform, densify(geo, step))

def window_for(poly, ds):
    inv = ~ds.transform
    coords = [inv * xy for xy in poly.exterior.coords]
    c0 = math.floor(min(x for x, y in coords)) - 1
    r0 = math.floor(min(y for x, y in coords)) - 1
    c1 = math.ceil(max(x for x, y in coords)) + 1
    r1 = math.ceil(max(y for x, y in coords)) + 1
    return Window(c0, r0, c1-c0, r1-r0)

def members(poly, ds, win):
    trans = ds.window_transform(win)
    rows, cols = np.indices((int(win.height), int(win.width)))
    xx = trans.c + (cols+0.5)*trans.a + (rows+0.5)*trans.b
    yy = trans.f + (cols+0.5)*trans.d + (rows+0.5)*trans.e
    selected = contains_xy(poly, xx, yy)
    ri = geometry_mask([mapping(poly)], out_shape=selected.shape, transform=trans,
                       invert=True, all_touched=False)
    return selected, ri

def hist(values):
    v, n = np.unique(values, return_counts=True)
    return {str(int(a)): int(b) for a, b in zip(v, n)}

def uncertainty_stats(values, missing):
    if not values.size:
        return {"known_count": 0, "missing_count": missing, "minimum_kelvin": None,
                "maximum_kelvin": None, "mean_kelvin": None, "percentiles_kelvin": None,
                **{f"fraction_above_{v}_kelvin": None for v in [2, 3, 4]}}
    return {"known_count": int(values.size), "missing_count": missing,
            "minimum_kelvin": float(values.min()), "maximum_kelvin": float(values.max()),
            "mean_kelvin": float(values.mean()),
            "percentiles_kelvin": {f"p{q:02d}": float(np.percentile(values, q))
                                   for q in [5, 25, 50, 75, 95]},
            **{f"fraction_above_{v}_kelvin": float(np.mean(values > v)) for v in [2, 3, 4]}}

def compare_stats(label, actual, expected, tol=1e-8):
    for k, value in expected.items():
        if isinstance(value, dict):
            compare_stats(label+"."+k, actual[k], value, tol)
        elif isinstance(value, int):
            check(label+"."+k, actual[k] == value)
        else:
            near(label+"."+k, actual[k], value, tol)

def oracle(st, qa, uq, poly, bits, mult, add, cutoff=None, win=None):
    win = win or window_for(poly, st)
    sel, ri = members(poly, st, win)
    rows, cols = np.indices(sel.shape)
    ingrid = ((rows+win.row_off >= 0) & (rows+win.row_off < st.height)
              & (cols+win.col_off >= 0) & (cols+win.col_off < st.width))
    data = [d.read(1, window=win, boundless=True, fill_value=d.nodata) for d in [st, qa, uq]]
    masks = [d.read_masks(1, window=win, boundless=True) > 0 for d in [st, qa, uq]]
    dn, q, u = data
    acquired = sel & ingrid & masks[1] & ((q & 1) == 0)
    temp = dn.astype(np.float64)*mult + add - 273.15
    base = acquired & masks[0] & (dn > 0) & np.isfinite(temp) & ((q & sum(1 << b for b in bits)) == 0)
    known = masks[2] & (u >= 0) & (u <= 32767) & (u != -9999)
    uk = u.astype(np.float64)*0.01
    valid = base if cutoff is None else base & known & (uk <= cutoff)
    counts = {"requested_count": int(sel.sum()), "selected_count": int((sel & ingrid).sum()),
              "acquired_count": int(acquired.sum()), "base_valid_count": int(base.sum()),
              "post_uncertainty_valid_count": int(valid.sum()),
              "uncertainty_exceeded_count": int((base & known & (uk > cutoff)).sum()) if cutoff is not None else 0,
              "uncertainty_missing_excluded_count": int((base & ~known).sum()) if cutoff is not None else 0,
              "outside_grid_count": int((sel & ~ingrid).sum()),
              "qa_fill_or_unknown_count": int((sel & ingrid & ~acquired).sum())}
    counts.update(acquired_fraction_of_requested=float(acquired.sum()/sel.sum()),
                  grid_fraction_of_requested=float((sel & ingrid).sum()/sel.sum()),
                  post_uncertainty_valid_fraction_of_acquired=float(valid.sum()/acquired.sum()) if acquired.any() else None)
    stats = uncertainty_stats(uk[base & known], int((base & ~known).sum()))
    return dict(win=win, selected=sel, ri=ri, acquired=acquired, base=base, known=known,
                valid=valid, temp=temp, uk=uk, data=data, counts=counts, uq_stats=stats)

freeze = ROOT/"OUTCOMES_FROZEN.json"
check("outcome freeze manifest hash", sha(freeze) == "779cc90c9aaf816cf5e5c41e4fc79202cae36d8656fa82a934604241ad6b67ea")
inventory = read(freeze)
bad = []
for rec in inventory["records"]:
    p = ROOT/rec["file"]
    if not p.exists() or p.stat().st_size != rec["bytes"] or sha(p) != rec["sha256"]:
        bad.append(rec["file"])
check("all frozen inventory bytes and hashes", not bad, {"records": len(inventory["records"]), "mismatches": bad})
expected_prior = {"PUBLIC_CASES.json": "ae6a5051d5c56ad964cc254f10ea1094a10dbd2455a2d89c1ffc8319706b6621",
                  "PUBLIC_BRIEF.md": "f84a2588a0519b26c669f530d145ec19db39e01d76003b3e76b5fd394f114493",
                  "SEALED_CRITERIA.json": "1b5111cdafdaf194b9f7399eff0d86945383c6ffffc6bcb7507fc35677f0b980",
                  "SEALED_CRITERIA.md": "d0b98a5fb931832c7c8ad81837e81ba6c99ee855cd166bd1f147ba6ad661a278",
                  "SHA256_MANIFEST.json": "6538c83b82b362b21065d53e7c07c9e7ae901e8171b995981be1d3806e1a8bea"}
for name, digest in expected_prior.items():
    check("prior file "+name, sha(HERE/name) == digest)
for rec in read(HERE/"SHA256_MANIFEST.json")["files"]:
    check("prior manifest member "+rec["path"], sha(HERE/rec["path"]) == rec["sha256"])
if any(not r["passed"] for r in E["checks"]):
    raise RuntimeError("Integrity mismatch; no native analysis permitted")

spec = read(HERE/"PUBLIC_CASES.json")
total_bytes = 0
for case in spec["cases"]:
    cid = case["id"]
    directory = ROOT/cid
    searchgeo = shape(case["source_search"]["intent"]["aoi"])
    retained_search = geometry(read(directory/"search-aoi.geojson"))
    check(cid+" search AOI unchanged", searchgeo.equals(retained_search))
    catalog = read(directory/"discovery/catalog-page-1.json")
    eligible = []
    for item in catalog["features"]:
        prop = item["properties"]
        if (prop.get("platform") in ["landsat-8", "landsat-9"]
            and prop.get("landsat:correction") == "L2SP"
            and case["source_search"]["datetime_inclusive_utc_dates"][0] <= prop["datetime"][:10] <= case["source_search"]["datetime_inclusive_utc_dates"][1]
            and prop.get("eo:cloud_cover", 101) <= case["source_search"]["max_cloud_percent"]
            and shape(item["geometry"]).covers(searchgeo)
            and all(k in item["assets"] for k in case["fixed_native_assets"])):
            eligible.append(item)
    eligible.sort(key=lambda x: x["id"])
    eligible.sort(key=lambda x: x["properties"]["datetime"], reverse=True)
    eligible.sort(key=lambda x: x["properties"]["eo:cloud_cover"])
    check(cid+" metadata ranking", eligible[0]["id"] == case["selected_item_id"])
    proposal = read(directory/"discovery/report.json")
    request = read(directory/"request.json")
    check(cid+" search cloud and date requirements", request["search"]["max_scene_cloud"] == case["source_search"]["max_cloud_percent"]
          and request["intent"]["acquired_between"] == case["source_search"]["datetime_inclusive_utc_dates"])
    actual_order = [x["id"] for x in proposal["candidates"] if x["eligible"]]
    check(cid+" discovery eligible order", actual_order == [x["id"] for x in eligible])
    check(cid+" fixed selection", read(directory/"selection.json")["item"] == case["selected_item_id"])
    records = read(directory/"package/fetch-manifest.json")["records"]
    paths = {}
    for rec in records:
        path = directory/"package/inputs"/rec["file"]
        check(cid+" native identity "+rec["role"], rec["url"] == case["fixed_native_assets"][rec["role"]]
              and sha(path) == rec["sha256"] and path.stat().st_size == rec["bytes"])
        paths[rec["role"]] = path
        total_bytes += path.stat().st_size
    check(cid+" exactly four native assets", set(paths) == {"mtl.txt", "lwir11", "qa_pixel", "qa"})
    groups = {}
    stack = []
    for key, value in re.findall(r'^\s*(\w+)\s*=\s*(.+?)\s*$', paths["mtl.txt"].read_text(), flags=re.M):
        value = value.strip('"')
        if key == "GROUP":
            stack.append(value)
        elif key == "END_GROUP":
            stack.pop()
        else:
            groups.setdefault(stack[-1], {})[key] = value
    mtl = {**groups["PRODUCT_CONTENTS"], **groups["IMAGE_ATTRIBUTES"],
           **groups["LEVEL2_SURFACE_TEMPERATURE_PARAMETERS"]}
    check(cid+" MTL native filenames", all(path.name in groups["PRODUCT_CONTENTS"].values() for role, path in paths.items() if role != "mtl.txt")
          and mtl["LANDSAT_PRODUCT_ID"]+"_MTL.txt" == paths["mtl.txt"].name)
    mult, add = float(mtl["TEMPERATURE_MULT_BAND_ST_B10"]), float(mtl["TEMPERATURE_ADD_BAND_ST_B10"])
    check(cid+" native metadata identity", mtl["SPACECRAFT_ID"] in ["LANDSAT_8", "LANDSAT_9"]
          and mtl["PROCESSING_LEVEL"] == "L2SP" and case["selected_item_id"][17:25] == mtl["DATE_ACQUIRED"].replace("-", "")
          and mult == 0.00341802 and add == 149.)
    with rasterio.open(paths["lwir11"]) as st, rasterio.open(paths["qa_pixel"]) as qa, rasterio.open(paths["qa"]) as uq:
        check(cid+" native types and fills", st.dtypes == ("uint16",) and st.nodata == 0
              and qa.dtypes == ("uint16",) and uq.dtypes == ("int16",) and uq.nodata == -9999)
        check(cid+" native grid alignment", all(d.shape == st.shape and d.crs == st.crs
              and np.max(np.abs(np.array(tuple(d.transform)[:6])-tuple(st.transform)[:6])) <= 1e-9 for d in [qa, uq]))
        meta = case["metadata_projection"]
        check(cid+" catalog projection equals header", list(st.shape) == meta["proj:shape"]
              and st.crs.to_epsg() == meta["proj:epsg"] and np.max(np.abs(np.array(tuple(st.transform)[:6])-meta["proj:transform"])) <= 1e-9)
        if cid == "R2":
            geo = geometry(read(directory/"corner-aoi.geojson"))
            to_wgs = Transformer.from_crs(st.crs, 4326, always_xy=True)
            native_expected = densify(box(*(st.transform*(0, 10)), *(st.transform*(10, 0))), 7.5)
            expected_geo = geom_transform(to_wgs.transform, native_expected)
            poly = geom_transform(Transformer.from_crs(4326, st.crs, always_xy=True).transform, geo)
            # Hausdorff compares vertex geometry, independent of polygon orientation/start vertex.
            error_pixels = poly.hausdorff_distance(box(*(st.transform*(0, 10)), *(st.transform*(10, 0)))) / 30
            check(cid+" header-derived exact corner", error_pixels <= 1e-5, {"max_edge_roundtrip_error_pixels": error_pixels})
            E["corner_boundary_diagnostic"] = {
                "ideal_native_window_area_square_m": 90000.,
                "inverse_projected_polygon_area_square_m": poly.area,
                "inverse_projected_area_outside_native_grid_square_m": poly.difference(box(*st.bounds)).area,
                "max_edge_roundtrip_error_pixels": error_pixels,
                "product_reported_outside_area_fraction": read(directory/"R2-corner-default/plan.json")["facts"]["outside_grid_extent_fraction_native_plane"],
                "product_grid_extent_covers_aoi": read(directory/"R2-corner-default/plan.json")["facts"]["grid_extent_covers_aoi"],
                "meaning": "Continuous-boundary numerical artifact; requested centre coverage is tested separately. Does not isolate an admission path with extent Boolean true."}
            frozen = read(directory/"corner-geometry-freeze.json")
            check(cid+" corner freeze identity", frozen["aoi_sha256"] == sha(directory/"corner-aoi.geojson")
                  and frozen["diagnostic_pixels_read_before_this_freeze"] is False)
        else:
            geo = searchgeo
            poly = native_polygon(geo, st)
        initial = oracle(st, qa, uq, poly, case["source_search"]["intent"]["reject_qa_bits"], mult, add)
        if cid != "R2":
            finer = oracle(st, qa, uq, native_polygon(geo, st, 0.00005), case["source_search"]["intent"]["reject_qa_bits"], mult, add, win=initial["win"])
            check(cid+" geographic edge refinement stable", np.array_equal(initial["selected"], finer["selected"]))
        check(cid+" two membership algorithms agree", np.array_equal(initial["selected"], initial["ri"]))
        if cid == "R2":
            rr, cc = np.where(initial["selected"])
            rowcols = sorted(zip((rr+int(initial["win"].row_off)).tolist(), (cc+int(initial["win"].col_off)).tolist()))
            check(cid+" exactly requested corner centres", rowcols == [(r, c) for r in range(10) for c in range(10)])
        E["cases"][cid] = {"selected_item_id": case["selected_item_id"], "date": mtl["DATE_ACQUIRED"],
            "scene_time": mtl["SCENE_CENTER_TIME"], "shape": list(st.shape), "crs": str(st.crs),
            "affine": list(tuple(st.transform)[:6]), "scale": mult, "offset_kelvin": add,
            "native_band_dtypes": {"ST_B10": st.dtypes[0], "QA_PIXEL": qa.dtypes[0], "ST_QA": uq.dtypes[0]},
            "native_nodata_metadata": {"ST_B10": st.nodata, "QA_PIXEL": qa.nodata, "ST_QA": uq.nodata},
            "MTL_PRODUCT_CONTENTS_PROCESSING_LEVEL": groups["PRODUCT_CONTENTS"]["PROCESSING_LEVEL"],
            "MTL_LEVEL1_PROCESSING_RECORD_PROCESSING_LEVEL": groups["LEVEL1_PROCESSING_RECORD"]["PROCESSING_LEVEL"],
            "baseline_counts": initial["counts"], "baseline_uncertainty": initial["uq_stats"],
            "raw_histograms": {k: hist(a[initial["selected"]]) for k, a in zip(["ST_B10", "QA_PIXEL", "ST_QA"], initial["data"])}}
        for variant in case["workflow_variants"]:
            vid = variant["id"]
            vd = directory/vid
            cutoff = variant["max_uncertainty_kelvin"]
            cutoff = None if cutoff == "omit" else cutoff
            o = oracle(st, qa, uq, poly, case["source_search"]["intent"]["reject_qa_bits"], mult, add, cutoff)
            counts = o["counts"]
            plan = read(vd/"plan.json")
            workflow = read(vd/"workflow.json")
            intent = workflow["intent"]
            check(vid+" intent unchanged", intent["quantity"] == "land-surface-temperature" and intent["unit"] == "degree_Celsius"
                  and intent["reject_qa_bits"] == [0,1,2,3,4,5,7] and intent["min_valid_fraction"] == variant["min_valid_fraction"]
                  and intent.get("max_uncertainty_kelvin") == cutoff and "scene_coverage" not in intent
                  and geometry(read(intent["aoi"])).equals(geo)
                  and intent["acquired_between"] == case["source_search"]["datetime_inclusive_utc_dates"])
            for k, value in counts.items():
                if isinstance(value, int):
                    check(vid+" plan "+k, plan["facts"]["support"][k] == value)
                else:
                    near(vid+" plan "+k, plan["facts"]["support"][k], value, 1e-12)
            compare_stats(vid+" plan uncertainty", plan["facts"]["support"]["uncertainty_before_filter"], o["uq_stats"])
            full = counts["requested_count"] > 0 and counts["acquired_count"] == counts["requested_count"] and counts["outside_grid_count"] == 0
            admissible = full and counts["post_uncertainty_valid_count"] > 0 and counts["post_uncertainty_valid_fraction_of_acquired"] >= variant["min_valid_fraction"]
            check(vid+" admission", plan["status"] == ("ready-for-review" if admissible else "unresolved"))
            check(vid+" QA full coverage fact", plan["facts"]["full_aoi_acquired"] == full)
            check(vid+" MTL facts and source retained", workflow["source"]["metadata"] == str(paths["mtl.txt"])
                  and plan["facts"]["product_id"] == mtl["LANDSAT_PRODUCT_ID"] and plan["facts"]["date"] == mtl["DATE_ACQUIRED"]
                  and plan["facts"]["scene_time"] == mtl["SCENE_CENTER_TIME"]
                  and plan["facts"]["sensor"] == mtl["SPACECRAFT_ID"] and plan["facts"]["scale"] == mult and plan["facts"]["offset_kelvin"] == add)
            record = {"counts": counts, "expected_admissible": bool(admissible), "actual_admission": plan["status"], "issues": plan.get("issues", [])}
            if not admissible:
                check(vid+" stopped before approval and output", not (vd/"approval.json").exists() and not (vd/"outputs").exists())
                if cid == "R2":
                    check(vid+" explicit acquisition refusal reason", any("acquisition coverage" in x for x in plan.get("issues", [])))
            else:
                summary = read(vd/"outputs/summary.json")
                for key, expected in {"requested_count": counts["requested_count"], "acquired_count": counts["acquired_count"],
                                      "valid_count": counts["post_uncertainty_valid_count"], "base_valid_count": counts["base_valid_count"]}.items():
                    check(vid+" summary "+key, summary[key] == expected)
                vals = o["temp"][o["valid"]]
                tempstats = {"min_celsius": float(vals.min()), "max_celsius": float(vals.max()), "mean_celsius": float(vals.mean())}
                compare_stats(vid+" Celsius statistics", summary, tempstats, 1e-4)
                compare_stats(vid+" summary uncertainty before", summary["uncertainty_before_filter"], o["uq_stats"])
                compare_stats(vid+" summary uncertainty delivered", summary["uncertainty_delivered"], o["uq_stats"])
                near(vid+" summary mean uncertainty", summary["mean_product_uncertainty_kelvin"], o["uq_stats"]["mean_kelvin"], 1e-8)
                near(vid+" summary valid fraction", summary["valid_fraction_of_acquired"], counts["post_uncertainty_valid_fraction_of_acquired"], 1e-12)
                record["temperature_statistics"] = tempstats
                record["uncertainty_statistics"] = o["uq_stats"]
                approval = read(vd/"approval.json")
                run = read(vd/"run-result.json")
                verify = read(vd/"verify-result.json")
                provenance = read(vd/"outputs/workflow.json")
                check(vid+" provenance links exact retained state", provenance["intent_document"] == workflow
                      and provenance["approval"] == approval and provenance["product_facts"] == plan["facts"]
                      and provenance["verification"] == verify and provenance["spec_digest"] == plan["spec_digest"] == approval["spec_digest"])
                for rec in approval["inputs"]:
                    path = Path(rec["path"])
                    check(vid+" approval input "+path.name, sha(path) == rec["sha256"] and path.stat().st_size == rec["bytes"])
                for rec in provenance["outputs"]:
                    path = vd/"outputs"/rec["path"]
                    check(vid+" provenance output "+path.name, sha(path) == rec["sha256"] and path.stat().st_size == rec["bytes"])
                check(vid+" review declaration", approval["review"] == {"identity_authenticated": False, "kind": "engineering-self-review"}
                      and run["review"] == approval["review"])
                check(vid+" numerical grade and limitations", all(r["status"] == "verified" and r["grade"] == "checks-passed"
                      and r["physical_accuracy_validated"] is False for r in [run, verify])
                      and "not uncertainty of the mean" in summary["uncertainty_meaning"]
                      and "not a period estimate" in summary["temporal_support"])
                outdir = vd/"outputs"
                with rasterio.open(outdir/"temperature_celsius.tif") as delivered:
                    col, row = (~st.transform) * (delivered.transform.c, delivered.transform.f)
                    check(vid+" delivered native crop", abs(col-round(col)) <= 1e-9 and abs(row-round(row)) <= 1e-9
                          and delivered.crs == st.crs and delivered.transform.a == st.transform.a and delivered.transform.e == st.transform.e
                          and delivered.transform.b == delivered.transform.d == 0 and delivered.scales == (1.,) and delivered.offsets == (0.,))
                    win = Window(round(col), round(row), delivered.width, delivered.height)
                    co = oracle(st, qa, uq, poly, intent["reject_qa_bits"], mult, add, cutoff, win)
                    check(vid+" crop retains all selected centres", int(co["selected"].sum()) == counts["requested_count"])
                    dt = delivered.read(1)
                    check(vid+" delivered valid mask", np.array_equal(delivered.read_masks(1)>0, co["valid"]))
                    max_temp_error = float(np.max(np.abs(dt[co["valid"]]-co["temp"][co["valid"]])))
                    check(vid+" delivered Celsius pixels", max_temp_error <= 1e-4, {"max_absolute_error_C": max_temp_error})
                    record["maximum_delivered_temperature_error_C"] = max_temp_error
                    for name, expected in [("aoi",co["selected"]),("acquired",co["acquired"]),("validity",co["valid"])]:
                        with rasterio.open(outdir/(name+".tif")) as d:
                            check(vid+" delivered "+name+" mask", d.transform == delivered.transform and d.crs == delivered.crs
                                  and np.array_equal(d.read(1), expected.astype(np.uint8)))
                    with rasterio.open(outdir/"uncertainty_kelvin.tif") as d:
                        umask = co["valid"] & co["known"]
                        arr = d.read(1)
                        expected = co["uk"][umask].astype(arr.dtype)
                        check(vid+" delivered uncertainty mask", np.array_equal(d.read_masks(1)>0, umask))
                        check(vid+" delivered uncertainty pixels", np.array_equal(arr[umask], expected),
                              {"comparison": "exact representable float32 of signed native DN times0.01; no Celsius offset or sqrt(n)",
                               "max_encoding_error_K": float(np.max(np.abs(arr[umask]-co["uk"][umask])))})
                with rasterio.open(outdir/"decoded_celsius.tif") as decoded:
                    check(vid+" decoded full native grid", decoded.shape == st.shape and decoded.transform == st.transform and decoded.crs == st.crs)
                    mismatches = 0
                    maxerr = 0.
                    n = 0
                    for r0 in range(0, st.height, 128):
                        w = Window(0, r0, st.width, min(128, st.height-r0))
                        raw = st.read(1, window=w)
                        good = (st.read_masks(1, window=w)>0) & (raw>0)
                        dec = decoded.read(1, window=w)
                        mismatches += int(np.count_nonzero((decoded.read_masks(1, window=w)>0) != good))
                        err = np.abs(dec[good]-(raw[good].astype(np.float64)*mult+add-273.15))
                        if err.size:
                            maxerr = max(maxerr, float(err.max()))
                        n += int(good.sum())
                    check(vid+" decoded entire native raster", mismatches == 0 and maxerr <= 1e-4,
                          {"mask_mismatches": mismatches, "valid_native_pixels_checked": n, "max_absolute_error_C": maxerr})
                    record["decoded_full_native_pixels_checked"] = n
                for name in ["report.html", "map.svg"]:
                    text = (outdir/name).read_text(encoding="utf-8")
                    check(vid+" "+name+" status disclosure", "VERIFIED (" in text and "engineering-self-review" in text
                          and "not authenticated" in text and "scientific certification" in text)
            E["variants"][vid] = record
    print(cid, "native calculation complete", E["cases"][cid]["baseline_counts"], flush=True)

check("aggregate exact native bytes", total_bytes == 323321401 and total_bytes <= 536870912,
      {"native_bytes": total_bytes, "maximum_bytes": 536870912})
ledger = read(ROOT/"transfer-ledger.json")
check("retained transfer ledger", ledger["new_native_bytes"] == total_bytes and ledger["retries"] == 0)
E["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
E["check_count"] = len(E["checks"])
E["failed_checks"] = [x for x in E["checks"] if not x["passed"]]
(HERE/"independent-evidence.json").write_text(json.dumps(E, indent=2, allow_nan=False)+"\n", encoding="utf-8")
print("CHECKS", E["check_count"], "FAILED", len(E["failed_checks"]))
print(json.dumps(E["failed_checks"], indent=2))
