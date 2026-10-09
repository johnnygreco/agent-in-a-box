"""Linux-only checks of each confinement mechanism, run natively (PLAN.md, M1-L).

The shared conformance suite shows outcomes; many of its "blocked" probes
are stopped because the path is not in the sandbox's view. These tests aim
at each mechanism separately: Landlock on paths that are mounted,
read-only mounts for truncate, the network namespace for IPv6, UDP,
alternate loopback, and abstract sockets, the seccomp filter, and the PID
namespace. Expectations are authored from PLAN.md's native boundary list
and ADR 0010, not from observed output.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid

import pytest

from agent_in_a_box.contracts import plain
from agent_in_a_box.experiments import scenario
from agent_in_a_box.policy import schema
from tests.native.required import native_runtime_or_skip

pytestmark = [pytest.mark.native,
              pytest.mark.skipif(sys.platform != "linux", reason="Linux-only checks")]


@pytest.fixture
def runtime(tmp_path):
    return native_runtime_or_skip("landlock", tmp_path / "runs")


def events(record, kind):
    return [plain(event.payload) for event in record.events if event.kind == kind]


def run_bash(runtime, command, **tokens):
    """Run one bash command as the workload; return (record, observation).

    @DIRECT_PORT@ becomes the fixture's own port, and @NAME@ the value of `name=`.
    """
    def build(route):
        text = command.replace("@DIRECT_PORT@", str(route.port))
        for key, value in tokens.items():
            text = text.replace(f"@{key.upper()}@", str(value))
        return {"name": "bash", "arguments": {"command": text}}

    record = scenario.run(runtime, schema.load_variant("P0"), probe=build, deadline_s=30)
    assert record.status == "completed" and record.enforcement == "landlock"
    return record, events(record, "agent.observation")[0]["data"]["observation"]


def run_python(runtime, code, **tokens):
    """Run a child Python program; it prints one JSON object of results."""
    command = "python3 -c " + "'" + code.replace("'", "'\"'\"'") + "'"
    record, observation = run_bash(runtime, command, **tokens)
    return record, json.loads(observation["output"].strip().splitlines()[-1])


def test_mounted_but_ungranted_files_are_denied_by_landlock(runtime):
    _, observation = run_bash(runtime, "head -c 1 /usr/bin/id; echo; /usr/bin/id")
    assert observation["detail"]["exit_status"] != 0
    assert observation["output"].count("Permission denied") == 2  # read, then execute


def test_write_only_grant_cannot_be_read_back(runtime):
    _, observation = run_bash(runtime, "echo note > results/note && cat results/note")
    assert observation["detail"]["exit_status"] != 0
    assert "Permission denied" in observation["output"]


def test_read_only_grant_cannot_be_written_or_truncated(runtime):
    code = """
import json, os
results = {}
for name, attempt in (("append", lambda: open("measurements.csv", "a").write("x")),
                      ("truncate", lambda: os.truncate("measurements.csv", 0))):
    try:
        attempt(); results[name] = "allowed"
    except OSError as error:
        results[name] = error.strerror
results["size"] = os.path.getsize("measurements.csv")
print(json.dumps(results))
"""
    _, results = run_python(runtime, code)
    assert results["append"] != "allowed" and results["truncate"] != "allowed"
    assert results["size"] > 0


def test_symlinks_and_renames_cannot_reach_protected_state(runtime):
    code = """
import json, os
results = {}
os.symlink("../../private/policy.cedar", "results/link")
try:
    open("results/link").read(); results["through_symlink"] = "allowed"
except OSError as error:
    results["through_symlink"] = error.strerror
try:
    os.rename("results", "elsewhere"); results["move_write_root"] = "allowed"
except OSError as error:
    results["move_write_root"] = error.strerror
print(json.dumps(results))
"""
    _, results = run_python(runtime, code)
    assert results["through_symlink"] == "No such file or directory"
    assert results["move_write_root"] != "allowed"


def test_network_paths_other_than_the_proxy_are_unreachable(runtime):
    name = f"agent-in-a-box-test-{uuid.uuid4().hex}"
    host_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    host_listener.bind("\0" + name)  # an abstract socket in the host's network namespace
    host_listener.listen(1)
    code = """
