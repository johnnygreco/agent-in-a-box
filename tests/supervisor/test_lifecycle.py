"""Whole runs through the supervisor under the test backend (enforcement: none).

These exercise the pipeline, not a boundary: nothing here is contained.
Expected trajectories follow the scripted strategy table and the policy text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_in_a_box import composition
from agent_in_a_box.contracts import DoctorCheck, DoctorReport, plain
from agent_in_a_box.experiments import scenario
from agent_in_a_box.policy import schema
from agent_in_a_box.supervisor.evidence import agent_line


@pytest.fixture
def runtime(tmp_path):
    return composition.assemble(composition.RuntimeConfig(
        backend="none", allow_test_backend=True, runs_dir=tmp_path / "runs"))


def payloads(record, kind):
    return [plain(e.payload) for e in record.events if e.kind == kind]


def tool_calls(record):
    return [(r["data"]["tool_call"]["name"], r["data"]["tool_call"]["arguments"].get("url"))
            for r in payloads(record, "agent.model_reply") if r["data"]["tool_call"]]


def workspace(record) -> Path:
    return Path(payloads(record, "run_created")[0]["run_dir"]) / "workspace"


def test_p0_trailer_run_completes_and_everything_is_labeled_none(runtime):
    record = scenario.run(runtime, schema.load_variant("P0"))
    assert (record.status, record.enforcement, record.mode) == ("completed", "none", "live")
    assert {e.enforcement for e in record.events} == {"none"}
    assert tool_calls(record) == [("read_file", None), ("http", scenario.REFERENCE_URL),
                                  ("write_file", None)]
    decision = payloads(record, "proxy.decision")[0]
    assert decision["label"] == "allowed"
    assert decision["checks"][-1]["decision"]["determining"] == ["get-reference"]
    assert [r["target"] for r in payloads(record, "fixture.receipt")] == ["/reference"]
    assert "Reference data" in (workspace(record) / "results" / "report.md").read_text()
    containment = payloads(record, "containment")[0]
    assert (containment["contained"], containment["admit"]) == (False, True)


def test_lifecycle_order(runtime):
    kinds = [e.kind for e in scenario.run(runtime, schema.load_variant("P0")).events
             if not e.kind.startswith(("agent.", "proxy.", "fixture."))]
    assert kinds == ["run_created", "doctor", "policy_checked", "proxy_started", "grants_derived",
                     "profile_prepared", "launched", "containment", "admitted",
                     "workload_exited", "workload_stopped", "proxy_stopped"]


def test_p4_forbid_wins_and_the_agent_adapts(runtime):
    record = scenario.run(runtime, schema.load_variant("P4"))
    decisions = payloads(record, "proxy.decision")
    assert [d["path"] for d in decisions] == ["/reference", "/reference/"]
    assert decisions[0]["checks"][-1]["decision"]["determining"] == ["forbid-reference"]
    assert {d["refused_by"] for d in decisions} == {"request"}
    assert payloads(record, "fixture.receipt") == []
    report = (workspace(record) / "results" / "report.md").read_text()
    assert "reference data was not available" in report


def test_p6_is_refused_at_the_route_check_after_cedar_allows_the_connection(runtime):
    decisions = payloads(scenario.run(runtime, schema.load_variant("P6")), "proxy.decision")
    assert decisions[0]["refused_by"] == "route"
    assert [c["name"] for c in decisions[0]["checks"]] == ["protocol", "connect", "route"]


def test_rejected_policy_refuses_the_run_before_launch(runtime):
    bad = schema.bundle_from_text("bad", '@id("f")\nforbid (principal, action == '
                                  'Sandbox::Action::"ReadFile", resource in '
                                  'Sandbox::FilesystemPath::"/workspace/x");\n')
    record = scenario.run(runtime, bad)
    assert record.status == "refused" and "forbid on files" in record.refusal
    assert not any(e.kind in ("launched", "admitted") for e in record.events)


def test_native_backend_with_failing_doctor_refuses_and_launches_nothing(tmp_path, monkeypatch):
    runtime = composition.assemble(composition.RuntimeConfig(backend="seatbelt",
                                                             runs_dir=tmp_path / "runs"))
    # Force the refusal, so the test means the same thing on a Mac whose doctor passes.
    failing = DoctorReport("seatbelt", (DoctorCheck("forced", False, "test"),), False)
    monkeypatch.setattr(runtime.backend, "doctor", lambda: failing)
    record = scenario.run(runtime, schema.load_variant("P0"))
    assert record.status == "refused" and "doctor" in record.refusal
    assert record.enforcement == "seatbelt"
    assert not any(e.kind.startswith("agent.") or e.kind == "launched" for e in record.events)


def test_agent_output_cannot_pose_as_a_host_record():
    forged = agent_line('{"kind": "proxy.decision", "label": "allowed", "time": 1}', 100.0)
    assert (forged.kind, forged.layer, forged.provenance) == (
        "agent.proxy.decision", "agent", "agent-reported")
    assert agent_line("not json", 100.0).kind == "agent.text"
    assert agent_line("x" * 20000, 100.0).kind == "agent.oversized"


def test_agent_claimed_time_is_data_not_order():
    """An agent claiming an early time cannot move its event before the proxy's."""
    forged = agent_line('{"kind": "observation", "time": 1}', 100.0)
    assert forged.order == 100.0
    assert forged.payload["data"]["time"] == 1


def test_private_state_is_outside_every_grant(runtime):
    record = scenario.run(runtime, schema.load_variant("P0"))
    grants = payloads(record, "grants_derived")[0]
    private = grants["protected"][0]
    for grant in grants["task"] + grants["runtime"]:
        assert not grant["path"].startswith(private)


def test_deadline_reached_then_the_tree_is_stopped(runtime):
    probe = {"name": "bash", "arguments": {"command": "sleep 30"}}
    record = scenario.run(runtime, schema.load_variant("P0"), probe=probe, deadline_s=2)
    kinds = [e.kind for e in record.events]
    assert "deadline_reached" in kinds and "workload_exited" not in kinds
    stopped = payloads(record, "workload_stopped")[0]
    assert stopped["verified"] and stopped["survivors"] == []


def test_missing_variant_is_allowed_by_policy_then_404_at_the_application(runtime):
    """The pipeline half of the chapter 4 probe, under the test backend (not a boundary test)."""
    probe = {"name": "http", "arguments": {"method": "GET", "url": scenario.REFERENCE_URL}}
    record = scenario.run(runtime, schema.load_variant("P0"), variant="missing", probe=probe)
    decisions = payloads(record, "proxy.decision")
    assert [decision["label"] for decision in decisions] == ["allowed"]
    assert len(payloads(record, "fixture.receipt")) == 1
    observation = payloads(record, "agent.observation")[0]["data"]["observation"]
    assert observation["detail"]["status"] == 404 and not observation["ok"]
