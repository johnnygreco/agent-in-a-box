"""The real per-run proxy (mitmproxy + our decision path) in front of the real fixture.

The central check (M0 gate): a refused request never reaches the fixture
handler. The fixture logs every request that reaches its handler before
answering, so a refused request must leave no receipt. Since decisions/0015,
a request without the run's credential is not even decided, and the fixture
answers only requests the proxy stamped.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_in_a_box.experiments.scenario import REFERENCE, fixture_service
from agent_in_a_box.network.fixture_service import STAMP_ENV, STAMP_HEADER
from agent_in_a_box.network.proxy import Route
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.compiler import compile_policy
from agent_in_a_box.policy.evaluator import CedarpyEvaluator
from agent_in_a_box.supervisor import dataplane, runs
from agent_in_a_box.supervisor.dataplane import Lab


@pytest.fixture
def lab(tmp_path):
    """A fixture service and a proxy for P0, as a run would start them."""
    run = runs.create_run(tmp_path / "runs")
    receipts = tmp_path / "receipts.jsonl"
    stamp = secrets.token_urlsafe(8)
    with fixture_service("default", receipts, stamp) as route:
        compiled = compile_policy(schema.load_variant("P0"), CedarpyEvaluator())
        proxy = dataplane.start_proxy(run, compiled, Lab({REFERENCE: route}, stamp), "cedarpy")
        try:
            yield proxy, receipts, route
        finally:
            dataplane.stop(proxy.process)


def send(proxy, method, url, body=None, headers=None, credential=True):
    """A request through the proxy, with the run's credential unless told otherwise."""
    proxy_url = proxy.url if credential else f"http://127.0.0.1:{proxy.port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url}))
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def receipts_of(path: Path) -> list[tuple[str, str]]:
    return [(r["method"], r["target"]) for r in map(json.loads, path.read_text().splitlines())]


def decisions_of(proxy) -> list[dict]:
    return [json.loads(line) for line in proxy.decisions_path.read_text().splitlines()]


def test_allowed_get_reaches_the_fixture(lab):
    proxy, receipts, _ = lab
    status, _, body = send(proxy, "GET", "http://reference.fixture/reference")
    assert status == 200 and b"temperature_c,21.0" in body
    assert receipts_of(receipts) == [("GET", "/reference")]
    decision = decisions_of(proxy)[0]
    assert decision["label"] == "allowed"
    assert decision["checks"][0]["detail"].endswith("target as sent: /reference")


def test_a_request_without_the_run_credential_is_neither_decided_nor_recorded(lab):
    """Another process on this host cannot put a request into the run's evidence."""
    proxy, receipts, _ = lab
    status, _, _ = send(proxy, "GET", "http://reference.fixture/reference", credential=False)
    assert status == 407
    assert decisions_of(proxy) == [] and receipts_of(receipts) == []


def test_the_proxy_forwards_one_stamp_and_no_proxy_credential(tmp_path):
    """What the upstream sees: exactly the run's stamp, whatever the client sent under that
    name, and never the Proxy-Authorization the client used to reach the proxy."""
    seen: list[list[tuple[str, str]]] = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            seen.append([(name.lower(), value) for name, value in self.headers.items()])
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *arguments):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    run = runs.create_run(tmp_path / "runs")
    compiled = compile_policy(schema.load_variant("P0"), CedarpyEvaluator())
    route = Route(REFERENCE, "127.0.0.1", upstream.server_address[1])
    proxy = dataplane.start_proxy(run, compiled, Lab({REFERENCE: route}, "the-stamp"), "cedarpy")
    try:
        status, _, _ = send(proxy, "GET", "http://reference.fixture/reference",
                            headers={STAMP_HEADER: "forged"})
    finally:
        dataplane.stop(proxy.process)
        upstream.shutdown()
    assert status == 200 and len(seen) == 1
    assert [value for name, value in seen[0] if name == STAMP_HEADER.lower()] == ["the-stamp"]
    assert "proxy-authorization" not in [name for name, _ in seen[0]]


