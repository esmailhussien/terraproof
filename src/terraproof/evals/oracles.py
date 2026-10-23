"""Independent numerical oracles used by the benchmark recipes.

The oracles recompute expected values from first principles (the published estimator, the
calibration formula, power-domain averaging, spectral indices) instead of comparing a check
result with itself. The spec constants (for example Olofsson et al. 2014, Table 8) are the
ground truth; where a fixture supplies its own controls the oracle uses those controls.

Nothing here imports the check implementations it is grading.
"""

from __future__ import annotations

import math

import numpy as np

NORMAL_975 = 1.959964


def rounded(value: float, digits: int = 9) -> float:
    return round(float(value), digits)


class Assertion:
    """One named numeric or structural comparison."""

    def __init__(self, name: str, passed: bool, observed, expected, tolerance=None, note: str = ""):
        self.name = name
        self.passed = bool(passed)
        self.observed = observed
        self.expected = expected
        self.tolerance = tolerance
        self.note = note

    def to_dict(self) -> dict:
        record = {
            "name": self.name,
            "passed": self.passed,
            "observed": _plain(self.observed),
            "expected": _plain(self.expected),
        }
        if self.tolerance is not None:
            record["tolerance"] = self.tolerance
        if self.note:
            record["note"] = self.note
        return record


def _plain(value):
    """Make oracle values JSON-safe without depending on the report layer."""
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Oracle:
    """Collects assertions; the control passes the oracle only when all of them pass."""

    def __init__(self, title: str):
        self.title = title
        self.assertions: list[Assertion] = []

    # -- constructors -------------------------------------------------------------------
    def close(self, name: str, observed, expected, tolerance: float, note: str = "") -> Assertion:
        observed_value = rounded(observed) if _is_number(observed) else observed
        expected_value = rounded(expected) if _is_number(expected) else expected
        passed = _is_number(observed) and abs(float(observed) - float(expected)) <= tolerance
        assertion = Assertion(name, passed, observed_value, expected_value, tolerance, note)
        self.assertions.append(assertion)
        return assertion

    def equal(self, name: str, observed, expected, note: str = "") -> Assertion:
        assertion = Assertion(name, observed == expected, observed, expected, None, note)
        self.assertions.append(assertion)
        return assertion

    def require(self, name: str, condition: bool, observed, expected, note: str = "") -> Assertion:
        assertion = Assertion(name, condition, observed, expected, None, note)
        self.assertions.append(assertion)
        return assertion

    def differs_by(self, name: str, observed, unexpected, minimum: float, note: str = "") -> Assertion:
        distance = abs(float(observed) - float(unexpected)) if _is_number(observed) and _is_number(unexpected) else None
        assertion = Assertion(
            name,
            distance is not None and distance >= minimum,
            rounded(observed) if _is_number(observed) else observed,
            f"differs from {rounded(unexpected) if _is_number(unexpected) else unexpected} by >= {minimum}",
            minimum,
            note,
        )
        self.assertions.append(assertion)
        return assertion

    @property
    def passed(self) -> bool:
        return bool(self.assertions) and all(assertion.passed for assertion in self.assertions)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "passed": self.passed,
            "assertions": [assertion.to_dict() for assertion in self.assertions],
        }


