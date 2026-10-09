"""The proxy decision path, without mitmproxy: four checks, first failure refuses.

Expected outcomes follow network/proxy.py's documented order and the policy
text of P0 and P6.
"""

from __future__ import annotations

import pytest

from agent_in_a_box.network.protocol import ParsedRequest
from agent_in_a_box.network.proxy import DecisionPath, Route
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.compiler import compile_policy
from agent_in_a_box.policy.evaluator import CedarpyEvaluator

EV = CedarpyEvaluator()
ROUTE = {"reference.fixture:80": Route("reference.fixture:80", "127.0.0.1", 9999)}


def path_for(variant: str) -> DecisionPath:
    compiled = compile_policy(schema.load_variant(variant), EV)
    return DecisionPath("run-1", compiled.bundle, EV, compiled.proxy, ROUTE)


def request(method="GET", target="/reference", host="reference.fixture", host_header=None,
            scheme="http", version="HTTP/1.1", upgrade=False, port=80):
    return ParsedRequest(method, scheme, host, port, target,
                         host if host_header is None else host_header, version, upgrade)


def checks(decision):
    return [(c.name, c.passed) for c in decision.checks]


def test_allowed_get_passes_all_four_checks_and_is_forwarded():
    decision = path_for("P0").decide(request())
    assert decision.forwarded and decision.refused_by is None
    assert checks(decision) == [("protocol", True), ("connect", True), ("route", True),
                                ("request", True)]
    assert decision.route == ROUTE["reference.fixture:80"]
    assert decision.checks[3].decision.determining == ("get-reference",)
    assert decision.to_json()["label"] == "allowed"


def test_post_is_refused_by_cedar_at_the_request_check():
    decision = path_for("P0").decide(request("POST"))
    assert (decision.forwarded, decision.refused_by) == (False, "request")
    assert decision.route is None
    assert decision.to_json()["label"] == "refused"


def test_query_string_is_not_part_of_the_path_cedar_sees():
    decision = path_for("P0").decide(request(target="/reference?x=1"))
    assert decision.path == "/reference" and decision.forwarded


def test_unknown_endpoint_is_refused_at_connect():
    decision = path_for("P0").decide(request(host="collector.example"))
    assert decision.refused_by == "connect"


def test_p6_cedar_allows_the_connection_but_no_route_is_derived():
    decision = path_for("P6").decide(request())
    assert checks(decision) == [("protocol", True), ("connect", True), ("route", False)]
    assert decision.refused_by == "route"


@pytest.mark.parametrize("bad", [
    request(method="CONNECT"),
    request(scheme="https"),
    request(version="HTTP/2.0"),
    request(method="BREW"),
    request(upgrade=True),
    request(target="reference"),
    request(target="/ref erence"),
    request(target="/réf"),
    request(host_header="evil.example"),
    request(host="bad host"),
    request(port=0),
])
def test_protocol_refusals(bad):
    decision = path_for("P0").decide(bad)
    assert decision.refused_by == "protocol"
    assert [c.name for c in decision.checks] == ["protocol"]


def test_host_header_with_port_and_case_agrees():
    assert path_for("P0").decide(request(host_header="Reference.Fixture:80")).forwarded


def test_plan_from_another_policy_is_rejected():
    p0 = compile_policy(schema.load_variant("P0"), EV)
    with pytest.raises(ValueError):
        DecisionPath("r", schema.load_variant("P1"), EV, p0.proxy, ROUTE)


def test_identity_is_never_read_from_the_request():
    """ParsedRequest has no identity field; principal comes from request construction."""
    decision = path_for("P0").decide(request())
    assert decision.checks[3].decision.request.principal == schema.CURRENT_PROCESS
