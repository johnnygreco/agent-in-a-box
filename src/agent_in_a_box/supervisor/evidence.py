"""Collect a run's evidence into ordered, immutable records.

Sources and how much each is trusted:

    supervisor lifecycle   trusted; provenance "lifecycle"
    proxy decision records trusted; provenance "host-enforcement"; the layer
                           is "cedar" when a Cedar check refused, else "proxy"
    fixture receipts       the upstream's own log; provenance "fixture-receipt"
    harness stdout         agent-reported and untrusted: kinds are prefixed
                           "agent.", sizes are bounded, malformed lines are
                           kept as text, and nothing in them can claim to be
                           a host record

Ordering. The supervisor polls every source on a short interval. Within one
poll, proxy decisions and fixture receipts are ordered by the time their own
trusted component wrote them, and agent lines by the moment the supervisor
read them. A time the agent claims is kept in its payload as data and never
used for ordering, so an agent cannot move its events earlier than the
proxy's. Order across sources is therefore approximate to one poll interval.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_in_a_box.contracts import Enforcement, EvidenceEvent, Layer, Provenance

MAX_AGENT_LINE = 16384
Publish = Callable[[EvidenceEvent], None]


@dataclass(frozen=True)
class Pending:
    """One line read from a source, not yet appended to the log."""

    order: float
    kind: str
    layer: Layer
    provenance: Provenance
    payload: dict[str, Any]


class Tail:
    """Read the complete lines appended to a file since the last call."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0

    def read(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as source:
            source.seek(self.offset)
            data = source.read()
        complete = data[: data.rfind(b"\n") + 1]
        self.offset += len(complete)
        return complete.decode(errors="replace").splitlines()


class EvidenceLog:
    def __init__(self, run_id: str, enforcement: Enforcement, publish: Publish | None = None):
        self.run_id = run_id
        self.enforcement = enforcement
        self.events: list[EvidenceEvent] = []
        self.publish = publish or (lambda event: None)
        self.agent: Tail | None = None
        self.decisions: Tail | None = None
        self.receipts: Tail | None = None

    def add(self, kind: str, layer: Layer, provenance: Provenance,
            payload: dict[str, Any]) -> EvidenceEvent:
        event = EvidenceEvent(len(self.events) + 1, self.run_id, kind, layer, provenance,
                              self.enforcement, "live", payload)
        self.events.append(event)
        self.publish(event)
        return event

    def lifecycle(self, kind: str, **payload: Any) -> EvidenceEvent:
        return self.add(kind, "supervisor", "lifecycle", payload)

    def follow(self, agent: Path, decisions: Path, receipts: Path | None) -> None:
        self.agent = Tail(agent)
        self.decisions = Tail(decisions)
        self.receipts = Tail(receipts) if receipts is not None else None

    def poll(self) -> None:
        """Append every new line from the followed sources (see Ordering above)."""
        read_at = time.time()
        pending = []
        if self.agent is not None:
            pending += [agent_line(line, read_at) for line in self.agent.read()]
        if self.decisions is not None:
            pending += [decision_line(line) for line in self.decisions.read()]
        if self.receipts is not None:
            pending += [receipt_line(line) for line in self.receipts.read()]
        pending.sort(key=lambda item: item.order)
        for item in pending:
            self.add(item.kind, item.layer, item.provenance, item.payload)


def agent_line(line: str, read_at: float) -> Pending:
    """An untrusted line from the harness, ordered by when the supervisor read it."""
    if len(line) > MAX_AGENT_LINE:
        return Pending(read_at, "agent.oversized", "agent", "agent-reported", {"bytes": len(line)})
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return Pending(read_at, "agent.text", "agent", "agent-reported", {"text": line})
    kind = "unknown"
    if isinstance(data, dict):
        kind = str(data.get("kind", "unknown"))[:64]
    return Pending(read_at, f"agent.{kind}", "agent", "agent-reported", {"data": data})


def decision_line(line: str) -> Pending:
    """A proxy decision record, ordered by the time the proxy wrote it."""
    data = json.loads(line)
    if data["refused_by"] in ("connect", "request"):
        layer = "cedar"
    else:
        layer = "proxy"
    return Pending(data["time"], "proxy.decision", layer, "host-enforcement", data)


def receipt_line(line: str) -> Pending:
    """A fixture receipt, ordered by the time the fixture wrote it."""
    data = json.loads(line)
    return Pending(data["time"], "fixture.receipt", "fixture", "fixture-receipt", data)
