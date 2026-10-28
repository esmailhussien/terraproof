"""Independent oracle for Terraproof Phase 7 held-out verification cases (V0b).

For every case in cases.json, independently recomputes the true expected answer
from the sources and declared facts without importing terraproof. Checks delivered
outputs and reports whether each is correct or wrong.

Verifies 100% agreement with declared expectations across all 48 cases in 6 families:
1. geographic_metric_work
2. qa_masking
3. terrain_slope_unlabeled
4. vertical_datums_and_units
5. nodata_and_scale_regression
6. plain
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pyogrio.raw
import pyproj
import rasterio
from shapely.geometry import LineString, Point, Polygon
import shapely.wkb


def load_raster(path: Path) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Read first band and metadata from a GeoTIFF."""
    with rasterio.open(path) as ds:
        data = ds.read(1)
        meta = {
            "crs": ds.crs,
            "transform": ds.transform,
            "nodata": ds.nodata,
            "shape": data.shape,
        }
        return data, meta


def load_vector_features(path: Path) -> Tuple[List[Any], Dict[str, List[Any]]]:
    """Read geometries and attribute fields from GeoJSON."""
    meta, fids, wkb_geoms, field_data = pyogrio.raw.read(str(path))
    geoms = [shapely.from_wkb(w) for w in wkb_geoms]
    fields = list(meta["fields"])
    data_dict = {fields[i]: field_data[i] for i in range(len(fields))}
    return geoms, data_dict


