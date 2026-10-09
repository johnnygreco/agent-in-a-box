"""Build Cedar requests from facts the runtime established (chapter 1's source).

The agent supplies none of these values. The supervisor supplies the process
identity; the proxy supplies the destination it normalized and the method and
path it parsed from the request line. Headers the agent sends, including any
identity claim, are never read here.
"""

from __future__ import annotations

from agent_in_a_box.contracts import CedarRequest, EntityRef
from agent_in_a_box.policy import schema

# The only methods the proxy constructs requests for; it refuses any other.
SUPPORTED_METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS")
PROVENANCE_PRINCIPAL = "supervisor: one sandbox process per run"
PROVENANCE_RESOURCE = "proxy: destination it normalized from the request target"


def normalize_host(host: str) -> str:
    """Lowercase, and strip one trailing dot: a fully qualified DNS name such as
    "reference.fixture." names the same host as "reference.fixture"."""
    if host.endswith("."):
        host = host[:-1]
    allowed = host.isascii() and not any(c.isspace() or c in "/@:" for c in host)
    if not host or not allowed:
        raise ValueError(f"not a host name the proxy accepts: {host!r}")
    return host.lower()


def endpoint_id(host: str, port: int) -> str:
    """The NetworkEndpoint entity id: "host:port" with the normalized host."""
    if not 1 <= port <= 65535:
        raise ValueError(f"port out of range: {port}")
    return f"{normalize_host(host)}:{port}"


def _entities(host: str, port: int) -> tuple[dict, ...]:
    """Entities for one request: the current process, its user and group, and
    the destination endpoint with attributes derived from the endpoint id."""
    host = normalize_host(host)
    process = {
        "uid": schema.CURRENT_PROCESS.to_json(),
        "attrs": {
            "user": {"__entity": schema.SANDBOX_USER.to_json()},
            "group": {"__entity": schema.SANDBOX_GROUP.to_json()},
        },
        "parents": [],
    }
    endpoint = {
        "uid": {"type": schema.NETWORK_ENDPOINT, "id": endpoint_id(host, port)},
        "attrs": {"host": host, "port": port, "host_port": endpoint_id(host, port)},
        "parents": [],
    }
    user = {"uid": schema.SANDBOX_USER.to_json(), "attrs": {}, "parents": []}
    group = {"uid": schema.SANDBOX_GROUP.to_json(), "attrs": {}, "parents": []}
    return (process, user, group, endpoint)


def network_connect(host: str, port: int) -> CedarRequest:
    """The request the proxy submits before it opens an upstream connection."""
    return CedarRequest(
        principal=schema.CURRENT_PROCESS,
        action=schema.action(schema.NETWORK_CONNECT),
        resource=EntityRef(schema.NETWORK_ENDPOINT, endpoint_id(host, port)),
        context={},
        entities=_entities(host, port),
        provenance={
            "principal": PROVENANCE_PRINCIPAL,
            "action": "proxy: the workload asked to reach this endpoint",
            "resource": PROVENANCE_RESOURCE,
        },
    )


def http_request(host: str, port: int, method: str, path: str) -> CedarRequest:
    """The request the proxy submits for each HTTP request it parsed."""
    return CedarRequest(
        principal=schema.CURRENT_PROCESS,
        action=schema.action(schema.HTTP_REQUEST),
        resource=EntityRef(schema.NETWORK_ENDPOINT, endpoint_id(host, port)),
        context={"method": method, "path": path},
        entities=_entities(host, port),
        provenance={
            "principal": PROVENANCE_PRINCIPAL,
            "action": "proxy: it parsed an HTTP request",
            "resource": PROVENANCE_RESOURCE,
            "context.method": "proxy: method from the request line",
            "context.path": "proxy: path from the request target, query removed",
        },
    )
