"""The local gateway: the operator's control plane (PLAN.md, Gateway).

It binds 127.0.0.1 only. Every request must name this gateway in its Host
header, which defeats DNS rebinding. A state-changing request must carry JSON
and must come from this origin or from a non-browser client. Every /api/v1
route except health needs the session token, sent as a bearer token or as the
cookie that POST /api/v1/session sets. The contained workload can connect
only to its proxy and never receives the token.

The API returns agent output as data inside JSON. Any page that renders it
must escape it; nothing here produces HTML from agent output.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import threading
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from agent_in_a_box.contracts import plain
from agent_in_a_box.experiments.controller import Controller

API = "/api/v1"
COOKIE = "agent_in_a_box_session"
SAFE_METHODS = ("GET", "HEAD")


class EventHub:
    """Ordered, bounded event store. Worker threads publish; SSE readers poll."""

    def __init__(self, limit: int = 10_000) -> None:
        self.items: list[tuple[int, dict]] = []
        self.next_id, self.limit, self.lock = 1, limit, threading.Lock()

    def publish(self, envelope: dict) -> None:
        with self.lock:
            self.items.append((self.next_id, envelope))
            self.next_id += 1
            del self.items[: max(0, len(self.items) - self.limit)]

    def since(self, last_id: int) -> list[tuple[int, dict]]:
        with self.lock:
            return [item for item in self.items if item[0] > last_id]


def create_app(controller: Controller, hub: EventHub, token: str, port: int) -> Starlette:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts}
    runtime = controller.runtime

    def problem(request: Request) -> Response | None:
        if request.headers.get("host") not in hosts:
            return JSONResponse({"error": "unexpected Host header"}, 421)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in origins:
                return JSONResponse({"error": "cross-origin request refused"}, 403)
            if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
                return JSONResponse({"error": "cross-site request refused"}, 403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"error": "state-changing requests must send JSON"}, 415)
        return None

    def authorized(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.startswith("Bearer ") else request.cookies.get(COOKIE)
        return presented is not None and hmac.compare_digest(presented, token)

    def guarded(handler, *, auth: bool = True):
        async def endpoint(request: Request) -> Response:
            if (refusal := problem(request)) is not None:
                return refusal
            if auth and not authorized(request):
                return JSONResponse({"error": "missing or wrong session token"}, 401)
            return await handler(request)
        return endpoint

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True, "api": 1, "enforcement": runtime.enforcement,
                             "backend_refusal": runtime.backend_refusal})

    async def session(request: Request) -> Response:
        response = JSONResponse({"ok": True})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path=API)
        return response

    async def submit(request: Request) -> Response:
        try:
            body = await request.json()
            command_id, kind, payload = body["command_id"], body["kind"], body["payload"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return JSONResponse({"error": "expected {command_id, kind, payload}"}, 400)
        if set(body) != {"command_id", "kind", "payload"} or not isinstance(payload, dict):
            return JSONResponse({"error": "expected exactly {command_id, kind, payload}"}, 400)
        result = await run_in_threadpool(controller.start, str(command_id), str(kind), payload)
        return JSONResponse(plain(result), 202 if result.status == "running" else 200)

    async def command(request: Request) -> Response:
        result = controller.result(request.path_params["command_id"])
        if result is None:
            return JSONResponse({"error": "no such command"}, 404)
        return JSONResponse(plain(result))

    async def bundle(request: Request) -> Response:
        bundle_id = request.path_params["bundle_id"]
        directory = runtime.config.runs_dir.parent / "bundles"
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            if path.stem.endswith(bundle_id[:12]):
                document = json.loads(Path(path).read_text())
                if document["bundle_id"] == bundle_id:
                    return JSONResponse(document)
        return JSONResponse({"error": "no such bundle"}, 404)

    async def events(request: Request) -> Response:
        last = int(request.headers.get("last-event-id") or request.query_params.get("after", 0))
        follow = request.query_params.get("follow", "1") != "0"

        async def stream():
            nonlocal last
            while True:
                for event_id, envelope in hub.since(last):
                    last = event_id
                    yield (f"id: {event_id}\nevent: {envelope['type']}\n"
                           f"data: {json.dumps(envelope)}\n\n")
                if not follow or await request.is_disconnected():
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    return Starlette(routes=[
        Route(f"{API}/health", guarded(health, auth=False)),
        Route(f"{API}/session", guarded(session), methods=["POST"]),
        Route(f"{API}/commands", guarded(submit), methods=["POST"]),
        Route(f"{API}/commands/{{command_id}}", guarded(command)),
        Route(f"{API}/bundles/{{bundle_id}}", guarded(bundle)),
        Route(f"{API}/events", guarded(events)),
    ])
