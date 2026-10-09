"""The reference fixture service: a real local HTTP server for the lessons.

    GET  /reference   reference data from the selected variant file
    POST /collect     a sink that records what it received and acknowledges
    anything else     404 (other methods on /reference: 405)

Every request that reaches the handler is appended to a receipts file before
it is answered. That file is the evidence that a refused request never
reached the fixture: the proxy refuses before forwarding, so no receipt exists.

    python -m agent_in_a_box.network.fixture_service --variant default --receipts PATH

prints `READY <port>` once it listens on 127.0.0.1. The workload never learns
this port; it reaches the fixture only through the proxy's named route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_in_a_box.policy.schema import REPO_ROOT

VARIANT_DIR = REPO_ROOT / "fixtures" / "reference"
MAX_BODY = 1 << 20


def load_variant(name: str) -> dict:
    path = VARIANT_DIR / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"unknown fixture variant {name!r}")
    return json.loads(path.read_text())


class Receipts:
    """The fixture's own log: one numbered line per request that reached the handler."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0
        self.lock = threading.Lock()

    def append(self, method: str, target: str, host: str | None, body: bytes) -> None:
        with self.lock:
            self.count += 1
            receipt = {
                "seq": self.count, "time": time.time(), "method": method, "target": target,
                "host": host, "body_bytes": len(body),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
            with self.path.open("a") as log:
                log.write(json.dumps(receipt) + "\n")


def make_handler(variant: dict, receipts: Receipts) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "reference-fixture/1"

        def log_message(self, format: str, *args: object) -> None:  # quiet
            pass

        def _receive(self) -> bytes:
            """Read the body and log the receipt before anything is answered."""
            length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
            body = self.rfile.read(length) if length else b""
            receipts.append(self.command, self.path, self.headers.get("Host"), body)
            return body

        def _send(self, status: int, body: str, content_type: str = "text/plain") -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _handle(self) -> None:
            body = self._receive()
            path = self.path.split("?", 1)[0]
            if path == "/reference" and self.command in ("GET", "HEAD"):
                # The injection variant names this server's own address, known only now.
                direct_url = f"http://127.0.0.1:{self.server.server_address[1]}/collect"
                body = variant["body"].replace("{direct_url}", direct_url)
                self._send(variant["status"], body, variant["content_type"])
            elif path == "/reference":
                self._send(405, "method not allowed\n")
            elif path == "/collect" and self.command == "POST":
                self._send(200, json.dumps({"received_bytes": len(body)}) + "\n",
                           "application/json")
            else:
                self._send(404, "not found\n")

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _handle

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Reference fixture service")
    parser.add_argument("--variant", default="default")
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    args.receipts.touch()
    variant = load_variant(args.variant)
    handler = make_handler(variant, Receipts(args.receipts))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"READY {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
