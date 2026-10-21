"""Accuracy-assessment checks: accuracy.sample_design and accuracy.estimates.

Both read a reference-sample CSV with columns `map_class,ref_class`, optionally with a
`stratum_weight` column. accuracy.estimates additionally needs the map-class areas
(`class_areas`: a mapping of class name to area, in pixels or hectares, or a single
number applied to every class).

The estimators follow the stratified area-adjusted approach of
Olofsson et al. (2014), "Good practices for estimating area and assessing accuracy of land
change", Remote Sensing of Environment 148:42-57. Map strata are the rows of the confusion
matrix and the estimated quantities are per *reference* class k, because a map stratum's row
always sums to 1 and estimating from it would just return the mapped area unchanged.

    W_i       = A_i / A                           (stratum i's share of the mapped area)
    p_ij      = W_i * n_ij / n_i                  (area-weighted cell proportion)
    p_k       = sum_i p_ij                        (estimated proportion of reference class k)
    A_k       = A * p_k                           (estimated area of reference class k)
    Var(p_k)  = sum_i W_i^2 * (n_ik/n_i)(1 - n_ik/n_i) / (n_i - 1)
    SE(A_k)   = A * sqrt(Var(p_k))
    CI95      = A_k +/- 1.96 * SE(A_k)

User's accuracy for map class i is n_ii / n_i. Producer's accuracy for reference class j is
the area-weighted column ratio p_jj / sum_i p_ij. Overall accuracy is sum_j p_jj. The 1.96
is the normal quantile the paper uses for these intervals; no SciPy dependency is used.
"""

from __future__ import annotations

import csv
import math
import os
from collections import Counter

from terraproof.checks.base import FAIL, NOT_RUN, PASS, WARN, result

# Common rule of thumb for a per-class accuracy statement: 50 reference samples per mapped
# class gives a worst-case (95% confidence) margin of error of about +/- 14 percentage points
# under simple random sampling; 100 gives about +/- 10. Both are configurable via min_per_class.
DEFAULT_MIN_PER_CLASS = 50
MIN_PER_CLASS_JUSTIFICATION = (
    f"the default of {DEFAULT_MIN_PER_CLASS} samples per map class is a common rule of thumb: under simple "
    "random sampling it bounds the worst-case 95% margin of error for a per-class proportion at roughly "
    "+/- 0.14. It is a design convention, not a statistical requirement; set min_per_class to match the "
    "precision the study needs"
)

# Normal 0.975 quantile, the multiplier the paper uses for these confidence intervals.
NORMAL_975 = 1.959964


def read_samples(path: str | os.PathLike) -> dict:
    """Read the reference-sample CSV: map_class, ref_class, optional stratum_weight."""
    path = os.fspath(path)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header row")
        names = {name.strip() for name in reader.fieldnames}
        missing = [name for name in ("map_class", "ref_class") if name not in names]
        if missing:
            raise ValueError(f"{path} is missing required column(s): {', '.join(missing)}")
        has_weight = "stratum_weight" in names
        records = []
        for line_number, row in enumerate(reader, start=2):
            map_class = (row.get("map_class") or "").strip()
            ref_class = (row.get("ref_class") or "").strip()
            if not map_class or not ref_class:
                continue
            weight = None
            if has_weight:
                text = (row.get("stratum_weight") or "").strip()
                if text:
                    try:
                        weight = float(text)
                    except ValueError:
                        raise ValueError(f"{path} line {line_number}: stratum_weight '{text}' is not a number")
            records.append({"map_class": map_class, "ref_class": ref_class, "stratum_weight": weight})
    if not records:
        raise ValueError(f"{path} has no sample rows")
    return {"path": path, "records": records, "has_weights": has_weight}


