"""Concrete Cedar decisions, in process, through cedarpy (decisions/0002).

The runtime allows a request only when Cedar allows it and reports no
evaluation error (DecisionRecord.decision). Determining policies and errors
are reported by their authored @id (authored_ids.py).
"""

from __future__ import annotations

import functools
from importlib.metadata import version

import cedarpy

from agent_in_a_box.contracts import (
    CedarRequest, DecisionRecord, Diagnostic, PolicyBundle, PolicyText, ValidationReport, plain,
)
from agent_in_a_box.policy import toolchain
from agent_in_a_box.policy.authored_ids import determining, parse, with_authored_ids

RAW_DECISION = {"Allow": "allow", "Deny": "deny"}  # cedarpy's NoDecision -> "no-decision"


@functools.lru_cache(maxsize=8)
def parse_schema(schema_text: str) -> cedarpy.Schema:
    return cedarpy.Schema.from_str(schema_text)


class CedarpyEvaluator:
    def __init__(self) -> None:
        bundled = toolchain.pinned("cedarpy", "bundled_cedar_policy")
        self.name = f"cedarpy {version('cedarpy')} (cedar-policy {bundled})"

    def validate(self, bundle: PolicyBundle) -> ValidationReport:
        try:
            parsed = parse(bundle.policy_text)
        except ValueError as error:  # parse errors and PolicyIdError
            return ValidationReport(False, (Diagnostic(None, str(error)),), (), (), self.name)
        result = cedarpy.validate_policies(bundle.policy_text, parse_schema(bundle.schema_text))
        errors = []
        for error in result.errors:
            _, message = with_authored_ids(error.error, parsed.names)
            errors.append(Diagnostic(parsed.names.get(error.policy_id, error.policy_id), message))
        policies = [PolicyText(parsed.names[positional_id], policy["effect"], "", policy)
                    for positional_id, policy in parsed.json.items()]
        policies.sort(key=lambda policy: policy.id)
        return ValidationReport(result.validation_passed, tuple(errors), (), tuple(policies),
                                self.name)

    def evaluate(self, bundle: PolicyBundle, request: CedarRequest) -> DecisionRecord:
        try:
            parsed = parse(bundle.policy_text)
        except ValueError as error:
            problem = Diagnostic(None, str(error))
            return DecisionRecord(request, "no-decision", (), (problem,), bundle.policy_hash,
                                  bundle.schema_hash, self.name)
        cedar_request = {
            "principal": request.principal.to_json(),
            "action": request.action.to_json(),
            "resource": request.resource.to_json(),
            "context": plain(request.context),
        }
        result = cedarpy.is_authorized(cedar_request, parsed.policy_set, plain(request.entities),
                                       parse_schema(bundle.schema_text))
        errors = [Diagnostic(*with_authored_ids(message, parsed.names))
                  for message in result.diagnostics.errors]
        return DecisionRecord(
            request=request,
            raw=RAW_DECISION.get(result.decision.value, "no-decision"),
            determining=determining(result.diagnostics.reasons, parsed.names),
            errors=tuple(errors),
            policy_hash=bundle.policy_hash,
            schema_hash=bundle.schema_hash,
            evaluator=self.name,
        )
