"""Compile the parts of a policy set that must be fixed before launch.

A kernel profile is an allow-list of paths installed once, before the agent
starts. It cannot ask Cedar about each file operation. So a filesystem policy
is accepted only when its meaning is exactly "the process tree may read (or
write) these subtrees"; anything else is rejected at load rather than
widened. The accepted shapes:

  permit (principal, action in [ReadFile, WriteFile], resource in FilesystemPath::"/p");
  permit (principal, action == ReadFile, resource) when { resource in P1 || resource in P2 };

`principal` may be unconstrained or `principal is Sandbox::Process`.

ReadFile and WriteFile stay separate grants (PLAN.md, Filesystem grant
extraction). A WriteFile-only policy becomes a write-only grant, never a
read-and-write one; each backend renders it or rejects it.

Connections: a NetworkConnect permit that names its endpoint literally in the
scope makes that endpoint an eligible proxy route. The route must be known
before any request arrives, and a condition can only be evaluated against a
request. So a permit that names the endpoint only in a condition is still
evaluated by Cedar, but no route is derived from it (variant P6).
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent_in_a_box.contracts import (
    Access, CedarEvaluator, EligibleEndpoint, PolicyBundle, PolicyText, ProxyPlan,
    ValidationReport,
)
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.policy_json import (
    resource_may_be, scope_actions, scope_entity, when_paths,
)

# Policy ids starting with this are reserved for analysis domains (ADR 0005).
RESERVED_ID_PREFIX = "domain:"
# The two file actions, and the grant each one means.
FILE_ACCESS = {schema.READ_FILE: Access.READ, schema.WRITE_FILE: Access.WRITE}


class PolicyRejected(ValueError):
    """The policy set failed validation or uses a shape we cannot enforce exactly."""

    def __init__(self, reasons: Iterable[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


def rejected(policy_id: str, reason: str) -> PolicyRejected:
    return PolicyRejected([f"{policy_id}: {reason}"])


@dataclass(frozen=True)
class LogicalGrant:
    """A grant as authored: a logical /workspace path and one access."""

    logical: str
    access: Access
    policy_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompiledPolicy:
    bundle: PolicyBundle
    validation: ValidationReport
    grants: tuple[LogicalGrant, ...]
    proxy: ProxyPlan


# ── The compiler ──────────────────────────────────────────────────────────


def compile_policy(bundle: PolicyBundle, evaluator: CedarEvaluator) -> CompiledPolicy:
    """Validate against the schema, then derive grants and routes, or raise PolicyRejected."""
    report = evaluator.validate(bundle)
    if not report.valid:
        reasons = [f"{error.policy_id or 'policy set'}: {error.message}"
                   for error in report.errors]
        raise PolicyRejected(reasons)

    grants: list[LogicalGrant] = []
    routes: dict[str, list[str]] = {}  # endpoint -> ids of the permits that name it
    for policy in report.policies:
        if policy.id.startswith(RESERVED_ID_PREFIX):
            raise rejected(policy.id, f"ids starting with {RESERVED_ID_PREFIX!r} are reserved")
        if touches_files(policy.json):
            grants += filesystem_grants(policy.id, policy.json)
        endpoint = route_endpoint(policy)
        if endpoint is not None:
            routes.setdefault(endpoint, []).append(policy.id)

    eligible = tuple(EligibleEndpoint(endpoint, tuple(sorted(policy_ids)))
                     for endpoint, policy_ids in sorted(routes.items()))
    return CompiledPolicy(bundle, report, merge(grants), ProxyPlan(eligible, bundle.policy_hash))


# ── Filesystem grants ─────────────────────────────────────────────────────


def touches_files(policy: dict[str, Any]) -> bool:
    """Whether the policy can apply to a file: its action scope includes ReadFile
    or WriteFile (or is every action), and its resource can be a FilesystemPath."""
    actions = scope_actions(policy)
    file_action = actions is None or bool(actions & set(FILE_ACCESS))
    return file_action and resource_may_be(policy, schema.FILESYSTEM_PATH)


def filesystem_grants(policy_id: str, policy: dict[str, Any]) -> list[LogicalGrant]:
    """The grants one filesystem policy means. Raises PolicyRejected when an
    allow-list kernel profile could not enforce exactly what the policy says."""
    if policy["effect"] == "forbid":
        raise rejected(policy_id, "a forbid on files cannot be enforced by an allow-list "
                                  "kernel profile")
    actions = scope_actions(policy)
    if actions is None or not actions <= set(FILE_ACCESS):
        raise rejected(policy_id, "a policy that can apply to files must list only ReadFile "
                                  "and/or WriteFile")
    any_process = {"op": "is", "entity_type": schema.PROCESS}
    if policy["principal"]["op"] != "All" and policy["principal"] != any_process:
        raise rejected(policy_id, "filesystem grants apply to the whole process tree; use "
                                  "`principal` or `principal is Sandbox::Process`")
    paths = filesystem_paths(policy_id, policy)
    for path in paths:
        problem = check_logical_path(path)
        if problem is not None:
            raise rejected(policy_id, f"{path!r}: {problem}")

    grants = []
    for path in paths:
        for action in sorted(actions):
            grants.append(LogicalGrant(path, FILE_ACCESS[action], (policy_id,)))
    return grants


def filesystem_paths(policy_id: str, policy: dict[str, Any]) -> list[str]:
    """The paths a filesystem policy names: one in its scope, or several in a
    single `when` made only of `resource in` tests."""
    if policy["resource"]["op"] == "==":
        raise rejected(policy_id, "`resource ==` names one path, but the profile grants a "
                                  'subtree; use `resource in Sandbox::FilesystemPath::"/..."`')
    in_scope = scope_entity(policy, schema.FILESYSTEM_PATH)
    if in_scope is not None:
        if policy.get("conditions"):
            raise rejected(policy_id, "when/unless conditions on a filesystem policy cannot "
                                      "be enforced")
        return [in_scope]
    paths = when_paths(policy)
    if paths is None:
        raise rejected(policy_id, "name paths in the scope or in one `when` that only ORs "
                                  "`resource in` tests")
    return paths


def check_logical_path(path: str) -> str | None:
    """Why `path` cannot be a grant, or None. Paths are logical, under /workspace."""
    for character in path:
        if ord(character) < 0x20 or character == "\x7f":
            return "path contains a control character"
    if path.startswith("//") or posixpath.normpath(path) != path:
        return "path is not normalized (no '.', '..', '//', or trailing '/')"
    root = schema.WORKSPACE_ROOT
    if path != root and not path.startswith(root + "/"):
        return f"path is outside the task root {root}"
    return None


def merge(grants: list[LogicalGrant]) -> tuple[LogicalGrant, ...]:
    """One grant per (path, access), naming every policy that asked for it."""
    policy_ids: dict[tuple[str, Access], set[str]] = {}
    for grant in grants:
        policy_ids.setdefault((grant.logical, grant.access), set()).update(grant.policy_ids)
    merged = []
    for (path, access), ids in sorted(policy_ids.items()):
        merged.append(LogicalGrant(path, access, tuple(sorted(ids))))
    return tuple(merged)


# ── Connection routes ─────────────────────────────────────────────────────


def route_endpoint(policy: PolicyText) -> str | None:
    """The endpoint a NetworkConnect permit names in its scope, if any."""
    if policy.effect != "permit":
        return None
    actions = scope_actions(policy.json)
    if actions is not None and schema.NETWORK_CONNECT not in actions:
        return None
    endpoint = scope_entity(policy.json, schema.NETWORK_ENDPOINT)
    if endpoint is None:
        return None
    problem = check_endpoint(endpoint)
    if problem is not None:
        raise rejected(policy.id, f"endpoint {endpoint!r}: {problem}")
    return endpoint


def check_endpoint(endpoint: str) -> str | None:
    """Why `endpoint` is not a "host:port" literal a request could ever match, or None.
    Requests carry a lowercase host with no trailing dot (requests.normalize_host)."""
    host, colon, port = endpoint.rpartition(":")
    if not colon or not host:
        return 'expected "host:port"'
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return "port must be in 1..65535"
    if host != host.lower() or host.endswith("."):
        return "host must be lowercase with no trailing '.'"
    return None
