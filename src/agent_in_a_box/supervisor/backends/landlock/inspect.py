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
    """The namespace's init must be the launcher, so that PID 1 is under the same Landlock
    ruleset as the workload (decisions/0014). bubblewrap's own reaper would carry the
    launcher's name too, later in its argument list, so the check is positional: the
    init was started as `<interpreter> -m <launcher module>`. Whether a process has a
    Landlock domain is not visible in /proc; that rests on the launcher's own report."""
    arguments = command_line(init_pid)
    started_as = arguments[1:3] == ["-m", launcher]
    observed = "launcher" if started_as else " ".join(arguments[:3]) or "unreadable"
    return [ProbeResult("the namespace's init is the launcher", "launcher", observed,
                        observed == "launcher")]


def member_checks(pid_namespace: int) -> list[ProbeResult]:
    """Every process in the namespace, init included, has no-new-privileges and seccomp on."""
    checked, unconfined = 0, []
    for pid in namespace_members(pid_namespace):
        fields = status_fields(pid)
        if not fields and not os.path.exists(f"/proc/{pid}"):
            continue  # it exited between the listing and the read
        checked += 1
        if (fields.get("NoNewPrivs"), fields.get("Seccomp")) != ("1", "2"):
            unconfined.append(pid)
    if not checked:
        observed = "no process found"
    elif unconfined:
        observed = f"{len(unconfined)} of {checked} without"
    else:
        observed = "all"
    return [ProbeResult("every process in the namespace has no-new-privileges and seccomp",
                        "all", observed, observed == "all")]


def in_namespace_tree(pid: int, pid_namespace: int) -> bool:
    """Whether `pid` is in the PID namespace with this inode, or in one nested inside it.

    With user namespaces disabled inside, nothing in the sandbox can make a PID
    namespace of its own; the walk is defense in depth for a host where that
    limit does not hold. It ends where the kernel will not show the parent,
    which is at the supervisor's own namespace or above it.
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
