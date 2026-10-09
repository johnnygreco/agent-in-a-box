"""Ask the solver whether permission expanded, then replay what it found.

The property (PLAN.md, Formal verification):

    search for x such that  Domain(x) AND Allow(new, x) AND NOT Allow(old, x)

SAT gives a distinguishing input, which is shown as one only after it is
replayed under both policy sets and still distinguishes them. UNSAT means no
permission expansion in the stated domain. UNKNOWN, a timeout, an error, or a
replay disagreement is "no conclusion" and is never counted as success.

With the domain encoded as a forbid on both sides (domains.py), the search
above is exactly the SymCC query `implies(new + D, old + D)`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from agent_in_a_box.contracts import (
    AnalysisResult, CedarEvaluator, CedarRequest, DecisionRecord, Domain, EntityRef, PolicyBundle,
)
from agent_in_a_box.policy import bridge, toolchain
from agent_in_a_box.policy.bridge import BridgeError
from agent_in_a_box.policy.domains import D_HTTP, domain_policy, in_domain

DEFAULT_SOLVER_ARGS = ("--tlimit-per=60000",)
# The lesson's deliberate "no conclusion": a resource limit too small for any query.
STARVED_SOLVER_ARGS = ("--rlimit-per=1",)
# Our property names, and the SymCC query that answers each.
QUERIES = {"no-permission-expansion": "implies", "equivalence": "equivalent"}


def solve(query: str, first: PolicyBundle, second: PolicyBundle, domain: Domain,
          solver_args: tuple[str, ...], emit_smtlib: bool) -> dict[str, Any]:
    """Run one SymCC query through the bridge. A bridge failure becomes
    status "timeout" or "error", never an answer."""
    command = {
        "op": "analyze",
        "property": query,
        "schema": first.schema_text,
        "policies": first.policy_text + domain_policy(domain),
        "other_policies": second.policy_text + domain_policy(domain),
        "request_env": {"principal_type": domain.principal_type,
                        "action": domain.action.to_json(),
                        "resource_type": domain.resource_type},
        "solver": {"path": str(toolchain.load().cvc5), "args": list(solver_args)},
        "emit_smtlib": emit_smtlib,
    }
    try:
        return bridge.call(command, timeout_s=120)
    except BridgeError as failure:
        status = "timeout" if failure.kind == "timeout" else "error"
        return {"status": status, "error": {"kind": failure.kind, "message": failure.message}}


def witness_request(witness: dict[str, Any]) -> CedarRequest:
    """The solver's raw witness as a Cedar request, unchanged."""
    request = witness["request"]
    return CedarRequest(
        principal=EntityRef(**request["principal"]),
        action=EntityRef(**request["action"]),
        resource=EntityRef(**request["resource"]),
        context=request["context"],
        entities=tuple(witness["entities"]),
        provenance={"*": "analyzer: solver witness"},
    )


def replay(evaluator: CedarEvaluator, bundles: tuple[PolicyBundle, ...],
           request: CedarRequest) -> tuple[DecisionRecord, ...]:
    """Evaluate one request concretely under each policy set. No effects."""
    records = []
    for bundle in bundles:
        record = evaluator.evaluate(bundle, request)
        records.append(dataclasses.replace(record, hypothetical=True))
    return tuple(records)


def replay_problem(prop: str, new: DecisionRecord, old: DecisionRecord,
                   inside_domain: bool) -> str | None:
    """Why a witness fails to confirm, or None. Raw Cedar decisions are what the
    solver reasoned about; enforced decisions also deny on evaluation errors."""
    if not inside_domain:
        return "replay disagreement: the witness is outside the domain"
    if prop == "no-permission-expansion":
        raw_distinguishes = new.raw == "allow" and old.raw != "allow"
        enforced_distinguishes = new.decision == "allowed" and old.decision == "denied"
    else:
        raw_distinguishes = new.raw != old.raw
        enforced_distinguishes = new.decision != old.decision
    if not raw_distinguishes:
        return "replay disagreement: raw Cedar decisions do not distinguish the witness"
    if not enforced_distinguishes:
        return "replay disagreement: enforced decisions differ from raw (evaluation errors)"
    return None


def check(prop: str, old: PolicyBundle, new: PolicyBundle, evaluator: CedarEvaluator,
          domain: Domain = D_HTTP, solver_args: tuple[str, ...] = DEFAULT_SOLVER_ARGS,
          emit_smtlib: bool = False) -> AnalysisResult:
    """`prop` is "no-permission-expansion" (old -> new) or "equivalence"."""
    answer = solve(QUERIES[prop], new, old, domain, solver_args, emit_smtlib)
    status = answer["status"]
    witness = answer.get("witness")
    replayed: tuple[DecisionRecord, ...] = ()
    error = None
    if status == "sat":
        request = witness_request(witness)
        replayed = replay(evaluator, (new, old), request)
        inside = in_domain(evaluator, domain, new.schema_text, request)
        error = replay_problem(prop, replayed[0], replayed[1], inside)
        if error is None:
            labels = ("distinguishing input", "confirmed by replay")
        else:
            labels = ("no conclusion",)
    elif status == "unsat" and prop == "no-permission-expansion":
        labels = ("no permission expansion", "proved for domain D")
    elif status == "unsat":
        labels = ("proved for domain D",)
    else:
        labels = ("no conclusion",)
        details = answer.get("error") or {}
        error = details.get("message") or f"solver status {status}"
    symcc = toolchain.pinned("cedar", "cedar_policy_symcc")
    return AnalysisResult(
        property=prop, old_policy_hash=old.policy_hash, new_policy_hash=new.policy_hash,
        schema_hash=old.schema_hash, domain=domain, status=status, labels=labels,
        witness=witness, replay=replayed, error=error,
        analyzer=f"agent-in-a-box-cedar (SymCC {symcc})", smtlib=answer.get("smtlib"),
    )


def task_preserved(evaluator: CedarEvaluator, bundle: PolicyBundle,
                   request: CedarRequest) -> tuple[DecisionRecord, str]:
    """A concrete positive decision for an operation the task needs."""
    record = evaluator.evaluate(bundle, request)
    if record.decision == "allowed":
        return record, "intended task preserved"
    return record, "denied"
