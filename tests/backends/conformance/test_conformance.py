"""One conformance suite for every native backend (PLAN.md, Backend module boundary).

Written from CURRICULUM.md's controlled probe table and PLAN.md's native
boundary acceptance list, not from any backend's observed behavior. A backend
that is not implemented, or whose doctor refuses on this host, is skipped
with its reason. None of these probes has run natively yet (STATUS.md);
macOS Seatbelt defines the expectations, and a Linux gap is marked
expected-fail with a reason recorded in reference/platform-differences.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent_in_a_box.contracts import RunRecord, plain
from agent_in_a_box.experiments import scenario
from agent_in_a_box.network.proxy import Route
from agent_in_a_box.policy import schema
from tests.native.required import native_runtime_or_skip

NATIVE_BACKENDS = ("seatbelt", "landlock")
# Linux-only expected failures, each with its reason. None are known yet.
EXPECTED_FAIL: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class Probe:
    """One row of CURRICULUM.md's controlled probe table.

    `command` is a bash command or, for `tool == "http"`, a URL. It may name
    {canary}, {outside} (paths outside every grant) and {direct} (the fixture's
    own host and port, which only the proxy should be able to reach).
    """

    name: str
    tool: str
    command: str
    expected: str  # "succeeds", "blocked", "allowed", "refused", "allowed, then 404",
    #               or "killed at teardown"
    method: str = "GET"
    variant: str = "default"


PROBES = [
    Probe("read a granted file", "bash", "cat measurements.csv", "succeeds"),
    Probe("read a canary outside the grant", "bash", "cat {canary}", "blocked"),
    Probe("write outside the grant", "bash", "echo x > {outside}/file", "blocked"),
    Probe("read protected supervisor state", "bash", "cat ../private/policy.cedar", "blocked"),
    Probe("GET through the proxy", "http", scenario.REFERENCE_URL, "allowed"),
    Probe("GET directly to the fixture host and port", "bash",
          "curl -sS --fail --noproxy '*' --max-time 5 http://{direct}/reference", "blocked"),
    Probe("POST through the proxy under P0", "http", scenario.REFERENCE_URL, "refused",
          method="POST"),
    Probe("GET through the proxy when the fixture has no data", "http", scenario.REFERENCE_URL,
          "allowed, then 404", variant="missing"),
    Probe("child Python reads the canary", "bash",
          "python3 -c 'print(open(\"{canary}\").read())'", "blocked"),
    Probe("detach and sleep", "bash", "nohup sleep 600 >/dev/null 2>&1 &", "killed at teardown"),
]


def tool_call(probe: Probe, route: Route, paths: dict[str, str]) -> dict:
    """The probe's tool call, with the run's fixture address and canary paths filled in."""
    text = probe.command.format(direct=f"{route.host}:{route.port}", **paths)
    if probe.tool == "http":
        return {"name": "http", "arguments": {"method": probe.method, "url": text}}
    return {"name": "bash", "arguments": {"command": text}}


@pytest.fixture(params=NATIVE_BACKENDS)
def native_runtime(request, tmp_path):
    return native_runtime_or_skip(request.param, tmp_path / "runs")


def events(record: RunRecord, kind: str) -> list[dict]:
    return [plain(event.payload) for event in record.events if event.kind == kind]


def observation(record: RunRecord) -> dict:
    return events(record, "agent.observation")[0]["data"]["observation"]


def run_probe(runtime, probe: Probe, tmp_path) -> RunRecord:
    (tmp_path / "canary.txt").write_text("canary\n")
    (tmp_path / "outside").mkdir()
    paths = {"canary": str(tmp_path / "canary.txt"), "outside": str(tmp_path / "outside")}

    def build_call(route: Route) -> dict:
        return tool_call(probe, route, paths)

    return scenario.run(runtime, schema.load_variant("P0"), variant=probe.variant,
                        probe=build_call, deadline_s=20)


def check_expected(record: RunRecord, probe: Probe) -> None:
    """Compare a run's evidence with the probe's authored expectation and "how we know"."""
    decisions = events(record, "proxy.decision")
    receipts = events(record, "fixture.receipt")
    if probe.expected == "killed at teardown":
        stopped = events(record, "workload_stopped")[0]
        assert stopped["verified"] and stopped["survivors"] == []
    elif probe.expected == "succeeds":
        assert observation(record)["ok"] and decisions == []
    elif probe.expected == "blocked":
        assert not observation(record)["ok"]
        assert decisions == [] and receipts == []
    elif probe.expected == "refused":
        assert [decision["label"] for decision in decisions] == ["refused"]
        assert receipts == []
    elif probe.expected == "allowed":
        assert [decision["label"] for decision in decisions] == ["allowed"]
        assert len(receipts) == 1
    elif probe.expected == "allowed, then 404":
        assert [decision["label"] for decision in decisions] == ["allowed"]
        assert len(receipts) == 1
        assert observation(record)["detail"]["status"] == 404
    else:
        raise AssertionError(f"unknown expectation {probe.expected!r}")


@pytest.mark.native
@pytest.mark.parametrize("probe", PROBES, ids=lambda probe: probe.name)
def test_probe(native_runtime, probe, tmp_path):
    reason = EXPECTED_FAIL.get((native_runtime.backend.name, probe.name))
    if reason:
        pytest.xfail(reason)
    record = run_probe(native_runtime, probe, tmp_path)
    assert record.status == "completed"
    assert record.enforcement == native_runtime.backend.name
    check_expected(record, probe)
