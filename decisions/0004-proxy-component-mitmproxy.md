# 0004. Per-run egress proxy: mitmproxy in regular mode, with our decision path in front of every forward

Date: 2026-10-09
Status: accepted

## Context

PLAN.md requires an established proxy component, selected in Milestone 0, so we do not implement HTTP or TLS parsing ourselves; the default was to evaluate mitmproxy first and choose the component that passes the M0 proxy tests with the least custom protocol code. The proxy must decide before anything is sent upstream, so that a refused request never reaches the fixture handler; take identity from the run, not from headers; refuse opaque CONNECT tunnels and unsupported protocols rather than forward them uninspected; and later (Milestone 3) terminate TLS with a per-run CA trusted only by contained clients.

## Decision

Use **mitmproxy 12.2.3** (MIT license, pinned with hashes in `uv.lock`) in regular (explicit proxy) mode, one process per run, started and stopped by the supervisor outside the workload boundary (`src/agent_in_a_box/network/proxy_server.py`, about 110 lines). mitmproxy only parses HTTP. Every decision is made by our decision path (`src/agent_in_a_box/network/proxy.py`, within the 150-line budget), which runs four checks in order (protocol, Cedar NetworkConnect, route eligibility, Cedar HttpRequest) in the `requestheaders` hook, before mitmproxy opens an upstream connection. A refusal is answered by the proxy itself (`403`, JSON body, `X-Agent-In-A-Box-Refused` header) and recorded; an allowed request is re-addressed to the lab transport for its logical endpoint with the original `Host` header kept. CONNECT is refused in the `http_connect` hook until inspected HTTPS is implemented. HTTP/2, WebSocket, and raw TCP are disabled through mitmproxy options. mitmproxy's configuration directory, including the CA it generates at startup, is the run's private directory, which is outside every grant and denied by every profile. Nothing installs or trusts that CA in Milestone 0.

Evaluation on 2026-10-09 (Linux, test backend), all passing in `tests/network/`:

- an allowed GET reaches the fixture; the fixture's receipt log has exactly that request;
- a refused POST with a 100 KB body never reaches the fixture handler (no receipt), and the decision record names the Cedar check and the determining policies;
- a `Host` header that disagrees with the request target is refused before Cedar is asked;
- a header claiming another principal has no effect on the Cedar request;
- a CONNECT tunnel is refused;
- the proxy refuses to start if its policy file no longer matches the hash the supervisor recorded.

Custom protocol code: none. Our code reads fields mitmproxy already parsed (method, scheme, host, port, request target, Host header, HTTP version, Upgrade header).

## Alternatives rejected

- **A small asyncio HTTP/1.1 proxy of our own.** It would be readable, but it means writing request parsing, framing, and later TLS interception ourselves, which PLAN.md rules out.
- **Envoy or Squid with an external authorization callout.** Strong proxies, but they add a non-Python process with its own configuration language, and the decision path would live in a separate service, which is harder to read in chapter 9 and to test per request.
- **`proxy.py`.** Pluggable and Python, but less established for TLS interception, which Milestone 3 needs.

## Consequences

- mitmproxy brings dependencies with native code: `cryptography`, `aioquic`, `pylsqpack`, `zstandard`, `brotli`, `bcrypt`, `argon2-cffi-bindings`, `msgpack`, `tornado`, and `mitmproxy_rs`. On Linux it also installs `mitmproxy_linux`, and on macOS `mitmproxy_macos`, for local capture modes we do not use. All are pinned by hash in `uv.lock`.
- Starting a proxy costs about one second per run, including CA generation.
- For plain HTTP, NetworkConnect is evaluated for every request rather than once per upstream connection, because one client connection to an explicit proxy can carry requests for different hosts. This is stricter than per-connection evaluation and is recorded in the decision records.
- Redirects are not followed by the proxy. A client that follows a redirect sends a new request, which goes through all four checks. A redirect fixture and its tests arrive with Milestone 3's bypass and redirect tests.
- Milestone 3 builds inspected HTTPS on mitmproxy's TLS interception, with the per-run CA kept in the run's private directory and installed only into the contained clients' trust configuration. A client that cannot use it fails; nothing falls back to opaque forwarding.
- The proxy's own correctness is not covered by any Cedar proof (invariant 5). Chapter 6 uses this.

## Plan sections affected

PLAN.md: Open questions and defaults (HTTP/TLS proxy component row); Network mediation (component named).
