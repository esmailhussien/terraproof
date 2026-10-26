"""Explicit Docker boundary for local task processes; no native-host fallback.

Only the active task is mounted. No host home, credentials, evaluator, Docker
socket or network is exposed. This module never starts a model on its own.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import threading
import uuid

import agent_runtime

BASE = re.compile(r"python@sha256:[a-f0-9]{64}")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")


def stage_context(destination, base_image, agent_archive, sha512):
    """Export an allowlisted build context, excluding the grading checkout."""
    if not BASE.fullmatch(base_image):
        raise ValueError("pin an official Python image by repository digest")
    archive = Path(agent_archive)
    if hashlib.sha512(archive.read_bytes()).hexdigest() != sha512:
        raise ValueError("agent archive does not match the reviewed official manifest")
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    files = agent_runtime.expected_files()
    for relative, digest in files.items():
        source = (agent_runtime.ROOT / relative[5:] if relative.startswith("data/")
                  else agent_runtime.ROOT / "src/terraproof" / relative)
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("production source changed while staging")
        target = destination / "runtime/terraproof" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    # Extract only the named regular executable, never arbitrary archive paths.
    with tarfile.open(archive, "r:gz") as bundle:
        entry = bundle.getmember("antigravity")
        if not entry.isfile():
            raise ValueError("agent payload is not a regular executable")
        with bundle.extractfile(entry) as source, (destination/"agy").open("xb") as target:
            shutil.copyfileobj(source, target)
    dockerfile = f'''FROM {base_image}
RUN python -c "import sys; assert sys.version_info[:2] == (3,12)"
RUN pip install --no-cache-dir numpy==2.5.4 rasterio==1.5.2 pyogrio==0.13.0 pyproj==3.8.0 shapely==2.2.0 mcp==2.3.0
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
COPY runtime/ /usr/local/lib/python3.12/site-packages/
COPY --chmod=0555 agy /usr/local/bin/agy
ENV HOME=/home/agent PYTHONNOUSERSITE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8
WORKDIR /workspace
USER 65534:65534
CMD ["python"]
'''
    (destination/"Dockerfile").write_text(dockerfile, encoding="utf-8", newline="\n")
    manifest = {"schema": "terraproof.contained-context/1", "base_image": base_image,
        "production_files": files, "agent_archive_sha512": sha512,
        "agent_binary_sha256": hashlib.sha256((destination/"agy").read_bytes()).hexdigest(),
        "dockerfile_sha256": hashlib.sha256(dockerfile.encode()).hexdigest()}
    (destination/"context.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return manifest


def create_command(image, project, command, name):
    if not IMAGE.fullmatch(image) or not re.fullmatch(r"study-box-[a-f0-9]{32}", name):
        raise ValueError("use an immutable local image ID and an owned container name")
    original = Path(project).absolute()
    for path in (original, *original.parents):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("task directories must not contain links or junctions")
    project = original.resolve()
    if not project.is_dir() or "," in str(project):
        raise ValueError("invalid task directory")
    for path in (project, *project.parents, *project.rglob("*")):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("task directories must not contain links or junctions")
    if not command or not all(isinstance(v, str) and v and "\0" not in v for v in command):
        raise ValueError("supply an explicit contained program argv")
    uid = os.getuid() if hasattr(os, "getuid") and os.getuid() else 65534
    return ["docker", "create", "--interactive", "--name", name, "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
        "--pids-limit", "256", "--memory", "1g", "--cpus", "2", "--user", f"{uid}:{uid}",
        "--mount", f"type=bind,source={project},target=/workspace", "--workdir", "/workspace",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
        "--tmpfs", "/home/agent:rw,nosuid,nodev,size=128m,mode=1777", image, *command]


def attest(inspected):
    config, host = inspected["Config"], inspected["HostConfig"]
    mounts = inspected.get("Mounts", [])
    return {"network_none": host.get("NetworkMode") == "none", "readonly_root": host.get("ReadonlyRootfs") is True,
        "not_privileged": host.get("Privileged") is False,
        "host_namespaces_absent": all(host.get(key) != "host" for key in ("PidMode", "IpcMode", "UTSMode")),
        "nonroot": str(config.get("User", "")).split(":")[0] not in ("", "0", "root"),
        "capabilities_dropped": "ALL" in [s.upper() for s in host.get("CapDrop") or []],
        "no_new_privileges": any(v in ("no-new-privileges", "no-new-privileges=true") for v in host.get("SecurityOpt") or []),
        "only_active_task_mounted": len(mounts) == 1 and mounts[0].get("Destination") == "/workspace"
            and mounts[0].get("Type") == "bind" and mounts[0].get("RW") is True,
        "resource_limits": host.get("Memory", 0) > 0 and host.get("PidsLimit", 0) > 0
            and host.get("NanoCpus", 0) > 0,
        "private_temporary_home": set(host.get("Tmpfs", {})) == {"/tmp", "/home/agent"}}


def run(image, project, command, *, timeout=120, stdin=None):
    name = "study-box-" + uuid.uuid4().hex
    argv = create_command(image, project, command, name)
    created = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    if created.returncode:
        raise ValueError("Docker refused contained runtime creation")
    try:
        metadata = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, check=True, timeout=30)
        checks = attest(json.loads(metadata.stdout)[0])
        if not all(checks.values()):
            raise ValueError("container boundary attestation failed")
        with subprocess.Popen(["docker", "start", "--attach", "--interactive", name], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            captured = {"stdout": bytearray(), "stderr": bytearray()}
            truncated = [False]
            def drain(stream, key):
                while chunk := stream.read(65536):
                    room = max(0, 8*1024*1024-len(captured[key]))
                    captured[key].extend(chunk[:room])
                    truncated[0] |= len(chunk) > room
            readers = [threading.Thread(target=drain, args=(getattr(process, key), key), daemon=True)
                       for key in captured]
            for reader in readers:
                reader.start()
            def feed():
                try:
                    if stdin:
                        process.stdin.write(stdin.encode("utf-8"))
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()
            writer = threading.Thread(target=feed, daemon=True)
            writer.start()
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(["docker", "kill", name], capture_output=True, timeout=30, check=False)
                process.kill()
                process.wait(timeout=30)
            for reader in readers:
                reader.join(timeout=30)
            writer.join(timeout=30)
            if any(reader.is_alive() for reader in readers) or writer.is_alive():
                raise ValueError("contained output did not terminate")
            return {"exit_code": process.returncode, "timed_out": timed_out, "truncated": truncated[0],
                    "boundary": checks, **{key: bytes(value).decode("utf-8", errors="replace") for key, value in captured.items()}}
    finally:
        # Only the freshly generated, attested container is owned by this invocation.
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 900:
        parser.error("timeout must be positive and at most 900 seconds")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        result = run(args.image, args.project, command, timeout=args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Contained runtime refused: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["exit_code"] or result["timed_out"] or result["truncated"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
