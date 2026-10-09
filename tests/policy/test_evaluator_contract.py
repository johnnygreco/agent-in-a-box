"""Contract cases every CedarEvaluator must pass (decisions/0002).

Expected outcomes are authored by hand from the policy text in
policies/variants and the rules of Cedar authorization (a request is allowed
when some permit is satisfied and no forbid is satisfied; determining
policies are the satisfied permits for an allow, the satisfied forbids for a
deny). They were not produced by running either adapter. The official CLI
checks the same raw decisions independently.
"""

from __future__ import annotations

import pytest

from agent_in_a_box.policy import requests
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.bridge_evaluator import BridgeEvaluator
from agent_in_a_box.policy.evaluator import CedarpyEvaluator
from agent_in_a_box.policy.toolchain import load as load_toolchain
from tests.policy.cli_oracle import cli_decide

pytestmark = pytest.mark.toolchain

EVALUATORS = [CedarpyEvaluator(), BridgeEvaluator()]
REF = ("reference.fixture", 80)

# (variant, request, raw decision, determining policy ids)
HTTP_CASES = [
    ("P0", ("GET", "/reference"), "allow", ["get-reference"]),
    ("P0", ("POST", "/reference"), "deny", []),
    ("P0", ("GET", "/reference/"), "deny", []),
    ("P0", ("GET", "/missing"), "deny", []),
    ("P1", ("GET", "/reference"), "allow", ["get-reference"]),
    ("P1", ("POST", "/reference"), "allow", ["get-reference"]),
    ("P1", ("PUT", "/reference"), "deny", []),
    ("P2", ("GET", "/reference"), "allow", ["any-method-reference"]),
    ("P2", ("POST", "/reference"), "deny", ["forbid-post"]),
    ("P2", ("PUT", "/reference"), "allow", ["any-method-reference"]),
    ("P2", ("DELETE", "/reference"), "allow", ["any-method-reference"]),
    ("P3", ("GET", "/reference"), "deny", ["forbid-all-http"]),
    ("P3", ("POST", "/reference"), "deny", ["forbid-all-http"]),
    ("P4", ("GET", "/reference"), "deny", ["forbid-reference"]),
    ("P4", ("GET", "/reference/"), "deny", []),
    ("P5", ("GET", "/reference"), "allow", ["get-reference"]),
    ("P5", ("POST", "/reference"), "deny", []),
    ("P6", ("GET", "/reference"), "allow", ["get-reference"]),
    ("P6", ("POST", "/reference"), "deny", []),
]

CONNECT_CASES = [
    ("P0", ("reference.fixture", 80), "allow", ["connect-reference"]),
    ("P0", ("Reference.Fixture.", 80), "allow", ["connect-reference"]),
    ("P0", ("reference.fixture", 8080), "deny", []),
    ("P0", ("collector.example", 80), "deny", []),
    ("P6", ("reference.fixture", 80), "allow", ["connect-reference"]),
]

ALL_CASES = [
    (v, requests.http_request(*REF, m, p), raw, det) for v, (m, p), raw, det in HTTP_CASES
] + [(v, requests.network_connect(h, port), raw, det) for v, (h, port), raw, det in CONNECT_CASES]

OVERFLOW = (
    '\n@id("overflow")\npermit (principal, action == Sandbox::Action::"HttpRequest", resource)\n'
    "when { resource.port * 9223372036854775807 > 0 };\n"
)


def _ids(cases):
    return [f"{v}-{r.action.id}-{dict(r.context) or r.resource.id}" for v, r, *_ in cases]


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda e: e.name.split()[0])
@pytest.mark.parametrize(("variant", "request_", "raw", "determining"), ALL_CASES,
                         ids=_ids(ALL_CASES))
def test_decision_and_determining_policies(evaluator, variant, request_, raw, determining):
    record = evaluator.evaluate(schema.load_variant(variant), request_)
    assert record.raw == raw
    assert list(record.determining) == determining
    assert record.errors == ()
    assert record.decision == ("allowed" if raw == "allow" else "denied")


@pytest.mark.parametrize(("variant", "request_", "raw", "determining"), ALL_CASES,
                         ids=_ids(ALL_CASES))
def test_official_cli_agrees(variant, request_, raw, determining):
    cli = load_toolchain().cedar_cli
    if cli is None:
        pytest.skip("official CLI not installed; run tooling/bootstrap.py --with-cli")
    assert cli_decide(cli, schema.load_variant(variant), request_) == (raw, determining)


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda e: e.name.split()[0])
def test_evaluation_error_denies_even_when_cedar_allows(evaluator):
    """Raw Cedar skips an erroring policy; the runtime denies (formal review F2)."""
    text = schema.load_variant("P0").policy_text + OVERFLOW
    bundle = schema.bundle_from_text("P0+overflow", text)
    record = evaluator.evaluate(bundle, requests.http_request(*REF, "GET", "/reference"))
    assert record.raw == "allow"
    assert record.determining == ("get-reference",)
    assert [e.policy_id for e in record.errors] == ["overflow"]
    assert "overflow" in record.errors[0].message
    assert record.decision == "denied"


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda e: e.name.split()[0])
def test_malformed_request_is_no_decision_and_denied(evaluator):
    good = requests.http_request(*REF, "GET", "/reference")
    bad = type(good)(good.principal, good.action, good.resource, {"method": "GET"},
                     good.entities, good.provenance)
    record = evaluator.evaluate(schema.load_variant("P0"), bad)
    assert record.raw == "no-decision"
    assert record.decision == "denied"
    assert record.errors


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda e: e.name.split()[0])
def test_policy_without_id_is_refused(evaluator):
    bundle = schema.bundle_from_text(
        "no-id", 'permit (principal, action == Sandbox::Action::"HttpRequest", resource);\n'
    )
    assert not evaluator.validate(bundle).valid
    assert evaluator.evaluate(bundle, requests.http_request(*REF, "GET", "/")).decision == "denied"


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda e: e.name.split()[0])
@pytest.mark.parametrize("variant", schema.variant_names())
def test_shipped_variants_are_checked_against_the_schema(evaluator, variant):
    report = evaluator.validate(schema.load_variant(variant))
    assert report.valid, report.errors


def test_both_evaluators_see_the_same_policy_json():
    for variant in schema.variant_names():
        a, b = (e.validate(schema.load_variant(variant)) for e in EVALUATORS)
        assert [(p.id, p.effect, dict(p.json)) for p in a.policies] == [
            (p.id, p.effect, dict(p.json)) for p in b.policies
        ]


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda e: e.name.split()[0])
def test_cedar_4_12_canary(evaluator):
    """cedar-policy 4.12 rejects an action scope that cannot apply; 4.13 only warns.

    cedarpy reports no Cedar version at run time, so this checks the bundled
    version by behavior (decisions/0002). Update it when the stack moves.
    """
    bundle = schema.bundle_from_text(
        "canary",
        '@id("canary")\npermit (principal, action == Sandbox::Action::"ReadFile", '
        'resource == Sandbox::NetworkEndpoint::"x:1");\n',
    )
    report = evaluator.validate(bundle)
    assert not report.valid
    assert report.errors[0].policy_id == "canary"
    assert "applicable action" in report.errors[0].message
