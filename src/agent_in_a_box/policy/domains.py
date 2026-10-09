"""Analysis domains: the inputs a property quantifies over (decisions/0005).

A domain is one request environment of the schema (principal type, action,
resource type), optionally narrowed by one stated Cedar condition on the
request. A condition is encoded exactly, as a forbid added to both policy
sets in a query:

    Allow(P + forbid-outside-D, x)  =  Allow(P, x) AND D(x)
"""

from __future__ import annotations

from agent_in_a_box.contracts import CedarEvaluator, CedarRequest, Domain, PolicyBundle
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.requests import SUPPORTED_METHODS

QUOTED_METHODS = ", ".join(f'"{method}"' for method in SUPPORTED_METHODS)

# HttpRequest requests the proxy can construct. The method list is the proxy's
# own: it refuses any other method before Cedar is asked.
D_HTTP = Domain(
    name="D_http",
    principal_type=schema.PROCESS,
    action=schema.action(schema.HTTP_REQUEST),
    resource_type=schema.NETWORK_ENDPOINT,
    condition=f"[{QUOTED_METHODS}].contains(context.method)",
    description="HttpRequest requests the proxy can construct: a supported method, any path, "
    "any endpoint, and any entity data the schema allows.",
)

D_CONNECT = Domain(
    name="D_connect",
    principal_type=schema.PROCESS,
    action=schema.action(schema.NETWORK_CONNECT),
    resource_type=schema.NETWORK_ENDPOINT,
    condition=None,
    description="Every NetworkConnect request the schema allows.",
)

DOMAINS = {domain.name: domain for domain in (D_HTTP, D_CONNECT)}


def domain_policy(domain: Domain) -> str:
    """The forbid that restricts a policy set to `domain`; empty for a whole environment."""
    if domain.condition is None:
        return ""
    return (f'\n@id("domain:{domain.name}")\n'
            f"forbid (principal is {domain.principal_type}, action == {domain.action}, "
            f"resource is {domain.resource_type})\n"
            f"unless {{ {domain.condition} }};\n")


def in_domain(evaluator: CedarEvaluator, domain: Domain, schema_text: str,
              request: CedarRequest) -> bool:
    """Whether a concrete request satisfies the domain's condition."""
    if domain.condition is None:
        return True
    probe_text = (f'@id("in-domain")\npermit (principal, action == {domain.action}, resource)\n'
                  f"when {{ {domain.condition} }};\n")
    probe = PolicyBundle(f"domain:{domain.name}", schema_text, probe_text)
    return evaluator.evaluate(probe, request).decision == "allowed"
