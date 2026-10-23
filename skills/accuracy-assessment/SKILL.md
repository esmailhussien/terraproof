---
name: accuracy-assessment
description: Design and analyze a statistically defensible accuracy assessment for a classified or change map, covering probability sampling stratified by map class, the response design, area-weighted confusion matrices, overall/user's/producer's accuracy with confidence intervals, and stratified area-adjusted class areas; use whenever a land-cover or change map's accuracy or class areas will be reported.
license: MIT
---

# Accuracy assessment and area estimation

## Report estimates, not pixel counts

A map's class pixel counts are not an unbiased estimate of class area: every
omission and commission error shifts area between classes, and rare classes (such
as change) are often affected most. Good practice is to estimate area from the
**reference classification of a probability sample**, using the map to stratify,
and to report confidence intervals for accuracy and area [S1, S2].

Worked example (counts from Olofsson et al. 2014, Table 8, recomputed with the
estimator in [the reference](references/stratified-estimator.md)): the map shows
18,000 ha of deforestation; the stratified estimate is **21,158 ha ± 6,158 ha**
(95 % CI). Reporting 18,000 ha as "the area" hides both the bias and the
uncertainty.

The workflow has three parts, each documented in the report: sampling design,
response design and analysis [S1, S3, S4]. Use
[statistical analysis](../statistical-analysis/SKILL.md) for general statistics and
[time series and change](../time-series-and-change/SKILL.md) for producing change
maps. Shared rules: [engineering](../../instructions/engineering.md),
[simplicity](../../instructions/simplicity.md), [security](../../instructions/security.md).

## Sampling design: stratified random by map class

Use a **probability sampling design**: every unit in the population has a known,
non-zero inclusion probability [S1, S4]. Stratified random sampling with the
final map classes as strata is the common choice for change and rare classes,
because it guarantees samples in small strata [S1, S2].

- Draw the sample from the **final** map that will be reported, within the
  exact reporting region. Record every stratum's mapped area `A_m,i` (in an
  equal-area CRS or with true per-pixel areas; see
  [CRS and units](../crs-and-units/SKILL.md)).
- Do **not** reuse training, calibration or hand-picked "clear" points; they are
  not a probability sample and give unknown bias.
- Allocation: equal allocation favours user's accuracy of rare classes;
  proportional allocation usually gives smaller standard errors for overall and
  producer's accuracy. A compromise with a minimum per stratum is suggested [S2].
  FAO cites a minimum of 20 to 100 samples per stratum (Congalton and Green) [S2].
- Size the sample from a target standard error and anticipated user's
  accuracies, following the sample-size section of Olofsson et al. (after Cochran
  1977) [S1, S2]. No sample size makes a biased (non-probability) sample valid.
- Keep the sampling seed, frame, strata raster and unit list, so the sample can
  be regenerated.

If the strata are **not** the map classes being assessed (e.g. a stratification
from an older map), the estimators below do not apply directly; use the estimator
for strata that differ from map classes [S5].

## Response design: how reference labels are decided

The response design specifies the spatial assessment unit (pixel, block or
polygon), the reference data sources, the labeling protocol and the definition of
agreement [S1, S2, S4].

- The reference classification must be more accurate than the map: a better
  source (finer resolution, field data) or a more careful process (expert visual
  interpretation of the same imagery) [S2].
- Reference data should be temporally coincident with the map (for change: cover
  both dates); otherwise area estimates refer to the reference date [S2].
- Define the minimum mapping unit, rules for mixed units and the agreement rule
  before labeling [S2]. Interpret blind to the map label where feasible.
- Record interpreter, source image/date and confidence per unit; evaluate
  reference-label variability rather than assuming the reference is perfect [S1].

## Confusion matrix in proportion of area

Rows are map classes (strata) `i`, columns reference classes `j`, `n_ij` sample
counts, `n_i·` the row total, `W_i = A_m,i / A_tot` the mapped area proportion.
When strata are the map classes (simple random, systematic or stratified random
sampling), estimate each cell as a proportion of area [S1, S2]:

```text
p_ij = W_i * n_ij / n_i·
```

Report this estimated matrix (in area proportions), not only raw counts [S1].
Raw-count matrices from a stratified sample over-represent rare strata and give
biased overall and producer's accuracies if used directly.

## Overall, user's and producer's accuracy

From the area-proportion matrix [S1, S2]:

```text
overall accuracy      O   = Σ_j p_jj
user's accuracy       U_i = p_ii / p_i·      (= n_ii / n_i· under this design)
producer's accuracy   P_j = p_jj / p_·j
commission error      = 1 - U_i
omission error        = 1 - P_j
```

User's accuracy answers "if the map says class i, how often is it i?"; producer's
accuracy answers "of the true class j area, how much is mapped as j?" [S2].
Report all three with confidence intervals (variances in
[the reference](references/stratified-estimator.md)) [S1].

Kappa is not recommended as an accuracy measure [S2, S6]; do not report it as a
substitute for these estimates.

## Area-adjusted estimates with confidence intervals

Estimate the area of reference class `k` from the column of the area-proportion
matrix, with the stratified-estimator standard error [S1, S2]:

```text
p_·k      = Σ_i W_i * n_ik / n_i·
A_k       = A_tot * p_·k
SE(p_·k)  = sqrt( Σ_i W_i² * (n_ik / n_i·) * (1 - n_ik / n_i·) / (n_i· - 1) )
SE(A_k)   = A_tot * SE(p_·k)
95 % CI   = A_k ± 1.96 * SE(A_k)
```

