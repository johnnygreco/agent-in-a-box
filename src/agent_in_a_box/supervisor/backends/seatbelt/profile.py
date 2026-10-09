"""Render a GrantPlan as a Seatbelt profile (SBPL). Pure text; no macOS calls.

This renderer defines what the shared GrantPlan must carry (PLAN.md,
primacy rule 1); other backends conform to the same plan. Its output is
confirmed natively on the macOS runner (decisions/0014).

Shape of the profile, in order:

1. (deny default): anything not allowed below is blocked.
2. The macOS baseline every process needs (os_baseline.py), each rule with
   its reason as a comment, and the refusal of process information:
   (deny default) does not cover it, so without an explicit rule a workload
   could read the arguments and environment of any process its user runs.
3. Runtime grants: the interpreter, harness code, and the run's home and
   tmp, which the supervisor supplies and discloses apart from the task.
4. Task grants derived from policy.
5. Metadata on every ancestor of a granted path, so lookups reach it.
6. Network: only TCP to the per-run proxy's port on localhost. No DNS, no
   UDP, no other ports, no Unix sockets.
7. The run's marker: a Mach name no service uses, which lets the supervisor
   find every process under this profile (accounting.py).
8. Protected paths, denied last so no grant above can reach them.

Each path is the plan's canonical spelling: Seatbelt checks resolved paths,
and a rule naming a symlink would enforce nothing while reading as a grant.
"""

from __future__ import annotations

import os
import posixpath

from agent_in_a_box.contracts import Access, Extent, GrantPlan, PathGrant
from agent_in_a_box.supervisor.backends.seatbelt.os_baseline import BASELINE, Entry

PROFILE_FORMAT = "sbpl"


def sbpl_path(path: str) -> str:
    """An absolute, normalized path as an SBPL string literal."""
    if not path.startswith("/") or path.startswith("//") or posixpath.normpath(path) != path:
        raise ValueError(f"profile paths must be absolute and normalized: {path!r}")
    for character in path:
        if ord(character) < 0x20 or character == "\x7f":
            raise ValueError(f"profile paths may not contain control characters: {path!r}")
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ── The baseline ──────────────────────────────────────────────────────────


def baseline_rule(entry: Entry) -> str:
    if entry.filter == "none":
        return f"(allow {entry.operation})"
    if entry.filter == "target":
        return f"(allow {entry.operation} (target {entry.value}))"
    if entry.filter in ("subpath", "literal"):
        values = " ".join(sbpl_path(value) for value in entry.values)
    else:
        values = " ".join(f'"{value}"' for value in entry.values)
    return f"(allow {entry.operation} ({entry.filter} {values}))"


def baseline_lines() -> list[str]:
    lines = [";; macOS baseline: what any process needs from the system (os_baseline.py)."]
    for entry in BASELINE:
        lines.append(f";; {entry.why}")
        lines.append(baseline_rule(entry))
    return lines


def process_info_lines() -> list[str]:
    """Each process may inspect only itself. Later rules take precedence in SBPL."""
    return [";; Process information. (deny default) does not cover it on macOS 15: without",
            ";; these two rules the workload could list every process and read the arguments",
            ";; and environment of any process its user runs, the supervisor's included.",
            "(deny process-info*)",
            "(allow process-info* (target self))"]


# ── Grants ────────────────────────────────────────────────────────────────


def grant_filter(grant: PathGrant) -> str:
    if grant.extent is Extent.SUBTREE:
        return f"(subpath {sbpl_path(grant.path)})"
    return f"(literal {sbpl_path(grant.path)})"


def grant_rules(grant: PathGrant) -> list[str]:
    """The SBPL rules for one grant. Read and write stay separate."""
    target = grant_filter(grant)
    if grant.access is Access.READ:
        return [f"(allow file-read* {target})"]
    if grant.access is Access.METADATA:
        return [f"(allow file-read-metadata {target})"]
    if grant.access is Access.EXECUTE:
        if grant.extent is not Extent.FILE:
            raise ValueError(f"execute grants name one file, not a subtree: {grant.path}")
        return [f"(allow process-exec {target})", f"(allow file-read-metadata {target})"]
    rules = [f"(allow file-write* {target})"]
    if grant.extent is Extent.SUBTREE:
        # Pin the write root itself: no removing it or putting something else there.
        root = f"(literal {sbpl_path(grant.path)})"
        rules.append(f"(deny file-write-unlink {root})")
        rules.append(f"(deny file-write-create {root})")
    return rules


def grant_comment(grant: PathGrant) -> str:
    source = grant.logical or "runtime"
    reasons = ", ".join(grant.because)
    return f";; {grant.access.value} {grant.extent.value}: {source} ({reasons})"