def _normalise_areas(class_areas) -> tuple[dict[str, float], str | None]:
    """Accept a {class: area} mapping or one number applied to every sampled class."""
    if class_areas is None:
        return {}, None
    if isinstance(class_areas, dict):
        areas = {str(name): float(value) for name, value in class_areas.items()}
        return areas, None
    try:
        value = float(class_areas)
    except (TypeError, ValueError):
        return {}, f"class_areas must be a mapping of class name to area or a single number, got {class_areas!r}"
    return {}, f"class_areas must be a mapping of class name to area; got a single number {value}"


def check_sample_design(
    samples: dict,
    class_areas=None,
    min_per_class: int = DEFAULT_MIN_PER_CLASS,
    estimates_requested: bool = False,
) -> list:
    """Every mapped class needs at least `min_per_class` reference samples.

    A missing class area when area estimates are requested is a warning, not a failure: the
    samples may still support an accuracy statement.
    """
    path = samples["path"]
    counts = Counter(record["map_class"] for record in samples["records"])
    areas, areas_error = _normalise_areas(class_areas)
    evidence = {
        "input": path,
        "sample_count": len(samples["records"]),
        "map_classes": sorted(counts),
        "per_class_counts": {name: counts[name] for name in sorted(counts)},
        "min_per_class": min_per_class,
        "min_per_class_default": min_per_class == DEFAULT_MIN_PER_CLASS,
        "min_per_class_rationale": MIN_PER_CLASS_JUSTIFICATION,
        "has_stratum_weights": samples["has_weights"],
        "estimates_requested": estimates_requested,
        "class_areas_given": sorted(areas) if areas else [],
    }

    under = {name: counts[name] for name in sorted(counts) if counts[name] < min_per_class}
    if under:
        listed = ", ".join(f"{name} ({count})" for name, count in under.items())
        return [
            result(
                "accuracy.sample_design",
                FAIL,
                f"{len(under)} of {len(counts)} map classes in {path} have fewer than {min_per_class} reference "
                f"samples: {listed}. {MIN_PER_CLASS_JUSTIFICATION}.",
                **evidence,
            )
        ]

    if areas_error:
        return [
            result(
                "accuracy.sample_design",
                NOT_RUN,
                f"Map class areas were given in a form this check cannot use: {areas_error}.",
                **evidence,
            )
        ]
    if estimates_requested and not areas:
        return [
            result(
                "accuracy.sample_design",
                WARN,
                f"Every map class in {path} reaches {min_per_class} samples, but no map-class areas or "
                "stratum weights were given, so area-adjusted area estimates cannot be produced. Report "
                "accuracy without area estimates, or supply the class areas.",
                **evidence,
            )
        ]
    message = f"Every one of the {len(counts)} map classes in {path} has at least {min_per_class} reference samples."
    if estimates_requested and areas:
        message += f" Map-class areas were supplied for {len(areas)} classes."
    return [result("accuracy.sample_design", PASS, message, **evidence)]


def _confusion(records: list[dict]) -> tuple[dict[str, Counter], dict[str, int]]:
    """Per-stratum counts n_ij (row = map class, column = reference class) and each n_i."""
    strata: dict[str, Counter] = {}
    totals: dict[str, int] = Counter()
    for record in records:
        strata.setdefault(record["map_class"], Counter())[record["ref_class"]] += 1
        totals[record["map_class"]] += 1
    return strata, dict(totals)


