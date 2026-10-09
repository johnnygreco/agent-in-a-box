"""Call the pinned Cedar bridge (native/cedar-bridge): one JSON command per process.

A bridge failure never becomes an allow or a proof. Callers turn
BridgeError into a deny (evaluation) or "no conclusion" (analysis).
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from agent_in_a_box.policy import toolchain


class BridgeError(RuntimeError):
    """The bridge could not answer: it crashed, timed out, or reported a failure."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


def call(command: dict[str, Any], *, timeout_s: float = 30.0) -> dict[str, Any]:
    bridge = toolchain.load().bridge
    try:
        proc = subprocess.run(
            [str(bridge)], input=json.dumps(command), capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("timeout", f"bridge did not answer within {timeout_s}s") from exc
    if proc.returncode != 0:
        raise BridgeError("crash", f"exit {proc.returncode}: {proc.stderr[-2000:]}")
    try:
        document = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BridgeError("output", f"unparsable bridge output: {proc.stdout[:500]!r}") from exc
    if not document.get("ok"):
        error = document.get("error") or {}
        raise BridgeError(error.get("kind", "unknown"), error.get("message", ""))
    return document["result"]
