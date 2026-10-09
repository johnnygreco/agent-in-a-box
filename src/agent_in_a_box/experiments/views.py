"""View models for the website, built from bundles. Pure: no process, connection, or solver.

The website renders these; it computes no evidence of its own. Every view
carries the bundle's evidence label (recorded, enforcement), and every
result label is a glossary term. Steps are found by the names in steps.py,
the same names the experiment scripts submitted them under.
"""

from __future__ import annotations

from typing import Any

from agent_in_a_box.contracts import CedarEvaluator
from agent_in_a_box.experiments import records
from agent_in_a_box.experiments.steps import CHAPTER5, TRAILER, Chapter5, Trailer, steps_by_name
from agent_in_a_box.glossary import TERMS
from agent_in_a_box.policy import requests


def label(document: dict) -> dict[str, Any]:
    return {
        "title": document["title"],
        "published": False,
        "bundle_id": document["bundle_id"],
        "viewed_as": document["viewed_as"],
        "enforcement": document["enforcement"],
        "built": document["created"],
        "test_backend": "none" in document["enforcement"],
        "toolchain": toolchain_versions(document),
    }


def toolchain_versions(document: dict) -> dict[str, str]:
    manifest = document["tool_manifest"]
    solver = str(manifest.get("cvc5", "unknown")).removeprefix("This is ").split(" [")[0]
    solver = solver.replace(" version", "")
    return {"cedar_policy": manifest.get("cedar_policy", "unknown"),
            "symcc": manifest.get("cedar_policy_symcc", "unknown"), "solver": solver,
            "cedarpy": manifest.get("cedarpy", "unknown")}


def provenance(document: dict, enforcement: str) -> dict[str, str]:
    return {"mode": "recorded", "enforcement": enforcement, **toolchain_versions(document)}


def event_text(event: dict) -> str:
    """One readable line for an event. Agent-reported text stays data: it is
    shown as the agent's claim, never as a host record."""
    payload = event["payload"]
    kind = event["kind"]
    if kind == "agent.model_reply":
        call = payload["data"]["tool_call"]
        if not call:
            return "agent finishes"
        arguments = call["arguments"]
        target = arguments.get("url") or arguments.get("path") or ""
        return f"agent proposes {call['name']} {arguments.get('method', '')} {target}"
    if kind == "agent.observation":
        observation = payload["data"]["observation"]
        outcome = "ok" if observation["ok"] else "failed"
        return f"agent observes {observation['tool']}: {outcome}"
    if kind == "proxy.decision":
        where = f" at {payload['refused_by']}" if payload["refused_by"] else ""
        return f"{payload['method']} {payload['path'] or ''}: {payload['label']}{where}"
    if kind == "fixture.receipt":
        return f"fixture received {payload['method']} {payload['target']}"
    if kind == "agent.agent_start":
        return "the harness starts the task"
    if kind == "agent.agent_finish":
        return f"the harness stops: {payload['data'].get('reason', '')}"
    return kind.replace("_", " ")


def event_layers(event: dict) -> list[str]:
    """Every layer an event involved: a proxy decision consults Cedar unless refused first."""
    if event["kind"] != "proxy.decision":
        return [event["layer"]]
    asked_cedar = any(check["decision"] for check in event["payload"]["checks"])
    if asked_cedar:
        return ["proxy", "cedar"]
    return ["proxy"]


def run_view(step: dict) -> dict[str, Any]:
    run = step["result"]["run"]
    attempts = []
    receipts = 0
    shown = []
    for event in run["events"]:
        if event["kind"] == "proxy.decision":
            decision = event["payload"]
            cedar = decision["checks"][-1]["decision"]
            attempts.append({
                "method": decision["method"], "path": decision["path"],
                "label": decision["label"], "refused_by": decision["refused_by"],
                "determining": cedar["determining"] if cedar else [],
            })
        if event["kind"] == "fixture.receipt":
            receipts += 1
        if event["layer"] != "supervisor":
            shown.append({"seq": event["seq"], "layer": event["layer"],
                          "layers": event_layers(event), "provenance": event["provenance"],
                          "text": event_text(event)})
    return {"policy": run["policy_name"], "enforcement": run["enforcement"],
            "status": run["status"], "attempts": attempts, "receipts": receipts,
            "events": shown}


