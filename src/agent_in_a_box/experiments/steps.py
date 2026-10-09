"""Named steps of the scripted experiments, and helpers for reading their results.

The trailer and chapter 5 scripts submit one command per step. The website's
views find those steps again in an exported bundle. Both use the names
defined here, so a step cannot be renamed in one place and missed in the
other. A step's command ID is "<session>.<experiment>.<step>".
"""

from __future__ import annotations

from typing import Any

from agent_in_a_box.client import GatewayClient
from agent_in_a_box.contracts import CommandResult, plain

TRAILER = "trailer"
CHAPTER5 = "chapter5"


class Trailer:
    """Steps of the chapter 0 trailer, in order."""

    RUN_P0 = "run-p0"
    RUN_P1 = "run-p1"
    VERIFY = "verify"
    INSPECT_P0 = "inspect-p0"
    INSPECT_P1 = "inspect-p1"
    REPAIR = "repair"
    TASK = "task"
    EXPORT = "export"


class Chapter5:
    """Steps of chapter 5's ladder, in order."""

    P0_TO_P1 = "p0-p1"
    P0_TO_P2 = "p0-p2"
    P2_WITNESS_UNDER_P0 = "p2-witness-p0"
    P2_WITNESS_UNDER_P2 = "p2-witness-p2"
    REPAIR = "repair"
    TASK_P0 = "task-p0"
    DENY_ALL = "deny-all"
    TASK_P3 = "task-p3"
    STARVED = "starved"
    EXPORT = "export"


def command_id(session: str, experiment: str, step: str) -> str:
    return f"{session}.{experiment}.{step}"


class Session:
    """Submits one experiment's steps through the gateway, and remembers their
    command IDs so the experiment can be exported as one bundle."""

    def __init__(self, client: GatewayClient, session: str, experiment: str) -> None:
        self.client = client
        self.session = session
        self.experiment = experiment
        self.command_ids: list[str] = []

    def submit(self, step: str, kind: str, payload: dict) -> dict[str, Any]:
        """Submit (or retrieve) the step's command and return its result."""
        step_id = command_id(self.session, self.experiment, step)
        self.command_ids.append(step_id)
        return succeeded(self.client.run(kind, payload, step_id))

    def export(self, step: str, title: str) -> dict[str, Any]:
        payload = {"commands": list(self.command_ids), "title": title, "client": "cli"}
        return self.submit(step, "export", payload)


def succeeded(result: CommandResult) -> dict[str, Any]:
    """The result of a command that must have succeeded."""
    if result.status != "succeeded":
        raise RuntimeError(f"{result.command_id} {result.status}: {plain(result.result)}")
    return plain(result.result)


def steps_by_name(document: dict, experiment: str) -> dict[str, dict]:
    """A bundle's steps for one experiment, keyed by step name."""
    found = {}
    for step in document["steps"]:
        _session, recorded_experiment, name = step["command_id"].rsplit(".", 2)
        if recorded_experiment == experiment:
            found[name] = step
    return found


# ── Reading a run record ──────────────────────────────────────────────────


def events(run: dict, kind: str) -> list[dict]:
    """Payloads of a run's events of one kind, in order."""
    return [event["payload"] for event in run["events"] if event["kind"] == kind]


def decision_label(run: dict, method: str, path: str) -> str | None:
    """The proxy's label ("allowed" or "refused") for the run's first request with
    this method and path, or None if the run made no such request."""
    for decision in events(run, "proxy.decision"):
        if decision["method"] == method and decision["path"] == path:
            return decision["label"]
    return None


def receipt_count(run: dict) -> int:
    """How many requests reached the fixture service's handler."""
    return len(events(run, "fixture.receipt"))


def http_summary(run: dict) -> str:
    """One line per HTTP request, for display: method, path, label, determining policies."""
    parts = []
    for decision in events(run, "proxy.decision"):
        cedar = decision["checks"][-1]["decision"]
        text = f"{decision['method']} {decision['path'] or '?'}: {decision['label']}"
        if cedar and cedar["determining"]:
            text += f" ({', '.join(cedar['determining'])})"
        parts.append(text)
    return ", ".join(parts) or "no HTTP request"


def witness_probe(analysis: dict) -> dict:
    """An http tool call that sends the analysis witness's method and path to its endpoint."""
    witness = analysis["witness"]
    if witness is None:
        raise RuntimeError("the solver returned no distinguishing input to run")
    request = witness["request"]
    host, port = request["resource"]["id"].rsplit(":", 1)
    authority = host if port == "80" else f"{host}:{port}"
    url = f"http://{authority}{request['context']['path']}"
    return {"name": "http", "arguments": {"method": request["context"]["method"], "url": url}}


def witness_context(analysis: dict) -> dict:
    """The witness request's context (method and path), or {} if there is no witness."""
    if analysis["witness"] is None:
        return {}
    return analysis["witness"]["request"]["context"]
