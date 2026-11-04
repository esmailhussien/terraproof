# Independent assessment of the frozen public acceptance cases

**Decision: success for all three prior written main targets and all five fixed workflow variants.** The original native source conditions were independently established. No substantive product failure or infrastructure limitation was found in these runs. This is bounded numerical and engineering acceptance, with the unexercised conditions below. It is not field validation or science certification.

| Target/variant | Independently established native support | Assessment |
|---|---|---|
| R1-full, Phoenix |18,318 requested/acquired;18,309 usable; valid/acquired99.950868% >=90% |Success: no-cutoff workflow correctly admitted and delivered. |
| R2-corner-default, Cape Town scene |Exactly100 requested centres in the native grid;0 acquired;0 usable |Success: unresolved before approval, explicit QA acquisition refusal. |
| R2-corner-cutoff, same corner |Same100 centres and0 acquired; explicit2K does not create support |Success: unresolved before approval. |
| R3-baseline, Brisbane |19,416 requested/acquired;17,105 usable;88.097445% >=75% |Success: no-cutoff workflow correctly admitted and delivered. |
| R3-strict, same Brisbane AOI |17,105 known-above-limit exclusions;0 unknown exclusions;0 usable/19,416 acquired at0.005K |Success: uncertainty insufficiency correctly unresolved before approval. |

## Integrity and method

I verified SHA256 and byte lengths for all119 frozen inventory records, the10 members of the original reviewer manifest, the original public files and both sealed criteria files. The outcome-freeze hash is `779cc90c9aaf816cf5e5c41e4fc79202cae36d8656fa82a934604241ad6b67ea`; the prior criteria JSON hash is `1b5111cdafdaf194b9f7399eff0d86945383c6ffffc6bcb7507fc35677f0b980`. No criteria, tolerances, product files, original native files or frozen outcomes were changed. The12 native files total323,321,401 bytes, below536,870,912; the retained transfer ledger records0 retries. Byte identity establishes retained-file consistency, not cryptographic authenticity of an unauthenticated upstream/download process.

The standalone `independent_checker.py` imports no Terraproof code. It does not use implementer `raw-evidence.json` values as an oracle. It reads original native MTL groups, ST_B10, QA_PIXEL and signed int16 ST_QA. Metadata eligibility, ranking, fixed asset URLs, selected IDs and date/cloud/AOI requirements agree independently. Native grids, dtypes, fills, MTL calibration and exact request/provenance links agree. QA_PIXEL has no TIFF nodata tag in these files; bit0 still explicitly identifies fill.

AOI membership was recomputed at native centres using projected dense boundaries and checked with two methods (Shapely point membership and rasterio rasterization with `all_touched=False`). Geographic-edge refinement from0.0001 to0.00005 degree changed no membership. The diagnostic corner was separately checked against native rows0..9/columns0..9; the retained AOI freeze identifies the geometry and declares no preceding corner pixel read. The public pre-execution clarification permits unchanged acquisition to preflight the separate search AOI. This review cannot independently reconstruct every past in-memory read; the native derivation, retained freeze, fixed window and recorded protocol are consistent.

The final checker completed346 explicit comparisons with0 failures. These are reproducible evidence comparisons, not a claimed independent test-suite size or model benchmark. Integer counts were exact; admission fractions used tolerance1e-12, Celsius comparisons1e-4C and full-precision uncertainty summaries1e-8K. Float32 uncertainty rasters were compared exactly with the representable float32 form of independently decoded signed DN*0.01; their encoding roundoff was not treated as a changed scientific threshold. No cutoff membership tolerance was added.

## Delivered numbers and declarations

Phoenix's independent mean is57.920363527799466C, range49.67682512..63.23611046C. Mean pixel product uncertainty is1.660028401332678K, range1.58..3.24K. The delivered Celsius raster's maximum source-comparison error is1.90675780232e-06C.

Brisbane's independent baseline mean is32.033100197769095C, range24.16130582..37.43347748C. Mean pixel product uncertainty is3.907287927506577K, range2.53..6.04K. The delivered Celsius raster's maximum source-comparison error is1.90612303186e-06C. No unknown uncertainty occurs among its17,105 base-usable candidates. Therefore all17,105 fail the explicit0.005K requirement for known-above-limit reasons, and the usable/acquired fraction is0. The cutoff was a fixed admission diagnostic, not a recommended scientific accuracy requirement.