def analysis_view(step: dict, policy_names: dict[str, str]) -> dict[str, Any]:
    analysis = step["result"]["analysis"]
    witness = analysis["witness"]
    replayed = []
    for record in analysis["replay"]:
        name = policy_names.get(record["policy_hash"], record["policy_hash"][:12])
        replayed.append({"policy": name, "decision": record["decision"]})
    return {
        "old": step["payload"]["old"], "new": step["payload"]["new"],
        "status": analysis["status"], "labels": analysis["labels"],
        "domain": analysis["domain"],
        "witness": witness["request"] if witness else None,
        "witness_text": witness["display"] if witness else None,
        "replay": replayed, "error": analysis["error"],
    }


def policy_names(document: dict) -> dict[str, str]:
    """Policy hash -> the policy's name (P0, P1, ...)."""
    return {policy_hash: policy["name"] for policy_hash, policy in document["policies"].items()}


def chapter0(document: dict, evaluator: CedarEvaluator) -> dict[str, Any]:
    steps = steps_by_name(document, TRAILER)
    names = policy_names(document)

    def run(step: str) -> dict:
        view = run_view(steps[step])
        return {**view, "provenance": provenance(document, view["enforcement"])}

    def analysis(step: str) -> dict:
        return {**analysis_view(steps[step], names),
                "provenance": provenance(document, "analysis only")}

    request = requests.http_request("reference.fixture", 80, "GET", "/reference")
    examples = {name: evaluator.evaluate(records.policy_named(document, name), request).decision
                for name in ("P0", "P1")}
    return {
        "label": label(document),
        "policies": {name: records.policy_named(document, name).policy_text
                     for name in ("P0", "P1")},
        "examples": examples,
        "run_p0": run(Trailer.RUN_P0),
        "run_p1": run(Trailer.RUN_P1),
        "verify": analysis(Trailer.VERIFY),
        "inspect": {"P0": run(Trailer.INSPECT_P0), "P1": run(Trailer.INSPECT_P1)},
        "repair": analysis(Trailer.REPAIR),
        "task": steps[Trailer.TASK]["result"]["label"],
    }


def chapter5(document: dict, evaluator: CedarEvaluator) -> dict[str, Any]:
    steps = steps_by_name(document, CHAPTER5)
    names = policy_names(document)
    variants = [records.policy_named(document, name) for name in ("P0", "P1", "P2")]

    def run(step: str) -> dict:
        view = run_view(steps[step])
        return {**view, "provenance": provenance(document, view["enforcement"])}

    def analysis(step: str) -> dict:
        return {**analysis_view(steps[step], names),
                "provenance": provenance(document, "analysis only")}

    return {
        "label": label(document),
        "policies": {variant.name: variant.policy_text for variant in variants},
        "grid": records.matrix(evaluator, variants, ["GET", "POST", "PUT"],
                               ["/reference", "/missing"]),
        "grid_provenance": provenance(document, "analysis only"),
        "p1": analysis(Chapter5.P0_TO_P1),
        "p2": analysis(Chapter5.P0_TO_P2),
        "p2_runs": {"P0": run(Chapter5.P2_WITNESS_UNDER_P0),
                    "P2": run(Chapter5.P2_WITNESS_UNDER_P2)},
        "repair": analysis(Chapter5.REPAIR),
        "task_p0": steps[Chapter5.TASK_P0]["result"]["label"],
        "deny_all": analysis(Chapter5.DENY_ALL),
        "task_p3": steps[Chapter5.TASK_P3]["result"]["label"],
        "starved": analysis(Chapter5.STARVED),
    }


def glossary() -> list[dict[str, str]]:
    return [{"term": term.term, "means": term.means, "claimed_by": term.claimed_by,
             "evidence": term.evidence} for term in TERMS.values()]