def compute_estimates(records: list[dict], areas: dict[str, float]) -> dict:
    """Confusion matrix, the three accuracies, and stratified area-adjusted class areas.

    The area estimator is per *reference* class k, not per map stratum. A map stratum's row
    always sums to 1, so summing it would return the mapped area unchanged; the quantity of
    interest is the area share of each reference class, estimated across strata:

        W_i    = A_i / A                       stratum i's share of the mapped area
        p_ij   = W_i * n_ij / n_i              area-weighted cell proportion
        p_k    = sum_i p_ij                    estimated proportion of reference class k
        A_k    = A_total * p_k
        Var(p_k) = sum_i W_i^2 * (n_ik/n_i)(1 - n_ik/n_i) / (n_i - 1)
        SE(A_k)  = A_total * sqrt(Var(p_k))
        CI95     = A_k +/- 1.96 * SE(A_k)

    User's accuracy for map class i is the row ratio n_ii / n_i. Producer's accuracy for
    reference class j is the area-weighted column ratio p_jj / sum_i p_ij. Overall accuracy
    is sum_j p_jj. These are Olofsson et al. (2014), eqs. 5-6 and 10-12; the 1.96 is the
    normal quantile the paper uses for these confidence intervals.
    """
    strata, n_i = _confusion(records)
    map_classes = sorted(strata)
    reference_classes = sorted({record["ref_class"] for record in records})
    sample_count = sum(n_i.values())

    matrix = {
        name: {ref: strata[name].get(ref, 0) for ref in reference_classes} for name in map_classes
    }

    total_area = float(sum(areas.values()))
    weights = {
        name: (areas[name] / total_area if total_area and name in areas else 0.0)
        for name in map_classes
    }

    # Area-weighted cell proportions p_ij and the per-reference-class estimators.
    p_ij = {
        i: {j: weights[i] * strata[i].get(j, 0) / n_i[i] for j in reference_classes}
        for i in map_classes
    }
    column_total = {
        j: sum(p_ij[i][j] for i in map_classes) for j in reference_classes
    }
    proportion = {j: column_total[j] for j in reference_classes}
    variance = {}
    for j in reference_classes:
        terms = []
        for i in map_classes:
            if weights[i] == 0.0 or n_i[i] < 2:
                continue
            share = strata[i].get(j, 0) / n_i[i]
            terms.append(weights[i] ** 2 * share * (1.0 - share) / (n_i[i] - 1))
        variance[j] = sum(terms)

    area_estimate = {j: total_area * proportion[j] for j in reference_classes}
    standard_error = {j: total_area * math.sqrt(variance[j]) for j in reference_classes}
    margin_of_error = {j: NORMAL_975 * standard_error[j] for j in reference_classes}

    # User's accuracy: the reference class that agrees with the map class, over that class's
    # own sample. Producer's accuracy: the area-weighted column ratio.
    user_accuracy = {}
    for i in map_classes:
        if i in reference_classes:
            user_accuracy[i] = strata[i].get(i, 0) / n_i[i] if n_i[i] else float("nan")
        else:
            user_accuracy[i] = float("nan")
    producer_accuracy = {}
    for j in reference_classes:
        producer_accuracy[j] = (
            p_ij[j][j] / column_total[j] if column_total[j] else float("nan")
        )
    overall_accuracy = sum(producer_accuracy[j] * column_total[j] for j in reference_classes)

    # Sample (unweighted) accuracies, kept alongside so the area-adjusted values can be
    # compared with the raw confusion matrix.
    sample_overall = (
        sum(strata[i].get(i, 0) for i in map_classes if i in strata) / sample_count
        if sample_count
        else float("nan")
    )

    class_area_estimate = {
        j: {
            "area_estimated": area_estimate[j],
            "area_proportion": proportion[j],
            "standard_error": standard_error[j],
            "variance": variance[j],
            "margin_of_error_95": margin_of_error[j],
            "ci_95_low": area_estimate[j] - margin_of_error[j],
            "ci_95_high": area_estimate[j] + margin_of_error[j],
            "mapped_area_in_strata": sum(areas.get(i, 0.0) for i in map_classes if i == j),
        }
        for j in reference_classes
    }

    return {
        "sample_count": sample_count,
        "map_classes": map_classes,
        "reference_classes": reference_classes,
        "confusion_matrix": matrix,
        "n_stratum": n_i,
        "overall_accuracy": overall_accuracy,
        "sample_overall_accuracy": sample_overall,
        "user_accuracy": user_accuracy,
        "producer_accuracy": producer_accuracy,
        "map_class_areas": {name: areas.get(name) for name in map_classes},
        "total_map_area": total_area,
        "stratum_weights": weights,
        "area_weighted_cell_proportions": p_ij,
        "area_proportion": proportion,
        "class_area_estimate": class_area_estimate,
        "area_estimated": area_estimate,
        "area_standard_error": standard_error,
        "area_margin_of_error_95": margin_of_error,
        "ci_95_multiplier": NORMAL_975,
        "method": (
            "stratified area-adjusted estimator over map strata, estimating each reference class's area "
            "(Olofsson et al. 2014, Remote Sensing of Environment 148:42-57, eqs. 5-6 and 10-12); "
            "95% intervals use the normal quantile 1.96 as in the paper"
        ),
    }


