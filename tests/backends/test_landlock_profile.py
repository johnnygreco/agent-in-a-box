"""The Landlock backend's pure parts, tested on any platform.

The seccomp program is checked instruction by instruction against the rules
in seccomp.py's docstring; the renderer against PLAN.md's grant mapping and
ADR 0010; the doctor's refusals by removing each prerequisite in turn.
"""

from __future__ import annotations

import json
import struct

import pytest

from agent_in_a_box.contracts import Access, DoctorCheck, Extent, GrantPlan, PathGrant
from agent_in_a_box.supervisor.backends.landlock import doctor, profile, seccomp, syscalls


def grant(path, access, extent=Extent.SUBTREE, origin="policy"):
    return PathGrant(path, access, extent, origin, ("p",))


PLAN = GrantPlan(
    task=(grant("/r/ws/measurements.csv", Access.READ), grant("/r/ws/results", Access.WRITE)),
    runtime=(grant("/py/bin/python3", Access.EXECUTE, Extent.FILE, "runtime"),
             grant("/py", Access.READ, origin="runtime"),
             grant("/r/ws", Access.METADATA, Extent.FILE, "runtime"),
             grant("/r/home", Access.READ, origin="runtime"),
             grant("/r/home", Access.WRITE, origin="runtime")),
    protected=("/r/private",),
    proxy_port=4123,
    policy_hash="abc",
)


def decode(program: bytes) -> list[tuple[int, int, int, int]]:
    return [struct.unpack("<HBBI", program[i:i + 8]) for i in range(0, len(program), 8)]


def run_filter(machine: str, number: int, first_argument: int = 0, arch=None) -> int:
    """Interpret the program for one syscall, as the kernel would."""
    data = {seccomp.NR: number,
            seccomp.ARCH: arch if arch is not None else seccomp.ARCHITECTURES[machine].audit_arch,
            seccomp.FIRST_ARGUMENT: first_argument}
    instructions = decode(seccomp.compiled(machine))
    accumulator, position = 0, 0
    while True:
        code, jump_true, jump_false, k = instructions[position]
        if code == seccomp.LOAD_WORD:
            accumulator = data[k]
        elif code == seccomp.RETURN:
            return k
        elif code == seccomp.JUMP_EQUAL:
            position += jump_true if accumulator == k else jump_false
        elif code == seccomp.JUMP_AT_LEAST:
            position += jump_true if accumulator >= k else jump_false
        position += 1


@pytest.mark.parametrize("machine", sorted(seccomp.ARCHITECTURES))
def test_socket_families(machine):
    socket_number = seccomp.ARCHITECTURES[machine].socket
    for family in seccomp.ALLOWED_FAMILIES.values():
        assert run_filter(machine, socket_number, family) == seccomp.ALLOW
    for refused in (16, 17, 40, 41):  # netlink, packet, vsock, unknown
        assert run_filter(machine, socket_number, refused) == seccomp.ERRNO | seccomp.EAFNOSUPPORT


@pytest.mark.parametrize("machine", sorted(seccomp.ARCHITECTURES))
def test_other_syscalls(machine):
    assert run_filter(machine, seccomp.IO_URING_SETUP) == seccomp.ERRNO | seccomp.ENOSYS
    assert run_filter(machine, 0) == seccomp.ALLOW
    assert run_filter(machine, 0, arch=0x12345678) == seccomp.KILL_PROCESS


def test_x32_syscalls_are_refused():
    assert run_filter("x86_64", 0x40000000 | 41, 2) == seccomp.ERRNO | seccomp.ENOSYS


def test_rendered_profile_carries_the_exact_programs():
    rendered = json.loads(profile.render(PLAN))
    for machine, program in rendered["seccomp"]["programs"].items():
        assert bytes.fromhex(program) == seccomp.compiled(machine)


def test_mounts_follow_grant_intent():
    mounts = {entry["path"]: entry["kind"] for entry in profile.mounts(PLAN)}
    assert mounts["/r/ws"] == "--ro-bind-try"            # metadata: read-only view
    assert mounts["/r/ws/results"] == "--bind-try"        # write grant: writable
    assert mounts["/r/home"] == "--bind-try"              # read and write: writable
    assert "/r/ws/measurements.csv" not in mounts         # already read-only under /r/ws
    assert "/py/bin/python3" not in mounts                # already read-only under /py
    assert "/r/private" not in mounts                     # protected: not in the view
    order = [entry["path"] for entry in profile.mounts(PLAN)]
    assert order.index("/r/ws") < order.index("/r/ws/results")


def test_rights_keep_read_and_write_separate():
    rules = {rule["path"]: rule for rule in profile.landlock_rules(PLAN)}
    assert rules["/r/ws/results"]["if_directory"] == list(profile.WRITE_RIGHTS_ON_DIRECTORY)
    assert "read_file" not in rules["/r/ws/results"]["if_directory"]
    assert rules["/r/ws/measurements.csv"]["if_file"] == ["read_file"]
    assert rules["/py/bin/python3"]["if_file"] == ["execute", "read_file"]
    assert rules["/r/ws"]["if_file"] == [] and rules["/r/ws"]["if_directory"] == []


def test_protected_paths_become_absence_probes():
    probes = json.loads(profile.render(PLAN))["probes"]
    assert {"op": "stat", "target": "/r/private", "expect": "absent"}.items() <= next(
        probe for probe in probes if probe["op"] == "stat").items()


@pytest.mark.parametrize("bad", ["relative", "/a/../b", "/a\nb", "//a"])
def test_unsafe_paths_are_refused(bad):
    with pytest.raises(ValueError):
        profile.render(GrantPlan((grant(bad, Access.READ),), (), (), 1, "h"))


def test_execute_must_name_a_file():
    with pytest.raises(ValueError):
        profile.render(GrantPlan((), (grant("/usr/bin", Access.EXECUTE),), (), 1, "h"))


def test_known_rights_follow_the_abi():
    assert "refer" not in syscalls.known_rights(1)
    assert "refer" in syscalls.known_rights(2) and "truncate" not in syscalls.known_rights(2)
    assert "truncate" in syscalls.known_rights(3) and "ioctl_dev" in syscalls.known_rights(5)


def test_doctor_names_a_missing_bubblewrap(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor.bubblewrap() == DoctorCheck("bubblewrap", False, "bwrap is not installed")
    assert not doctor.namespaces().ok


def test_doctor_refuses_an_old_abi(monkeypatch):
    monkeypatch.setattr(doctor.syscalls, "abi_version", lambda: 1)
    check = doctor.landlock_abi()
    assert not check.ok and "at least 2" in check.detail


def test_doctor_names_the_apparmor_restriction(monkeypatch):
    values = {"/proc/sys/kernel/apparmor_restrict_unprivileged_userns": "1"}
    monkeypatch.setattr(doctor, "read", values.get)
    assert "kernel.apparmor_restrict_unprivileged_userns=1" in doctor.userns_restriction()
