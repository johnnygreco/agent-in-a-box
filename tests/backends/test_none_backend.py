"""The test double: never a sandbox, never a fallback, always labeled `none`."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent_in_a_box import composition
from agent_in_a_box.contracts import ContainmentReport, LaunchRefused
from agent_in_a_box.supervisor import runs
from agent_in_a_box.supervisor.backends.none import NoEnforcementBackend


def test_capabilities_and_doctor_disclose_no_enforcement():
    backend = NoEnforcementBackend()
    caps = backend.capabilities()
    assert (caps.profile_format, caps.network_mechanism) == ("none", "none")
    assert not backend.doctor().native_execution


def test_not_selectable_without_explicit_test_configuration():
    with pytest.raises(LaunchRefused):
        composition.select_backend(composition.RuntimeConfig(backend="none"))


def test_the_default_is_never_the_test_backend():
    runtime = composition.assemble(composition.RuntimeConfig())
    assert runtime.backend is None or runtime.backend.name != "none"


def test_never_a_fallback_for_a_missing_native_backend(monkeypatch):
    monkeypatch.setattr(composition, "NATIVE_BY_PLATFORM", {})
    runtime = composition.assemble(composition.RuntimeConfig())
    assert runtime.backend is None
    assert "no native backend" in runtime.backend_refusal


def test_containment_report_cannot_claim_containment_for_none():
    with pytest.raises(ValueError):
        ContainmentReport("none", contained=True, admit=True, probes=(), notes=())
    with pytest.raises(ValueError):
        ContainmentReport("seatbelt", contained=False, admit=True, probes=(), notes=())


def test_workload_waits_at_the_gate_until_confirm(tmp_path):
    backend = NoEnforcementBackend()
    run = runs.create_run(tmp_path / "runs")
    probe = {"name": "bash", "arguments": {"command": "echo hi"}}
    workload = runs.workload(run, "t", proxy_port=9, deadline_s=10, probe=probe)
    process = backend.launch(backend.prepare(_empty_plan(), run), workload)
    time.sleep(0.5)
    assert Path(workload.stdout_path).read_text() == ""
    report = backend.confirm(process)
    assert (report.enforcement, report.contained, report.admit) == ("none", False, True)
    assert backend.wait(process, 10) == 0
    stopped = backend.stop(process)
    assert stopped.exit_status == 0 and stopped.verified
    assert '"agent_start"' in Path(workload.stdout_path).read_text()


def test_stop_ends_lingering_descendants_in_the_group(tmp_path):
    backend = NoEnforcementBackend()
    run = runs.create_run(tmp_path / "runs")
    command = "nohup sleep 600 >/dev/null 2>&1 & sleep 600"
    probe = {"name": "bash", "arguments": {"command": command}}
    workload = runs.workload(run, "t", proxy_port=9, deadline_s=1, probe=probe)
    process = backend.launch(backend.prepare(_empty_plan(), run), workload)
    backend.confirm(process)
    assert backend.wait(process, 1) is None
    stopped = backend.stop(process)
    assert stopped.verified and stopped.survivors == ()
    assert stopped.limits


def _empty_plan():
    from agent_in_a_box.contracts import GrantPlan

    return GrantPlan((), (), (), 9, "h")