def grant_lines(title: str, grants: tuple[PathGrant, ...]) -> list[str]:
    lines = [f";; {title}."]
    for grant in grants:
        lines.append(grant_comment(grant))
        lines += grant_rules(grant)
    return lines


def ancestors(path: str) -> list[str]:
    """Every directory above `path`: "/r/ws/results" -> ["/", "/r", "/r/ws"]."""
    found = []
    parent = posixpath.dirname(path)
    while parent != "/":
        found.append(parent)
        parent = posixpath.dirname(parent)
    found.append("/")
    return found


def ancestor_lines(plan: GrantPlan) -> list[str]:
    directories = set()
    for grant in (*plan.runtime, *plan.task):
        directories.update(ancestors(grant.path))
    lines = [";; Ancestor metadata so granted paths can be looked up."]
    for directory in sorted(directories):
        lines.append(f"(allow file-read-metadata (literal {sbpl_path(directory)}))")
    return lines


# ── The profile ───────────────────────────────────────────────────────────


def network_lines(plan: GrantPlan) -> list[str]:
    return [";; Network: only TCP to the per-run proxy. Seatbelt's localhost is 127.0.0.1 and ::1.",
            f'(allow network-outbound (remote tcp "localhost:{plan.proxy_port}"))']


def marker_lines(marker: str) -> list[str]:
    if not all(character.isalnum() or character in ".-" for character in marker):
        raise ValueError(f"marker must be a plain Mach name: {marker!r}")
    return [";; The run's marker: no service has this name. The supervisor asks the kernel",
            ";; which processes may look it up, to find every process under this profile.",
            f'(allow mach-lookup (global-name "{marker}"))']


def protected_lines(plan: GrantPlan) -> list[str]:
    lines = [";; Protected: never reachable, whatever the grants above say."]
    for path in plan.protected:
        lines.append(f"(deny file-read* file-write* (subpath {sbpl_path(path)}))")
    return lines


def self_probes(plan: GrantPlan, nonce: str, exists=os.path.exists) -> list[dict]:
    """Operations the launcher tries inside the sandbox, after confining itself.

    Each must fail with Seatbelt's refusal (EPERM, "denied"). A protected path
    that does not exist on this host is expected to be absent instead.
    """
    other_port = 9 if plan.proxy_port != 9 else 10
    probes = [
        {"name": "an ungranted directory cannot be listed", "op": "listdir",
         "target": "/Library", "expect": "denied"},
        {"name": "an ungranted, world-writable directory refuses a new file", "op": "create",
         "target": f"/private/tmp/agent-in-a-box-probe-{nonce}", "expect": "denied"},
        {"name": "TCP to another loopback port is refused", "op": "tcp",
         "target": f"127.0.0.1:{other_port}", "expect": "denied"},
        {"name": "TCP to another IPv6 loopback port is refused", "op": "tcp",
         "target": f"[::1]:{other_port}", "expect": "denied"},
        {"name": "TCP to a public address is refused", "op": "tcp", "target": "192.0.2.1:80",
         "expect": "denied"},
        {"name": "UDP is refused, even to the proxy's port", "op": "udp",
         "target": f"127.0.0.1:{plan.proxy_port}", "expect": "denied"},
        {"name": "a Unix socket is refused", "op": "unix", "target": "/private/var/run/syslog",
         "expect": "denied"},
        {"name": "a kernel control socket is refused", "op": "socket", "target": "32,2,2",
         "expect": "denied"},
    ]
    for path in plan.protected:
        probes.append({"name": f"protected path is refused: {path}", "op": "stat",
                       "target": path, "expect": "denied" if exists(path) else "absent"})
    return probes


def render(plan: GrantPlan, marker: str | None = None) -> str:
    """The whole profile: one section per step listed in the module docstring.

    `marker` is the run's marker name; a profile rendered for display has none.
    """
    if not 1 <= plan.proxy_port <= 65535:
        raise ValueError(f"proxy port out of range: {plan.proxy_port}")
    header = ["(version 1)", f";; Agent in a Box Seatbelt profile. Policy {plan.policy_hash}.",
              "(deny default)"]
    sections = [
        header,
        baseline_lines(),
        process_info_lines(),
        grant_lines("Runtime grants", plan.runtime),
        grant_lines("Task grants", plan.task),
        ancestor_lines(plan),
        network_lines(plan),
        marker_lines(marker) if marker else [],
        protected_lines(plan),
    ]
    return "\n\n".join("\n".join(section) for section in sections if section) + "\n"


class SbplRenderer:
    profile_format = PROFILE_FORMAT

    def render(self, plan: GrantPlan) -> str:
        return render(plan)
