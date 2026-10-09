"""Typed client for the gateway's v1 API, shared by the CLI and the notebooks.

Every effect goes through `submit` with a command ID. Retrying with the same
ID returns the stored result; a new ID is a new intent. Waiting for a result
or reading events never starts anything.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from agent_in_a_box.contracts import CommandResult


class GatewayError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, url: str, token: str, timeout_s: float = 30.0) -> None:
        self.http = httpx.Client(base_url=url, timeout=timeout_s,
                                 headers={"Authorization": f"Bearer {token}"})

    @classmethod
    def from_state(cls, path: Path) -> GatewayClient:
        state = json.loads(Path(path).read_text())
        return cls(state["url"], state["token"])

    def _json(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise GatewayError(f"{response.status_code}: {response.text[:500]}")
        return response.json()

    def health(self) -> dict:
        return self._json(self.http.get("/api/v1/health"))

    def submit(self, kind: str, payload: dict, command_id: str | None = None) -> CommandResult:
        command_id = command_id or f"{kind}-{uuid.uuid4().hex}"
        body = {"command_id": command_id, "kind": kind, "payload": payload}
        return CommandResult(**self._json(self.http.post("/api/v1/commands", json=body)))

    def result(self, command_id: str) -> CommandResult | None:
        response = self.http.get(f"/api/v1/commands/{command_id}")
        return None if response.status_code == 404 else CommandResult(**self._json(response))

    def wait(self, command_id: str, timeout_s: float = 300.0) -> CommandResult:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self.result(command_id)
            if result is not None and result.status != "running":
                return result
            time.sleep(0.25)
        raise GatewayError(f"command {command_id} did not finish within {timeout_s}s")

    def run(self, kind: str, payload: dict, command_id: str | None = None,
            timeout_s: float = 300.0) -> CommandResult:
        """Submit (or retrieve) a command and wait for its stored outcome."""
        started = self.submit(kind, payload, command_id)
        if started.status != "running":
            return started
        return self.wait(started.command_id, timeout_s)

    def bundle(self, bundle_id: str) -> dict:
        return self._json(self.http.get(f"/api/v1/bundles/{bundle_id}"))

    def events(self, after: int = 0, follow: bool = False) -> Iterator[tuple[int, dict]]:
        """Server-sent events as (id, envelope). With follow=False, the backlog only."""
        params = {"after": after, "follow": "1" if follow else "0"}
        with self.http.stream("GET", "/api/v1/events", params=params, timeout=None) as response:
            event_id = 0
            data: list[str] = []
            for line in response.iter_lines():
                if line.startswith("id: "):
                    event_id = int(line[4:])
                elif line.startswith("data: "):
                    data.append(line[6:])
                elif line == "" and data:
                    yield event_id, json.loads("\n".join(data))
                    data = []

    def close(self) -> None:
        self.http.close()
