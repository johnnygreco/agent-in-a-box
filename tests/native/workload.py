"""Run one command as the workload of a native run and return what it observed.

Shared by the platform-only native suites (tests/native/linux, tests/native/macos).
"""

from __future__ import annotations

import json

from agent_in_a_box.contracts import plain
from agent_in_a_box.experiments import scenario
from agent_in_a_box.policy import schema


def events(record, kind):
    return [plain(event.payload) for event in record.events if event.kind == kind]


def run_bash(runtime, command, **tokens):
    """Run one bash command as the workload; return (record, observation).

    @DIRECT_PORT@ becomes the fixture's own port, and @NAME@ the value of `name=`.
    """
    def build(route):
        text = command.replace("@DIRECT_PORT@", str(route.port))
        for key, value in tokens.items():
            text = text.replace(f"@{key.upper()}@", str(value))
        return {"name": "bash", "arguments": {"command": text}}

    record = scenario.run(runtime, schema.load_variant("P0"), probe=build, deadline_s=30)
    assert record.status == "completed", record.refusal
    assert record.enforcement == runtime.backend.name
    return record, events(record, "agent.observation")[0]["data"]["observation"]


def run_python(runtime, code, **tokens):
    """Run a child Python program; it prints one JSON object of results."""
    command = "python3 -c " + "'" + code.replace("'", "'\"'\"'") + "'"
    record, observation = run_bash(runtime, command, **tokens)
    lines = observation["output"].strip().splitlines()
    assert lines, observation
    return record, json.loads(lines[-1])
