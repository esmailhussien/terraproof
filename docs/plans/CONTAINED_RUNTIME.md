# Offline process containment for study preparation

`tests/contained_runtime.py` runs an explicit local program in Docker. This is
an opt-in development harness, not an enabled backend of `tests/real_host_agent.py`
and not a claim that a native Windows agent has become contained.

The whole process tree must run in the container. Mounting only shell helpers
does not contain a host agent's other file-reading tools.

## Boundary

- One read/write bind mount: the **fresh active task only**, at `/workspace`.
  Never select the grading checkout, an archive or a parent containing secrets.
- No host home, credentials, private evaluator, Docker socket or host namespaces.
- No network, read-only root, nonroot user, all capabilities dropped,
  no-new-privileges, private temporary home and temporary directory.
- Explicit memory/CPU/process limits; bounded output and execution timeout.
- Immutable image ID, inspect/attest before start, failure stops execution.
  Only a generated `study-box-<uuid>` container is removed afterward.
- Links/junctions in the task directory or its ancestors are refused.

The host coordinator owns image selection, task staging, inspect metadata and
private outputs. The container is not protection against a malicious host,
Docker daemon or kernel exploit. A project directory must already be free of
private data: a boundary cannot hide data intentionally placed in its mount.
No ACL, ownership, integrity-label or application security setting is changed.

## Build and run

Call `stage_context(new_directory, base_image, agent_archive, sha512)` from
`tests/contained_runtime.py`. It exports only the production allowlist from
`tests/agent_runtime.py`, including upstream attribution/licenses; no evaluator.
Supply an official `python@sha256:...` digest and a separately downloaded official
Linux Antigravity archive with its manifest SHA-512. Only its named regular
executable is extracted; no installer is executed. Build using Docker, then
resolve the resulting local image's immutable `sha256:...` ID.

```bash
python tests/contained_runtime.py --image sha256:IMAGE_ID --project /fresh/task -- python -I -c "print('contained')"
python tests/probe_contained_runtime.py --image sha256:IMAGE_ID --work /new/proof
```

The first example needs a real 64-hex image ID and a task directory. The proof
creates its own fresh task and outside-mount canary. Its report checks read/write
access to task files, seven attempted private paths on Windows, evaluator import
absence, blocked root writes/network, Antigravity version startup and the six
production MCP tools over actual subprocess stdio. It never calls a model.

Image builds need network access for dependencies. Execution is offline. The
base digest, production hashes, agent archive/binary hashes and Dockerfile hash
are recorded in `context.json`; dependency versions and system packages should
also be archived with the final image ID. Builds include a Debian system package
and transitive Python dependencies resolved at build time, so the Dockerfile
alone is not a fully locked future rebuild. The immutable tested image is the
admitted artifact. Production changes require a new image and proof.

## Measured readiness and remaining gate

On 2026-10-26 the local Linux Docker proof passed with Antigravity 1.4.7 and
production MCP. The first image exposed a missing `libexpat.so.1` dependency;
the corrected build installs `libexpat1`. The failed proof remains separate from
the successful one. No account data was inspected/copied and no model ran.

This offline image has no Google sign-in and deliberately has no network. A live
study still needs a separately reviewed authenticated runtime/network policy,
with a supported sign-in flow, condition-matched dependencies, a captured real
workspace init fixture and integration into the paired-run coordinator. Do not
mount host credential stores or fall back to a native uncontained agent.
Keep real-agent performance claims and release decisions separate from this
offline boundary evidence.