Both delivered AOI masks, acquisition masks, validity masks, temperature values and uncertainty values agree with the independent source calculation. Min/max/mean, known/missing uncertainty counts, percentiles and fractions above2/3/4K agree. I also checked every valid source cell in each full native decoded raster:40,563,785 Phoenix cells and39,872,406 Brisbane cells, with correct masks and Celsius decode within the prior tolerance.

The original native corner has QA_PIXEL raw1, ST_B10 raw0 and ST_QA signed-9999 at all100 requested centres. These are missing acquisition/temperature observations, not0C observations or known zero-uncertainty values. With no base-usable candidates its uncertainty-summary missing count and cutoff missing-exclusion count are both0; counting raw corner-9999 as an otherwise usable unknown candidate would be incorrect. Both plans explicitly report the0/100 acquisition problem and stop before approval/output.

The two admitted runs have machine grade `checks-passed`, status `verified` and `physical_accuracy_validated=false`. Their approval records explicitly declare `engineering-self-review` and `identity_authenticated=false`; run provenance embeds the exact retained intent, facts, approval, output hashes and verification. HTML/SVG say VERIFIED (numerical), declare the review type, disclose no scientific certification and identify a single acquisition rather than a period estimate. The uncertainty summaries retain pixel product magnitudes; neither an uncertainty-of-mean claim nor sqrt(n) reduction is supported. The three unresolved variants have no approval record or delivered output. No approval bypass was attempted, and none is claimed impossible.

## Corner boundary qualification

The ideal native10x10 footprint has area90,000m2. The inverse-projected retained polygon differs from its native edge by at most4.65661287308e-11pixel, within the prior1e-5pixel criterion. Independently measured area outside the native grid is9.76530524591e-08m2. All100 requested centres are inside the grid and outside-grid centre count is0.

The product additionally reports continuous outside-area fraction1.75004699621e-09 (about1.75004699621e-07%) and `grid_extent_covers_aoi=false`, while its grid-centre fraction is1.0. This is a small boundary/projection diagnostic sensitivity, quantitatively distinct from missing native acquisition. It does not alter centre counts, source QA, the correct refusal or any output (none was produced). It means this run does not isolate a rejection path with the continuous-extent Boolean true. The preregistered target condition—missing QA acquisition among100 contained native centres—is nevertheless independently established and the plan explicitly states that failure. No conclusion that rejection depended exclusively on acquisition masking is drawn.

## Unexercised conditions and limits

- Unknown-uncertainty exclusion among otherwise base-usable candidates is **unexercised**. Both useful AOIs have0 such candidates; the missing-acquisition corner cannot substitute for this branch. Zero counters agree, but do not validate a positive unknown-exclusion example.
- Exact uncertainty-cutoff equality, a mixed kept/excluded cutoff population, explicit allow-partial behavior, out-of-grid requested centres and source-selection ties were not exercised. The supported discovery ranking is verified for the actual candidates, not every possible tie or malformed source.
- A refusal before approval was observed through the supported path. Authenticated review, security/tamper resistance and bypass resistance were not tested.
- No claim follows about absolute surface-temperature accuracy, air temperature, regional climate, monthly means, health risk, cloud-adjacency causes or a calibrated uncertainty of the AOI mean.

## Oracle implementation history and independence

The acceptance choices, targets, numerical tolerances and decision rules were written before native access and their hashes remain unchanged. The executable checker was written **after outcome freeze**, when the reviewer could inspect retained formats and reported statuses. This is AI-context role separation with prior criteria, not independent human expertise, cryptographic blinding or a fully blinded prewritten executable oracle. No product implementation/history or active Phase11 files were inspected. No external model API was called; public catalog metadata was the only network source used by this reviewer during selection.

The first checker/evidence are preserved as `independent_checker.v1.py` and `independent-evidence.v1.json`. They recorded10 false comparison failures caused by checker interpretation assumptions: flattening repeated MTL L1/L2 PROCESSING_LEVEL keys; requiring QA_PIXEL TIFF nodata1 instead of its actual absent nodata tag and bit0 semantics; and requiring the literal machine grade in HTML/SVG rather than their explicit VERIFIED (numerical) disclosure. The corrected checker parses MTL groups, reads actual nodata metadata and checks the displayed numerical/review declarations while still requiring machine `checks-passed`. The raw native mask/calibration formulas and all prior tolerances were unchanged. Initial findings were retained rather than overwritten as product failures. The final provenance checks were then added and executed.

`ASSESSMENT.json` contains machine-readable decisions and artifact hashes. `independent-evidence.json` contains exact counts, raw native histograms, every final comparison and the quantified boundary observation. The checker, first checker/evidence and final run log are retained. Original outcomes remain frozen.