def test_the_fixture_refuses_to_start_without_a_stamp(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key != STAMP_ENV}
    result = subprocess.run([sys.executable, "-m", "agent_in_a_box.network.fixture_service",
                             "--receipts", str(tmp_path / "receipts.jsonl")],
                            capture_output=True, text=True, timeout=30, env=environment)
    assert result.returncode != 0 and STAMP_ENV in result.stderr


def raw_request(route, request: bytes, until_eof: bool = False) -> bytes:
    """One raw request; with `until_eof`, everything until the fixture closes the connection,
    which a hang would turn into a socket timeout."""
    with socket.create_connection((route.host, route.port), timeout=10) as sock:
        sock.sendall(request)
        reply = sock.recv(4096)
        while until_eof:
            more = sock.recv(4096)
            if not more:
                return reply
            reply += more
        return reply


def test_the_fixture_refuses_a_stamp_with_bytes_past_ascii_without_a_traceback(lab):
    """The header arrives as latin-1 text; comparing it as bytes cannot raise."""
    _, receipts, route = lab
    reply = raw_request(route, b"GET /reference HTTP/1.1\r\nHost: reference.fixture\r\n"
                               b"X-Agent-In-A-Box-Stamp: s\xff\xe1\r\n\r\n")
    assert reply.startswith(b"HTTP/1.1 403") and receipts_of(receipts) == []


def test_a_chunked_body_is_refused_by_the_proxy_before_cedar_and_leaves_no_receipt(lab):
    """Without a declared length the receipt could not describe the body, so the protocol
    check refuses the request (as it refuses upgrades) and records why."""
    proxy, receipts, _ = lab
    parts = urllib.parse.urlsplit(proxy.url)
    basic = base64.b64encode(f"{parts.username}:{parts.password}".encode()).decode()
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as sock:
        sock.sendall(b"POST http://reference.fixture/collect HTTP/1.1\r\n"
                     b"Host: reference.fixture\r\n"
                     b"Proxy-Authorization: Basic " + basic.encode() + b"\r\n"
                     b"Transfer-Encoding: chunked\r\n\r\nb\r\nhello world\r\n0\r\n\r\n")
        reply = sock.recv(4096)
    assert reply.startswith(b"HTTP/1.1 403") and receipts_of(receipts) == []
    decision = decisions_of(proxy)[0]
    assert decision["refused_by"] == "protocol" and "chunked" in decision["checks"][0]["detail"]


def test_the_fixture_refuses_undeclared_or_bad_body_lengths_before_reading(tmp_path):
    receipts = tmp_path / "receipts.jsonl"
    stamped = (b"POST /collect HTTP/1.1\r\nHost: reference.fixture\r\n"
               b"X-Agent-In-A-Box-Stamp: known-stamp\r\n")
    with fixture_service("default", receipts, "known-stamp") as route:
        chunked = raw_request(route, stamped + b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
                              until_eof=True)
        negative = raw_request(route, stamped + b"Content-Length: -1\r\n\r\n", until_eof=True)
        not_a_number = raw_request(route, stamped + b"Content-Length: abc\r\n\r\n",
                                   until_eof=True)
    assert chunked.startswith(b"HTTP/1.1 411")
    assert negative.startswith(b"HTTP/1.1 400") and not_a_number.startswith(b"HTTP/1.1 400")
    assert receipts_of(receipts) == []


def test_the_fixture_is_quiet_when_a_client_resets_and_loud_otherwise(capsys):
    from agent_in_a_box.network.fixture_service import QuietServer

    server = QuietServer.__new__(QuietServer)  # handle_error needs no bound socket
    try:
        raise ConnectionResetError("peer reset")
    except ConnectionResetError:
        server.handle_error(None, ("127.0.0.1", 1))
    assert capsys.readouterr().err == ""
    try:
        raise ValueError("a real bug")
    except ValueError:
        server.handle_error(None, ("127.0.0.1", 1))
    assert "a real bug" in capsys.readouterr().err


def test_the_fixture_honours_a_clients_connection_close_on_an_accepted_request(tmp_path):
    receipts = tmp_path / "receipts.jsonl"
    with fixture_service("default", receipts, "known-stamp") as route:
        reply = raw_request(route, b"GET /reference HTTP/1.1\r\nHost: reference.fixture\r\n"
                                   b"X-Agent-In-A-Box-Stamp: known-stamp\r\n"
                                   b"Connection: close\r\n\r\n", until_eof=True)
    assert reply.startswith(b"HTTP/1.1 200") and receipts_of(receipts) == [("GET", "/reference")]


