"""Look at a running sandbox from outside, through /proc.

The launcher's probe report comes from inside the sandbox. These checks come
from the supervisor reading kernel state about the sandbox's processes, so
nothing inside can forge them.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from agent_in_a_box.contracts import ProbeResult

NAMESPACES = ("user", "pid", "net", "mnt", "ipc", "uts")
NS_GET_PARENT = 0xB702  # ioctl on a namespace descriptor: a descriptor for its parent


def namespace_of(pid: int, kind: str) -> str:
    return os.readlink(f"/proc/{pid}/ns/{kind}")


def namespace_checks(init_pid: int) -> list[ProbeResult]:
    """The sandbox's init must be in a namespace of its own, of every kind."""
    results = []
    for kind in NAMESPACES:
        try:
            shared = namespace_of(init_pid, kind) == namespace_of(os.getpid(), kind)
            observed = "shared" if shared else "separate"
        except OSError as error:
            observed = f"unreadable: {error.strerror}"
        results.append(ProbeResult(f"own {kind} namespace", "separate", observed,
                                   observed == "separate"))
    return results


def status_fields(pid: int) -> dict[str, str]:
    fields = {}
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return fields
    for line in text.splitlines():
        key, _, value = line.partition(":")
        fields[key] = value.strip()
    return fields


def command_line(pid: int) -> list[str]:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return []


def init_checks(init_pid: int, launcher: str) -> list[ProbeResult]:
    """The namespace's init must be the launcher: a process as confined as the
    workload, not an unconfined reaper the workload could borrow (decisions/0014)."""
    arguments = command_line(init_pid)
    observed = "launcher" if launcher in arguments else " ".join(arguments[:3]) or "unreadable"
    return [ProbeResult("the namespace's init is the launcher", "launcher", observed,
                        observed == "launcher")]


def member_checks(pid_namespace: int) -> list[ProbeResult]:
    """Every process in the namespace, init included, has no-new-privileges and seccomp on."""
    members = namespace_members(pid_namespace)
    unconfined = [pid for pid in members
                  if (status_fields(pid).get("NoNewPrivs"), status_fields(pid).get("Seccomp"))
                  != ("1", "2")]
    if not members:
        observed = "no process found"
    elif unconfined:
        observed = f"{len(unconfined)} of {len(members)} without"
    else:
        observed = "all"
    return [ProbeResult("every process in the namespace has no-new-privileges and seccomp",
                        "all", observed, observed == "all")]


def in_namespace_tree(pid: int, pid_namespace: int) -> bool:
    """Whether `pid` is in the PID namespace with this inode, or in one nested inside it.

    A process could try to hide in a namespace of its own; walking up through
    the parents finds it anyway. The walk ends where the kernel will not show
    the parent, which is at the supervisor's own namespace or above it.
    """
    try:
        descriptor = os.open(f"/proc/{pid}/ns/pid", os.O_RDONLY)
    except OSError:
        return False
    try:
        while True:
            if os.fstat(descriptor).st_ino == pid_namespace:
                return True
            try:
                parent = fcntl.ioctl(descriptor, NS_GET_PARENT)
            except OSError:
                return False
            os.close(descriptor)
            descriptor = parent
    finally:
        os.close(descriptor)


def namespace_members(pid_namespace: int) -> list[int]:
    """Host PIDs of every process in the given PID namespace, or in one nested inside it."""
    return sorted(int(entry) for entry in os.listdir("/proc")
                  if entry.isdigit() and in_namespace_tree(int(entry), pid_namespace))
