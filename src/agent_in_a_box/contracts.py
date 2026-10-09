"""Shared records and the few protocols the runtime actually substitutes.

Read this file first. Every record is a frozen dataclass holding plain data:
no process handles, SDK clients, or keys. A Protocol here describes what a
component does, not what it is allowed to do; in-process implementations are
trusted code, and a Protocol does not sandbox them.

Learner-facing labels come from `agent_in_a_box.glossary`, never from here.
"""

from __future__ import annotations

import hashlib
import json
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

Enforcement = Literal["seatbelt", "landlock", "none"]
Mode = Literal["live", "recorded"]
BackendName = Literal["seatbelt", "landlock", "none"]


def read_only(value: Any) -> Any:
    """Return a read-only copy of JSON-like data: mappings become read-only
    mapping proxies and lists become tuples, all the way down."""
    if isinstance(value, Mapping):
        return types.MappingProxyType({str(key): read_only(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(read_only(item) for item in value)
    return value


def plain(value: Any) -> Any:
    """Return JSON-compatible data from a record or from read-only data."""
    if hasattr(value, "__dataclass_fields__"):
        return {name: plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return value


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_hash(data: Any) -> str:
    """Hash of JSON-compatible data in a canonical encoding."""
    return sha256_text(json.dumps(plain(data), sort_keys=True, separators=(",", ":")))


# ── Cedar requests and decisions ────────────────────────────────────────────


@dataclass(frozen=True)
class EntityRef:
    type: str
    id: str

    def to_json(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}

    def __str__(self) -> str:
        return f"{self.type}::{json.dumps(self.id)}"


@dataclass(frozen=True)
class CedarRequest:
    """One authorization request, built by trusted runtime code.

    `provenance` names the component that supplied each field, so the
    inspector can show which facts the agent could not have chosen.
    """

    principal: EntityRef
    action: EntityRef
    resource: EntityRef
    context: Mapping[str, Any]
    entities: tuple[Mapping[str, Any], ...]
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        # A frozen dataclass refuses ordinary assignment, even here. The
        # constructor may still replace a field through object.__setattr__;
        # records in this file use that once, to store read-only copies of
        # the mappings and lists they were given.
        for name in ("context", "entities", "provenance"):
            object.__setattr__(self, name, read_only(getattr(self, name)))


@dataclass(frozen=True)
class PolicyBundle:
    """A schema and a policy set, identified by the hashes of their exact text."""

    name: str
    schema_text: str
    policy_text: str
    schema_hash: str = field(init=False)
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_hash", sha256_text(self.schema_text))
        object.__setattr__(self, "policy_hash", sha256_text(self.policy_text))


@dataclass(frozen=True)
class Diagnostic:
    policy_id: str | None
    message: str


@dataclass(frozen=True)
class DecisionRecord:
    """Cedar's raw answer for one request, and the outcome the runtime enforces.

    `decision` is computed, not stored: the runtime allows only when Cedar
    allows and reports no evaluation error. An evaluator that cannot produce a
    decision reports raw "no-decision", which is denied.
    """

    request: CedarRequest
    raw: Literal["allow", "deny", "no-decision"]
    determining: tuple[str, ...]
    errors: tuple[Diagnostic, ...]
    policy_hash: str
    schema_hash: str
    evaluator: str
    hypothetical: bool = False

    @property
    def decision(self) -> Literal["allowed", "denied"]:
        return "allowed" if self.raw == "allow" and not self.errors else "denied"

    def to_json(self) -> dict[str, Any]:
        return {**plain(self), "decision": self.decision}


@dataclass(frozen=True)
class PolicyText:
    id: str
    effect: Literal["permit", "forbid"]
    text: str
    json: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "json", read_only(self.json))


@dataclass(frozen=True)
class ValidationReport:
    """Result of parsing and checking a policy set against the schema."""

    valid: bool
    errors: tuple[Diagnostic, ...]
    warnings: tuple[Diagnostic, ...]
    policies: tuple[PolicyText, ...]
    validator: str


class CedarEvaluator(Protocol):
    """Concrete Cedar evaluation. Two adapters implement it (decisions/0002)."""

    name: str

    def validate(self, bundle: PolicyBundle) -> ValidationReport: ...

    def evaluate(self, bundle: PolicyBundle, request: CedarRequest) -> DecisionRecord: ...


# ── Symbolic analysis ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Domain:
    """The inputs a property quantifies over: one request environment of the
    schema, optionally narrowed by a stated Cedar condition on the request."""

    name: str
    principal_type: str
    action: EntityRef
    resource_type: str
    condition: str | None
    description: str


@dataclass(frozen=True)
class AnalysisResult:
    """A property check over a domain, with the raw solver evidence kept."""

    property: Literal["no-permission-expansion", "equivalence", "always-denies"]
    old_policy_hash: str
    new_policy_hash: str
    schema_hash: str
    domain: Domain
    status: Literal["sat", "unsat", "unknown", "timeout", "error"]
    labels: tuple[str, ...]
    witness: Mapping[str, Any] | None
    replay: tuple[DecisionRecord, ...]
    error: str | None
    analyzer: str
    smtlib: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "witness", read_only(self.witness))


# ── Grants: what the kernel profile is derived from ─────────────────────────


class Access(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    METADATA = "metadata"


class Extent(StrEnum):
    FILE = "file"
    SUBTREE = "subtree"


@dataclass(frozen=True)
class PathGrant:
    """One path the installed profile lets the process tree use.

    `path` is the canonical absolute path the kernel checks. Policy grants
    also keep the authored `logical` path; runtime grants say why the runtime
    needs them in `because`.
    """

    path: str
    access: Access
    extent: Extent
    origin: Literal["policy", "runtime"]
    because: tuple[str, ...]
    logical: str | None = None


@dataclass(frozen=True)
class GrantPlan:
    """Platform-neutral input to every backend's ProfileRenderer.

    Designed from the Seatbelt backend's needs (PLAN.md, primacy rule 1).
    The only network destination is the per-run proxy on 127.0.0.1.
    """

    task: tuple[PathGrant, ...]
    runtime: tuple[PathGrant, ...]
    protected: tuple[str, ...]
    proxy_port: int
    policy_hash: str


@dataclass(frozen=True)
class EligibleEndpoint:
    endpoint: str
    policy_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProxyPlan:
    """Configuration the proxy derives from policy text before launch."""

    eligible: tuple[EligibleEndpoint, ...]
    policy_hash: str


# ── Backends ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BackendCapabilities:
    profile_format: Literal["sbpl", "landlock+bwrap+seccomp", "none"]
    separate_read_write_grants: bool
    controls_truncate: bool
    pid_isolation: bool
    network_mechanism: Literal["port-allow", "namespace", "none"]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    backend: BackendName
    checks: tuple[DoctorCheck, ...]
    native_execution: bool

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


@dataclass(frozen=True)
class RunSpec:
    """Canonical paths of one run. `private` is never inside any grant."""

    run_id: str
    run_dir: str
    workspace: str
    home: str
    tmp: str
    private: str


@dataclass(frozen=True)
class WorkloadSpec:
    run_id: str
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: str
    stdout_path: str
    stderr_path: str
    deadline_s: float
    output_limit_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "env", read_only(self.env))


@dataclass(frozen=True)
class PreparedProfile:
    backend: BackendName
    profile_format: str
    profile_path: str | None
    profile_sha256: str | None
    disclosed: tuple[str, ...]


@dataclass(frozen=True)
class ContainedProcess:
    run_id: str
    pid: int
    backend: BackendName
    started_at: float


@dataclass(frozen=True)
class ProbeResult:
    name: str
    expected: str
    observed: str
    passed: bool


@dataclass(frozen=True)
class ContainmentReport:
    """Whether the workload may be admitted, and on what evidence.

    A native backend may admit only a contained, probe-confirmed process.
    Only the test double admits without containment, and it says so.
    """

    enforcement: Enforcement
    contained: bool
    admit: bool
    probes: tuple[ProbeResult, ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.enforcement != "none" and self.admit and not self.contained:
            raise ValueError("a native backend cannot admit an uncontained workload")
        if self.enforcement == "none" and self.contained:
            raise ValueError("the test backend never reports containment")


@dataclass(frozen=True)
class TeardownReport:
    """What `stop` did: the processes it stopped, any it could not, and what it
    could not verify about the tree."""

    exit_status: int | None
    stopped: tuple[int, ...]
    survivors: tuple[int, ...]
    verified: bool
    limits: tuple[str, ...]


class LaunchRefused(RuntimeError):
    """A backend refused to prepare, launch, or admit. The run does not start."""


class SupervisorBackend(Protocol):
    """Native process lifecycle and installed enforcement artifacts.

    See PLAN.md, Backend module boundary. Backends are registered by explicit
    name in composition.py; no core module imports one.

    The supervisor calls these in order:
      launch   start the workload held at a gate, under the prepared profile
      confirm  run the probes; release the gate only if they pass (`admit`)
      wait     wait up to `deadline_s` for the workload to exit by itself;
               return its exit status, or None if it is still running
      stop     stop the whole process tree, descendants included, and report
    Any refusal raises LaunchRefused.
    """

    name: BackendName

    def capabilities(self) -> BackendCapabilities: ...

    def doctor(self) -> DoctorReport: ...

    def prepare(self, plan: GrantPlan, run: RunSpec) -> PreparedProfile: ...

    def launch(self, prepared: PreparedProfile, workload: WorkloadSpec) -> ContainedProcess: ...

    def confirm(self, process: ContainedProcess) -> ContainmentReport: ...

    def wait(self, process: ContainedProcess, deadline_s: float) -> int | None: ...

    def stop(self, process: ContainedProcess) -> TeardownReport: ...


class ProfileRenderer(Protocol):
    """Renders a GrantPlan into one backend's profile text. Pure."""

    profile_format: str

    def render(self, plan: GrantPlan) -> str: ...


# ── Agent and model ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", read_only(self.arguments))


@dataclass(frozen=True)
class Observation:
    """What a tool reported back to the agent. Agent-side data, untrusted."""

    tool: str
    ok: bool
    output: str
    detail: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", read_only(self.detail))


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_call: ToolCall | None


@dataclass(frozen=True)
class Turn:
    reply: ModelReply
    observation: Observation | None


class ModelAdapter(Protocol):
    """Provider protocol conversion. Configuration, never permission."""

    name: str

    def reply(self, task: str, history: Sequence[Turn]) -> ModelReply: ...


# ── Evidence ────────────────────────────────────────────────────────────────

Layer = Literal["agent", "kernel", "proxy", "cedar", "solver", "supervisor", "fixture"]
Provenance = Literal[
    "host-enforcement", "agent-reported", "probe", "installed-profile", "symbolic", "lifecycle",
    "fixture-receipt",
]


@dataclass(frozen=True)
class EvidenceEvent:
    """One ordered, immutable record of a run. Agent-reported payloads are data."""

    seq: int
    run_id: str
    kind: str
    layer: Layer
    provenance: Provenance
    enforcement: Enforcement
    mode: Mode
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", read_only(self.payload))


@dataclass(frozen=True)
class RunRecord:
    """Everything one run produced, in order. `enforcement` and `mode` label all of it.

    `profile_sha256` is the profile of an admitted run. A refused run has none;
    if a profile was prepared before the refusal, its hash is in the events.
    """

    run_id: str
    enforcement: Enforcement
    mode: Mode
    status: Literal["completed", "refused", "failed"]
    task: str
    policy_name: str
    policy_hash: str
    schema_hash: str
    fixture_variant: str
    profile_sha256: str | None
    refusal: str | None
    events: tuple[EvidenceEvent, ...]


# ── Commands ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CommandResult:
    """The stored outcome of one explicit command. Retrying returns this."""

    command_id: str
    kind: str
    input_hash: str
    status: Literal["running", "succeeded", "refused", "failed"]
    result: Mapping[str, Any]
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", read_only(self.result))
        object.__setattr__(self, "payload", read_only(self.payload))


class RunController(Protocol):
    """Versioned commands with idempotency; shared by gateway, CLI, notebooks."""

    def submit(self, command_id: str, kind: str, payload: Mapping[str, Any]) -> CommandResult: ...

    def result(self, command_id: str) -> CommandResult | None: ...
