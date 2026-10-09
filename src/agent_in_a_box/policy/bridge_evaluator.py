"""Concrete Cedar decisions through the pinned bridge: the interchangeable evaluator.

Same CedarEvaluator contract as evaluator.CedarpyEvaluator, and the same
contract cases (tests/policy/test_evaluator_contract.py). Spawns one bridge
process per call, so it is used for validation, analysis replay
cross-checks, and tests rather than on the proxy's per-request path.
"""

from __future__ import annotations

from agent_in_a_box.contracts import (
    CedarRequest, DecisionRecord, Diagnostic, PolicyBundle, PolicyText, ValidationReport, plain,
)
from agent_in_a_box.policy import bridge, toolchain
from agent_in_a_box.policy.bridge import BridgeError


class BridgeEvaluator:
    def __init__(self) -> None:
        pinned = toolchain.pinned("cedar", "cedar_policy")
        self.name = f"agent-in-a-box-cedar bridge (cedar-policy {pinned})"

    def validate(self, bundle: PolicyBundle) -> ValidationReport:
        try:
            answer = bridge.call({"op": "validate", "schema": bundle.schema_text,
                                  "policies": bundle.policy_text})
        except BridgeError as failure:
            problem = Diagnostic(None, failure.message)
            return ValidationReport(False, (problem,), (), (), self.name)
        return ValidationReport(
            valid=answer["valid"],
            errors=tuple(Diagnostic(error["policy_id"], error["message"])
                         for error in answer["errors"]),
            warnings=tuple(Diagnostic(warning["policy_id"], warning["message"])
                           for warning in answer["warnings"]),
            policies=tuple(PolicyText(policy["id"], policy["effect"], policy["text"],
                                      policy["json"]) for policy in answer["policies"]),
            validator=self.name,
        )

    def evaluate(self, bundle: PolicyBundle, request: CedarRequest) -> DecisionRecord:
        command = {
            "op": "authorize",
            "schema": bundle.schema_text,
            "policies": bundle.policy_text,
            "request": {
                "principal": request.principal.to_json(),
                "action": request.action.to_json(),
                "resource": request.resource.to_json(),
                "context": plain(request.context),
            },
            "entities": plain(request.entities),
        }
        try:
            answer = bridge.call(command)
        except BridgeError as failure:
            problem = Diagnostic(None, str(failure))
            return DecisionRecord(request, "no-decision", (), (problem,), bundle.policy_hash,
                                  bundle.schema_hash, self.name)
        errors = tuple(Diagnostic(error["policy_id"], error["message"])
                       for error in answer["errors"])
        return DecisionRecord(request, answer["decision"], tuple(answer["determining"]), errors,
                              bundle.policy_hash, bundle.schema_hash, self.name)
