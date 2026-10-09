"""Experiment bundles, schema v1: export, import, and replay without effects.

A bundle is one JSON document holding everything needed to inspect and
re-check an experiment: scenario and fixture hashes, the schema and every
policy text by hash, the tool and backend manifests, the nonsecret transport
mappings, and each command's input and stored result (run records, decision
records, raw solver witnesses and their replays).

Its id is the hash of its canonical content, so an edited bundle is detected
on import. Importing runs nothing; imported evidence is shown as recorded.
Replay re-evaluates every recorded Cedar decision with the current evaluator
and reports agreement, without contacting anything. A bundle produced under
the test backend says `enforcement: ["none"]` and is refused as a native run.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agent_in_a_box.composition import Runtime
from agent_in_a_box.contracts import (
    CedarEvaluator, CommandResult, PolicyBundle, canonical_hash, plain, sha256_text,
)
from agent_in_a_box.experiments import records, scenario
from agent_in_a_box.policy import schema, toolchain

SCHEMA = "agent-in-a-box-bundle/1"
POLICY_FIELDS = ("policy", "old", "new")


class BundleError(ValueError):
    """The bundle is malformed, was modified, or cannot be imported as asked."""


def _policies(steps: Sequence[CommandResult]) -> dict[str, dict[str, str]]:
    found = {}
    for step in steps:
        for field in POLICY_FIELDS:
            if field in step.payload:
                bundle = schema.resolve_policy(plain(step.payload[field]))
                found[bundle.policy_hash] = {"name": bundle.name, "text": bundle.policy_text}
    return found


def _runs(steps: Sequence[CommandResult]) -> Iterator[dict]:
    for step in steps:
        if step.kind == "run" and "run" in step.result:
            yield plain(step.result["run"])


def _transports(steps: Sequence[CommandResult]) -> list[dict]:
    """The lab's logical-endpoint -> local-transport mappings the runs used. Nonsecret."""
    mappings = set()
    for run in _runs(steps):
        for event in run["events"]:
            if event["kind"] != "proxy_started":
                continue
            for route in event["payload"]["routes"]:
                transport = f"http://{route['host']}:{route['port']}"
                mappings.add((route["endpoint"], transport))
    return [{"endpoint": endpoint, "transport": transport, "note": "lab route; nonsecret"}
            for endpoint, transport in sorted(mappings)]


def build(steps: Sequence[CommandResult], runtime: Runtime, title: str, client: str) -> dict:
    try:
        manifest: dict[str, Any] = toolchain.manifest()
    except toolchain.ToolchainError as exc:
        manifest = {"unavailable": str(exc)}
    backend = runtime.backend
    document = {
        "bundle_schema": SCHEMA,
        "title": title,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "live",
        "enforcement": sorted({run["enforcement"] for run in _runs(steps)}),
        "source": {"client": client, "agent_in_a_box": version("agent-in-a-box")},
        "scenario": {"name": scenario.NAME, "task": scenario.TASK,
                     "fixtures": scenario.fixture_hashes()},
        "schema": {"sha256": sha256_text(schema.schema_text()), "text": schema.schema_text()},
        "policies": _policies(steps),
        "tool_manifest": manifest,
        "evaluator": runtime.evaluator.name,
        "backend": {"name": backend.name if backend else None,
                    "capabilities": plain(backend.capabilities()) if backend else None},
        "transport_mappings": _transports(steps),
        "steps": [plain(step) for step in steps],
    }
    document["bundle_id"] = canonical_hash(document)
    return document


def write(document: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", document["title"].lower()).strip("-") or "bundle"
    path = directory / f"{slug}-{document['bundle_id'][:12]}.json"
    path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n")
    return path


def load(path: Path, *, as_native: bool = False) -> dict:
    """Read and verify a bundle. The result is marked to be shown as recorded."""
    document = json.loads(Path(path).read_text())
    if document.get("bundle_schema") != SCHEMA:
        raise BundleError(f"unsupported bundle schema {document.get('bundle_schema')!r}")
    claimed = document.pop("bundle_id", None)
    if claimed != canonical_hash(document):
        raise BundleError("bundle content does not match its id; it was modified")
    document["bundle_id"] = claimed
    if as_native and (not document["enforcement"] or "none" in document["enforcement"]):
        raise BundleError("a bundle produced under the test backend (enforcement: none) "
                          "cannot be imported as a native run")
    return {**document, "viewed_as": "recorded"}


def _decisions(document: dict) -> Iterator[tuple[str, dict]]:
    """Every recorded decision record, with where it came from."""
    for step in document["steps"]:
        result = step["result"]
        step_id = step["command_id"]
        for event in result.get("run", {}).get("events", []):
            if event["kind"] != "proxy.decision":
                continue
            for check in event["payload"]["checks"]:
                if check["decision"]:
                    yield f"{step_id}#{event['seq']}/{check['name']}", check["decision"]
        for number, record in enumerate(result.get("analysis", {}).get("replay", [])):
            yield f"{step_id}/replay{number}", record
        if "decision" in result:
            yield f"{step_id}/decision", result["decision"]


def replay(document: dict, evaluator: CedarEvaluator) -> dict:
    """Re-evaluate every recorded decision. No process, connection, or solver is started."""
    schema_text = document["schema"]["text"]
    matched = 0
    mismatched = []
    for where, recorded in _decisions(document):
        policy = document["policies"].get(recorded["policy_hash"])
        if policy is None:
            mismatched.append({"where": where, "problem": "policy text not in bundle"})
            continue
        bundle = PolicyBundle(policy["name"], schema_text, policy["text"])
        now = evaluator.evaluate(bundle, records.request_from(recorded))
        then = (recorded["raw"], recorded["determining"],
                [error["policy_id"] for error in recorded["errors"]])
        again = (now.raw, list(now.determining), [error.policy_id for error in now.errors])
        if then == again:
            matched += 1
        else:
            mismatched.append({"where": where, "recorded": then, "replayed": again})
    return {"decisions": matched + len(mismatched), "matched": matched,
            "mismatched": mismatched, "effects": "none", "evaluator": evaluator.name}
