"""The proxy's decision path: what happens to one HTTP request.

Four checks, in order, each recorded. The request is forwarded only if all
pass; a refusal names the first check that failed. Nothing is sent upstream
before the decision, so a refused request never reaches the fixture.

  1. protocol  a request the proxy supports and can describe (protocol.py)
  2. connect   Cedar NetworkConnect for the normalized endpoint
  3. route     the endpoint is an eligible route (derived from policy names,
               compiler.py) and the lab has a transport for it
  4. request   Cedar HttpRequest for the parsed method and path

Identity comes from the run this proxy serves, never from a header the agent
sent. For plain HTTP, NetworkConnect is evaluated for every request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent_in_a_box.contracts import CedarEvaluator, DecisionRecord, PolicyBundle, ProxyPlan, plain
from agent_in_a_box.network.protocol import ParsedRequest, protocol_problem
from agent_in_a_box.policy import requests


@dataclass(frozen=True)
class Route:
    """A lab transport for a logical endpoint. Nonsecret; recorded in bundles."""

    endpoint: str
    host: str
    port: int


@dataclass(frozen=True)
class Check:
    """One check's outcome. Cedar checks keep their full decision record."""

    name: str
    passed: bool
    detail: str
    decision: DecisionRecord | None = None


@dataclass(frozen=True)
class ProxyDecision:
    seq: int
    run_id: str
    method: str
    endpoint: str | None
    path: str | None
    checks: tuple[Check, ...]
    forwarded: bool
    refused_by: str | None
    route: Route | None

    def to_json(self) -> dict:
        data = plain(self)
        data["checks"] = []
        for check in self.checks:
            decision = check.decision.to_json() if check.decision else None
            data["checks"].append({**plain(check), "decision": decision})
        data["label"] = "allowed" if self.forwarded else "refused"
        return data


class DecisionPath:
    def __init__(self, run_id: str, bundle: PolicyBundle, evaluator: CedarEvaluator,
                 plan: ProxyPlan, routes: Mapping[str, Route]) -> None:
        if plan.policy_hash != bundle.policy_hash:
            raise ValueError("proxy plan was derived from a different policy")
        self.run_id = run_id
        self.bundle = bundle
        self.evaluator = evaluator
        self.eligible = {eligible.endpoint for eligible in plan.eligible}
        self.routes = dict(routes)
        self.seq = 0

    def decide(self, parsed: ParsedRequest) -> ProxyDecision:
        """Run the four checks in order. The first that fails refuses the request."""
        self.seq += 1
        checks: list[Check] = []

        problem = protocol_problem(parsed)
        checks.append(Check("protocol", problem is None, problem or "plain HTTP/1.x request"))
        if problem is not None:
            return self.refused(parsed, checks, endpoint=None, path=None)
        endpoint = requests.endpoint_id(parsed.host, parsed.port)
        path = parsed.target.split("?", 1)[0]

        connect_request = requests.network_connect(parsed.host, parsed.port)
        connect = self.evaluator.evaluate(self.bundle, connect_request)
        checks.append(Check("connect", connect.decision == "allowed",
                            f"Cedar NetworkConnect {connect.decision}", connect))
        if connect.decision != "allowed":
            return self.refused(parsed, checks, endpoint, path)

        checks.append(self.route_check(endpoint))
        if not checks[-1].passed:
            return self.refused(parsed, checks, endpoint, path)

        http_request = requests.http_request(parsed.host, parsed.port, parsed.method, path)
        http = self.evaluator.evaluate(self.bundle, http_request)
        checks.append(Check("request", http.decision == "allowed",
                            f"Cedar HttpRequest {http.decision}", http))
        if http.decision != "allowed":
            return self.refused(parsed, checks, endpoint, path)

        return ProxyDecision(self.seq, self.run_id, parsed.method, endpoint, path, tuple(checks),
                             forwarded=True, refused_by=None, route=self.routes[endpoint])

    def route_check(self, endpoint: str) -> Check:
        if endpoint not in self.eligible:
            reason = "no NetworkConnect permit names this endpoint in its scope"
            return Check("route", False, reason)
        if endpoint not in self.routes:
            return Check("route", False, "the lab has no transport for this endpoint")
        return Check("route", True, "eligible route with a lab transport")

    def refused(self, parsed: ParsedRequest, checks: list[Check], endpoint: str | None,
                path: str | None) -> ProxyDecision:
        """A refusal names the last check run, which is the one that failed."""
        return ProxyDecision(self.seq, self.run_id, parsed.method, endpoint, path, tuple(checks),
                             forwarded=False, refused_by=checks[-1].name, route=None)
