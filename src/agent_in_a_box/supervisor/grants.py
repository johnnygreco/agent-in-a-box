"""Assemble the GrantPlan: task grants from policy, runtime grants from the supervisor.

Runtime grants are what the interpreter, the harness code, and the tools'
programs need to run at all. They are disclosed separately from the task
grants that policy produced, and the harness code is granted read-only so
the workload cannot change it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from agent_in_a_box.contracts import Access, Extent, GrantPlan, PathGrant, RunSpec
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.compiler import CompiledPolicy, PolicyRejected
from agent_in_a_box.policy.toolchain import toolchain_dir

# Programs the harness tools and the lessons' probes run.
RUNTIME_PROGRAMS = ("bash", "sh", "env", "cat", "ls", "echo", "head", "grep", "curl", "sleep",
                    "nohup")
HARNESS_CODE = Path(__file__).resolve().parents[1]


def place_grants(compiled: CompiledPolicy, workspace: str) -> tuple[PathGrant, ...]:
    """Map the policy's logical /workspace grants onto this run's workspace.

    The kernel checks resolved paths, so each grant is rendered by its
    canonical spelling. A grant whose resolved path leaves the workspace (for
    example through a symlink in the fixture) is rejected.
    """
    root = os.path.realpath(workspace)
    placed = []
    for grant in compiled.grants:
        relative = grant.logical.removeprefix(schema.WORKSPACE_ROOT).lstrip("/")
        path = os.path.realpath(os.path.join(root, relative))
        if path != root and not path.startswith(root + os.sep):
            policy_ids = ", ".join(grant.policy_ids)
            raise PolicyRejected([f"{policy_ids}: {grant.logical} resolves outside the workspace"])
        placed.append(PathGrant(path, grant.access, Extent.SUBTREE, "policy", grant.policy_ids,
                                grant.logical))
    return tuple(placed)


def _grant(path: str, access: Access, extent: Extent, why: str) -> PathGrant:
    return PathGrant(os.path.realpath(path), access, extent, "runtime", (why,))


def runtime_grants(run: RunSpec) -> tuple[PathGrant, ...]:
    grants = [_grant(sys.executable, Access.EXECUTE, Extent.FILE, "Python interpreter")]
    for program in RUNTIME_PROGRAMS:
        if found := shutil.which(program):
            grants.append(_grant(found, Access.EXECUTE, Extent.FILE, f"tool program {program}"))
    grants += [
        _grant(sys.base_prefix, Access.READ, Extent.SUBTREE, "Python standard library"),
        _grant(sys.prefix, Access.READ, Extent.SUBTREE, "Python environment (dependencies)"),
        _grant(str(HARNESS_CODE), Access.READ, Extent.SUBTREE, "harness code, read-only"),
        _grant(run.workspace, Access.METADATA, Extent.FILE, "working directory"),
    ]
    grants.append(_grant(run.home, Access.READ, Extent.SUBTREE, "run home"))
    grants.append(_grant(run.home, Access.WRITE, Extent.SUBTREE, "run home"))
    grants.append(_grant(run.tmp, Access.READ, Extent.SUBTREE, "run temporary directory"))
    grants.append(_grant(run.tmp, Access.WRITE, Extent.SUBTREE, "run temporary directory"))
    # Drop exact duplicates (for example, when the venv is the base prefix), keeping order.
    return tuple(dict.fromkeys(grants))


def protected_paths(run: RunSpec) -> tuple[str, ...]:
    """Never reachable, whatever policy grants: run state, evidence, native helpers."""
    return (os.path.realpath(run.private), os.path.realpath(toolchain_dir()))


def _overlaps(grant: str, protected: str) -> bool:
    """Whether either path is the other or contains it."""
    if grant == protected:
        return True
    return grant.startswith(protected + os.sep) or protected.startswith(grant + os.sep)


def grant_plan(compiled: CompiledPolicy, run: RunSpec, proxy_port: int) -> GrantPlan:
    task = place_grants(compiled, run.workspace)
    runtime = runtime_grants(run)
    protected = protected_paths(run)
    for grant in (*task, *runtime):
        for path in protected:
            if grant.access is not Access.EXECUTE and _overlaps(grant.path, path):
                raise PolicyRejected([f"grant {grant.path} overlaps protected path {path}"])
    return GrantPlan(task, runtime, protected, proxy_port, compiled.bundle.policy_hash)
