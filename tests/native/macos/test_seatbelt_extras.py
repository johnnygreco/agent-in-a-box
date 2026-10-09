"""macOS-only checks of the Seatbelt boundary, run natively (PLAN.md, Milestone 1).

The shared conformance suite shows outcomes. These tests aim at the edges
PLAN.md's native boundary list names: execute without read, write-only and
read-only grants, symlink, hard link, and replacement cases, every network
path other than the proxy (IPv4, IPv6, UDP, alternate loopback, Unix
sockets, DNS), other processes' information and signals, widening the
profile from inside, and detached descendants at teardown. Expectations are
authored from PLAN.md and decisions/0014, not from observed output. Seatbelt
refuses with EPERM, which Python and the shell report as "Operation not
permitted".
"""

from __future__ import annotations

import os
import socket
import sys
import time
import uuid

import pytest

from agent_in_a_box.experiments import scenario
from agent_in_a_box.policy import schema
from tests.native.diagnostics import seatbelt_denials
from tests.native.required import native_runtime_or_skip
from tests.native.workload import events, run_bash, run_python

pytestmark = [pytest.mark.native,
              pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only checks")]

REFUSED = "Operation not permitted"


@pytest.fixture
def runtime(tmp_path):
    return native_runtime_or_skip("seatbelt", tmp_path / "runs")


def test_bash_and_child_python_run_under_the_profile(runtime):
    code = """
import ctypes, json, os
check = ctypes.CDLL(None).sandbox_check
check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
print(json.dumps({"confined": check(os.getpid(), None, 0)}))
"""
    _, results = run_python(runtime, code)
    assert results == {"confined": 1}


def test_an_execute_grant_does_not_let_the_program_be_read(runtime):
    _, observation = run_bash(runtime, "/bin/cat /dev/null && echo ran; head -c 1 /bin/cat")
    assert observation["output"].startswith("ran")
    assert REFUSED in observation["output"]


def test_write_only_grant_cannot_be_read_back(runtime):
    _, observation = run_bash(runtime, "echo note > results/note && cat results/note")
    assert observation["detail"]["exit_status"] != 0
    assert REFUSED in observation["output"]


def test_read_only_grant_cannot_be_written_truncated_or_replaced(runtime):
    code = """
import json, os
results = {}
open("results/new.csv", "w").write("replacement")
for name, attempt in (("append", lambda: open("measurements.csv", "a").write("x")),
                      ("truncate", lambda: os.truncate("measurements.csv", 0)),
                      ("replace", lambda: os.rename("results/new.csv", "measurements.csv")),
                      ("remove", lambda: os.unlink("measurements.csv"))):
    try:
        attempt(); results[name] = "allowed"
    except OSError as error:
        results[name] = error.strerror
results["size"] = os.path.getsize("measurements.csv")
print(json.dumps(results))
"""
    _, results = run_python(runtime, code)
    assert {name: results[name] for name in ("append", "truncate", "replace", "remove")} == {
        "append": REFUSED, "truncate": REFUSED, "replace": REFUSED, "remove": REFUSED}
    assert results["size"] > 0


def test_symlinks_hard_links_and_renames_cannot_reach_protected_state(runtime):
    code = """
import json, os
results = {}
def attempt(name, action):
    try:
        action(); results[name] = "allowed"
    except OSError as error:
        results[name] = error.strerror
attempt("move the write root", lambda: os.rename("results", "results-moved"))
attempt("remove the write root", lambda: os.rmdir("results"))
attempt("list protected state", lambda: os.listdir("../private"))
attempt("hard link protected state into the write grant",
        lambda: os.link("../private/policy.cedar", "results/hard"))
os.symlink("../../private/policy.cedar", "results/link")
attempt("read through a symlink", lambda: open("results/link").read())
print(json.dumps(results))
"""
    _, results = run_python(runtime, code)
    assert set(results.values()) == {REFUSED}, results


def test_network_paths_other_than_the_proxy_are_refused(runtime):
    path = f"/private/tmp/aib-{uuid.uuid4().hex[:12]}.sock"
    host_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    host_listener.bind(path)
    host_listener.listen(1)
    code = """
import json, os, socket
proxy_port = int(os.environ["HTTP_PROXY"].rsplit(":", 1)[1])
attempts = {
    "ipv4 direct to fixture": (socket.AF_INET, socket.SOCK_STREAM, ("127.0.0.1", @DIRECT_PORT@)),
    "ipv6 loopback to fixture": (socket.AF_INET6, socket.SOCK_STREAM, ("::1", @DIRECT_PORT@)),
    "ipv6 twin of the proxy port": (socket.AF_INET6, socket.SOCK_STREAM, ("::1", proxy_port)),
    "alternate loopback": (socket.AF_INET, socket.SOCK_STREAM, ("127.0.0.2", proxy_port)),
    "outside address": (socket.AF_INET, socket.SOCK_STREAM, ("192.0.2.1", 80)),
    "udp to the proxy port": (socket.AF_INET, socket.SOCK_DGRAM, ("127.0.0.1", proxy_port)),
    "udp outside": (socket.AF_INET, socket.SOCK_DGRAM, ("192.0.2.1", 53)),
    "host unix socket": (socket.AF_UNIX, socket.SOCK_STREAM, "@NAME@"),
    "system log socket": (socket.AF_UNIX, socket.SOCK_STREAM, "/private/var/run/syslog"),
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
try:
    socket.getaddrinfo("example.com", 80)
    results["dns"] = "resolved"
except OSError as error:
    results["dns"] = "failed"
print(json.dumps(results))
"""
    try:
        _, results = run_python(runtime, code, name=path)
    finally:
        host_listener.close()
        os.unlink(path)
    # The profile allows the IPv6 twin of the proxy's port (Seatbelt's localhost is both
    # 127.0.0.1 and ::1). The backend holds it bound and not listening (decisions/0014),
    # so the connection reaches nothing: refused, or on the runner, unanswered.
    assert results.pop("ipv6 twin of the proxy port") in ("Connection refused", "TimeoutError")
    assert results.pop("dns") == "failed"
    assert set(results.values()) == {REFUSED}, results


def test_other_processes_cannot_be_inspected_or_signalled(runtime):
    code = """
import ctypes, json, os
libc = ctypes.CDLL(None, use_errno=True)
libc.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
libc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
results = {}
size = ctypes.c_size_t(0)
mib = (ctypes.c_int * 3)(1, 49, @HOST_PID@)  # kern.procargs2: arguments and environment
answer = libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0)
results["read the supervisor's environment"] = os.strerror(ctypes.get_errno()) if answer else "read"
answer = libc.proc_listallpids(None, 0)
results["list processes"] = os.strerror(ctypes.get_errno()) if answer <= 0 else "listed"
try:
    os.kill(@HOST_PID@, 0); results["signal the supervisor"] = "allowed"
except OSError as error:
    results["signal the supervisor"] = error.strerror
try:
    os.kill(1, 0); results["signal launchd"] = "allowed"
except OSError as error:
    results["signal launchd"] = error.strerror
print(json.dumps(results))
"""
    _, results = run_python(runtime, code, host_pid=os.getpid())
    assert set(results.values()) == {REFUSED}, results


def test_the_profile_cannot_be_widened_from_inside(runtime):
    code = """
import ctypes, json, os
lib = ctypes.CDLL(None)
lib.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
error = ctypes.c_char_p()
answer = lib.sandbox_init(b"(version 1)(allow default)", 0, ctypes.byref(error))
results = {"sandbox_init": answer}
try:
    os.listdir("/Library"); results["after"] = "allowed"
except OSError as failure:
    results["after"] = failure.strerror
print(json.dumps(results))
"""
    _, results = run_python(runtime, code)
    assert results["sandbox_init"] != 0
    assert results["after"] == REFUSED


def test_a_detached_new_session_is_found_and_stopped(runtime):
    code = """
import json, os, time
read, write = os.pipe()
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        quiet = os.open("/dev/null", os.O_RDWR)
        os.write(write, str(os.getpid()).encode())
        for descriptor in (0, 1, 2):
            os.dup2(quiet, descriptor)
        time.sleep(600)
    os._exit(0)
print(json.dumps({"detached": int(os.read(read, 32))}))
"""
    record, results = run_python(runtime, code)
    detached = results["detached"]
    stopped = events(record, "workload_stopped")[0]
    assert stopped["verified"] and stopped["survivors"] == []
    assert detached in stopped["stopped"]
    with pytest.raises(ProcessLookupError):
        for _ in range(50):
            os.kill(detached, 0)
            time.sleep(0.02)


def test_the_kernel_reports_what_it_refused(runtime, tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text("canary\n")
    since = time.time()
    _, observation = run_bash(runtime, f"cat {canary}")
    assert REFUSED in observation["output"]
    real = os.path.realpath(canary)
    for _ in range(20):  # the unified log can lag the kernel
        lines = seatbelt_denials(since)
        if any(f"deny(1) file-read-data {real}" in line for line in lines):
            break
        time.sleep(1)
    assert any(f"deny(1) file-read-data {real}" in line for line in lines), lines


def test_here_documents_fail_with_macos_bash(runtime):
    """A documented limit, not a goal: /bin/bash 3.2 writes them to /var/tmp."""
    _, observation = run_bash(runtime, "cat <<END\nhello\nEND")
    assert "cannot create temp file for here document" in observation["output"]


def test_a_failed_self_probe_refuses_the_run_and_leaves_nothing_running(runtime, monkeypatch):
    import agent_in_a_box.supervisor.backends.seatbelt as backend

    honest = backend.self_probes

    def with_an_impossible_probe(plan, nonce):
        return [*honest(plan, nonce), {"name": "impossible", "op": "listdir",
                                       "target": "/Library", "expect": "allowed"}]

    monkeypatch.setattr(backend, "self_probes", with_an_impossible_probe)
    record = scenario.run(runtime, schema.load_variant("P0"), deadline_s=30)
    assert record.status == "refused" and "containment" in record.refusal
    containment = events(record, "containment")[0]
    assert (containment["contained"], containment["admit"]) == (False, False)
    assert not any(event.kind.startswith("agent.") for event in record.events)
    stopped = events(record, "workload_stopped")[0]
    assert stopped["verified"] and stopped["survivors"] == []