`A_tot` and `A_m,i` must be true areas (or pixel counts in an equal-area grid
multiplied by pixel area). The 1.96 factor is the large-sample normal
approximation used in the guidance [S2]; with very small strata or proportions
near 0 or 1, state that the interval is approximate.
For a random-start systematic sample, these variance formulas are approximate
and typically overestimate uncertainty [S1]. They assume pixel units with hard
map/reference labels; polygon units or mixed labels require other estimators.

A stratum needs at least 2 sample units (division by `n_i· - 1`); a class with
no reference sample has an estimated area of zero with an uninformative SE, which
is a design gap to report, not evidence of absence.

## Compute the estimates

Full, tested Python for accuracy, variances and areas, with the worked example
above, is in [references/stratified-estimator.md](references/stratified-estimator.md).
Minimal area estimate:

```python
import numpy as np

def stratified_area(counts, mapped_area, z=1.96):
    n = np.asarray(counts, dtype=float)        # rows: map strata, cols: reference
    a_map = np.asarray(mapped_area, dtype=float)
    n_i = n.sum(axis=1)
    if np.any(n_i < 2):
        raise ValueError("every stratum needs at least 2 sample units")
    w = a_map / a_map.sum()
    frac = n / n_i[:, None]
    area = a_map.sum() * (w[:, None] * frac).sum(axis=0)
    se = a_map.sum() * np.sqrt((w[:, None] ** 2 * frac * (1 - frac)
                                / (n_i[:, None] - 1)).sum(axis=0))
    return area, z * se
```

Keep the counts matrix, `A_m,i` per stratum, CRS/area method and the code
version with the results so that the numbers can be recomputed.

## Report checklist

- Sampling design (strata, allocation, sample size rationale, seed) and the map
  version sampled.
- Response design (unit, sources and dates, labeling protocol, agreement rule,
  interpreter procedure) and any deviations from good practice [S1].
- Estimated error matrix in area proportions; overall, user's and producer's
  accuracy with 95 % CIs.
- Mapped area and stratified area estimate with 95 % CI per class; say which one
  any downstream number uses.
- Limitations: reference-label uncertainty, strata/class mismatch, missing
  strata.

## Verify with Terraproof

Existing checks help with the inputs, not with the statistics:

```bash
python -m terraproof check classified_map.tif --operation area
python -m terraproof check sample_points.gpkg
```

`crs.defined`, `crs.consistent` and `raster.nodata_declared` check map/sample
metadata; `geometry.valid`, `geometry.non_empty`, `geometry.type_consistent`
and `scope.record_count` check the sample file. With `--operation area`,
`crs.metric_operation` fails geographic/geocentric CRSs and passes projected
metre/foot CRSs; it does not confirm an equal-area projection.

```bash
python -m terraproof check classified_map.tif --accuracy-samples samples.json --class-areas areas.json --min-per-class 50 --estimates-requested
```

`samples.json` contains reference records with `map_class`, `ref_class` and
optional `stratum_weight`; `areas.json` maps each map class to its mapped area
in consistent units. `accuracy.sample_design` checks class coverage, counts and
declared weights. The default minimum of 50 per class is a configurable design
convention, not a precision guarantee. `accuracy.estimates` computes the
area-weighted matrix, accuracy estimates and approximate intervals, plus
area-adjusted class areas. It does not compare an external published report's
claims with those estimates.

**Not checked automatically:** whether the sample was truly probability-based,
whether reference labels are correct or temporally coincident, response-design
rules, and whether reported numbers are used correctly downstream. See
[verification](../verification/SKILL.md).

## Sources

- [S1 — Olofsson, P., Foody, G.M., Herold, M., Stehman, S.V., Woodcock, C.E., Wulder, M.A. (2014). Good practices for estimating area and assessing accuracy of land change. Remote Sensing of Environment 148:42–57](https://doi.org/10.1016/j.rse.2014.02.015): good-practice recommendations, stratified estimators for accuracy, area and their variances; Table 8 example counts.
- [S2 — FAO (2016). Map accuracy assessment and area estimation: a practical guide. NFMA Working Paper 46](https://www.fao.org/3/i5601e/i5601e.pdf): sampling/response/analysis steps, allocation trade-offs, 20–100 per stratum minimum, `p_ij = W_i n_ij / n_i·` when strata are map classes, accuracy definitions, CI as 1.96 × SE, area from reference column totals, kappa not recommended; references Olofsson et al. (2014) eqs. 5–7 and 10–11 for the variances.
- [S3 — Olofsson, P., Foody, G.M., Stehman, S.V., Woodcock, C.E. (2013). Making better use of accuracy data in land change studies. Remote Sensing of Environment 129:122–131](https://doi.org/10.1016/j.rse.2012.10.031): stratified estimation of accuracy and area.
- [S4 — Stehman, S.V., Czaplewski, R.L. (1998). Design and analysis for thematic map accuracy assessment: fundamental principles. Remote Sensing of Environment 64(3):331–344](https://doi.org/10.1016/S0034-4257(98)00010-8); [Stehman, S.V., Foody, G.M. (2019). Key issues in rigorous accuracy assessment of land cover products. Remote Sensing of Environment 231:111199](https://doi.org/10.1016/j.rse.2019.05.018): sampling, response and analysis components.
- [S5 — Stehman, S.V. (2014). Estimating area and map accuracy for stratified random sampling when the strata are different from the map classes. International Journal of Remote Sensing 35(13):4923–4939](https://doi.org/10.1080/01431161.2014.930207).
- [S6 — Pontius, R.G., Millones, M. (2011). Death to Kappa. International Journal of Remote Sensing 32(15):4407–4429](https://doi.org/10.1080/01431161.2011.552923).
- [mapaccuracy R package, `olofsson()` (H. Costa)](https://github.com/cran/mapaccuracy/blob/master/R/olofsson.R): independent implementation used to cross-check the formulas and the Table 8 counts.
