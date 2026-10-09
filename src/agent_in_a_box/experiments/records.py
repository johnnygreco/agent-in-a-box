"""Pure helpers for reading bundles in notebooks and the website.

Nothing here starts a process, opens a connection, or calls a solver. The
evaluator calls are concrete Cedar evaluations of recorded or edited
requests; an edited request is labeled hypothetical.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Any

from agent_in_a_box.contracts import (
    CedarEvaluator, CedarRequest, DecisionRecord, EntityRef, PolicyBundle,
)
from agent_in_a_box.policy import requests


def policy(document: dict, policy_hash: str) -> PolicyBundle:
    entry = document["policies"][policy_hash]
    return PolicyBundle(entry["name"], document["schema"]["text"], entry["text"])


def policy_named(document: dict, name: str) -> PolicyBundle:
    for policy_hash, entry in document["policies"].items():
        if entry["name"] == name:
            return policy(document, policy_hash)
    raise KeyError(f"bundle has no policy named {name!r}")


def request_from(record: dict) -> CedarRequest:
    """The request inside a recorded decision record, as a CedarRequest."""
    request = record["request"]
    return CedarRequest(
        principal=EntityRef(**request["principal"]),
        action=EntityRef(**request["action"]),
        resource=EntityRef(**request["resource"]),
        context=request["context"],
        entities=tuple(request["entities"]),
        provenance=request["provenance"],
    )


def http_attempts(document: dict) -> list[dict]:
    """Every HTTP attempt in the bundle's runs: proposal, proxy decision, observation."""
    attempts = []
    for step in document["steps"]:
        run = step["result"].get("run")
        if not run:
            continue
        events = run["events"]
        for position, event in enumerate(events):
            if event["kind"] != "proxy.decision":
                continue
            attempts.append({
                "command_id": step["command_id"], "run_id": run["run_id"],
                "policy": run["policy_name"], "enforcement": run["enforcement"],
                "proposal": last_proposal(events[:position]),
                "decision": event["payload"],
                "observation": next_observation(events[position:]),
            })
    return attempts


def last_proposal(events: list[dict]) -> dict | None:
    """The tool call in the last model reply among `events` (agent-reported)."""
    replies = [event for event in events if event["kind"] == "agent.model_reply"]
    if not replies:
        return None
    return replies[-1]["payload"]["data"]["tool_call"]


def next_observation(events: list[dict]) -> dict | None:
    """The first observation among `events` (agent-reported)."""
    for event in events:
        if event["kind"] == "agent.observation":
            return event["payload"]["data"]["observation"]
    return None


def provenance_rows(record: dict) -> list[dict[str, str]]:
    """Each request fact, its value, and who supplied it."""
    request = record["request"]
    provenance = request["provenance"]
    rows = []
    for field in ("principal", "action", "resource"):
        entity = request[field]
        rows.append({"field": field, "value": f"{entity['type']}::\"{entity['id']}\"",
                     "supplied by": provenance.get(field, "unknown")})
    for key, value in request["context"].items():
        rows.append({"field": f"context.{key}", "value": repr(value),
                     "supplied by": provenance.get(f"context.{key}", "unknown")})
    return rows


def hypothetical(evaluator: CedarEvaluator, bundle: PolicyBundle, record: dict,
                 context: dict[str, Any]) -> DecisionRecord:
    """Re-evaluate a recorded request with an edited context. Not evidence of what an
    agent can make the runtime send: the runtime builds these facts itself."""
    request = dataclasses.replace(request_from(record), context=context,
                                  provenance={"*": "edited in the inspector (hypothetical)"})
    return dataclasses.replace(evaluator.evaluate(bundle, request), hypothetical=True)


def matrix(evaluator: CedarEvaluator, bundles: Iterable[PolicyBundle], methods: Iterable[str],
           paths: Iterable[str], host: str = "reference.fixture", port: int = 80
           ) -> list[dict[str, str]]:
    """A bounded method x path grid of decisions. This is testing, not proof."""
    bundles = list(bundles)
    rows = []
    for method in methods:
        for path in paths:
            request = requests.http_request(host, port, method, path)
            row = {"method": method, "path": path}
            for bundle in bundles:
                row[bundle.name] = evaluator.evaluate(bundle, request).decision
            rows.append(row)
    return rows
