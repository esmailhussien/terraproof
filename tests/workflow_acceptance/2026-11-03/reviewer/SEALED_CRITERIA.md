# Prior assessment criteria

This document is sealed by procedural agreement until every public-case outcome has been retained and hashed. Its companion `SEALED_CRITERIA.json` is the normative detailed procedure. No product implementation, old report, other chat, native image/header or outcome was consulted in writing it. This is an independent reviewer role, not human domain expertise or cryptographic blinding.

## Decision rule

Each challenge must first be established from the original native sources using a separate rasterio/numpy/pyproj oracle. A plausible place name, catalog cloud value, product diagnostic, or rejection alone cannot establish exercise. Missing evidence and environmental limits mean unexercised. A contradiction of an established applicable contract means failed. All three distinct targets must be exercised and pass for overall acceptance. Report variant-level and condition-level results so an unexercised unknown-uncertainty branch is visible.

## Independent native calculation

Verify hashes, identity, native headers and MTL before analysis. Build the requested native-centre mask without resampling. Acquired support is QA availability with bit0 unset, independently of temperature validity. Base usability additionally requires native temperature and requested QA acceptance. Full coverage requires every requested centre acquired and inside grid; denominator for minimum quality is acquired support. Use original uint16 ST_B10, original QA_PIXEL and signed int16 ST_QA. Decode Celsius with native MTL scale/offset, then subtract273.15. With a cutoff, partition base candidates into valid uncertainty at/below limit, unknown uncertainty, and known above limit. Without a cutoff, unknown uncertainty does not remove otherwise usable temperature. Never divide uncertainty by sqrt(sample count). Compare available counts exactly and temperature to1e-4C; all detailed tolerances and boundary handling are in JSON.

## Fixed cases

R1 targets a genuinely useful full-AOI output. It is exercised only when native acquisition is complete and the no-cutoff valid fraction meets0.90. It must resolve, admit engineering approval, and complete with independent numerical agreement. If natural data fail support, correct refusal is compatible behavior but the useful-output target is unexercised.

R2 targets missing acquisition in a native contained10x10 corner. Establish exactly100 requested in-grid centres and at least1 missing QA acquisition. Both no-cutoff and2K variants must then be unresolved before approval. An empty acquired denominator cannot permit output. If all100 are acquired, the padding hypothesis is unexercised; do not move it.

R3 targets explicit uncertainty insufficiency in a paired control. Establish full acquisition and no-cutoff quality at least0.75, then independently establish that0.005K leaves less than0.75 usable/acquired. Baseline must admit correctly; strict variant must refuse approval. Independently compare distinct unknown/above-limit counts and only claim unknown handling exercised when unknown candidates actually occur. The tiny cutoff is a deliberate diagnostic requirement, not a scientific recommendation.

## Confounders and claims

Maintain original frozen attempts. Source mismatch, grid mismatch, incomplete downloads, authentication/network/budget limits and unsupported serialization need explicit attribution. Pixel cloud/temperature gaps cannot be inferred from metadata. Do not repair a test by changing item, region, date, mask, minimum or threshold. No temporal aggregation or scientific certification follows from any result. Engineering approval remains self-declared and numerical checks-passed remains an engineering grade.