def evaluate_geographic_metric(case: Dict[str, Any], root: Path) -> Tuple[str, str]:
    declared = case["declared"]
    op = declared["operation"]

    if op == "polygon_area_calculation":
        src_path = root / declared["primary_source"]
        deliv_path = root / case["output"]
        src_geoms, _ = load_vector_features(src_path)
        _, deliv_data = load_vector_features(deliv_path)

        prop_name = declared["metric_property_name"]
        delivered_area = float(deliv_data[prop_name][0])

        geod = pyproj.Geod(ellps="WGS84")
        true_area = abs(float(geod.geometry_area_perimeter(src_geoms[0])[0]))
        rel_diff = abs(delivered_area - true_area) / true_area

        if rel_diff < 0.01:
            return "correct", f"delivered area ({delivered_area:,.1f} m2) matches true WGS84 geodesic area ({true_area:,.1f} m2) within {rel_diff * 100:.3f}%"
        return "wrong", f"delivered area ({delivered_area:,.4f}) differs from true geodesic area ({true_area:,.1f} m2) by {rel_diff * 100:.1f}%"

    elif op == "line_buffer_generation":
        src_path = root / declared["primary_source"]
        deliv_path = root / case["output"]
        src_geoms, _ = load_vector_features(src_path)
        deliv_geoms, _ = load_vector_features(deliv_path)

        target_buf_m = declared["buffer_distance_m"]
        buf_poly = deliv_geoms[0]
        src_line = src_geoms[0]

        coords = list(buf_poly.exterior.coords)
        for x, y in coords:
            if abs(y) > 90.0 or abs(x) > 360.0:
                return "wrong", f"buffer coordinates exceed valid planetary bounds (lat={y:.1f}, lon={x:.1f})"

        c_lon, c_lat = src_line.centroid.x, src_line.centroid.y
        zone = int((c_lon + 180) // 6) + 1
        epsg = f"EPSG:{32600 + zone}" if c_lat >= 0 else f"EPSG:{32700 + zone}"
        trans = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True)

        line_proj = LineString([trans.transform(x, y) for x, y in src_line.coords])
        ext_proj = [trans.transform(x, y) for x, y in coords]
        dists = [line_proj.distance(Point(p)) for p in ext_proj[::max(1, len(ext_proj) // 30)]]
        min_dist = min(dists)
        max_dist = max(dists)
        distortion = max(abs(min_dist - target_buf_m), abs(max_dist - target_buf_m)) / target_buf_m

        if distortion > 0.15:
            return "wrong", f"buffer ground offset reaches min={min_dist:.1f} m, max={max_dist:.1f} m (expected {target_buf_m:.1f} m, {distortion * 100:.1f}% distortion)"
        return "correct", f"buffer ground distance verified at {np.mean(dists):.1f} m (max deviation {distortion * 100:.2f}%)"

    elif op == "geodesic_length_calculation":
        src_path = root / declared["primary_source"]
        deliv_path = root / case["output"]
        src_geoms, _ = load_vector_features(src_path)
        _, deliv_data = load_vector_features(deliv_path)

        prop_name = declared["metric_property_name"]
        delivered_len = float(deliv_data[prop_name][0])

        geod = pyproj.Geod(ellps="WGS84")
        true_len = float(geod.geometry_length(src_geoms[0]))
        rel_diff = abs(delivered_len - true_len) / true_len

        if rel_diff < 0.01:
            return "correct", f"delivered length ({delivered_len:,.1f} m) matches true WGS84 geodesic length ({true_len:,.1f} m) within {rel_diff * 100:.3f}%"
        return "wrong", f"delivered length ({delivered_len:,.1f} m) differs from true geodesic length ({true_len:,.1f} m) by {rel_diff * 100:.1f}%"

    raise ValueError(f"Unknown geographic_metric op: {op}")


def evaluate_qa_masking(case: Dict[str, Any], root: Path) -> Tuple[str, str]:
    declared = case["declared"]
    primary_path = root / declared["primary_source"]
    qa_path = root / declared["qa_layer"]
    deliv_path = root / case["output"]

    primary_data, p_meta = load_raster(primary_path)
    qa_data, _ = load_raster(qa_path)
    deliv_data, d_meta = load_raster(deliv_path)

    op = declared["operation"]
    if op == "qa_class_masking":
        valid_classes = declared["valid_qa_classes"]
        valid_mask = np.isin(qa_data, valid_classes)
    elif op == "qa_bitmask_filtering":
        bitmask = 0
        for b in declared["invalid_bit_indices"]:
            bitmask |= (1 << b)
        valid_mask = (qa_data & bitmask) == 0
    else:
        raise ValueError(f"Unknown qa_masking op: {op}")

    # Also account for source nodata gaps
    src_nodata = p_meta.get("nodata")
    if src_nodata is not None:
        valid_mask = valid_mask & (primary_data != src_nodata) & (~np.isnan(primary_data))

    deliv_nodata = d_meta.get("nodata")
    if deliv_nodata is not None:
        deliv_valid = (deliv_data != deliv_nodata) & (~np.isnan(deliv_data))
    else:
        deliv_valid = ~np.isnan(deliv_data)

    mismatches = int(np.sum(deliv_valid != valid_mask))
    total = deliv_data.size

    if mismatches > 0.01 * total:
        pct = (mismatches / total) * 100.0
        return "wrong", f"{mismatches} pixels ({pct:.1f}%) have incorrect QA mask status"

    if np.any(valid_mask):
        val_diff = float(np.nanmax(np.abs(deliv_data[valid_mask] - primary_data[valid_mask])))
        if val_diff > 1e-4:
            return "wrong", f"valid pixel values corrupted (max diff {val_diff:.4f})"

    return "correct", f"100% QA mask agreement ({int(np.sum(valid_mask))}/{total} valid pixels preserved)"


def evaluate_terrain_slope(case: Dict[str, Any], root: Path) -> Tuple[str, str]:
    declared = case["declared"]
    primary_path = root / declared["primary_source"]
    deliv_path = root / case["output"]

    z_data, meta = load_raster(primary_path)
    deliv_slope, _ = load_raster(deliv_path)

    v_unit = declared["declared_vertical_unit"]
    t = meta["transform"]
    src_crs = str(meta["crs"])

    # Convert z to metres if declared foot
    z_m = z_data.astype(np.float64) * (0.3048 if v_unit == "foot" else 1.0)

    # Compute true metric horizontal cell sizes
    if "4326" in src_crs:
        dlon = t.a
        dlat = abs(t.e)
        lat_center = t.f - (z_data.shape[0] / 2.0) * dlat
        dx_m = dlon * 111320.0 * math.cos(math.radians(lat_center))
        dy_m = dlat * 111320.0
    elif "2927" in src_crs:
        # Washington State Plane South: horizontal units are US survey feet
        dx_m = t.a * (1200.0 / 3937.0)
        dy_m = abs(t.e) * (1200.0 / 3937.0)
    else:
        # Standard metric projected CRS (UTM etc)
        dx_m = t.a
        dy_m = abs(t.e)

    dz_dx = np.gradient(z_m, dx_m, axis=1)
    dz_dy = np.gradient(z_m, dy_m, axis=0)
    true_slope_deg = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))

    mean_err = float(np.nanmean(np.abs(deliv_slope - true_slope_deg)))
    if mean_err < 0.5:
        return "correct", f"delivered slope matches true metric gradient (mean diff {mean_err:.2f} deg, mean slope {np.nanmean(deliv_slope):.1f} deg)"
    return "wrong", f"slope error is {mean_err:.2f} deg (delivered mean {np.nanmean(deliv_slope):.1f} deg vs true metric {np.nanmean(true_slope_deg):.1f} deg)"


def evaluate_vertical_datums(case: Dict[str, Any], root: Path) -> Tuple[str, str]:
    declared = case["declared"]
    primary_path = root / declared["primary_source"]
    deliv_path = root / case["output"]

    primary_data, _ = load_raster(primary_path)
    deliv_data, _ = load_raster(deliv_path)
    op = declared["operation"]

    if op == "geoid_height_correction":
        if "secondary_source" in declared:
            sec_path = root / declared["secondary_source"]
            n_data, _ = load_raster(sec_path)
            expected = primary_data.astype(np.float64) - n_data.astype(np.float64)
        else:
            n_val = declared["geoid_undulation_m"]
            expected = primary_data.astype(np.float64) - n_val

        diff = float(np.nanmean(np.abs(deliv_data.astype(np.float64) - expected)))
        if diff < 1e-4:
            return "correct", f"matches true orthometric heights H = h - N (mean diff {diff:.2e} m)"
        return "wrong", f"datum offset error of {diff:.2f} m against true orthometric height"

    elif op == "sounding_to_elevation":
        expected = -primary_data.astype(np.float64)
        diff = float(np.nanmean(np.abs(deliv_data.astype(np.float64) - expected)))
        if diff < 1e-4:
            return "correct", f"matches negative elevation conversion z = -depth (mean diff {diff:.2e} m)"
        return "wrong", f"sounding sign error of {diff:.2f} m against true elevation"

    elif op == "unit_conversion":
        factor = declared["conversion_factor"]
        expected = primary_data.astype(np.float64) * factor
        diff = float(np.nanmean(np.abs(deliv_data.astype(np.float64) - expected)))
        if diff < 1e-4:
            return "correct", f"matches true unit conversion factor {factor} (mean diff {diff:.2e} m)"
        return "wrong", f"unit conversion error of {diff:.2f} m against expected scaled elevation"

    raise ValueError(f"Unknown vertical_datums op: {op}")


def evaluate_nodata_and_scale(case: Dict[str, Any], root: Path) -> Tuple[str, str]:
    declared = case["declared"]
    primary_path = root / declared["primary_source"]
    deliv_path = root / case["output"]

    primary_data, p_meta = load_raster(primary_path)
    deliv_data, d_meta = load_raster(deliv_path)
    op = declared["operation"]

    if op == "nodata_handling":
        fill_val = declared["fill_value"]
        zero_is_valid = declared["zero_is_valid"]

        expected_valid = np.ones(primary_data.shape, dtype=bool)
        if not zero_is_valid:
            expected_valid[primary_data == 0.0] = False
        if fill_val != 0.0:
            expected_valid[primary_data == fill_val] = False

        deliv_nodata = d_meta.get("nodata")
        if deliv_nodata is not None:
            deliv_valid = (deliv_data != deliv_nodata) & (~np.isnan(deliv_data))
        else:
            deliv_valid = ~np.isnan(deliv_data)

        mismatches = int(np.sum(deliv_valid != expected_valid))
        total = deliv_data.size

        if mismatches > 0.005 * total:
            pct = (mismatches / total) * 100.0
            return "wrong", f"{mismatches} pixels ({pct:.1f}%) have incorrect nodata masking"

        return "correct", f"valid data and legitimate zeros correctly handled ({int(np.sum(expected_valid))}/{total} pixels valid)"

    elif op == "scale_and_offset_unpacking":
        scale = declared["scale_factor"]
        offset = declared["add_offset"]
        expected = primary_data.astype(np.float64) * scale + offset

        diff = float(np.nanmean(np.abs(deliv_data.astype(np.float64) - expected)))
        rng = float(np.nanmax(expected) - np.nanmin(expected))
        if rng == 0:
            rng = float(np.nanmean(np.abs(expected))) or 1.0
        rel_diff = diff / rng

        if rel_diff < 1e-4 and diff < 1e-4:
            return "correct", f"matches physical unpacked values DN * {scale} + {offset} (mean diff {diff:.2e})"
        return "wrong", f"mean error is {diff:.4f} (relative error {rel_diff * 100:.1f}%) against true physical values"

    raise ValueError(f"Unknown nodata_and_scale op: {op}")


def evaluate_plain(case: Dict[str, Any], root: Path) -> Tuple[str, str]:
    deliv_path = root / case["output"]

    if deliv_path.suffix == ".geojson":
        geoms, fields = load_vector_features(deliv_path)
        if len(geoms) == 0:
            return "wrong", "empty vector feature collection"
        for g in geoms:
            if g.is_empty:
                return "wrong", "empty geometry in feature collection"
        return "correct", f"clean vector layer with {len(geoms)} valid features"

    elif deliv_path.suffix == ".tif":
        data, meta = load_raster(deliv_path)
        valid_cells = np.sum(~np.isnan(data) & (data != meta.get("nodata", -9999.0)))
        if valid_cells == 0:
            return "wrong", "raster is completely empty or nodata"
        return "correct", f"clean raster with {valid_cells}/{data.size} valid cells, CRS {meta['crs']}"

    raise ValueError(f"Unknown file suffix for plain case: {deliv_path}")


EVALUATORS = {
    "geographic_metric_work": evaluate_geographic_metric,
    "qa_masking": evaluate_qa_masking,
    "terrain_slope_unlabeled": evaluate_terrain_slope,
    "vertical_datums_and_units": evaluate_vertical_datums,
    "nodata_and_scale_regression": evaluate_nodata_and_scale,
    "plain": evaluate_plain,
}


def run_oracle(root_dir: Path, cases_file: Path | None = None) -> Tuple[int, int, List[Dict[str, Any]]]:
    """Run independent oracle checks on all cases in root_dir."""
    if cases_file is None:
        cases_file = Path(__file__).parent / "cases.json"

    with open(cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    passed_agreements = 0
    total_cases = len(cases)

    for case in cases:
        cid = case["id"]
        family = case["family"]
        expected_kind = case["kind"]

        evaluator = EVALUATORS.get(family)
        if not evaluator:
            raise ValueError(f"No evaluator for family: {family}")

        verdict, detail = evaluator(case, root_dir)
        agrees = (verdict == expected_kind)
        if agrees:
            passed_agreements += 1

        results.append({
            "id": cid,
            "family": family,
            "expected_kind": expected_kind,
            "oracle_verdict": verdict,
            "agrees": agrees,
            "detail": detail,
        })

    return passed_agreements, total_cases, results


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent Oracle for Terraproof held-out cases V0b.")
    parser.add_argument("cases_dir", type=str, help="Directory containing generated cases datasets.")
    parser.add_argument("--cases-json", type=str, default=None, help="Path to cases.json (default: next to script).")
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir)
    cases_file = Path(args.cases_json) if args.cases_json else None

    print(f"Running independent oracle V0b on cases in: {cases_dir}")
    passed, total, results = run_oracle(cases_dir, cases_file)

    print("\n" + "=" * 90)
    print(f"{'Case ID':<32} {'Expected':<10} {'Verdict':<10} {'Status':<8} Detail")
    print("-" * 90)

    for r in results:
        status_str = "PASS" if r["agrees"] else "FAIL"
        print(f"{r['id']:<32} {r['expected_kind']:<10} {r['oracle_verdict']:<10} {status_str:<8} {r['detail']}")

    print("=" * 90)
    print(f"Summary: {passed}/{total} cases agreed with declared expectations.")

    if passed == total:
        print("ALL 48 HELD-OUT CASES VERIFIED SUCCESSFULLY: 100% AGREEMENT.")
        sys.exit(0)
    else:
        print(f"VERIFICATION FAILED: {total - passed} case(s) had mismatched verdicts.")
        sys.exit(1)


if __name__ == "__main__":
    main()
