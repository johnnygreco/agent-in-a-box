"""Render a GrantPlan as a Seatbelt profile (SBPL). Pure text; no macOS calls.

Untested natively until Milestone 1 (STATUS.md). This renderer defines what
the shared GrantPlan must carry (PLAN.md, primacy rule 1); other backends
conform to the same plan.

Shape of the profile, in order:

1. (deny default): anything not allowed below is blocked.
2. The macOS baseline every process needs (os_baseline.py), each rule with
   its reason as a comment.
3. Runtime grants: the interpreter, harness code, and the run's home and
   tmp, which the supervisor supplies and discloses apart from the task.
4. Task grants derived from policy.
5. Metadata on every ancestor of a granted path, so lookups reach it.
6. Network: only the per-run proxy on localhost. No DNS, no other ports.
7. Protected paths, denied last so no grant above can reach them.

Each path is the plan's canonical spelling: Seatbelt checks resolved paths,
and a rule naming a symlink would enforce nothing while reading as a grant.
"""

from __future__ import annotations

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
    if entry.filter in ("subpath", "literal"):
        return f"(allow {entry.operation} ({entry.filter} {sbpl_path(entry.value)}))"
    if entry.filter == "global-name":
        return f'(allow {entry.operation} (global-name "{entry.value}"))'
    return f"(allow {entry.operation} (target {entry.value}))"


def baseline_lines() -> list[str]:
    lines = [";; macOS baseline: what any process needs from the system (os_baseline.py)."]
    for entry in BASELINE:
        lines.append(f";; {entry.why}")
        lines.append(baseline_rule(entry))
    return lines


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
    return [";; Network: only the per-run proxy.",
            f'(allow network-outbound (remote ip "localhost:{plan.proxy_port}"))']


def protected_lines(plan: GrantPlan) -> list[str]:
    lines = [";; Protected: never reachable, whatever the grants above say."]
    for path in plan.protected:
        lines.append(f"(deny file-read* file-write* (subpath {sbpl_path(path)}))")
    return lines


def render(plan: GrantPlan) -> str:
    """The whole profile: one section per step listed in the module docstring."""
    if not 1 <= plan.proxy_port <= 65535:
        raise ValueError(f"proxy port out of range: {plan.proxy_port}")
    header = ["(version 1)", f";; Agent in a Box Seatbelt profile. Policy {plan.policy_hash}.",
              "(deny default)"]
    sections = [
        header,
        baseline_lines(),
        grant_lines("Runtime grants", plan.runtime),
        grant_lines("Task grants", plan.task),
        ancestor_lines(plan),
        network_lines(plan),
        protected_lines(plan),
    ]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


class SbplRenderer:
    profile_format = PROFILE_FORMAT

    def render(self, plan: GrantPlan) -> str:
        return render(plan)
