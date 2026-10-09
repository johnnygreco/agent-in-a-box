"""The per-run egress proxy process: mitmproxy with our decision path (decisions/0004).

    python -m agent_in_a_box.network.proxy_server --config <run private>/proxy.json

The supervisor starts one per run, outside the workload boundary, and reads
the decision records it appends to the run's private directory. mitmproxy
parses HTTP; every decision is made by network/proxy.py before anything is
sent upstream. Prints `READY <port>` once listening on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from mitmproxy import http, options
from mitmproxy.tools.dump import DumpMaster

from agent_in_a_box import composition
from agent_in_a_box.contracts import EligibleEndpoint, PolicyBundle, ProxyPlan
from agent_in_a_box.network.protocol import ParsedRequest
from agent_in_a_box.network.proxy import DecisionPath, ProxyDecision, Route


class Enforcer:
    """mitmproxy addon: parse, decide, then forward or refuse."""

    def __init__(self, master: DumpMaster, decision_path: DecisionPath, sink: Path) -> None:
        self.master = master
        self.decision_path = decision_path
        self.sink = sink

    def running(self) -> None:
        proxyserver = self.master.addons.get("proxyserver")
        port = proxyserver.listen_addrs()[0][1]
        print(f"READY {port}", flush=True)

    def http_connect(self, flow: http.HTTPFlow) -> None:
        """CONNECT requests are always refused, by the protocol check."""
        decision = self.decision_path.decide(parse(flow, scheme="connect"))
        self.record(decision)
        self.refuse(flow, decision)

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        """Decide before mitmproxy opens any upstream connection."""
        decision = self.decision_path.decide(parse(flow, scheme=flow.request.scheme))
        self.record(decision)
        if not decision.forwarded or decision.route is None:
            self.refuse(flow, decision)
            return
        # Send to the lab transport for this endpoint; keep the Host the client sent.
        host_header = flow.request.host_header
        flow.request.host = decision.route.host
        flow.request.port = decision.route.port
        flow.request.host_header = host_header

    def record(self, decision: ProxyDecision) -> None:
        with self.sink.open("a") as sink:
            sink.write(json.dumps({**decision.to_json(), "time": time.time()}) + "\n")

    def refuse(self, flow: http.HTTPFlow, decision: ProxyDecision) -> None:
        """Answer from the proxy itself, so nothing reaches the upstream."""
        last = decision.checks[-1]
        determining = list(last.decision.determining) if last.decision else []
        body = {"refused_by": decision.refused_by, "detail": last.detail,
                "determining": determining}
        headers = {"Content-Type": "application/json",
                   "X-Agent-In-A-Box-Refused": decision.refused_by}
        flow.response = http.Response.make(403, json.dumps(body) + "\n", headers)


def parse(flow: http.HTTPFlow, scheme: str) -> ParsedRequest:
    request = flow.request
    return ParsedRequest(
        method=request.method, scheme=scheme, host=request.host, port=request.port,
        target=request.path, host_header=request.host_header,
        http_version=request.http_version, upgrade="upgrade" in request.headers,
    )


def read_pinned(path: str, expected_sha256: str) -> str:
    """Read a file the supervisor wrote, refusing it if it changed since."""
    text = Path(path).read_text()
    if hashlib.sha256(text.encode()).hexdigest() != expected_sha256:
        raise SystemExit(f"{path} does not match its recorded hash")
    return text


def load(config: dict) -> tuple[DecisionPath, Path]:
    schema_text = read_pinned(config["schema_path"], config["schema_sha256"])
    policy_text = read_pinned(config["policy_path"], config["policy_sha256"])
    bundle = PolicyBundle(config["policy_name"], schema_text, policy_text)
    eligible = tuple(EligibleEndpoint(entry["endpoint"], tuple(entry["policy_ids"]))
                     for entry in config["eligible"])
    routes = {entry["endpoint"]: Route(entry["endpoint"], entry["host"], entry["port"])
              for entry in config["routes"]}
    evaluator = composition.select_evaluator(config["evaluator"])
    decision_path = DecisionPath(config["run_id"], bundle, evaluator,
                                 ProxyPlan(eligible, bundle.policy_hash), routes)
    return decision_path, Path(config["decisions_path"])


async def serve(config: dict) -> None:
    decision_path, sink = load(config)
    master = DumpMaster(options.Options(), with_termlog=False, with_dumper=False)
    master.options.update(
        listen_host="127.0.0.1", listen_port=config.get("listen_port", 0),
        confdir=config["confdir"], http2=False, websocket=False, rawtcp=False,
    )
    master.addons.add(Enforcer(master, decision_path, sink))
    await master.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent in a Box per-run proxy")
    parser.add_argument("--config", required=True, type=Path)
    config = json.loads(parser.parse_args().config.read_text())
    asyncio.run(serve(config))


if __name__ == "__main__":
    main()
