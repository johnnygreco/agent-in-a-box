"""When a native backend cannot run here: skip locally, fail where CI requires it.

CI sets AGENT_IN_A_BOX_REQUIRE_NATIVE to the backend its runner must exercise
(for example "landlock" on ubuntu-24.04). There, a doctor refusal is a test
failure, so a native suite can never pass by silently skipping.
"""

from __future__ import annotations

import os

import pytest

from agent_in_a_box import composition


def native_runtime_or_skip(name: str, runs_dir):
    required = os.environ.get("AGENT_IN_A_BOX_REQUIRE_NATIVE", "")
    if name not in composition.BACKENDS:
        pytest.skip(f"{name} backend is not implemented yet")
    runtime = composition.assemble(composition.RuntimeConfig(backend=name, runs_dir=runs_dir))
    doctor = runtime.backend.doctor()
    if doctor.ok:
        return runtime
    reason = f"{name} doctor refuses on this host: " + "; ".join(
        check.detail for check in doctor.checks if not check.ok)
    if name in required.split(","):
        pytest.fail(f"this runner must run the {name} suite, but {reason}")
    pytest.skip(reason)