def test_the_fixture_refuses_an_oversize_body_before_reading_it(tmp_path):
    """A correctly stamped request whose body would exceed the fixture's limit gets 413
    before any of the body is read, leaves no receipt, and closes the connection."""
    receipts = tmp_path / "receipts.jsonl"
    with fixture_service("default", receipts, "known-stamp") as route:
        reply = raw_request(route, b"POST /collect HTTP/1.1\r\nHost: reference.fixture\r\n"
                                   b"X-Agent-In-A-Box-Stamp: known-stamp\r\n"
                                   b"Content-Length: 2000000\r\n\r\nshort", until_eof=True)
    assert reply.startswith(b"HTTP/1.1 413") and receipts_of(receipts) == []


def test_a_direct_request_to_the_fixture_without_the_stamp_leaves_no_receipt(lab):
    """The fixture answers only what the run's proxy forwarded."""
    _, receipts, route = lab
    request = urllib.request.Request(f"http://{route.host}:{route.port}/reference")
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=10)
    assert refused.value.code == 403 and receipts_of(receipts) == []


def test_refused_post_never_reaches_the_fixture_handler(lab):
    proxy, receipts, _ = lab
    status, headers, body = send(proxy, "POST", "http://reference.fixture/reference",
                                 body=b"x" * 100_000)
    assert status == 403 and headers["X-Agent-In-A-Box-Refused"] == "request"
    assert json.loads(body)["refused_by"] == "request"
    assert receipts_of(receipts) == []
    decision = decisions_of(proxy)[0]
    assert decision["label"] == "refused" and decision["refused_by"] == "request"
    assert decision["checks"][-1]["decision"]["decision"] == "denied"


def test_host_header_disagreement_is_refused_before_cedar(lab):
    proxy, receipts, _ = lab
    status, _, _ = send(proxy, "GET", "http://reference.fixture/reference",
                        headers={"Host": "collector.example"})
    assert status == 403 and receipts_of(receipts) == []
    assert decisions_of(proxy)[0]["refused_by"] == "protocol"


def test_claimed_identity_header_has_no_effect(lab):
    proxy, _, _ = lab
    send(proxy, "POST", "http://reference.fixture/reference",
         headers={"X-Sandbox-Principal": 'Sandbox::Process::"admin"'})
    decision = decisions_of(proxy)[0]
    request = decision["checks"][-1]["decision"]["request"]
    assert request["principal"] == {"type": "Sandbox::Process", "id": "current"}
    assert decision["label"] == "refused"


def test_connect_tunnel_is_refused(lab):
    proxy, receipts, _ = lab
    parts = urllib.parse.urlsplit(proxy.url)
    basic = base64.b64encode(f"{parts.username}:{parts.password}".encode()).decode()
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as sock:
        sock.sendall(b"CONNECT reference.fixture:443 HTTP/1.1\r\n"
                     b"Host: reference.fixture:443\r\n"
                     b"Proxy-Authorization: Basic " + basic.encode() + b"\r\n\r\n")
        reply = sock.recv(4096)
    assert reply.startswith(b"HTTP/1.1 403")
    assert receipts_of(receipts) == []
    assert decisions_of(proxy)[0]["refused_by"] == "protocol"


def test_proxy_refuses_to_start_with_a_tampered_policy(tmp_path):
    run = runs.create_run(tmp_path / "runs")
    compiled = compile_policy(schema.load_variant("P0"), CedarpyEvaluator())
    original = dataplane.start_proxy  # write files, then tamper and restart by hand
    proxy = original(run, compiled, Lab({}, "stamp"), "cedarpy")
    dataplane.stop(proxy.process)
    policy = Path(run.private) / "policy.cedar"
    policy.write_text(policy.read_text().replace('"GET"', '"POST"'))
    import subprocess
    import sys

    server = "agent_in_a_box.network.proxy_server"
    result = subprocess.run([sys.executable, "-m", server, "--config",
                             str(Path(run.private) / "proxy.json")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "does not match its recorded hash" in result.stderr
