"""The teaching source route stays within its line budgets (PLAN.md, invariant 9).

One file per concept, read top to bottom in chapter 9. Concepts not yet
implemented (model bridge: Milestone 3) are listed with no file and are added
here when they land. The launcher slot holds the first launcher to exist, the
Linux one; the macOS launcher joins it in Milestone 1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "agent_in_a_box"

ROUTE = [
    ("agent loop", "harness/loop.py", 150),
    ("request construction", "policy/requests.py", 100),
    ("determining-policy extraction", "policy/authored_ids.py", 100),
    ("evaluator adapter", "policy/evaluator.py", 100),
    ("policy subset compiler", "policy/compiler.py", 250),
    ("launcher", "supervisor/backends/landlock/launcher.py", 150),
    ("proxy decision path", "network/proxy.py", 150),
    ("analyzer adapter and witness replay", "policy/analyzer.py", 150),
    ("lifecycle", "supervisor/lifecycle.py", 150),
    ("model bridge", None, 150),
]


@pytest.mark.parametrize(("concept", "path", "budget"), ROUTE, ids=[r[0] for r in ROUTE])
def test_within_budget(concept, path, budget):
    if path is None:
        pytest.skip(f"{concept} is not implemented yet")
    lines = len((SRC / path).read_text().splitlines())
    assert lines <= budget, f"{concept}: {path} has {lines} lines, budget {budget}"
