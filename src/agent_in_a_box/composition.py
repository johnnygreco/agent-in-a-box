"""Assembly: the one place that names concrete implementations.

Backends are registered here by explicit name and imported nowhere else
(PLAN.md, Backend module boundary). Platform checks live here or inside a
backend package, never in core modules.

The test backend (`none`) is selected only when the caller passes
`allow_test_backend=True`, which only tests and the developer CLI flag
`--test-backend` do. It is never a fallback: if the native backend for this
host is missing or unimplemented, the run is refused.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_in_a_box.contracts import CedarEvaluator, LaunchRefused, SupervisorBackend
from agent_in_a_box.policy.schema import REPO_ROOT

# The native backend for each host platform.
NATIVE_BY_PLATFORM = {"darwin": "seatbelt", "linux": "landlock"}


def _seatbelt() -> SupervisorBackend:
    from agent_in_a_box.supervisor.backends.seatbelt import SeatbeltBackend

    return SeatbeltBackend()


def _none() -> SupervisorBackend:
    from agent_in_a_box.supervisor.backends.none import NoEnforcementBackend

    return NoEnforcementBackend()


def _landlock() -> SupervisorBackend:
    from agent_in_a_box.supervisor.backends.landlock import LandlockBackend

    return LandlockBackend()


BACKENDS: dict[str, Callable[[], SupervisorBackend]] = {
    "seatbelt": _seatbelt, "landlock": _landlock, "none": _none,
}


def _cedarpy() -> CedarEvaluator:
    from agent_in_a_box.policy.evaluator import CedarpyEvaluator

    return CedarpyEvaluator()


def _bridge() -> CedarEvaluator:
    from agent_in_a_box.policy.bridge_evaluator import BridgeEvaluator

    return BridgeEvaluator()


EVALUATORS: dict[str, Callable[[], CedarEvaluator]] = {"cedarpy": _cedarpy, "bridge": _bridge}


@dataclass(frozen=True)
class RuntimeConfig:
    """How to assemble a runtime. Defaults are the native, enforcing choices."""

    backend: str | None = None
    allow_test_backend: bool = False
    evaluator: str = "cedarpy"
    runs_dir: Path = REPO_ROOT / ".agent-in-a-box" / "runs"


def native_backend_name() -> str:
    name = NATIVE_BY_PLATFORM.get(sys.platform)
    if name is None:
        raise LaunchRefused(f"no native backend exists for {sys.platform}")
    return name


def select_backend(config: RuntimeConfig) -> SupervisorBackend:
    name = config.backend or native_backend_name()
    if name == "none" and not config.allow_test_backend:
        raise LaunchRefused("the test backend needs explicit test or developer configuration")
    if name not in BACKENDS:
        raise LaunchRefused(f"backend {name!r} is not available on this build; refusing to run")
    return BACKENDS[name]()


def select_evaluator(name: str) -> CedarEvaluator:
    if name not in EVALUATORS:
        raise ValueError(f"unknown evaluator {name!r}; known: {sorted(EVALUATORS)}")
    return EVALUATORS[name]()


@dataclass(frozen=True)
class Runtime:
    """One assembled runtime. `backend` is None when no backend can run on this
    host; runs are then refused with `backend_refusal`, and analysis and
    recorded content still work."""

    config: RuntimeConfig
    backend: SupervisorBackend | None
    backend_refusal: str | None
    evaluator: CedarEvaluator

    @property
    def enforcement(self) -> str | None:
        return self.backend.name if self.backend else None


def assemble(config: RuntimeConfig) -> Runtime:
    evaluator = select_evaluator(config.evaluator)
    try:
        backend = select_backend(config)
    except LaunchRefused as refusal:
        return Runtime(config, None, str(refusal), evaluator)
    return Runtime(config, backend, None, evaluator)
