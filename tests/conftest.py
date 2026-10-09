"""Shared test configuration.

Tests marked `toolchain` need the pinned Cedar bridge and cvc5 installed by
`python3 tooling/bootstrap.py`. They are skipped, with the reason shown, when
the toolchain is absent; CI installs it and runs them.
"""

from __future__ import annotations

import pytest

from agent_in_a_box.policy import toolchain


def _toolchain_reason() -> str | None:
    try:
        toolchain.load()
    except toolchain.ToolchainError as exc:
        return str(exc)
    return None


def pytest_collection_modifyitems(config, items):
    reason = _toolchain_reason()
    if reason is None:
        return
    skip = pytest.mark.skip(reason=f"pinned toolchain unavailable: {reason}")
    for item in items:
        if "toolchain" in item.keywords:
            item.add_marker(skip)
