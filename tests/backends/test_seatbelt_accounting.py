"""Seatbelt teardown's process accounting, with the kernel's answers simulated.

The rule under test (accounting.py, decisions/0014): a process belongs to a run
only if its profile allows the run's marker and refuses the run's control
name. The native suite checks the same rule against the real kernel.
"""

from __future__ import annotations

import signal

import pytest

from agent_in_a_box.supervisor.backends.seatbelt import accounting, sandbox

MARKER = accounting.Marker.for_run("run-1.ab")

# What each simulated process's profile allows: (marker, control).
PROFILES = {
    10: (True, True),     # unconfined
    11: (False, False),   # another deny-default sandbox
    12: (True, True),     # an allow-default sandbox
    20: (True, False),    # this run
    21: (True, False),    # this run, detached
    30: (None, None),     # exited: the kernel cannot answer
}


@pytest.fixture
def kernel(monkeypatch):
    alive = dict(PROFILES)
    sent: list[tuple[int, int]] = []

    def allows(pid, operation, kind, argument):
        assert (operation, kind) == ("mach-lookup", sandbox.FILTER_GLOBAL_NAME)
        answer = alive.get(pid, (None, None))
        return answer[0] if argument == MARKER.marker else answer[1]

    def kill(pid, number):
        sent.append((pid, number))
        if number == signal.SIGKILL:
            alive.pop(pid, None)

    monkeypatch.setattr(sandbox, "allows", allows)
    monkeypatch.setattr(accounting, "all_processes", lambda: sorted(alive))
    monkeypatch.setattr(accounting.os, "kill", kill)
    monkeypatch.setattr(accounting.time, "sleep", lambda _: None)
    return alive, sent


def test_marker_and_control_are_run_specific_names():
    assert MARKER.marker != MARKER.control
    assert MARKER.marker.endswith("run-1.ab") and MARKER.control.endswith("run-1.ab")


def test_only_the_runs_signature_is_a_member(kernel):
    assert accounting.members(MARKER) == [20, 21]


def test_members_are_frozen_before_they_are_killed(kernel):
    _, sent = kernel
    assert accounting.kill_all(MARKER) == [20, 21]
    stops = [pid for pid, number in sent if number == signal.SIGSTOP]
    kills = [pid for pid, number in sent if number == signal.SIGKILL]
    assert sorted(stops) == [20, 21] and kills == [20, 21]
    assert sent.index((21, signal.SIGSTOP)) < sent.index((20, signal.SIGKILL))
    assert accounting.survivors(MARKER) == []


def test_unrelated_processes_are_never_signalled(kernel):
    _, sent = kernel
    accounting.kill_all(MARKER)
    assert {pid for pid, _ in sent} == {20, 21}


def test_a_reused_pid_is_resumed_not_killed(kernel, monkeypatch):
    alive, sent = kernel
    real_kill = accounting.os.kill

    def kill(pid, number):
        real_kill(pid, number)
        if (pid, number) == (21, signal.SIGSTOP):
            alive[21] = (True, True)  # 21 exited and an unrelated process took its PID

    monkeypatch.setattr(accounting.os, "kill", kill)
    assert accounting.kill_all(MARKER) == [20]
    assert (21, signal.SIGCONT) in sent and (21, signal.SIGKILL) not in sent


def test_a_member_started_during_teardown_is_found(kernel, monkeypatch):
    alive, _ = kernel
    rounds = []
    real_members = accounting.members

    def members(marker):
        found = real_members(marker)
        if not rounds:
            alive[22] = (True, False)  # a fork that raced the first listing
        rounds.append(found)
        return found

    monkeypatch.setattr(accounting, "members", members)
    assert accounting.kill_all(MARKER) == [20, 21, 22]
