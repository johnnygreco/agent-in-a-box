"""Render a GrantPlan as a Linux profile: namespaces, mounts, Landlock rules, seccomp.

Pure: no system calls. The same GrantPlan the Seatbelt renderer consumes
becomes three layers here (decisions/0010):

  namespaces  bubblewrap gives the workload its own user, PID, network, IPC,
              and UTS namespaces. The network namespace has only loopback.
  mounts      the filesystem view. Paths with read, execute, or metadata
              grants are mounted read-only; paths with write grants are
              mounted writable. Anything else does not exist inside.
  landlock    access rights on what is mounted. Read and write stay separate;
              metadata is not governed by Landlock, so metadata grants are
              met by the mount alone.

The proxy is reached through a Unix socket mounted into the sandbox and a
relay inside it that listens on the plan's proxy port on loopback, so the
workload's HTTP_PROXY setting is the same as on every backend.

The profile is JSON so it can be hashed, diffed, and shown beside the SBPL
for the same plan (chapter 6).
"""

from __future__ import annotations

import json
import posixpath

from agent_in_a_box.contracts import Access, Extent, GrantPlan, PathGrant
from agent_in_a_box.supervisor.backends.landlock import os_baseline, seccomp

PROFILE_FORMAT = "landlock+bwrap+seccomp"
PROXY_SOCKET_DIR = "/run/agent-in-a-box"
PROXY_SOCKET = f"{PROXY_SOCKET_DIR}/proxy.sock"
NAMESPACES = ("--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc",
              "--unshare-uts", "--unshare-cgroup-try", "--die-with-parent", "--new-session")

WRITE_RIGHTS_ON_DIRECTORY = ("write_file", "truncate", "make_reg", "make_dir", "make_sym",
                             "make_fifo", "make_sock", "remove_file", "remove_dir", "refer")
WRITE_RIGHTS_ON_FILE = ("write_file", "truncate")


def rights_for(grant: PathGrant) -> dict[str, list[str]]:
    """Landlock rights for a grant, by what the path turns out to be at launch."""
    if grant.access is Access.READ and grant.extent is Extent.SUBTREE:
        return {"if_file": ["read_file"], "if_directory": ["read_dir", "read_file"]}
    if grant.access is Access.READ:
        return {"if_file": ["read_file"], "if_directory": ["read_dir"]}
    if grant.access is Access.WRITE and grant.extent is Extent.SUBTREE:
        return {"if_file": list(WRITE_RIGHTS_ON_FILE),
                "if_directory": list(WRITE_RIGHTS_ON_DIRECTORY)}
    if grant.access is Access.WRITE:
        return {"if_file": list(WRITE_RIGHTS_ON_FILE), "if_directory": []}
    if grant.access is Access.EXECUTE:
        if grant.extent is not Extent.FILE:
            raise ValueError(f"execute grants name one file, not a subtree: {grant.path}")
        # The kernel opens a program for reading to execute it, and Landlock checks
        # both rights, so an execute grant on Linux also lets the program be read.
        return {"if_file": ["execute", "read_file"], "if_directory": []}
    return {"if_file": [], "if_directory": []}  # metadata: the mount alone provides it


def check_path(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or posixpath.normpath(path) != path:
        raise ValueError(f"profile paths must be absolute and normalized: {path!r}")
    for character in path:
        if ord(character) < 0x20 or character == "\x7f":
            raise ValueError(f"profile paths may not contain control characters: {path!r}")
    return path


def is_beneath(path: str, ancestor: str) -> bool:
    return path == ancestor or path.startswith(ancestor.rstrip("/") + "/")


def mounts(plan: GrantPlan) -> list[dict[str, str]]:
    """The filesystem view, parents before children. Writable wins where grants overlap."""
    writable: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    for grant in (*plan.runtime, *plan.task):
        path = check_path(grant.path)
        writable[path] = writable.get(path, False) or grant.access is Access.WRITE
        reasons.setdefault(path, ", ".join(grant.because))
    view = [{"kind": mount.kind, "path": mount.path, "why": mount.why}
            for mount in os_baseline.MOUNTS]
    for path in sorted(writable, key=lambda item: (item.count("/"), item)):
        covering = [entry for entry in view if entry["kind"] in ("--ro-bind-try", "--bind-try")
                    and is_beneath(path, entry["path"])]
        same_kind = covering and (covering[-1]["kind"] == "--bind-try") == writable[path]
        if same_kind:
            continue  # already in the view, with the same writability
        kind = "--bind-try" if writable[path] else "--ro-bind-try"
        view.append({"kind": kind, "path": path, "why": reasons[path]})
    return view


def landlock_rules(plan: GrantPlan) -> list[dict]:
    rules = [{"path": rule.path, "if_file": list(rule.rights), "if_directory": list(rule.rights),
              "why": rule.why} for rule in os_baseline.RULES]
    for grant in (*plan.runtime, *plan.task):
        rules.append({"path": grant.path, **rights_for(grant),
                      "why": f"{grant.origin} grant: {', '.join(grant.because)}"})
    return rules


def self_probes(plan: GrantPlan) -> list[dict]:
    """Checks the launcher runs inside the sandbox, after restricting itself."""
    probes = [
        {"name": "an unlisted directory cannot be read", "op": "listdir", "target": "/",
         "expect": "denied"},
        {"name": "a mounted but ungranted directory refuses a new file", "op": "create",
         "target": "/tmp/.landlock-probe", "expect": "denied"},
        {"name": "no route leaves the network namespace", "op": "connect",
         "target": "192.0.2.1", "expect": "unreachable"},
        {"name": "seccomp refuses netlink sockets", "op": "socket", "target": "16",
         "expect": "refused"},
    ]
    for path in plan.protected:
        probes.append({"name": f"protected path is not reachable: {path}", "op": "stat",
                       "target": check_path(path), "expect": "absent"})
    return probes


def render(plan: GrantPlan) -> str:
    if not 1 <= plan.proxy_port <= 65535:
        raise ValueError(f"proxy port out of range: {plan.proxy_port}")
    profile = {
        "format": PROFILE_FORMAT,
        "policy_hash": plan.policy_hash,
        "namespaces": list(NAMESPACES),
        "mounts": mounts(plan),
        "landlock": landlock_rules(plan),
        "seccomp": {
            "allowed_socket_families": sorted(seccomp.ALLOWED_FAMILIES),
            "refused_syscalls": ["io_uring_setup"],
            # The exact programs, so the profile's hash covers what is loaded.
            "programs": {machine: seccomp.compiled(machine).hex()
                         for machine in sorted(seccomp.ARCHITECTURES)},
        },
        "proxy": {"port": plan.proxy_port, "socket": PROXY_SOCKET},
        "protected": list(plan.protected),
        "probes": self_probes(plan),
    }
    return json.dumps(profile, indent=1) + "\n"


def bwrap_arguments(profile: dict) -> list[str]:
    """The bubblewrap options for a rendered profile (without launch-time extras)."""
    arguments = list(profile["namespaces"])
    for mount in profile["mounts"]:
        if mount["kind"] in ("--proc", "--dev", "--tmpfs"):
            arguments += [mount["kind"], mount["path"]]
        else:
            arguments += [mount["kind"], mount["path"], mount["path"]]
    return arguments


class LandlockRenderer:
    profile_format = PROFILE_FORMAT

    def render(self, plan: GrantPlan) -> str:
        return render(plan)
