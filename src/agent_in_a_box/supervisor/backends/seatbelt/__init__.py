"""SeatbeltBackend: the primary native backend, macOS Seatbelt (decisions/0014).

The workload is confined by one kernel mechanism: a Seatbelt profile that
the launcher applies to itself with sandbox_init before any workload code
runs. The profile is inherited by every process the workload starts, and
nothing inside can remove or widen it.

  prepare  render the GrantPlan to an SBPL profile in the run's private
           directory, with the self-probes and the run's marker
  launch   start the launcher, which confines itself, probes the
           confinement, and waits as the workload for the admit signal
  confirm  read the launcher's report, ask the kernel from outside whether
           the workload is confined by this run's profile, and only then admit
  wait     wait for the workload to exit
  stop     find every process that carries this run's profile, freeze them,
           kill them, and verify that none is left (accounting.py)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import secrets
import select
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from agent_in_a_box.contracts import (
    BackendCapabilities, ContainedProcess, ContainmentReport, DoctorReport, GrantPlan,
    LaunchRefused, PreparedProfile, ProbeResult, RunSpec, TeardownReport, WorkloadSpec,
)
from agent_in_a_box.supervisor.backends.seatbelt import accounting, doctor, sandbox
from agent_in_a_box.supervisor.backends.seatbelt.os_baseline import BASELINE
from agent_in_a_box.supervisor.backends.seatbelt.profile import (
    PROFILE_FORMAT, render, self_probes,
)

LAUNCHER = "agent_in_a_box.supervisor.backends.seatbelt.launcher"
LAUNCH_FILE = "seatbelt-launch.json"
CONFIRM_TIMEOUT_S = 30.0


@dataclass
class Sandbox:
    """What the backend tracks for one running sandbox. Not a contract record."""

    process: subprocess.Popen
    report_pipe: int
    marker: accounting.Marker
    profile_sha256: str
    protected: tuple[str, ...]
    stderr_path: str
    reservation: socket.socket


def read_json(descriptor: int, timeout_s: float) -> dict | None:
    """Read one JSON document from a pipe; None if none arrives within `timeout_s`."""
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


class SeatbeltBackend:
    name = "seatbelt"

    def __init__(self) -> None:
        self._sandboxes: dict[int, Sandbox] = {}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            profile_format=PROFILE_FORMAT,
            separate_read_write_grants=True,
            controls_truncate=True,
            pid_isolation=False,
            network_mechanism="port-allow",
            notes=(
                "Seatbelt has no process namespace. The supervisor finds the run's processes "
                "by asking the kernel which processes carry this run's profile, then freezes "
                "and kills them.",
                "Network: only TCP to the proxy's port on 127.0.0.1 or ::1. UDP, other ports "
                "and addresses, DNS, and Unix sockets are refused.",
                "Every refused operation fails with 'Operation not permitted' (EPERM).",
                "An execute grant lets the workload run a program without reading its bytes.",
                "Programs list the root directory as they start, so the names of top-level "
                "directories are visible.",
                "The working directory's names can be listed, because getcwd opens it; "
                "reading what they name still needs a grant. Python started in a directory "
                "the workload cannot read fails at its first import.",
                "Inside a protected directory, a missing name reports 'No such file or "
                "directory' and an existing one 'Operation not permitted': names can be "
                "probed, not read.",
                "macOS's /bin/bash 3.2 writes here-documents to /var/tmp, outside every grant, "
                "so a here-document fails; printf or the write tool work instead.",
            ),
        )

    def doctor(self) -> DoctorReport:
        checks = doctor.checks()
        ok = all(check.ok for check in checks)
        return DoctorReport("seatbelt", checks, native_execution=ok)

    def prepare(self, plan: GrantPlan, run: RunSpec) -> PreparedProfile:
        nonce = secrets.token_hex(4)
        marker = accounting.Marker.for_run(f"{run.run_id}.{nonce}")
        text = render(plan, marker.marker, os.path.realpath(run.workspace))
        private = Path(run.private)
        (private / "profile.sb").write_text(text)
        launch = {"profile": text, "probes": self_probes(plan, nonce),
                  "marker": marker.marker, "control": marker.control,
                  "protected": list(plan.protected), "proxy_port": plan.proxy_port}
        (private / LAUNCH_FILE).write_text(json.dumps(launch, indent=1) + "\n")
        return PreparedProfile(
            backend="seatbelt", profile_format=PROFILE_FORMAT,
            profile_path=str(private / "profile.sb"),
            profile_sha256=hashlib.sha256(text.encode()).hexdigest(),
            disclosed=(
                f"macOS baseline: {len(BASELINE)} rules, each with its reason (os_baseline.py)",
                f"{len(plan.runtime)} runtime grants and {len(plan.task)} task grants",
                f"run marker {marker.marker}: a Mach name no service uses, for teardown",
            ),
        )

    def launch(self, prepared: PreparedProfile, workload: WorkloadSpec) -> ContainedProcess:
        if prepared.backend != "seatbelt" or prepared.profile_path is None:
            raise LaunchRefused("profile was prepared by another backend")
        launch_path = Path(prepared.profile_path).with_name(LAUNCH_FILE)
        launch = json.loads(launch_path.read_text())
        if hashlib.sha256(launch["profile"].encode()).hexdigest() != prepared.profile_sha256:
            raise LaunchRefused("the launch file does not hold the prepared profile")
        reservation = reserve_ipv6_twin(launch["proxy_port"])
        report_read, report_write = os.pipe()
        launch_fd = os.open(launch_path, os.O_RDONLY)
        passed = (launch_fd, report_write)
        argv = [workload.argv[0], "-m", LAUNCHER, "--profile-fd", str(launch_fd),
                "--report-fd", str(report_write), "--", *workload.argv]
        try:
            with open(workload.stdout_path, "wb") as out, open(workload.stderr_path, "wb") as err:
                process = subprocess.Popen(argv, env=dict(workload.env), cwd=workload.cwd,
                                           stdin=subprocess.PIPE, stdout=out, stderr=err,
                                           pass_fds=passed, start_new_session=True)
        except OSError:
            reservation.close()
            os.close(report_read)
            raise
        finally:
            for descriptor in passed:
                os.close(descriptor)
        marker = accounting.Marker(launch["marker"], launch["control"])
        self._sandboxes[process.pid] = Sandbox(process, report_read, marker,
                                               prepared.profile_sha256 or "",
                                               tuple(launch["protected"]), workload.stderr_path,
                                               reservation)
        return ContainedProcess(workload.run_id, process.pid, "seatbelt", time.time())

    def confirm(self, process: ContainedProcess) -> ContainmentReport:
        """Admit the workload only if the inside probes and the outside checks all pass."""
        tracked = self._sandboxes[process.pid]
        report = read_json(tracked.report_pipe, CONFIRM_TIMEOUT_S)
        if report is None:
            stderr = Path(tracked.stderr_path).read_text(errors="replace")[-800:]
            report = {"ok": False, "error": f"the launcher sent no report; stderr: {stderr}"}
        probes = [ProbeResult(probe["name"], probe["expected"], probe["observed"],
                              probe["passed"]) for probe in report.get("probes", [])]
        if "error" in report:
            probes.append(ProbeResult("launcher confined itself", "ok", report["error"], False))
        else:
            applied = report.get("profile_sha256")
            probes.append(ProbeResult("the launcher applied the prepared profile",
                                      tracked.profile_sha256, str(applied),
                                      applied == tracked.profile_sha256))
        probes += outside_checks(process.pid, tracked)
        contained = report.get("ok", False) and all(probe.passed for probe in probes)
        if contained:
            assert tracked.process.stdin is not None
            tracked.process.stdin.write(b"admit\n")
            tracked.process.stdin.close()
        notes = (f"macOS {platform.mac_ver()[0]} on {platform.machine()}",)
        return ContainmentReport("seatbelt", contained=contained, admit=contained,
                                 probes=tuple(probes), notes=notes)

    def wait(self, process: ContainedProcess, deadline_s: float) -> int | None:
        try:
            return self._sandboxes[process.pid].process.wait(timeout=max(deadline_s, 0))
        except subprocess.TimeoutExpired:
            return None

    def stop(self, process: ContainedProcess) -> TeardownReport:
        """Kill every process that carries the run's profile, then look for any left."""
        tracked = self._sandboxes.pop(process.pid)
        killed = accounting.kill_all(tracked.marker)
        if tracked.process.poll() is None:  # not yet confined, so not found by its marker
            tracked.process.kill()
        tracked.process.wait()
        left = accounting.survivors(tracked.marker)
        tracked.reservation.close()
        return TeardownReport(
            exit_status=tracked.process.returncode,
            stopped=tuple(sorted(set(killed) - set(left))),
            survivors=tuple(left),
            verified=not left,
            limits=("Seatbelt has no process namespace: the supervisor finds the run's "
                    "processes by asking the kernel which processes carry this run's "
                    "profile, freezes them, and kills them. A process that is not yet "
                    "confined is the launcher itself, which is killed directly.",),
        )


