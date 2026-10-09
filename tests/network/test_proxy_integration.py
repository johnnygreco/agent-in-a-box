"""The real per-run proxy (mitmproxy + our decision path) in front of the real fixture.

The central check (M0 gate): a refused request never reaches the fixture
handler. The fixture logs every request that reaches its handler before
answering, so a refused request must leave no receipt.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_in_a_box.experiments.scenario import REFERENCE, fixture_service
from agent_in_a_box.policy import schema
from agent_in_a_box.policy.compiler import compile_policy
from agent_in_a_box.policy.evaluator import CedarpyEvaluator
from agent_in_a_box.supervisor import dataplane, runs


@pytest.fixture
def lab(tmp_path):
    """A fixture service and a proxy for P0, as a run would start them."""
    run = runs.create_run(tmp_path / "runs")
    receipts = tmp_path / "receipts.jsonl"
    with fixture_service("default", receipts) as route:
        compiled = compile_policy(schema.load_variant("P0"), CedarpyEvaluator())
        proxy = dataplane.start_proxy(run, compiled, {REFERENCE: route}, "cedarpy")
        try:
            yield proxy, receipts, route
        finally:
            dataplane.stop(proxy.process)


def send(proxy, method, url, body=None, headers=None):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy.port}"}))
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
    assert decisions_of(proxy)[0]["label"] == "allowed"


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
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as sock:
        sock.sendall(b"CONNECT reference.fixture:443 HTTP/1.1\r\n"
                     b"Host: reference.fixture:443\r\n\r\n")
        reply = sock.recv(4096)
    assert reply.startswith(b"HTTP/1.1 403")
    assert receipts_of(receipts) == []
    assert decisions_of(proxy)[0]["refused_by"] == "protocol"


def test_proxy_refuses_to_start_with_a_tampered_policy(tmp_path):
    run = runs.create_run(tmp_path / "runs")
    compiled = compile_policy(schema.load_variant("P0"), CedarpyEvaluator())
    original = dataplane.start_proxy  # write files, then tamper and restart by hand
    proxy = original(run, compiled, {}, "cedarpy")
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
