"""A model that proposes exactly one tool call, then stops.

Used for controlled probes (chapter 4) and to run a distinguishing request
through the ordinary runtime: the same harness, proxy, and boundary as any
agent, with the trajectory fixed in advance.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_in_a_box.contracts import ModelReply, ToolCall, Turn


class ProbeModel:
    name = "probe"

    def __init__(self, call: ToolCall) -> None:
        self.call = call

    def reply(self, task: str, history: Sequence[Turn]) -> ModelReply:
        if not history:
            return ModelReply(f"probe: {self.call.name}", self.call)
        return ModelReply("probe finished", None)
