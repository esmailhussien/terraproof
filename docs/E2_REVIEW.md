# Phase 6 E2 development review

E2 completed on 2026-10-27 from main `93f9fd5`: four candidates, 12 development
tasks, one pair per task, 96 runs. No confirmation outputs were used. Original
reports and recordings are preserved in the maintainer archive; the plan's
confirmation protocol and frozen acceptance counts are unchanged.

| Candidate | Accepted with | Accepted without | MCP calls with | Skill reads |
|---|---:|---:|---:|---:|
| OpenCode GLM 5.3 Flash | 12/12 | 11/12 | 58 | 0 |
| OpenCode DeepSeek 4.1 Flash | 11/12 | 12/12 | 66 | 0 |
| Antigravity Gemini 3.8 Flash High | 10/12 | 11/12 | 56 | 15 |
| GPT-4o API | 6/12 | 5/12 | 48 | 0 |

Each candidate delivered Terraproof calls in all with-runs except Gemini, which
made MCP calls in 11/12. Subscription baseline acceptance is near ceiling on this
development sample. This does not predict the held-out confirmation population;
E4's prespecified screen, not this table, determines headroom there. All four
exploratory task-level sign-flip p-values are 1.0; no lift is established.

The reports show no infrastructure/preflight errors; the execution log records
no timeouts. GPT-4o API spend was $2.145869: with $1.867275, without $0.278594.
Other candidates used subscription quota, not zero economic cost. GPT-4o's paired
outcomes were two with-only acceptances and one without-only acceptance. Costs
and outcomes reflect each host's configured loop, including API completion review.

## Three issues found before E3

1. **Evaluator exposure.** One DeepSeek and two Gemini with-runs read harness/oracle
   sources. Their artifacts passed before contamination but remain rejected in the
   official counts. A separate product Python was on the agent PATH while MCP was
   registered with the harness interpreter. Source inspection confirms that exposed
   configuration route; its use in every historical run is not reconstructed.
2. **Completion is not artifact acceptance.** Seven GPT-4o with-runs ended with
   `output verification unresolved`. Three nevertheless passed the independent
   artifact oracle: `hr-landcover-shifted-grid`, `hr-modis-ndvi-scaled` and
   `hr-sar-boxcar-db`. Sanitized recordings do not retain the full MCP arguments
   and replies needed to identify their precise unresolved context. Do not claim
   seven failed scientific repairs or silently rewrite acceptance to host status.
3. **Coverage remains material.** All six rejected GPT-4o with-artifacts passed the
   final scoring invocation's checks and contract but failed its independent oracle.
   This does not establish that no intermediate call found an error. It shows that
   final production-check acceptance alone was insufficient in those invocations.

## This offline corrective batch

- Explicit `--mcp-python` registers isolated `-I -m terraproof.mcp`. The real lift
  driver passes the candidate product interpreter through project preparation and
  native overrides. Native/API preflight admits the actual MCP argv only when it
  matches the with-interpreter, contains no evaluator and matches the checkout's
  production code/assets. A changed product requires a fresh candidate wheel.
- A no-model local install proof found a second route: stale evaluator modules
  left in a reused `build_lib` could enter a wheel even with package exclusion.
  This occurred in a new local candidate, not the archived E2 product runtime.
  The product builder now removes only the bounded private build outputs; a
  source-output guard prevents accidental source deletion. Fresh/dirty-build
  packaging checks remain necessary alongside interpreter admission.
- No registered server is started when its interpreter admission fails. Defaults
  for ordinary user installation remain compatible; the stricter gate is for real
  study hosts. No new host or model call is part of this correction.
- API completion reports now retain fixed unresolved check labels and a digest of
  the context for future diagnosis. They do not persist data, arbitrary arguments
  or paths, and do not loosen existing failure/recheck rules. Historical missing
  trace evidence cannot be recovered by adding logging later.
- Optional [verification contracts](VERIFICATION_CONTRACTS.md) expose required,
  executed and missing checks with source/context binding and diagnostics.
  Unsigned evidence bundles bind those reports to recorded artifacts. No repair,
  source-data mutation or scientific certification is performed.

This fixes the visible interpreter route, not native filesystem permissions.
Product-only packaging cannot prove that another interpreter or the grading
checkout elsewhere on the host is unreadable. Native runs retain that threat
model limitation; do not claim filesystem containment from this change.

E2 is an exploratory development result. Select/freeze one primary configuration
at E3 only after the corrected development setup is ready, then follow E4–E6
without product tuning against confirmation results. Any further model calls
require the separately approved exact run count. Skills remain unmeasured/frozen.