# -- accuracy: stratified area-adjusted estimator (Olofsson et al. 2014) ------------------
def olofsson_estimates(
    matrix: dict[str, dict[str, int]],
    areas: dict[str, float],
) -> dict:
    """Recompute the stratified area-adjusted accuracies and areas from the published equations.

    W_i = A_i / A; p_ij = W_i n_ij / n_i; p_k = sum_i p_ik; A_k = A p_k;
    Var(p_k) = sum_i W_i^2 (n_ik/n_i)(1 - n_ik/n_i)/(n_i - 1); CI = A_k +/- 1.96 SE(A_k).

    User's accuracy is n_ii / n_i; producer's accuracy is p_jj / p_.j; overall accuracy is
    sum_j p_jj. This is an independent implementation: it does not call `checks.accuracy`.
    """
    map_classes = sorted(matrix)
    reference_classes = sorted({ref for row in matrix.values() for ref in row})
    total_area = sum(areas[name] for name in map_classes)
    weights = {name: areas[name] / total_area for name in map_classes}
    n_i = {name: sum(matrix[name].values()) for name in map_classes}

    p_ij = {
        i: {j: weights[i] * matrix[i].get(j, 0) / n_i[i] for j in reference_classes}
        for i in map_classes
    }
    p_k = {j: sum(p_ij[i][j] for i in map_classes) for j in reference_classes}
    variance = {}
    for j in reference_classes:
        variance[j] = sum(
            weights[i] ** 2 * (matrix[i].get(j, 0) / n_i[i]) * (1 - matrix[i].get(j, 0) / n_i[i]) / (n_i[i] - 1)
            for i in map_classes
            if n_i[i] > 1
        )
    user_accuracy = {
        name: matrix[name].get(name, 0) / n_i[name] for name in map_classes if name in reference_classes
    }
    producer_accuracy = {j: p_ij[j][j] / p_k[j] if p_k[j] else float("nan") for j in reference_classes}
    overall = sum(producer_accuracy[j] * p_k[j] for j in reference_classes)
    area = {j: total_area * p_k[j] for j in reference_classes}
    standard_error = {j: total_area * math.sqrt(variance[j]) for j in reference_classes}
    margin = {j: NORMAL_975 * standard_error[j] for j in reference_classes}
    return {
        "map_classes": map_classes,
        "reference_classes": reference_classes,
        "n_stratum": n_i,
        "stratum_weights": weights,
        "area_proportion": p_k,
        "area": area,
        "area_standard_error": standard_error,
        "area_margin_95": margin,
        "ci95_low": {j: area[j] - margin[j] for j in reference_classes},
        "ci95_high": {j: area[j] + margin[j] for j in reference_classes},
        "user_accuracy": user_accuracy,
        "producer_accuracy": producer_accuracy,
        "overall_accuracy": overall,
    }


# -- calibration and power-domain helpers ------------------------------------------------
S2_L2A_SCALE = 0.0001
S2_L2A_OFFSET = -0.1
LANDSAT_C2_L2_SCALE = 0.0000275
LANDSAT_C2_L2_OFFSET = -0.2


def s2_decode(dn: float) -> float:
    return dn * S2_L2A_SCALE + S2_L2A_OFFSET


def landsat_decode(dn: float) -> float:
    return dn * LANDSAT_C2_L2_SCALE + LANDSAT_C2_L2_OFFSET


def db_to_linear(values_db) -> np.ndarray:
    return np.power(10.0, np.asarray(values_db, dtype=float) / 10.0)


def linear_to_db(value: float) -> float:
    return 10.0 * math.log10(float(value))


def power_mean_db(values_db) -> float:
    """Mean of dB values averaged in linear power, returned in dB."""
    return linear_to_db(float(np.mean(db_to_linear(values_db))))


def arithmetic_mean_db(values_db) -> float:
    return float(np.mean(np.asarray(values_db, dtype=float)))


def ndvi(red, nir):
    red = np.asarray(red, dtype=float)
    nir = np.asarray(nir, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (nir - red) / (nir + red)


def evi(blue, red, nir):
    blue = np.asarray(blue, dtype=float)
    red = np.asarray(red, dtype=float)
    nir = np.asarray(nir, dtype=float)
    return 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)


def savi(red, nir, l_factor: float = 0.5):
    red = np.asarray(red, dtype=float)
    nir = np.asarray(nir, dtype=float)
    return ((nir - red) / (nir + red + l_factor)) * (1.0 + l_factor)


def nbr(nir, swir2):
    nir = np.asarray(nir, dtype=float)
    swir2 = np.asarray(swir2, dtype=float)
    return (nir - swir2) / (nir + swir2)


def ndwi_mcfeeters(green, nir):
    green = np.asarray(green, dtype=float)
    nir = np.asarray(nir, dtype=float)
    return (green - nir) / (green + nir)


def mndwi(green, swir1):
    green = np.asarray(green, dtype=float)
    swir1 = np.asarray(swir1, dtype=float)
    return (green - swir1) / (green + swir1)


def ndwi_gao(nir, swir1):
    nir = np.asarray(nir, dtype=float)
    swir1 = np.asarray(swir1, dtype=float)
    return (nir - swir1) / (nir + swir1)


def relative_difference(observed: float, expected: float) -> float:
    if expected == 0:
        return float("inf")
    return abs(float(observed) - float(expected)) / abs(float(expected))
