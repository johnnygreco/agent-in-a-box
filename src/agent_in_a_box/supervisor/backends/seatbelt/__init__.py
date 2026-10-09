"""SeatbeltBackend: the primary native backend, macOS Seatbelt.

Milestone 0 provides the SBPL renderer and `prepare`. The launcher, probes,
waiting, and stopping arrive in Milestone 1; until then `doctor` fails and `launch`
refuses, so selecting this backend never runs anything uncontained.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from agent_in_a_box.contracts import (
    BackendCapabilities, ContainedProcess, ContainmentReport, DoctorCheck, DoctorReport, GrantPlan,
    LaunchRefused, PreparedProfile, RunSpec, TeardownReport, WorkloadSpec,
)
from agent_in_a_box.supervisor.backends.seatbelt.os_baseline import BASELINE
from agent_in_a_box.supervisor.backends.seatbelt.profile import PROFILE_FORMAT, render

NOT_YET = "the Seatbelt launcher is implemented in Milestone 1; refusing to run"


class SeatbeltBackend:
    name = "seatbelt"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            profile_format=PROFILE_FORMAT,
            separate_read_write_grants=True,
            controls_truncate=True,
            pid_isolation=False,
            network_mechanism="port-allow",
            notes=(
                "Seatbelt does not hide other processes; teardown relies on supervisor "
                "process accounting.",
                "Profile rules are untested natively until Milestone 1.",
            ),
        )

    def doctor(self) -> DoctorReport:
        checks = (
            DoctorCheck("macOS host", sys.platform == "darwin", f"sys.platform is {sys.platform}"),
            DoctorCheck("Seatbelt launcher", False, NOT_YET),
        )
        return DoctorReport("seatbelt", checks, native_execution=False)

    def prepare(self, plan: GrantPlan, run: RunSpec) -> PreparedProfile:
        text = render(plan)
        path = Path(run.private) / "profile.sb"
        path.write_text(text)
        return PreparedProfile(
            backend="seatbelt",
            profile_format=PROFILE_FORMAT,
            profile_path=str(path),
            profile_sha256=hashlib.sha256(text.encode()).hexdigest(),
            disclosed=(
                f"macOS baseline: {len(BASELINE)} rules, each with its reason (os_baseline.py)",
                f"{len(plan.runtime)} runtime grants and {len(plan.task)} task grants",
            ),
        )

    def launch(self, prepared: PreparedProfile, workload: WorkloadSpec) -> ContainedProcess:
        raise LaunchRefused(NOT_YET)

    def confirm(self, process: ContainedProcess) -> ContainmentReport:
        raise LaunchRefused(NOT_YET)

    def wait(self, process: ContainedProcess, deadline_s: float) -> int | None:
        raise LaunchRefused(NOT_YET)

    def stop(self, process: ContainedProcess) -> TeardownReport:
        raise LaunchRefused(NOT_YET)