def reserve_ipv6_twin(port: int) -> socket.socket:
    """Hold [::1]:port for the run, bound but not listening.

    Seatbelt's `localhost` means both 127.0.0.1 and ::1, and the proxy listens
    only on 127.0.0.1. Holding the IPv6 twin of its port means no other local
    service can be listening there for the workload to reach; a connection
    to it is refused. If another process already holds it, the run is refused.
    """
    twin = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        twin.bind(("::1", port))
    except OSError as error:
        twin.close()
        raise LaunchRefused(f"[::1]:{port} is in use by another process, and the profile "
                            f"cannot tell it apart from the proxy's port: {error}") from error
    return twin


def outside_checks(pid: int, tracked: Sandbox) -> list[ProbeResult]:
    """Ask the kernel about the workload process without performing anything."""
    confined = sandbox.is_sandboxed(pid)
    checks = [
        ProbeResult("the kernel reports the workload confined", "confined",
                    "confined" if confined else "not confined", confined),
        ProbeResult("the workload carries this run's profile", "marker only",
                    "marker only" if accounting.carries(pid, tracked.marker) else "no",
                    accounting.carries(pid, tracked.marker)),
    ]
    for path in tracked.protected:
        if not os.path.exists(path):  # the kernel answers only for paths that exist
            continue
        readable = sandbox.allows(pid, "file-read-data", sandbox.FILTER_PATH, path)
        writable = sandbox.allows(pid, "file-write-data", sandbox.FILTER_PATH, path)
        observed = "refused" if readable is False and writable is False else "not refused"
        checks.append(ProbeResult(f"the kernel refuses the workload {path}", "refused",
                                  observed, observed == "refused"))
    return checks
