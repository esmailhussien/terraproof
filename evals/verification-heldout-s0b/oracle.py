"""Recompute the truth for every verification-heldout-s0b case independently
from the fetched sources and the facts in cases.json, then check each case's
stated kind.

Usage:
    python oracle.py <cache-dir> <out-dir>

Never imports terraproof and never imports derive.py. Every recomputation
follows the case's own `facts`: the described chain (order, target, spacing
interpretation, resampling, unit) for slopes; the described rule classes and
usable value for masks; the per-number statistic/selection/decode specs for
summary reports. Prints a JSON summary; exits non-zero on any disagreement.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Geod
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import MultiPolygon, shape

DEP3_FILL = -999999.0
R_EARTH_M = 6378137.0
SCALE = 1e-4
FT_PER_M = 3.280839895013123

RESAMPLINGS = {
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
    "nearest": Resampling.nearest,
}

TOL_ABS = 5e-6
TOL_REL = 5e-5      # float32 storage round-off of the delivered grids


def close(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= max(TOL_ABS, TOL_REL * max(abs(a), abs(b)))


def rel(path: str) -> str:
    return path[len("cache/"):] if path.startswith("cache/") else path


def read_tif(cache: Path, name: str):
    with rasterio.open(cache / rel(name), "r") as ds:
        return ds.read(1), {"crs": ds.crs, "transform": ds.transform,
                            "nodata": ds.nodata}


def read_out_tif(out: Path, case_id: str, name: str):
    with rasterio.open(out / "outputs" / case_id / name, "r") as ds:
        return ds.read(1)


def read_out_json(out: Path, case_id: str, name: str):
    return json.loads((out / "outputs" / case_id / name).read_text(encoding="utf-8"))


def s10(scl):
    return np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)


def mid_lat(prof, rows):
    res_y = abs(prof["transform"].e)
    return prof["transform"].f - (rows / 2.0) * res_y


def mag_of(z, dx, dy):
    zy, zx = np.gradient(z.astype(np.float64), dy, dx)
    return np.hypot(zx, zy)


def to_unit(mag, unit):
    return 100.0 * mag if unit == "percent" else np.degrees(np.arctan2(mag, 1.0))


def warp_arr(arr, prof, cache_rel, cache, crs, res, method):
    with rasterio.open(cache / rel(cache_rel)) as src:
        t, w, h = calculate_default_transform(src.crs, crs, src.width,
                                              src.height, *src.bounds,
                                              resolution=res)
    dst = np.full((int(h), int(w)), np.nan, dtype=np.float64)
    reproject(source=arr, destination=dst, src_transform=prof["transform"],
              src_crs=prof["crs"], dst_transform=t, dst_crs=crs,
              src_nodata=prof["nodata"], dst_nodata=np.nan,
              resampling=RESAMPLINGS[method])
    return dst


def geod_area_perim(geom):
    geod = Geod(ellps="WGS84")
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    area = perim = 0.0
    for p in polys:
        lons, lats = np.array(p.exterior.coords).T
        a, per = geod.polygon_area_perimeter(lons, lats)
        area += abs(a)
        perim += abs(per)
        for ring in p.interiors:
            lons, lats = np.array(ring.coords).T
            a, _ = geod.polygon_area_perimeter(lons, lats)
            area -= abs(a)
    return area / 1e6, perim / 1000.0


def honest_chain_mean(cache: Path, facts: dict) -> float:
    """Slope mean of the chain exactly as the case facts describe it."""
    relpath = facts["source_dem"]["path"]
    z, prof = read_tif(cache, relpath)
    unit = facts["slope_unit"]
    if "target_crs" in facts:  # reprojected chain
        order = facts["computation_order"]
        res_m = float(facts["target_resolution_m"])
        method = facts["resampling"]
        crs = facts["target_crs"]
        interp = facts.get("spacing_interpretation", "ground_metres")
        res_y, res_x = abs(prof["transform"].e), abs(prof["transform"].a)
        lat = mid_lat(prof, z.shape[0])
        dy_m = res_y * R_EARTH_M * math.pi / 180.0
        dx_m = res_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat))
        if order == "slope_then_warp":
            step = to_unit(mag_of(z, dx_m, dy_m), unit)
            out = warp_arr(step, prof, relpath, cache, crs, res_m, method)
            return float(out[~np.isnan(out)].mean())
        wd = warp_arr(z, prof, relpath, cache, crs, res_m, method)
        valid = ~np.isnan(wd)
        zf = np.where(valid, wd, 0.0)
        dx = dy = res_m
        if interp == "cos_reduced_ground_metres":
            dx = dy = res_m * math.cos(math.radians(lat))
        return float(to_unit(mag_of(zf, dx, dy), unit)[valid].mean())
    # same-grid chain: source grid, latitude-aware ground-metre steps
    res_y, res_x = abs(prof["transform"].e), abs(prof["transform"].a)
    lat = mid_lat(prof, z.shape[0])
    dy_m = res_y * R_EARTH_M * math.pi / 180.0
    dx_m = res_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat))
    return float(to_unit(mag_of(z, dx_m, dy_m), unit).mean())


def rule_mask(scl, classes):
    return np.isin(scl, classes)


def verdict(cid, kind, ok, notes):
    return {"id": cid, "kind": kind, "verdict": bool(ok), "notes": notes}


def check_case(cache: Path, out: Path, case: dict) -> dict:
    cid = case["id"]
    kind = case["kind"]
    facts = case["facts"]
    expect = case["oracle"]["value"]
    metric_name = case["oracle"]["value_metric"]

    # ------------------------------------------------------------- masks
    if cid.startswith("mask_"):
        scl, _ = read_tif(cache, facts["pixel_qa_layer"]["path"])
        desired = rule_mask(scl, facts["pixel_qa_classes_usable"])
        mask = read_out_tif(out, cid, "validity_mask.tif").astype(bool)
        sj = read_out_json(out, cid, "summary.json")
        exact = bool((mask == desired).all())
        assert int(facts["mask_usable_value"]) == 1
        if kind == "correct":
            return verdict(cid, kind, exact and close(expect, int(mask.sum()))
                           and int(sj["usable_pixel_count"]) == int(mask.sum()),
                           [f"exact={exact}; usable={int(mask.sum())}"])
        kept_invalid = int((mask & ~desired).sum())
        evicted = int((desired & ~mask).sum())
        metric = {
            "count_of_documented_invalid_pixels_kept_usable": kept_invalid,
            "count_of_documented_valid_pixels_evicted": evicted,
        }[metric_name]
        return verdict(cid, kind, (not exact) and metric == int(expect)
                       and metric > 0
                       and int(sj["usable_pixel_count"]) == int(mask.sum()),
                       [f"kept_invalid={kept_invalid}; evicted={evicted}"])

    # ------------------------------------------- reprojected slopes
    if cid.startswith("slope_rs_"):
        truth = honest_chain_mean(cache, facts)
        got = read_out_tif(out, cid, "slope.tif")
        dmean = float(got[got != -9999.0].astype(np.float64).mean())
        sj = read_out_json(out, cid, "summary.json")
        if kind == "correct":
            return verdict(cid, kind, close(dmean, truth) and close(expect, dmean)
                           and close(sj["mean_slope"], dmean),
                           [f"truth={truth}; delivered={dmean}"])
        dmean_chain = None  # wrongness factor uses recomputed truth
        factor = dmean / truth
        return verdict(cid, kind, close(factor, expect)
                       and abs(factor - 1.0) > 0.05 and not close(dmean, truth)
                       and close(sj["mean_slope"], dmean),
                       [f"delivered={dmean}; truth={truth}; factor={factor}"])

    # ------------------------------------------------- same-grid slopes
    if cid.startswith("slope_sg_"):
        z, _ = read_tif(cache, facts["source_dem"]["path"])
        res_y = float(facts["pixel_spacing_deg_north_south"])
        res_x = float(facts["pixel_spacing_deg_east_west"])
        lat = float(facts["source_window_mid_latitude_deg"])
        dy = res_y * R_EARTH_M * math.pi / 180.0
        dx = res_x * R_EARTH_M * math.pi / 180.0 * math.cos(math.radians(lat))
        truth = float(to_unit(mag_of(z, dx, dy), facts["slope_unit"]).mean())
        got = read_out_tif(out, cid, "slope.tif")
        dmean = float(got.astype(np.float64).mean())
        sj = read_out_json(out, cid, "summary.json")
        if kind == "correct":
            return verdict(cid, kind, close(dmean, truth) and close(expect, dmean)
                           and close(sj["mean_slope"], dmean),
                           [f"truth={truth}"])
        factor = dmean / truth
        return verdict(cid, kind, close(factor, expect)
                       and abs(factor - 1.0) > 0.05 and not close(dmean, truth)
                       and close(sj["mean_slope"], dmean),
                       [f"delivered={dmean}; truth={truth}; factor={factor}"])

    # --------------------------------------------------- summary reports
    if cid.startswith("report_"):
        numbers = facts["report_numbers"]
        truth_values = {}
        for key, spec in numbers.items():
            truth_values[key] = recompute_number(cache, spec)
        rep = read_out_json(out, cid, "report.json")

        def get(path):
            obj = rep
            for part in path.split("."):
                if part.isdigit():
                    obj = obj[int(part)]
                    continue
                obj = obj[part]
            return obj

        bad = [k for k, t in truth_values.items()
               if not (close(get(k), t) if isinstance(t, float) else get(k) == t)]
        if kind == "correct":
            headline = metric_name
            return verdict(cid, kind, not bad
                           and headline in truth_values
                           and close(expect, truth_values[headline]),
                           [f"all {len(truth_values)} numbers match"])
        if len(bad) != 1:
            return verdict(cid, kind, False, [f"wrong_keys={bad}"])
        d = float(get(bad[0]))
        t = float(truth_values[bad[0]])
        metric = {
            "mismatch_factor_abs_fill_averaged_in": abs(d - t) / t,
            "evicted_zero_height_pixels": t - d,
            "area_degrees_mismatch_factor": t / d,
            "share_ratio_honest_over_delivered": t / d,
            "nir_mean_over_green_mean": t / d,
            "blue_shortfall_abs_reflectance": abs(t - d),
        }[metric_name]
        return verdict(cid, kind, close(metric, expect),
                       [f"bad_key={bad[0]}; metric={metric}"])

    # ---------------------------------------------------------------- plain
    if cid.startswith("plain_"):
        delivered_name = ("report.json" if cid.endswith("_multi")
                          else "summary.json")
        delivered = read_out_json(out, cid, delivered_name)
        truths = {key: recompute_number(cache, spec)
                  for key, spec in facts["report_numbers"].items()}

        def get_plain(path):
            obj = delivered
            for part in path.split("."):
                obj = obj[part]
            return obj

        bad = [k for k, t in truths.items()
               if not (close(get_plain(k), t) if isinstance(t, float)
                       else get_plain(k) == t)]
        headline = metric_name
        return verdict(cid, kind, not bad and headline in truths
                       and close(expect, truths[headline]),
                       [f"bad={bad}; headline={headline}"])

    raise KeyError(cid)


def _z_transform(z, facts):  # removed; the same-grid branch is facts-driven now
    raise NotImplementedError


def selection_mask(arr, block: dict):
    if not block:
        return np.ones(arr.shape, dtype=bool)
    t = block.get("type")
    if t == "not_value":
        return arr != block["value"]
    if t == "not_zero":
        return arr != 0
    if t == "equal":
        return arr == block["value"]
    if t == "class_in":
        return np.isin(arr, block["classes"])
    if t == "all":
        return np.ones(arr.shape, dtype=bool)
    if t == "all_not_zero":
        for f in block["files"]:
            marr, _ = read_tif(Path("."), f)  # placeholder; replaced below
        raise KeyError("handled in recompute_number")
    if t == "none":
        return np.zeros(arr.shape, dtype=bool)
    raise KeyError(t)


def _scaled(arr, decode, dtype_scale=1.0):
    scale = decode.get("scale") if decode else None
    if scale is None:
        return arr.astype(np.float64)
    vals = arr.astype(np.float64) * scale
    off = decode.get("offset") or 0
    if off:
        vals = vals + off
    return vals


def _qa_mask(cache: Path, block: dict, base: np.ndarray) -> np.ndarray:
    if "qa_file" in block:
        qa, _ = read_tif(cache, block["qa_file"])
        classes = np.isin(qa, block["qa_classes"])
        if classes.shape != base.shape:
            factor = base.shape[0] // classes.shape[0]
            classes = np.repeat(np.repeat(classes, factor, 0), factor, 1)
        return base & classes
    return base


def recompute_number(cache: Path, spec: dict):
    """Recompute one report number from its structured facts spec."""
    stat = spec["statistic"]
    file_spec = spec["file"]
    block = dict(spec.get("selection", {}) or {})
    if "path" in file_spec:
        p = rel(file_spec["path"])
        if p.endswith(".geojson"):
            geo = json.loads((cache / p).read_text(encoding="utf-8"))
            feats = geo["features"]
            if stat == "feature_count":
                return len(feats)
            fam = next(f for f in feats
                       if f["properties"].get("NAME") == file_spec["feature"])
            geom = shape(fam["geometry"])
            area, perim = geod_area_perim(geom)
            if stat == "area_geodesic":
                return area
            if stat == "length_geodesic":
                return perim
            raise KeyError(stat)
        arr, _ = read_tif(cache, p)
        if block.get("type") == "all_not_zero":
            sel = arr != 0
            for mp in block["files"]:
                marr, _ = read_tif(cache, mp)
                sel &= marr != 0
        elif "qa_file" in block:
            qa, _ = read_tif(cache, block["qa_file"])
            classes = np.isin(qa, block.get("qa_classes", block.get("classes", [])))
            if classes.shape != arr.shape:
                factor = arr.shape[0] // classes.shape[0]
                classes = np.repeat(np.repeat(classes, factor, 0), factor, 1)
            sel = classes
        else:
            sel = selection_mask(arr, block)
        decode = spec.get("decode", {})
        vals = _scaled(arr, decode)
        if stat == "mean":
            return float(vals[sel].mean(dtype=np.float64))
        if stat == "maximum":
            return float(vals[sel].max())
        if stat == "minimum":
            return float(vals[sel].min())
        if stat == "count":
            return int(sel.sum())
        if stat == "share":
            denom = spec["denominator"]
            if denom == "all":
                return float(sel.sum() / arr.size)
            valid = selection_mask(arr, spec["denominator_mask"])
            return float(sel.sum() / valid.sum())
        raise KeyError(stat)
    if stat == "ndvi_mean":
        green, _ = read_tif(cache, file_spec["green"])
        nir, _ = read_tif(cache, file_spec["nir"])
        sel = (green != 0) & (nir != 0)
        for mp in block.get("mask_files", []):
            marr, _ = read_tif(cache, mp)
            sel &= marr != 0
        if "qa_file" in block:
            qa, _ = read_tif(cache, block["qa_file"])
            classes = np.isin(qa, block.get("qa_classes", block.get("classes", [])))
            if classes.shape != sel.shape:
                factor = sel.shape[0] // classes.shape[0]
                classes = np.repeat(np.repeat(classes, factor, 0), factor, 1)
            sel &= classes
        decode = spec.get("decode", {})
        g = _scaled(green, decode)
        n = _scaled(nir, decode)
        ndvi = (n - g) / np.maximum(n + g, 1e-12)
        return float(ndvi[sel].mean(dtype=np.float64))
    raise KeyError(stat)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    cache = Path(argv[1])
    out = Path(argv[2])
    here = Path(__file__).resolve().parent
    cases = json.loads((here / "cases.json").read_text(encoding="utf-8"))["cases"]
    results = [check_case(cache, out, case) for case in cases]
    n_ok = sum(1 for r in results if r["verdict"])
    print(json.dumps({"cases": results, "agree": n_ok, "total": len(results)},
                     indent=2, sort_keys=True))
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
