"""LandlockBackend: the secondary native backend, for Linux (decisions/0001, 0010).

It confines the workload with four kernel mechanisms, none of which needs
root: bubblewrap's namespaces (user, PID, network, IPC, UTS) and filesystem
view, a Landlock ruleset applied by the launcher before the workload starts,
and a seccomp filter on socket families. All four are inherited by every
process the workload starts, and none can be removed from inside.

  prepare  render the GrantPlan to a profile in the run's private directory
  launch   start bubblewrap; the launcher inside confines itself, probes the
           confinement, and waits as the workload for the admit signal
  confirm  read the launcher's probe report, check the namespaces, no-new-
           privileges, and seccomp from outside, and only then admit
  wait     wait for the workload to exit
  stop     stop the PID namespace's init, which ends every process in it,
           then verify that no process is left in that namespace
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from agent_in_a_box.contracts import (
    BackendCapabilities, ContainedProcess, ContainmentReport, DoctorReport, GrantPlan,
    LaunchRefused, PreparedProfile, ProbeResult, RunSpec, TeardownReport, WorkloadSpec,
)
from agent_in_a_box.supervisor.backends.landlock import doctor, seccomp, syscalls
from agent_in_a_box.supervisor.backends.landlock.inspect import (
    namespace_checks, namespace_members, workload_checks,
)
from agent_in_a_box.supervisor.backends.landlock.profile import (
    PROFILE_FORMAT, PROXY_SOCKET_DIR, bwrap_arguments, render,
)
from agent_in_a_box.supervisor.backends.landlock.relay import HostRelay

LAUNCHER = "agent_in_a_box.supervisor.backends.landlock.launcher"
CONFIRM_TIMEOUT_S = 30.0


@dataclass
class Sandbox:
    """What the backend tracks for one running sandbox. Not a contract record."""

    bwrap: subprocess.Popen
    relay: HostRelay
    report_pipe: int
    init_pid: int
    pid_namespace: int


def read_json(descriptor: int, timeout_s: float) -> dict | None:
    """Read one JSON document from a pipe; None if none arrives within `timeout_s`.

    The writer may keep the pipe open afterwards (bubblewrap holds its copies
    until it exits), so this stops at the end of the document, not at EOF.
    """
    data = b""
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([descriptor], [], [], deadline - time.monotonic())
            if not ready:
                return None
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return None
            data += chunk
            with contextlib.suppress(ValueError):
                return json.loads(data)
        return None
    finally:
        os.close(descriptor)


class LandlockBackend:
    name = "landlock"

    def __init__(self) -> None:
        self._sandboxes: dict[int, Sandbox] = {}

    def capabilities(self) -> BackendCapabilities:
        abi = syscalls.abi_version() if sys.platform == "linux" else 0
        return BackendCapabilities(
            profile_format=PROFILE_FORMAT,
            separate_read_write_grants=True,
            controls_truncate=True,
            pid_isolation=True,
            network_mechanism="namespace",
            notes=(
                f"Landlock ABI {abi} on this host.",
                "Truncate is refused outside write grants by read-only mounts on every ABI; "
                "Landlock itself governs truncate from ABI 3.",
                "Landlock does not govern file metadata: a mounted path can be looked up "
                "without a grant. Paths that are not mounted do not exist in the sandbox.",
                "A read grant on one directory lets the workload list the directories beneath "
                "it too: Landlock rules always apply to a path and everything beneath it.",
                "Executing a program requires reading it under Landlock, so an execute grant "
                "also lets the workload read that program's bytes.",
                "The proxy is reached through a Unix socket mounted into the sandbox; the "
                "sandbox's loopback is its own and reaches nothing else.",
                "A PID namespace holds the workload's processes; stopping it ends all of them.",
            ),
        )

    def doctor(self) -> DoctorReport:
        checks = doctor.checks()
        ok = all(check.ok for check in checks)
        return DoctorReport("landlock", checks, native_execution=ok)

    def prepare(self, plan: GrantPlan, run: RunSpec) -> PreparedProfile:
        text = render(plan)
        path = Path(run.private) / "landlock-profile.json"
        path.write_text(text)
        return PreparedProfile(
            backend="landlock", profile_format=PROFILE_FORMAT, profile_path=str(path),
            profile_sha256=hashlib.sha256(text.encode()).hexdigest(),
            disclosed=(
                f"Linux baseline: {len(json.loads(text)['mounts'])} mounts and Landlock rules, "
                "each with its reason (os_baseline.py)",
                f"{len(plan.runtime)} runtime grants and {len(plan.task)} task grants",
            ),
        )

    def launch(self, prepared: PreparedProfile, workload: WorkloadSpec) -> ContainedProcess:
        if prepared.backend != "landlock" or prepared.profile_path is None:
            raise LaunchRefused("profile was prepared by another backend")
        bwrap = shutil.which("bwrap")
        machine = seccomp.supported_machine()
        if bwrap is None or machine is None:
            raise LaunchRefused("bubblewrap or a supported seccomp architecture is missing")
        profile = json.loads(Path(prepared.profile_path).read_text())
        relay = HostRelay(profile["proxy"]["port"])

        seccomp_read, seccomp_write = os.pipe()
        os.write(seccomp_write, bytes.fromhex(profile["seccomp"]["programs"][machine]))
        os.close(seccomp_write)
        info_read, info_write = os.pipe()
        report_read, report_write = os.pipe()
        profile_fd = os.open(prepared.profile_path, os.O_RDONLY)
        passed = (seccomp_read, info_write, report_write, profile_fd)

        argv = [bwrap, *bwrap_arguments(profile),
                "--ro-bind", relay.directory, PROXY_SOCKET_DIR, "--chdir", workload.cwd,
                "--info-fd", str(info_write), "--seccomp", str(seccomp_read), "--",
                workload.argv[0], "-m", LAUNCHER, "--profile-fd", str(profile_fd),
                "--report-fd", str(report_write), "--", *workload.argv]
        with open(workload.stdout_path, "wb") as out, open(workload.stderr_path, "wb") as err:
            process = subprocess.Popen(argv, env=dict(workload.env), stdin=subprocess.PIPE,
                                       stdout=out, stderr=err, pass_fds=passed,
                                       start_new_session=True)
        for descriptor in passed:
            os.close(descriptor)

        info = read_json(info_read, CONFIRM_TIMEOUT_S)
        if info is None:
            process.kill()
            process.wait()
            relay.close()
            raise LaunchRefused("bubblewrap did not start the sandbox; see the run's stderr")
        self._sandboxes[process.pid] = Sandbox(process, relay, report_read, info["child-pid"],
                                               info["pid-namespace"])
        return ContainedProcess(workload.run_id, process.pid, "landlock", time.time())

    def confirm(self, process: ContainedProcess) -> ContainmentReport:
        """Admit the workload only if the inside probes and the outside checks all pass."""
        sandbox = self._sandboxes[process.pid]
        report = read_json(sandbox.report_pipe, CONFIRM_TIMEOUT_S)
        if report is None:
            report = {"ok": False, "error": "the launcher sent no report"}
        probes = [ProbeResult(probe["name"], probe["expected"], probe["observed"],
                              probe["passed"]) for probe in report.get("probes", [])]
        if "error" in report:
            probes.append(ProbeResult("launcher confined itself", "ok", report["error"], False))
        probes += namespace_checks(sandbox.init_pid)
        probes += workload_checks(sandbox.init_pid)
        contained = report.get("ok", False) and all(probe.passed for probe in probes)
        notes = [f"Landlock ABI {report.get('landlock', {}).get('abi')}"]
        if contained:
            assert sandbox.bwrap.stdin is not None
            sandbox.bwrap.stdin.write(b"admit\n")
            sandbox.bwrap.stdin.close()
        return ContainmentReport("landlock", contained=contained, admit=contained,
                                 probes=tuple(probes), notes=tuple(notes))

    def wait(self, process: ContainedProcess, deadline_s: float) -> int | None:
        try:
            return self._sandboxes[process.pid].bwrap.wait(timeout=max(deadline_s, 0))
        except subprocess.TimeoutExpired:
            return None

    def stop(self, process: ContainedProcess) -> TeardownReport:
        """End the PID namespace by stopping its init, then look for anything left in it."""
        sandbox = self._sandboxes.pop(process.pid)
        members = namespace_members(sandbox.pid_namespace)
        if sandbox.bwrap.poll() is None:
            for pid in (sandbox.init_pid, sandbox.bwrap.pid):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
        sandbox.bwrap.wait()
        survivors = namespace_members(sandbox.pid_namespace)
        for _ in range(20):  # give the kernel a moment to reap the namespace
            if not survivors:
                break
            time.sleep(0.05)
            survivors = namespace_members(sandbox.pid_namespace)
        sandbox.relay.close()
        return TeardownReport(
            exit_status=sandbox.bwrap.returncode,
            stopped=tuple(sorted(set(members) - set(survivors))),
            survivors=tuple(survivors),
            verified=not survivors,
            limits=("every process the workload starts stays in its PID namespace; when the "
                    "namespace's init stops, the kernel stops all of them",),
        )
