"""Start the gateway on 127.0.0.1 with a fresh session token.

The token and URL are written to a state file readable only by the operator
(mode 0600). Clients on this machine read it; the workload has no grant to it.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
from pathlib import Path

import uvicorn

from agent_in_a_box.composition import Runtime
from agent_in_a_box.experiments.controller import Controller
from agent_in_a_box.gateway.app import EventHub, create_app


def state_file(runtime: Runtime) -> Path:
    return runtime.config.runs_dir.parent / "gateway.json"


def serve(runtime: Runtime, port: int = 0) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    hub = EventHub()
    app = create_app(Controller(runtime, hub.publish), hub, token, port)

    path = state_file(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as f:
        json.dump({"url": f"http://127.0.0.1:{port}", "token": token, "pid": os.getpid()}, f)
    print(f"READY http://127.0.0.1:{port} {path}", flush=True)

    config = uvicorn.Config(app, log_level="warning", lifespan="off")
    asyncio.run(uvicorn.Server(config).serve(sockets=[sock]))
