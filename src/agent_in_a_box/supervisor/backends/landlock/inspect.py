"""Look at a running sandbox from outside, through /proc.

The launcher's probe report comes from inside the sandbox. These checks come
from the supervisor reading kernel state about the sandbox's processes, so
nothing inside can forge them.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_in_a_box.contracts import ProbeResult

NAMESPACES = ("user", "pid", "net", "mnt", "ipc", "uts")


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


def parent_of(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    after_name = stat.rsplit(")", 1)[1].split()  # the name may contain spaces
    return int(after_name[1])


def children_of(pid: int) -> list[int]:
    return sorted(int(entry) for entry in os.listdir("/proc")
                  if entry.isdigit() and parent_of(int(entry)) == pid)


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


def workload_checks(init_pid: int) -> list[ProbeResult]:
    """The process that becomes the workload must have no-new-privileges and seccomp on."""
    children = children_of(init_pid)
    if len(children) != 1:
        return [ProbeResult("one workload process under the sandbox's init", "1",
                            str(len(children)), False)]
    fields = status_fields(children[0])
    no_new_privileges = fields.get("NoNewPrivs", "missing")
    seccomp_mode = fields.get("Seccomp", "missing")
    return [
        ProbeResult("no new privileges", "1", no_new_privileges, no_new_privileges == "1"),
        ProbeResult("seccomp filter mode", "2", seccomp_mode, seccomp_mode == "2"),
    ]


def namespace_members(pid_namespace: int) -> list[int]:
    """Host PIDs of every process still in the given PID namespace."""
    target = f"pid:[{pid_namespace}]"
    members = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if os.readlink(f"/proc/{entry}/ns/pid") == target:
                members.append(int(entry))
        except OSError:
            continue
    return sorted(members)
