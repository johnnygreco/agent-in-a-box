"""What the proxy accepts as an HTTP request: the first of its four checks.

mitmproxy parses the bytes. This module decides whether the parsed request
is one the proxy supports and can describe truthfully to Cedar. Anything else
is refused before Cedar is asked: we never forward a request we did not
inspect.

Cedar sees the path exactly as the client spelled it (policy/requests.py).
A spelling an upstream might resolve into a different path is therefore
refused rather than guessed at: a dot segment, an empty segment, or a
percent-encoded slash or dot. The decision record keeps the target as sent
beside the path Cedar saw, so the two can be compared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_in_a_box.policy import requests

LATER = "inspected HTTPS arrives in Milestone 3"
ENCODED_SLASH_OR_DOT = re.compile(r"%2[efEF]")


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
    chunked: bool = False  # a Transfer-Encoding header: the body's length is not declared


def target_problem(target: str) -> str | None:
    """Why the request target cannot be handed to Cedar as a path, or None.

    The target must be an origin-form path: it starts with '/', is printable
    ASCII with no space, '#', or backslash, and spells every segment plainly.
    A trailing slash is an ordinary spelling ('/reference/' is a different
    path from '/reference', and Cedar sees it as one); a dot segment or an
    empty segment before the end is not.
    """
    if not target.startswith("/"):
        return "is not an absolute path"
    if not (target.isascii() and target.isprintable()):
        return "is not printable ASCII"
    if any(character in target for character in " #\\"):
        return "contains a space, '#', or a backslash"
    path = target.split("?", 1)[0]
    segments = path.split("/")[1:]
    if any(segment in (".", "..") for segment in segments):
        return "contains a dot segment, which an upstream could resolve to another path"
    if "" in segments[:-1]:
        return "contains an empty segment"
    if ENCODED_SLASH_OR_DOT.search(path):
        return "percent-encodes a slash or a dot"
    return None


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
    if parsed.chunked:
        return "a chunked request body is not supported; declare its length with Content-Length"
    problem = target_problem(parsed.target)
    if problem is not None:
        return f"request target {parsed.target!r} {problem}"
    if not host_header_agrees(parsed):
        return f"Host header {parsed.host_header!r} disagrees with the request target"
    try:
        requests.endpoint_id(parsed.host, parsed.port)
    except ValueError as error:
        return str(error)
    return None
