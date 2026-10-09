"""Workload entry point: `python -m agent_in_a_box.harness --task TEXT`.

Runs inside the workload process tree, in the run's workspace. It waits for
the backend to admit it (one line, "admit", on stdin), then runs the loop and
writes one JSON event per line to stdout. Everything it writes is
agent-reported data; the supervisor treats it as untrusted.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from agent_in_a_box.contracts import ToolCall
from agent_in_a_box.harness.loop import run_agent
from agent_in_a_box.harness.tools import TOOLS
from agent_in_a_box.models.probe import ProbeModel
from agent_in_a_box.models.scripted import ScriptedModel


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent in a Box harness")
    parser.add_argument("--task", required=True)
    parser.add_argument("--model", choices=["scripted", "probe"], default="scripted")
    parser.add_argument("--probe", help="JSON tool call for the probe model")
    parser.add_argument("--max-turns", type=int, default=12)
    args = parser.parse_args()
    if sys.stdin.readline().strip() != "admit":
        print(json.dumps({"kind": "not_admitted"}), flush=True)
        return 3
    if args.model == "probe":
        call = json.loads(args.probe)
        model = ProbeModel(ToolCall(call["name"], call["arguments"]))
    else:
        model = ScriptedModel()
    run_agent(args.task, model, TOOLS,
              lambda event: print(json.dumps({**event, "time": time.time()}), flush=True),
              args.max_turns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
