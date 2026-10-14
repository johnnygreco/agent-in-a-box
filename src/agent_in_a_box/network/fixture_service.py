"""The reference fixture service: a real local HTTP server for the lessons.

    GET  /reference   reference data from the selected variant file
    POST /collect     a sink that records what it received and acknowledges
    anything else     404 (other methods on /reference: 405)

Every request the fixture accepts for reading is appended to a receipts file
before it is answered. That file is the evidence that a refused request never
reached the fixture: the proxy refuses before forwarding, so no receipt exists.
Three refusals happen before reading and leave no receipt either: a request
without the run's stamp (403), one whose body length is not declared or not a
number (411, 400), and one whose declared body is over MAX_BODY (413).

    AGENT_IN_A_BOX_FIXTURE_STAMP=... \
    python -m agent_in_a_box.network.fixture_service --variant default --receipts PATH

prints `READY <port>` once it listens on 127.0.0.1. The workload never learns
this port; it reaches the fixture only through the proxy's named route. The
fixture answers only requests that carry the run's stamp, which the proxy
adds to what it forwards, so a request from anything else on this host gets
403 and no receipt (decisions/0015). The stamp arrives in the environment,
which other users' processes cannot read; a command-line argument could be.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_in_a_box.policy.schema import REPO_ROOT

VARIANT_DIR = REPO_ROOT / "fixtures" / "reference"
MAX_BODY = 1 << 20
STAMP_ENV = "AGENT_IN_A_BOX_FIXTURE_STAMP"
STAMP_HEADER = "X-Agent-In-A-Box-Stamp"
REFUSAL = "this fixture answers only the run's proxy"


def load_variant(name: str) -> dict:
    path = VARIANT_DIR / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"unknown fixture variant {name!r}")
    return json.loads(path.read_text())


class Receipts:
    """The fixture's own log: one numbered line per request the fixture accepted for reading."""

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


def make_handler(variant: dict, receipts: Receipts, stamp: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "reference-fixture/1"

        def log_message(self, format: str, *args: object) -> None:  # quiet
            pass

        def _receive(self) -> bytes | None:
            """Read the body and log the receipt before anything is answered.

            A body whose length is undeclared (Transfer-Encoding), not a number, or past
            MAX_BODY is refused before any of it is read, with no receipt, and the
            connection closes so unread bytes cannot be taken for the next request.
            """
            if "Transfer-Encoding" in self.headers:
                return self._refuse(411, "declare the body length with Content-Length\n")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._refuse(400, "Content-Length is not a number\n")
            if length < 0:
                return self._refuse(400, "Content-Length is negative\n")
            if length > MAX_BODY:
                return self._refuse(413, "body too large\n")
            body = self.rfile.read(length) if length else b""
            receipts.append(self.command, self.path, self.headers.get("Host"), body)
            return body

        def _refuse(self, status: int, body: str) -> None:
            """Answer without reading the body, and close so unread bytes are not a request."""
            self.close_connection = True
            self._send(status, body)

        def _send(self, status: int, body: str, content_type: str = "text/plain") -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _handle(self) -> None:
            presented = self.headers.get(STAMP_HEADER, "").encode("latin-1")  # as parsed
            if not hmac.compare_digest(presented, stamp.encode()):
                # Not from this run's proxy: answer without reading or recording anything.
                self._refuse(403, REFUSAL + "\n")
                return
            body = self._receive()
            if body is None:
                return
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


class QuietServer(ThreadingHTTPServer):
    """A client that resets or closes early is not an error worth a traceback on stderr."""

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionResetError | BrokenPipeError):
            super().handle_error(request, client_address)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reference fixture service")
    parser.add_argument("--variant", default="default")
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    stamp = os.environ.get(STAMP_ENV)
    if not stamp:
        raise SystemExit(f"refusing to start: {STAMP_ENV} is not set, so no request could be "
                         "told apart from one that bypassed the proxy")
    args.receipts.touch()
    variant = load_variant(args.variant)
    handler = make_handler(variant, Receipts(args.receipts), stamp)
    server = QuietServer(("127.0.0.1", args.port), handler)
    print(f"READY {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
