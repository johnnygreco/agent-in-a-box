"""What the proxy accepts as an HTTP request: the first of its four checks.

mitmproxy parses the bytes. This module decides whether the parsed request
is one the proxy supports and can describe truthfully to Cedar. Anything else
is refused before Cedar is asked: we never forward a request we did not
inspect.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_in_a_box.policy import requests

LATER = "inspected HTTPS arrives in Milestone 3"


@dataclass(frozen=True)
class ParsedRequest:
    """What the proxy parsed from the client's request line and headers."""

    method: str
    scheme: str
    host: str
    port: int
    target: str
    host_header: str | None
    http_version: str
    upgrade: bool


def is_absolute_path(target: str) -> bool:
    """A request target the proxy can hand to Cedar as a path: starts with '/',
    printable ASCII, with no spaces, fragments, or backslashes."""
    if not target.startswith("/"):
        return False
    if not (target.isascii() and target.isprintable()):
        return False
    return not any(character in target for character in " #\\")


def host_header_agrees(parsed: ParsedRequest) -> bool:
    """The Host header must name the same host (and port, if given) as the target."""
    header = (parsed.host_header or "").lower()
    host = parsed.host.lower()
    return header in (host, f"{host}:{parsed.port}")


def protocol_problem(parsed: ParsedRequest) -> str | None:
    """Why the proxy will not handle this request, or None if it will."""
    if parsed.method == "CONNECT":
        return f"opaque CONNECT tunnels cannot be inspected ({LATER})"
    if parsed.scheme != "http":
        return f"scheme {parsed.scheme!r} is not supported ({LATER})"
    if not parsed.http_version.startswith("HTTP/1."):
        return f"{parsed.http_version} is not supported"
    if parsed.method not in requests.SUPPORTED_METHODS:
        return f"method {parsed.method!r} is not supported"
    if parsed.upgrade:
        return "protocol upgrades (WebSocket and others) are not supported"
    if not is_absolute_path(parsed.target):
        return f"request target {parsed.target!r} is not an absolute path"
    if not host_header_agrees(parsed):
        return f"Host header {parsed.host_header!r} disagrees with the request target"
    try:
        requests.endpoint_id(parsed.host, parsed.port)
    except ValueError as error:
        return str(error)
    return None
