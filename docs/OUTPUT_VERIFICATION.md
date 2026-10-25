# Required output verification for API agents

The source-checkout API lift harness supports an explicit, opt-in output policy
with `--verification-plan FILE`. This is an engineering completion gate for the
OpenAI/Groq adapters in `tests/`, not a new production checker or an installed
`terraproof` CLI option. Existing runs without the flag keep their previous
completion behaviour and report `verification_status: "unverified"`.

## Declare the policy

A plan must cover exactly every declared deliverable of every selected task.
Each group names saved output paths, required check IDs from
[`routing/checks.json`](../routing/checks.json), and explicit `run_checks`
parameters. Paths use forward slashes relative to the run project, under
`inputs/` or `outputs/`; group targets must be under `outputs/`.

The included [NDVI example](../tests/verification_plans/ndvi-source-contract.json)
covers the original `indices-ndvi-physical-inputs` task's single output:

```json
{
  "schema": "terraproof.required-output-verification/1",
  "tasks": {
    "indices-ndvi-physical-inputs": [
      {
        "paths": ["outputs/ndvi.tif"],
        "checks": ["rs.index_formula"],
        "parameters": {
          "index_formula": "ndvi",
          "nir": "inputs/nir_dn.tif",
          "red": "inputs/red_dn.tif"
        }
      }
    ]
  }
}
```

This example does not cover other tasks, additional audit JSON, or every
scientific requirement. Authors must choose meaningful checks and source roles;
the host does not infer them. See [source-aware NDVI checking](INDEX_FORMULA.md).
Historical task specs, checker invocations and independent oracles are unchanged.

Plans are limited to 64 KiB, loaded once before inference, and fingerprinted with
SHA-256. Duplicate JSON keys/groups, unknown check IDs, escaping paths, incomplete
output coverage and invalid schemas are refused. The active MCP `run_checks`
schema must accept all arguments before a provider call. Plan-only mode validates
the document and coverage; preflight also checks current data and the MCP schema.

## Plan without inference

From a source checkout with Python dependencies and the `mcp` extra installed,
use the following **PowerShell** example. The prices `1` below are illustrative
planning inputs, not current provider prices. Replace them with your verified
prices before approving any paid run.

```powershell
python tests/agent_lift.py --agent-host openai --api-model gpt-4o --runs 1 --task indices-ndvi-physical-inputs --verification-plan tests/verification_plans/ndvi-source-contract.json --usd-per-million-input 1 --usd-per-million-output 1
```

Without `--approve-model-calls`, this only prints the plan: no provider request,
agent, API key or server startup is needed. The plan includes the policy hash,
`applies_to: "with-only"`, a preflight command and an approval command. Rendered
commands quote filenames for PowerShell on Windows and POSIX shells elsewhere.

Run the printed preflight command with a suitable dependency-only
`--agent-python-without` interpreter and configured provider environment. Preflight
starts local probes/MCP, checks key presence and isolation, but sends no model
request. A paid experiment still requires its own frozen protocol, prices,
budget and explicit invocation approval; this feature does not authorize one.

## What makes evidence current

The treatment model receives the required calls and check IDs before the task
prompt. Only actual matching MCP responses can satisfy them; no check or repair
is run automatically. Calls must use the same path group and parameter context
as declared (except report language and equivalent relative/absolute paths).
Adding explicit defaults not present in the plan creates a different context.

For each matching call, the host hashes all files under both data trees before
and after execution. Reported input hashes/byte sizes, source parameters, check
IDs and output scope must agree. The current bytes must still match when the
model requests completion and when the result is assembled. Content, file
membership and companions such as `.msk` files matter; restoring modification
times does not preserve an old pass. Even an unrelated output edit requires a
new check. Inputs must retain their original content and membership throughout
the run; rechecking altered sources cannot certify the original task.

Missing/unreadable data, symlinks, junctions, directory aliases, special files,
paths outside the data trees or an exhausted hashing deadline cannot certify.
Raster dependencies reported by GDAL must also be inside the captured trees.
Hashing reads the full trees and consumes the existing wall-time allowance; this
conservative profile can be expensive for large datasets.

## Status and completion

| Status | Meaning for declared requirements | Strict host completion |
| --- | --- | --- |
| `verified` | Every required check passed on current data | Allowed, subject to existing limits and observed-failure guard |
| `review-required` | Current required evidence contains `fail` or `warn` | Blocked |
| `unverified` | Missing, not-run, invalid, stale or unavailable evidence | Blocked |

When requirements have mixed states, `unverified` takes precedence, followed by
`review-required`. Counts retain the individual check states. A matching failed
attempt replaces an earlier pass. At most two completion-review prompts ask for
the required checks or a blocker report. They share the original call, token,
USD and time limits; there is no new session or reset. Caps, refusals and
transport failures retain their usual outcomes. The v0.7.1 observed-failure guard
also remains active: passing a declared subset cannot erase other unresolved
output failures.

Turn metadata includes `verification_status`, `verification_policy_applied`,
`verification_plan_sha256` and `required_verification`. The latter contains
zero-based output indexes in declared task order, required-check counts,
aggregate state counts and an opaque current snapshot hash. It does not save
raw filenames, source arguments, evidence prose or exception text. These
restrictions concern saved verification metadata; tool results remain visible
to the model during execution as before.

## Experimental and trust limits

The policy applies only to the **with-Terraproof** condition. The without
condition gets no policy instructions or MCP tools and is labelled `unverified`.
This changes the treatment and must be frozen explicitly for any future study;
the label is not a comparable acceptance score across conditions. Independent
artifact grading remains the primary acceptance measure.

`verified` means only that the configured trusted local MCP server returned
passing declared checks tied to the observed data. It does not establish that
the plan covers all task requirements, that production checks catch every
scientific error, or that agents reliably repair failures. This is not a sandbox
or filesystem lock: concurrent or adversarial out-of-band writes, transient
changes between snapshots, external dependencies of other formats and changes
after the final snapshot are outside that guarantee. Unsupported dependency
layouts should remain unverified rather than be advertised as certified.

Offline fake-provider regressions exercise the gate and real local MCP checks.
They establish no new paid experiment, general agent lift or published release.