def check_estimates(samples: dict, class_areas=None) -> list:
    """Confusion matrix, accuracies, and stratified area-adjusted class areas with 95% CIs."""
    path = samples["path"]
    records = samples["records"]
    areas, areas_error = _normalise_areas(class_areas)
    counts = Counter(record["map_class"] for record in records)
    base_evidence = {
        "input": path,
        "sample_count": len(records),
        "per_class_counts": {name: counts[name] for name in sorted(counts)},
        "class_areas_given": sorted(areas) if areas else [],
        "method": (
            "stratified area-adjusted estimator over map strata, estimating each reference class's area "
            "(Olofsson et al. 2014, Remote Sensing of Environment 148:42-57, eqs. 5-6 and 10-12); "
            "95% intervals use the normal quantile 1.96 as in the paper"
        ),
    }

    # Sample accuracies are always available; the area-adjusted ones need the class areas.
    strata, n_i = _confusion(records)
    accuracies = {
        "sample_overall_accuracy": (
            sum(strata[name].get(name, 0) for name in strata) / len(records) if records else float("nan")
        ),
        "user_accuracy": {
            name: (strata[name].get(name, 0) / n_i[name]) for name in sorted(strata) if n_i[name]
        },
    }

    if areas_error:
        return [
            result(
                "accuracy.estimates",
                NOT_RUN,
                f"Map class areas were given in a form this check cannot use: {areas_error}. "
                f"Sample accuracies were computed (overall {accuracies['sample_overall_accuracy']:.4f}).",
                **base_evidence,
                accuracies=accuracies,
            )
        ]
    if not areas:
        return [
            result(
                "accuracy.estimates",
                NOT_RUN,
                f"Sample accuracies for {path} were computed (overall "
                f"{accuracies['sample_overall_accuracy']:.4f}), but area-adjusted class-area estimates and "
                "their confidence intervals need the map-class areas; none were given, so no area estimate "
                "is reported.",
                **base_evidence,
                accuracies=accuracies,
            )
        ]

    missing = sorted(name for name in counts if name not in areas)
    if missing:
        return [
            result(
                "accuracy.estimates",
                NOT_RUN,
                f"Map-class areas are missing for {', '.join(missing)}, so no complete area estimate can be made "
                f"for {path}. Sample accuracies were computed (overall "
                f"{accuracies['sample_overall_accuracy']:.4f}).",
                **base_evidence,
                accuracies=accuracies,
                classes_without_area=missing,
            )
        ]

    full = compute_estimates(records, areas)
    # full also carries sample_count and method, which base_evidence already sets to the same values.
    estimates = {key: value for key, value in full.items() if key not in base_evidence}
    return [
        result(
            "accuracy.estimates",
            PASS,
            f"Computed the confusion matrix, area-adjusted accuracies (overall "
            f"{full['overall_accuracy']:.4f}), and stratified area-adjusted areas with 95% confidence "
            f"intervals for {len(full['reference_classes'])} reference classes over "
            f"{full['total_map_area']:.6g} total mapped units from {full['sample_count']} reference samples. "
            "Areas are estimated per reference class across map strata; they are not a probability sample "
            "unless the design was one.",
            **base_evidence,
            **estimates,
        )
    ]