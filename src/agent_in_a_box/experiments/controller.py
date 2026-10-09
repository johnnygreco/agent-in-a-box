"""The run controller: explicit commands with idempotency (shared by gateway, CLI, notebooks).

Every effect (a live run, a solver job, an export) is a command with a
caller-chosen ID. The input hash pins its payload. Submitting the same ID
again returns the stored result and runs nothing; reusing an ID with a
different payload is refused. Results persist on disk, so a restart, a page
refresh, or a reconnecting client cannot cause a second execution.

No command selects a backend. The backend is fixed when the runtime is
assembled (composition.py); unknown payload fields are refused.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agent_in_a_box.composition import Runtime
from agent_in_a_box.contracts import (
    CommandResult, EvidenceEvent, LaunchRefused, PolicyBundle, canonical_hash, plain,
)
from agent_in_a_box.experiments import bundle as bundles
from agent_in_a_box.experiments import scenario
from agent_in_a_box.policy import analyzer, requests, schema
from agent_in_a_box.policy.domains import DOMAINS
from agent_in_a_box.policy.toolchain import ToolchainError

COMMAND_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# The payload fields each command kind accepts. Anything else is refused.
FIELDS = {
    "run": {"policy", "fixture_variant", "probe"},
    "analyze": {"property", "old", "new", "solver", "emit_smtlib", "domain"},
    "evaluate": {"policy", "request"},
    "task_check": {"policy"},
    "export": {"commands", "title", "client"},
}
SOLVERS = {"default": analyzer.DEFAULT_SOLVER_ARGS, "starved": analyzer.STARVED_SOLVER_ARGS}


class Refused(Exception):
    """A command was well-formed but not allowed to run."""


def policy_bundle(reference: Any) -> PolicyBundle:
    try:
        return schema.resolve_policy(reference)
    except (KeyError, ValueError) as error:
        raise Refused(str(error)) from error


class Controller:
    def __init__(self, runtime: Runtime, publish: Callable[[dict], None] | None = None) -> None:
        self.runtime = runtime
        self.publish = publish or (lambda envelope: None)
        self.store = runtime.config.runs_dir.parent / "commands"
        self.store.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.running: dict[str, CommandResult] = {}
        self.pool = ThreadPoolExecutor(max_workers=2)
        # Where each command kind goes.
        self.handlers: dict[str, Callable[[str, Mapping[str, Any]], dict]] = {
            "run": self.run,
            "analyze": self.analyze,
            "evaluate": self.evaluate,
            "task_check": self.task_check,
            "export": self.export,
        }

    # ── Storage ─────────────────────────────────────────────────────────

    def path(self, command_id: str) -> Path:
        return self.store / f"{command_id}.json"

    def result(self, command_id: str) -> CommandResult | None:
        if command_id in self.running:
            return self.running[command_id]
        path = self.path(command_id)
        if not path.is_file():
            return None
        return CommandResult(**json.loads(path.read_text()))

    def finish(self, result: CommandResult) -> CommandResult:
        self.path(result.command_id).write_text(json.dumps(plain(result)))
        with self.lock:
            self.running.pop(result.command_id, None)
        self.publish({"type": "command", "result": plain(result)})
        return result

    # ── Submission ──────────────────────────────────────────────────────

    def admit(self, command_id: str, kind: str, payload: Mapping[str, Any]
              ) -> tuple[CommandResult, bool]:
        """Return (result, is_new). An existing ID returns its stored result."""
        input_hash = canonical_hash({"kind": kind, "payload": payload})
        if not COMMAND_ID.match(command_id) or kind not in FIELDS:
            reason = {"reason": "bad command id or unknown kind"}
            return CommandResult(command_id, kind, input_hash, "refused", reason, payload), False
        with self.lock:
            existing = self.result(command_id)
            if existing is not None and existing.input_hash != input_hash:
                reason = {"reason": "command id already used with a different input"}
                return CommandResult(command_id, kind, input_hash, "refused", reason,
                                     payload), False
            if existing is not None:
                return existing, False
            started = CommandResult(command_id, kind, input_hash, "running", {}, payload)
            self.running[command_id] = started
        return started, True

    def submit(self, command_id: str, kind: str, payload: Mapping[str, Any]) -> CommandResult:
        """Run a command to completion in this thread (or return its stored result)."""
        result, is_new = self.admit(command_id, kind, payload)
        if is_new:
            return self.execute(result, payload)
        return result

    def start(self, command_id: str, kind: str, payload: Mapping[str, Any]) -> CommandResult:
        """Start a command in the background; poll `result` for its outcome."""
        result, is_new = self.admit(command_id, kind, payload)
        if is_new:
            self.pool.submit(self.execute, result, payload)
        return result

    def execute(self, started: CommandResult, payload: Mapping[str, Any]) -> CommandResult:
        try:
            unknown = set(payload) - FIELDS[started.kind]
            if unknown:
                raise Refused(f"unknown fields: {sorted(unknown)}")
            status = "succeeded"
            body = self.handlers[started.kind](started.command_id, payload)
        except (Refused, LaunchRefused) as refusal:
            status = "refused"
            body = {"reason": str(refusal)}
        except (ToolchainError, KeyError, ValueError) as error:
            status = "failed"
            body = {"reason": f"{type(error).__name__}: {error}"}
        return self.finish(CommandResult(started.command_id, started.kind, started.input_hash,
                                         status, body, payload))

    # ── Command kinds ───────────────────────────────────────────────────

    def run(self, command_id: str, payload: Mapping[str, Any]) -> dict:
        def publish(event: EvidenceEvent) -> None:
            self.publish({"type": "evidence", "command_id": command_id, "event": plain(event)})

        bundle = policy_bundle(payload.get("policy", "P0"))
        variant = payload.get("fixture_variant", "default")
        record = scenario.run(self.runtime, bundle, variant, payload.get("probe"), publish)
        return {"run": plain(record)}

    def analyze(self, command_id: str, payload: Mapping[str, Any]) -> dict:
        result = analyzer.check(
            prop=payload.get("property", "no-permission-expansion"),
            old=policy_bundle(payload["old"]),
            new=policy_bundle(payload["new"]),
            evaluator=self.runtime.evaluator,
            domain=DOMAINS[payload.get("domain", "D_http")],
            solver_args=SOLVERS[payload.get("solver", "default")],
            emit_smtlib=bool(payload.get("emit_smtlib", False)),
        )
        replayed = [record.to_json() for record in result.replay]
        return {"analysis": {**plain(result), "replay": replayed}}

    def evaluate(self, command_id: str, payload: Mapping[str, Any]) -> dict:
        """A hypothetical request, evaluated without any effect."""
        asked = payload["request"]
        if asked["action"] == "NetworkConnect":
            request = requests.network_connect(asked["host"], int(asked["port"]))
        else:
            request = requests.http_request(asked["host"], int(asked["port"]), asked["method"],
                                            asked["path"])
        record = self.runtime.evaluator.evaluate(policy_bundle(payload["policy"]), request)
        return {"decision": {**record.to_json(), "hypothetical": True}}

    def task_check(self, command_id: str, payload: Mapping[str, Any]) -> dict:
        request = requests.http_request("reference.fixture", 80, "GET", "/reference")
        record, label = analyzer.task_preserved(self.runtime.evaluator,
                                                policy_bundle(payload["policy"]), request)
        return {"decision": record.to_json(), "label": label, "operation": "GET /reference"}

    def export(self, command_id: str, payload: Mapping[str, Any]) -> dict:
        steps = [self.result(step_id) for step_id in payload["commands"]]
        if any(step is None or step.status == "running" for step in steps):
            raise Refused("every exported command must exist and be finished")
        title = str(payload.get("title", "experiment"))
        document = bundles.build(steps, self.runtime, title, str(payload.get("client", "unknown")))
        path = bundles.write(document, self.runtime.config.runs_dir.parent / "bundles")
        return {"bundle_id": document["bundle_id"], "path": str(path)}
