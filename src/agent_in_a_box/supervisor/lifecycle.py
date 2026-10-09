"""Run one experiment in the order PLAN.md requires (Supervisor, startup order).

  1. validate configuration and policy     backend doctor; schema and subset checks
  2. allocate run state and listeners      run directory; the per-run proxy
  3. derive and inspect grants             task grants, runtime grants, protected paths
  4. prepare the native profile            backend.prepare
  5. start the launcher                    backend.launch; the workload waits at a gate
  6. confirm, then admit                   backend.confirm; refuse unless it admits
  7. wait for exit or the deadline         backend.wait; evidence is collected meanwhile
  8. stop the workload, then the proxy     data plane stays up until the tree is stopped

Any failure before admission refuses the run. No step falls back to an
uncontained launch; the test backend runs only when composition selected it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_in_a_box.contracts import (
    CedarEvaluator, ContainedProcess, LaunchRefused, PolicyBundle, RunRecord, RunSpec,
    SupervisorBackend, WorkloadSpec, plain,
)
from agent_in_a_box.network.proxy import Route
from agent_in_a_box.policy.compiler import PolicyRejected, compile_policy
from agent_in_a_box.supervisor import dataplane, runs
from agent_in_a_box.supervisor.evidence import EvidenceLog, Publish
from agent_in_a_box.supervisor.grants import grant_plan

POLL_S = 0.01
REFUSALS = (LaunchRefused, PolicyRejected, dataplane.DataPlaneError)


@dataclass(frozen=True)
class RunRequest:
    task: str
    bundle: PolicyBundle
    fixture_variant: str
    routes: Mapping[str, Route]
    receipts: Path | None = None
    deadline_s: float = 60.0
    probe: Mapping | None = None


@dataclass(frozen=True)
class Started:
    """What steps 1 to 6 produced: an admitted workload and the proxy serving it."""

    proxy: dataplane.ProxyHandle
    process: ContainedProcess
    workload: WorkloadSpec
    profile_sha256: str | None


def run(request: RunRequest, backend: SupervisorBackend, evaluator: CedarEvaluator,
        evaluator_name: str, runs_dir: Path, publish: Publish | None = None) -> RunRecord:
    run_spec = runs.create_run(runs_dir)
    log = EvidenceLog(run_spec.run_id, backend.name, publish)
    log.lifecycle("run_created", run_dir=run_spec.run_dir, backend=backend.name,
                  capabilities=plain(backend.capabilities()))
    try:
        started = start(request, backend, evaluator, evaluator_name, run_spec, log)
    except REFUSALS as refusal:
        log.lifecycle("refused", reason=str(refusal))
        return run_record(request, run_spec, backend, log, "refused", None, str(refusal))
    observe(request, backend, started, log)
    return run_record(request, run_spec, backend, log, "completed", started.profile_sha256, None)


def start(request: RunRequest, backend: SupervisorBackend, evaluator: CedarEvaluator,
          evaluator_name: str, run_spec: RunSpec, log: EvidenceLog) -> Started:
    """Steps 1 to 6. Raises one of REFUSALS, after stopping the proxy if it started."""
    doctor = backend.doctor()
    log.lifecycle("doctor", ok=doctor.ok, checks=plain(doctor.checks),
                  native_execution=doctor.native_execution)
    if not doctor.ok:
        failed = [check.detail for check in doctor.checks if not check.ok]
        raise LaunchRefused("doctor: " + "; ".join(failed))
    compiled = compile_policy(request.bundle, evaluator)
    log.lifecycle("policy_checked", label="checked against the schema",
                  validator=compiled.validation.validator,
                  policy_ids=[policy.id for policy in compiled.validation.policies],
                  warnings=plain(compiled.validation.warnings))

    proxy = dataplane.start_proxy(run_spec, compiled, dict(request.routes), evaluator_name)
    try:
        log.lifecycle("proxy_started", port=proxy.port, routes=plain(list(request.routes.values())),
                      eligible=plain(compiled.proxy.eligible))
        plan = grant_plan(compiled, run_spec, proxy.port)
        log.lifecycle("grants_derived", task=plain(plan.task), runtime=plain(plan.runtime),
                      protected=list(plan.protected))
        prepared = backend.prepare(plan, run_spec)
        if prepared.profile_path:
            log.add("profile_prepared", "kernel", "installed-profile", plain(prepared))
        else:
            log.lifecycle("profile_prepared", **plain(prepared))

        probe = plain(request.probe) if request.probe else None
        workload = runs.workload(run_spec, request.task, proxy.port, request.deadline_s, probe)
        process = backend.launch(prepared, workload)
        log.lifecycle("launched", pid=process.pid, argv=list(workload.argv))
        report = backend.confirm(process)
        log.lifecycle("containment", **plain(report))
        if not report.admit:
            backend.stop(process)
            raise LaunchRefused("containment was not confirmed; workload not admitted")
        log.lifecycle("admitted", contained=report.contained)
    except Exception:
        dataplane.stop(proxy.process)
        raise
    return Started(proxy, process, workload, prepared.profile_sha256)


def observe(request: RunRequest, backend: SupervisorBackend, started: Started,
            log: EvidenceLog) -> None:
    """Steps 7 and 8: collect evidence until the workload exits or the deadline
    passes, then stop the workload's process tree, then the proxy."""
    log.follow(Path(started.workload.stdout_path), started.proxy.decisions_path, request.receipts)
    deadline = time.monotonic() + request.deadline_s
    exit_status = None
    while exit_status is None and time.monotonic() < deadline:
        log.poll()
        exit_status = backend.wait(started.process, POLL_S)
    if exit_status is None:
        log.lifecycle("deadline_reached", deadline_s=request.deadline_s)
    else:
        log.lifecycle("workload_exited", exit_status=exit_status)

    report = backend.stop(started.process)
    log.poll()
    log.lifecycle("workload_stopped", **plain(report))
    log.lifecycle("proxy_stopped", exit_status=dataplane.stop(started.proxy.process))
    stderr = Path(started.workload.stderr_path)
    if stderr.exists() and stderr.stat().st_size:
        log.add("agent.stderr", "agent", "agent-reported", {"text": stderr.read_text()[-4000:]})


def run_record(request: RunRequest, run_spec: RunSpec, backend: SupervisorBackend,
               log: EvidenceLog, status: str, profile_sha256: str | None,
               refusal: str | None) -> RunRecord:
    return RunRecord(
        run_id=run_spec.run_id, enforcement=backend.name, mode="live", status=status,
        task=request.task, policy_name=request.bundle.name,
        policy_hash=request.bundle.policy_hash, schema_hash=request.bundle.schema_hash,
        fixture_variant=request.fixture_variant, profile_sha256=profile_sha256,
        refusal=refusal, events=tuple(log.events),
    )
