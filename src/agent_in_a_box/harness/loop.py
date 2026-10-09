"""The agent loop: messages -> model reply -> tool call -> observation -> next turn.

This is the whole harness. It knows nothing about policy, the proxy, the
kernel profile, or credentials. It proposes; the runtime decides. Every
event it emits is agent-reported data: a `tool_call` event means the agent
asked for something, not that anything was authorized or happened.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_in_a_box.contracts import ModelAdapter, Observation, Turn, plain

Tool = Callable[[Mapping[str, Any]], Observation]
Emit = Callable[[dict[str, Any]], None]


def run_agent(task: str, model: ModelAdapter, tools: Mapping[str, Tool], emit: Emit,
              max_turns: int = 12) -> list[Turn]:
    """Run until the model stops proposing tool calls or `max_turns` is reached."""
    history: list[Turn] = []
    emit({"kind": "agent_start", "task": task, "model": model.name, "tools": sorted(tools)})
    for number in range(1, max_turns + 1):
        reply = model.reply(task, history)
        call = reply.tool_call
        emit({"kind": "model_reply", "turn": number, "text": reply.text,
              "tool_call": plain(call) if call else None})
        if call is None:
            emit({"kind": "agent_finish", "turn": number, "reason": "model finished"})
            return history
        tool = tools.get(call.name)
        observation = (tool(call.arguments) if tool else
                       Observation(call.name, False, f"unknown tool {call.name!r}", {}))
        emit({"kind": "observation", "turn": number, "observation": plain(observation)})
        history.append(Turn(reply, observation))
    emit({"kind": "agent_finish", "turn": max_turns, "reason": "turn limit reached"})
    return history
