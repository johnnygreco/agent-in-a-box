"""The shared scenario: the research assistant (CURRICULUM.md, Shared scenario).

The agent reads workspace/measurements.csv, fetches GET /reference from
reference.fixture through the proxy, and writes workspace/results/report.md.
Every run gets a fresh fixture service, fresh connections, and a fresh copy
of the workspace fixture, so runs under different policies are comparable.
"""

from __future__ import annotations

import contextlib
import secrets
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

from agent_in_a_box.composition import Runtime
from agent_in_a_box.contracts import LaunchRefused, PolicyBundle, RunRecord, sha256_text
from agent_in_a_box.network.fixture_service import VARIANT_DIR
from agent_in_a_box.network.proxy import Route
from agent_in_a_box.supervisor import lifecycle
from agent_in_a_box.supervisor.evidence import Publish
from agent_in_a_box.supervisor.runs import WORKSPACE_FIXTURE

NAME = "research-assistant"
TASK = ("Read workspace/measurements.csv, fetch reference data with GET /reference from "
        "reference.fixture, and write workspace/results/report.md.")
REFERENCE = "reference.fixture:80"
REFERENCE_URL = "http://reference.fixture/reference"


@contextlib.contextmanager
def fixture_service(variant: str, receipts: Path) -> Iterator[Route]:
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_in_a_box.network.fixture_service", "--variant", variant,
         "--receipts", str(receipts)], stdout=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout is not None
        line = process.stdout.readline().split()
        if line[:1] != ["READY"]:
            raise LaunchRefused(f"fixture service did not start: {line}")
        yield Route(REFERENCE, "127.0.0.1", int(line[1]))
    finally:
        process.terminate()
        process.wait(timeout=5)


def fixture_hashes() -> dict[str, str]:
    """Hashes of every fixture file a run can read, for bundles."""
    workspace_files = sorted(path for path in WORKSPACE_FIXTURE.rglob("*") if path.is_file())
    variant_files = sorted(VARIANT_DIR.glob("*.json"))
    return {str(path.relative_to(WORKSPACE_FIXTURE.parent)): sha256_text(path.read_text())
            for path in workspace_files + variant_files}


def run(runtime: Runtime, bundle: PolicyBundle, variant: str = "default",
        probe: Mapping | Callable[[Route], Mapping] | None = None,
        publish: Publish | None = None, deadline_s: float = 60.0) -> RunRecord:
    """One live run. Raises LaunchRefused if no backend can run on this host.

    `probe` is a tool call for the one-call probe model, or a function that
    builds one from the fixture's route (for probes that bypass the proxy).
    """
    if runtime.backend is None:
        raise LaunchRefused(runtime.backend_refusal or "no backend")
    fixtures = runtime.config.runs_dir / "fixture-receipts"
    fixtures.mkdir(parents=True, exist_ok=True)
    receipts = fixtures / f"{secrets.token_hex(8)}.jsonl"
    with fixture_service(variant, receipts) as route:
        probe = probe(route) if callable(probe) else probe
        request = lifecycle.RunRequest(TASK, bundle, variant, {REFERENCE: route}, receipts,
                                       deadline_s, probe)
        return lifecycle.run(request, runtime.backend, runtime.evaluator,
                             runtime.config.evaluator, runtime.config.runs_dir, publish)
