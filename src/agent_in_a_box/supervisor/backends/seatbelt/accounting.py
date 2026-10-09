"""Find and stop every process that carries a run's profile.

Seatbelt has no process namespace: the workload's processes live among all
the user's other processes, and a detached one leaves the workload's
process group and session. What a process cannot leave is its profile.
Each run's profile allows a Mach lookup of one run-specific name (the
marker) and, like every deny-default profile, refuses a second
run-specific name (the control). The kernel answers, without performing
the lookup, which names a process's profile allows (sandbox.allows):

    unconfined process            marker allowed, control allowed
    another sandbox               marker refused, control refused (or both allowed)
    this run's processes          marker allowed, control refused

Only the last signature makes a process a member. Neither name is a real
service, so allowing the marker gives the workload nothing.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from dataclasses import dataclass

from agent_in_a_box.supervisor.backends.seatbelt import sandbox

ROUNDS = 50


@dataclass(frozen=True)
class Marker:
    marker: str
    control: str

    @classmethod
    def for_run(cls, token: str) -> Marker:
        return cls(f"org.agent-in-a-box.run.{token}", f"org.agent-in-a-box.control.{token}")


def carries(pid: int, marker: Marker) -> bool:
    """Whether process `pid` runs under the profile that `marker` names."""
    kind = sandbox.FILTER_GLOBAL_NAME
    return (sandbox.allows(pid, "mach-lookup", kind, marker.marker) is True
            and sandbox.allows(pid, "mach-lookup", kind, marker.control) is False)


def all_processes() -> list[int]:
    listing = subprocess.run(["/bin/ps", "-axo", "pid="], capture_output=True, text=True,
                             check=True)
    return [int(pid) for pid in listing.stdout.split()]


def members(marker: Marker) -> list[int]:
    """Every live process that carries the run's profile, lowest PID first."""
    return sorted(pid for pid in all_processes() if pid != os.getpid() and carries(pid, marker))


def _signal(pid: int, number: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, number)


def kill_all(marker: Marker) -> list[int]:
    """Freeze every member, then kill them all. Returns the PIDs killed.

    Freezing first means a member cannot start a new process between being
    found and being killed. Each frozen process is checked again before it
    is killed: if its PID was reused by an unrelated process in the moment
    between the check and the signal, that process is resumed and left alone.
    """
    frozen: set[int] = set()
    for _ in range(ROUNDS):
        found = set(members(marker)) - frozen
        if not found:
            break
        for pid in found:
            _signal(pid, signal.SIGSTOP)
        frozen |= found
    killed = []
    for pid in sorted(frozen):
        if carries(pid, marker):
            _signal(pid, signal.SIGKILL)
            killed.append(pid)
        else:
            _signal(pid, signal.SIGCONT)
    return killed


def survivors(marker: Marker) -> list[int]:
    """Members still present after a kill, allowing the kernel a moment to reap."""
    remaining = members(marker)
    for _ in range(ROUNDS):
        if not remaining:
            break
        time.sleep(0.02)
        remaining = members(marker)
    return remaining
