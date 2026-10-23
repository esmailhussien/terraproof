# Stratified estimator: formulas and tested code

Reference for [accuracy assessment](../SKILL.md). Applies when the sampling strata
are the map classes and units were selected by stratified random sampling [S1,
S2]. Equal-probability simple random or random-start systematic samples can use
the point estimates as poststratified estimators. For systematic sampling the
variance formulas are approximations, typically overestimating uncertainty;
document that limitation [S1, sections 2.1.3 and 4.3–4.4]. The formulas assume
pixel units with hard map/reference labels, not polygon units or mixed labels.
For strata that differ from the map classes use Stehman (2014) instead [S3].

## Notation

| Symbol | Meaning |
|---|---|
| `i` | map class = stratum (row) |
| `j`, `k` | reference class (column) |
| `n_ij` | sample units in stratum `i` with reference class `j` |
| `n_i·` | sample size in stratum `i` |
| `A_m,i` (`N_i·`) | mapped area (or pixel count in an equal-area grid) of stratum `i` |
| `A_tot` | total mapped area, `Σ_i A_m,i` |
| `W_i` | `A_m,i / A_tot` |

## Estimators

Point estimates [S1, S2]:

```text
p_ij  = W_i * n_ij / n_i·
O     = Σ_j p_jj
U_i   = p_ii / p_i·
P_j   = p_jj / p_·j
p_·k  = Σ_i W_i * n_ik / n_i·
A_k   = A_tot * p_·k
```

Variances (Olofsson et al. 2014, eqs. 5–7 for accuracy and 10–11 for area, as
referenced by FAO 2016; cross-checked against the `mapaccuracy` implementation)
[S1, S2, S4]:

```text
V(O)     = Σ_i W_i² * U_i * (1 - U_i) / (n_i· - 1)
V(U_i)   = U_i * (1 - U_i) / (n_i· - 1)
V(P_j)   = (1 / N_·j²) * [ N_j·² * (1 - P_j)² * U_j * (1 - U_j) / (n_j· - 1)
                           + P_j² * Σ_{i≠j} N_i·² * (n_ij / n_i·) * (1 - n_ij / n_i·) / (n_i· - 1) ]
           with N_·j = Σ_i (N_i· / n_i·) * n_ij
SE(p_·k) = sqrt( Σ_i W_i² * (n_ik / n_i·) * (1 - n_ik / n_i·) / (n_i· - 1) )
SE(A_k)  = A_tot * SE(p_·k)
95 % CI  = estimate ± 1.96 * SE
```

## Python implementation

```python
import numpy as np

def stratified_estimates(counts, mapped_area, z=1.96):
    """counts[i, j]: sample units in map stratum i with reference class j.
    mapped_area[i]: mapped area of stratum i (strata == map classes)."""
    n = np.asarray(counts, dtype=float)
    a_map = np.asarray(mapped_area, dtype=float)
    n_i = n.sum(axis=1)
    if n.shape[0] != n.shape[1] or n.shape[0] != a_map.size:
        raise ValueError("square matrix with one mapped area per stratum required")
    if np.any(n_i < 2):
        raise ValueError("each stratum needs at least 2 sample units for a variance")
    a_tot = a_map.sum()
    w = a_map / a_tot                                  # W_i
    p = w[:, None] * n / n_i[:, None]                  # p_ij
    oa = np.trace(p)
    ua = np.diag(p) / p.sum(axis=1)
    pa = np.diag(p) / p.sum(axis=0)
    area_prop = p.sum(axis=0)                          # p_.k
    frac = n / n_i[:, None]                            # n_ij / n_i.
    se_prop = np.sqrt((w[:, None] ** 2 * frac * (1 - frac) / (n_i[:, None] - 1)).sum(axis=0))
    var_oa = np.sum(w ** 2 * ua * (1 - ua) / (n_i - 1))
    var_ua = ua * (1 - ua) / (n_i - 1)
    n_hat_j = (a_map[:, None] * n / n_i[:, None]).sum(axis=0)   # N_.j
    var_pa = np.empty(n.shape[0])
    for j in range(n.shape[0]):
        own = a_map[j] ** 2 * (1 - pa[j]) ** 2 * ua[j] * (1 - ua[j]) / (n_i[j] - 1)
        others = sum(a_map[i] ** 2 * frac[i, j] * (1 - frac[i, j]) / (n_i[i] - 1)
                     for i in range(n.shape[0]) if i != j)
        var_pa[j] = (own + pa[j] ** 2 * others) / n_hat_j[j] ** 2
    return {
        "overall": (oa, z * np.sqrt(var_oa)),
        "users": (ua, z * np.sqrt(var_ua)),
        "producers": (pa, z * np.sqrt(var_pa)),
        "area": (area_prop * a_tot, z * se_prop * a_tot),
        "mapped_area": a_map,
    }
```

A class with a zero column (no reference units) yields `P_j` = NaN (0/0); report
it as not estimable rather than replacing it with 0 or 1.

## Worked example (regression test)

Counts from Olofsson et al. (2014) Table 8 (as encoded in the `mapaccuracy`
documentation), classes deforestation, forest gain, stable forest, stable
non-forest; mapped pixel counts 200,000 / 150,000 / 3,200,000 / 6,450,000 of 30 m
(0.09 ha) [S1, S4]:

```python
counts = [[66, 0, 5, 4], [0, 55, 8, 12], [1, 0, 153, 11], [2, 1, 9, 313]]
pixels = np.array([200_000, 150_000, 3_200_000, 6_450_000])
r = stratified_estimates(counts, pixels * 0.09)
```

Output computed with the code above (rounded):

| Class | Mapped (ha) | Estimated (ha) ± 95 % CI | User's ± CI | Producer's ± CI |
|---|---|---|---|---|
| Deforestation | 18,000 | 21,158 ± 6,158 | 0.88 ± 0.07 | 0.75 ± 0.21 |
| Forest gain | 13,500 | 11,686 ± 3,756 | 0.73 ± 0.10 | 0.85 ± 0.25 |
| Stable forest | 288,000 | 285,770 ± 15,510 | 0.93 ± 0.04 | 0.93 ± 0.03 |
| Stable non-forest | 580,500 | 581,386 ± 16,282 | 0.96 ± 0.02 | 0.96 ± 0.02 |

Overall accuracy 0.947 ± 0.018. Use this table to test any reimplementation;
treat it as a computed value, not as a quotation of the paper.

## Sources

- [S1 — Olofsson et al. (2014), Remote Sensing of Environment 148:42–57](https://doi.org/10.1016/j.rse.2014.02.015).
- [S2 — FAO (2016), Map accuracy assessment and area estimation: a practical guide](https://www.fao.org/3/i5601e/i5601e.pdf).
- [S3 — Stehman (2014), International Journal of Remote Sensing 35(13):4923–4939](https://doi.org/10.1080/01431161.2014.930207).
- [S4 — mapaccuracy `olofsson()` source](https://github.com/cran/mapaccuracy/blob/master/R/olofsson.R).
