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
        """Signal the workload's process group: SIGTERM, then SIGKILL if needed."""
        workload = self._processes.pop(process.pid)
        signalled = False
        for signal_number in (signal.SIGTERM, signal.SIGKILL):
            if not _group_exists(process.pid):
                break
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal_number)
                signalled = True
            time.sleep(0.2)
        workload.wait()
        group_empty = not _group_exists(process.pid)
        return TeardownReport(
            exit_status=workload.returncode,
            stopped=(process.pid,) if signalled else (),
            survivors=() if group_empty else (process.pid,),
            verified=group_empty,
            limits=("the test backend tracks one process group; a descendant that starts "
                    "its own session is not tracked",),
        )


def _group_exists(group_id: int) -> bool:
    """True if any process is still in the process group."""
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    return True