import json, socket
attempts = {
    "ipv4 direct to fixture": (socket.AF_INET, socket.SOCK_STREAM, ("127.0.0.1", @DIRECT_PORT@)),
    "ipv6 loopback": (socket.AF_INET6, socket.SOCK_STREAM, ("::1", @DIRECT_PORT@)),
    "alternate loopback": (socket.AF_INET, socket.SOCK_STREAM, ("127.0.0.2", @DIRECT_PORT@)),
    "outside address": (socket.AF_INET, socket.SOCK_STREAM, ("192.0.2.1", 80)),
    "udp outside": (socket.AF_INET, socket.SOCK_DGRAM, ("192.0.2.1", 53)),
    "host abstract socket": (socket.AF_UNIX, socket.SOCK_STREAM, "\\0@NAME@"),
}
results = {}
for label, (family, kind, address) in attempts.items():
    connection = socket.socket(family, kind)
    connection.settimeout(3)
    try:
        if kind == socket.SOCK_DGRAM:
            connection.sendto(b"x", address)
        else:
            connection.connect(address)
        results[label] = "connected"
    except OSError as error:
        results[label] = error.strerror or type(error).__name__
print(json.dumps(results))
"""
    try:
        _, results = run_python(runtime, code, name=name)
    finally:
        host_listener.close()
    assert "connected" not in results.values(), results


def test_seccomp_refuses_other_socket_families_and_io_uring(runtime):
    code = """
import ctypes, json, socket
results = {}
for label, family in (("vsock", 40), ("packet", 17), ("netlink", 16)):
    try:
        socket.socket(family, socket.SOCK_RAW if family != 40 else socket.SOCK_STREAM).close()
        results[label] = "allowed"
    except OSError as error:
        results[label] = error.errno
libc = ctypes.CDLL(None, use_errno=True)
results["io_uring_setup"] = -libc.syscall(425, 1, None) * ctypes.get_errno()
print(json.dumps(results))
"""
    _, results = run_python(runtime, code)
    assert results == {"vsock": 97, "packet": 97, "netlink": 97, "io_uring_setup": 38}


def test_host_processes_are_invisible_from_the_pid_namespace(runtime):
    _, observation = run_bash(runtime, "kill -0 @HOST_PID@", host_pid=os.getpid())
    assert observation["detail"]["exit_status"] != 0
    assert "No such process" in observation["output"]


def test_a_detached_new_session_is_still_stopped(runtime):
    code = """
import json, os, time
if os.fork() == 0:
    os.setsid()
    quiet = os.open("/dev/null", os.O_RDWR)
    for descriptor in (0, 1, 2):
        os.dup2(quiet, descriptor)
    time.sleep(600)
    os._exit(0)
print(json.dumps({"detached": True}))
"""
    record, results = run_python(runtime, code)
    stopped = events(record, "workload_stopped")[0]
    assert results == {"detached": True}
    assert stopped["verified"] and stopped["survivors"] == []


def test_a_failed_self_probe_refuses_the_run_and_leaves_nothing_running(runtime, monkeypatch):
    from agent_in_a_box.supervisor.backends.landlock import profile

    honest = profile.self_probes

    def with_an_impossible_probe(plan):
        return [*honest(plan), {"name": "impossible", "op": "listdir", "target": "/",
                                "expect": "allowed"}]

    monkeypatch.setattr(profile, "self_probes", with_an_impossible_probe)
    record = scenario.run(runtime, schema.load_variant("P0"), deadline_s=30)
    assert record.status == "refused" and "containment" in record.refusal
    containment = events(record, "containment")[0]
    assert (containment["contained"], containment["admit"]) == (False, False)
    assert not any(event.kind.startswith("agent.") for event in record.events)
    stopped = events(record, "workload_stopped")[0]
    assert stopped["verified"] and stopped["survivors"] == []
