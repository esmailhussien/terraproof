"""Container command policy is fail-closed; live Docker proof is a separate opt-in."""
import pytest

from test_api_agent import driver  # makes tests/ importable without a live provider
import contained_runtime as contained

IMAGE = "sha256:" + "a"*64
NAME = "study-box-" + "b"*32


def metadata():
    return {"Config": {"User": "65534:65534"}, "HostConfig": {
        "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
        "PidMode": "", "IpcMode": "private", "UTSMode": "", "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"], "Memory": 1024**3, "PidsLimit": 256,
        "NanoCpus": 2*10**9, "Tmpfs": {"/tmp": "rw", "/home/agent": "rw"}},
        "Mounts": [{"Destination": "/workspace", "Type": "bind", "RW": True}]}


def test_container_command_exposes_only_the_active_project(tmp_path):
    argv = contained.create_command(IMAGE, tmp_path, ["python", "-c", "print('ok')"], NAME)
    assert argv.count("--mount") == 1
    assert argv[argv.index("--network")+1] == "none"
    assert argv[argv.index("--pull")+1] == "never"
    assert "--read-only" in argv and "--privileged" not in argv
    assert argv[-4:] == [IMAGE, "python", "-c", "print('ok')"]
    assert not any("docker.sock" in part or ".gemini" in part for part in argv)


@pytest.mark.parametrize("image,name", [("mutable:latest", NAME), (IMAGE, "someone-elses-container")])
def test_refuse_mutable_images_or_unowned_container_names(tmp_path, image, name):
    with pytest.raises(ValueError):
        contained.create_command(image, tmp_path, ["python"], name)


@pytest.mark.parametrize("change", ["network", "root", "privileged", "host-pid", "extra-mount", "socket", "caps", "writable-root"])
def test_attestation_rejects_escape_hatches(change):
    info = metadata()
    assert all(contained.attest(info).values())
    if change == "network": info["HostConfig"]["NetworkMode"] = "host"
    elif change == "root": info["Config"]["User"] = "0:0"
    elif change == "privileged": info["HostConfig"]["Privileged"] = True
    elif change == "host-pid": info["HostConfig"]["PidMode"] = "host"
    elif change in ("extra-mount", "socket"):
        info["Mounts"].append({"Destination": "/private" if change == "extra-mount" else "/var/run/docker.sock", "Type": "bind", "RW": True})
    elif change == "caps": info["HostConfig"]["CapDrop"] = []
    else: info["HostConfig"]["ReadonlyRootfs"] = False
    assert not all(contained.attest(info).values())


def test_command_cannot_inject_an_extra_bind_mount(tmp_path):
    project = tmp_path/"project,extra-option"
    project.mkdir()
    with pytest.raises(ValueError, match="invalid task"):
        contained.create_command(IMAGE, project, ["python"], NAME)
