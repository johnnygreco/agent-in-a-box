"""NoEnforcementBackend: a test double. It is not a sandbox.

It runs the workload as an ordinary subprocess so the whole pipeline (proxy,
Cedar, harness, evidence) can be exercised on any platform. Nothing limits
what the workload does on this host. Every record it produces says
`enforcement: none`, its doctor never enables native execution, and
composition.py selects it only under explicit test or developer
configuration, never as a fallback. It shares nothing with the native
backends except the protocol.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time

from agent_in_a_box.contracts import (
    BackendCapabilities, ContainedProcess, ContainmentReport, DoctorCheck, DoctorReport, GrantPlan,
    LaunchRefused, PreparedProfile, RunSpec, TeardownReport, WorkloadSpec,
)

NOTE = "test backend: no kernel profile is installed; the workload runs uncontained"


class NoEnforcementBackend:
    name = "none"

    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen[bytes]] = {}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            profile_format="none",
            separate_read_write_grants=False,
            controls_truncate=False,
            pid_isolation=False,
            network_mechanism="none",
            notes=(NOTE, "Bypass attempts are not blocked; only the proxy's checks apply."),
        )

    def doctor(self) -> DoctorReport:
        check = DoctorCheck("test backend", True, "explicitly selected; native execution disabled")
        return DoctorReport("none", (check,), native_execution=False)

    def prepare(self, plan: GrantPlan, run: RunSpec) -> PreparedProfile:
        return PreparedProfile(
            backend="none", profile_format="none", profile_path=None, profile_sha256=None,
            disclosed=(NOTE, f"{len(plan.task)} task grants derived but not installed"),
        )

    def launch(self, prepared: PreparedProfile, workload: WorkloadSpec) -> ContainedProcess:
        if prepared.backend != "none":
            raise LaunchRefused("profile was prepared by another backend")
        with open(workload.stdout_path, "wb") as out, open(workload.stderr_path, "wb") as err:
            child = subprocess.Popen(
                list(workload.argv), env=dict(workload.env), cwd=workload.cwd,
                stdin=subprocess.PIPE, stdout=out, stderr=err, close_fds=True,
                start_new_session=True,
            )
        self._processes[child.pid] = child
        return ContainedProcess(workload.run_id, child.pid, "none", time.time())

    def confirm(self, process: ContainedProcess) -> ContainmentReport:
        """No probes can confirm anything here. Release the gate and say so."""
        child = self._processes[process.pid]
        assert child.stdin is not None
        child.stdin.write(b"admit\n")
        child.stdin.close()
        return ContainmentReport("none", contained=False, admit=True, probes=(), notes=(NOTE,))

    def wait(self, process: ContainedProcess, deadline_s: float) -> int | None:
        """Wait up to `deadline_s` for the workload to exit; None if it has not."""
        try:
            return self._processes[process.pid].wait(timeout=max(deadline_s, 0))
        except subprocess.TimeoutExpired:
            return None

    def stop(self, process: ContainedProcess) -> TeardownReport:
        """Signal the workload's process group: SIGTERM, then SIGKILL if needed.

        Membership comes from `pgrep -g`, which works the same on macOS and
        Linux. Probing a group with `killpg(group, 0)` does not: macOS answers
        "operation not permitted" where Linux answers "no such process".
        """
        workload = self._processes.pop(process.pid)
        signalled: set[int] = set()
        for signal_number in (signal.SIGTERM, signal.SIGKILL):
            members = _group_members(process.pid)
            if not members:
                break
            signalled.update(members)
            _signal_group(process.pid, members, signal_number)
            time.sleep(0.2)
        workload.wait()
        survivors = _group_members(process.pid)
        for _ in range(10):  # give the kernel a moment to reap what was signalled
            if not survivors:
                break
            time.sleep(0.1)
            survivors = _group_members(process.pid)
        limits = ["the test backend tracks one process group; a descendant that starts "
                  "its own session is not tracked"]
        if shutil.which("pgrep") is None:
            limits.append("pgrep is not installed, so survivors could not be enumerated")
        return TeardownReport(
            exit_status=workload.returncode,
            stopped=tuple(sorted(signalled - set(survivors))),
            survivors=tuple(survivors),
            verified=not survivors and shutil.which("pgrep") is not None,
            limits=tuple(limits),
        )


def _group_members(group_id: int) -> list[int]:
    """PIDs still in the process group, oldest first. Empty when pgrep is missing."""
    pgrep = shutil.which("pgrep")
    if pgrep is None:
        return []
    listing = subprocess.run([pgrep, "-g", str(group_id)], capture_output=True, text=True)
    return sorted(int(pid) for pid in listing.stdout.split())


def _signal_group(group_id: int, members: list[int], signal_number: int) -> None:
    """Signal the whole group; if the kernel refuses that, signal each member."""
    try:
        os.killpg(group_id, signal_number)
    except ProcessLookupError:
        return
    except PermissionError:
        for pid in members:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal_number)
