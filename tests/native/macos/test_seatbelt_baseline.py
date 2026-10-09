"""The macOS baseline, confirmed one entry at a time on a real Mac (decisions/0008, 0014).

For every baseline entry this test renders the run's profile without that
entry, runs a program under it, and checks the failure the entry's reason
names: an error message or an abort. The same program under the full
profile must not fail that way. Where the loss is invisible in a program's
normal output on the runner (its time zone is UTC, so a failed time zone
lookup falls back to the same answer), the program reads the file the
reason names directly. An entry with no evidence here fails the test, so
the baseline cannot grow by guesswork.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

import pytest

from agent_in_a_box.contracts import Access, Extent, GrantPlan, PathGrant
from agent_in_a_box.supervisor import grants, runs
from agent_in_a_box.supervisor.backends.seatbelt import os_baseline, profile
from tests.native.required import native_runtime_or_skip

pytestmark = [pytest.mark.native,
              pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only checks")]

PY = sys.executable
LOCAL_TIME_ZONE = [PY, "-c", "print(len(open('/etc/localtime', 'rb').read()))"]
CONFINE = ("import os, sys\n"
           "from agent_in_a_box.supervisor.backends.seatbelt import sandbox\n"
           "sandbox.apply(os.environ.pop('AIB_PROFILE'))\n"
           "os.execv(sys.argv[1], sys.argv[1:])\n")


@dataclass(frozen=True)
class Evidence:
    """Without the entry, `argv`'s output or exit shows `shows` ("abort" for SIGABRT)."""
    argv: list[str]
    shows: str


EVIDENCE = {
    "process-fork": Evidence(["/bin/bash", "-c", "/bin/echo a; /bin/echo b"],
                             "fork: Operation not permitted"),
    "signal same-sandbox": Evidence(["/bin/bash", "-c", "sleep 5 & kill $!; wait $!"], "kill: ("),
    "sysctl-read kern.ostype": Evidence([PY, "-c", "import os; os.uname()"], "PermissionError"),
    "sysctl-read hw.": Evidence([PY, "-c", "import os; os.uname()"], "PermissionError"),
    "file-read-data /": Evidence(["/bin/echo", "x"], "abort"),
    "file-read* /private/etc/localtime": Evidence(LOCAL_TIME_ZONE, "PermissionError"),
    "file-read* /private/var/db/timezone": Evidence(LOCAL_TIME_ZONE, "PermissionError"),
    "file-read-metadata /etc": Evidence(LOCAL_TIME_ZONE, "PermissionError"),
    "file-read-metadata /var": Evidence(LOCAL_TIME_ZONE, "PermissionError"),
    "file-read* /usr/share/locale": Evidence(
        [PY, "-c", "import locale; print(locale.setlocale(locale.LC_CTYPE, ''))"],
        "unsupported locale setting"),
    "file-read* /System/Library/CoreServices/SystemVersion.plist": Evidence(
        [PY, "-c", "import platform; print('version=' + platform.mac_ver()[0])"], "version=\n"),
    "file-read* /private/etc/ssl/openssl.cnf": Evidence(
        ["/usr/bin/curl", "-sS", "--max-time", "2", "http://127.0.0.1:9/"],
        "configuration file"),
    "file-read-metadata /private/var/select/sh": Evidence(["/bin/sh", "-c", "true"],
                                                          "Error opening /private/var/select/sh"),
    "file-read* /dev/null": Evidence(["/bin/cat", "/dev/null"], "Operation not permitted"),
    "file-write-data /dev/null": Evidence(["/bin/bash", "-c", "echo x > /dev/null"],
                                          "/dev/null: Operation not permitted"),
    "file-read-data /dev/fd": Evidence([PY, "-c", "import os; print(os.listdir('/dev/fd'))"],
                                       "PermissionError"),
    "mach-lookup com.apple.system.opendirectoryd.libinfo": Evidence(
        [PY, "-c", "import getpass; getpass.getuser()"], "KeyError"),
}


def key(entry: os_baseline.Entry) -> str:
    return f"{entry.operation} {entry.values[0]}".strip()


@pytest.fixture(scope="module")
def setting(tmp_path_factory):
    native_runtime_or_skip("seatbelt", tmp_path_factory.mktemp("doctor") / "runs")
    run = runs.create_run(tmp_path_factory.mktemp("baseline") / "runs")
    workspace = os.path.realpath(run.workspace)
    task = (PathGrant(workspace, Access.READ, Extent.SUBTREE, "policy", ("t",), "/workspace"),)
    plan = GrantPlan(task, grants.runtime_grants(run), grants.protected_paths(run), 9, "test")
    return run, plan, dict(runs.workload(run, "baseline", 9).env)


def confined(plan, env, cwd, argv, without=None):
    """Run `argv` under the profile, less one entry."""
    kept = tuple(entry for entry in os_baseline.BASELINE if entry is not without)
    original = profile.BASELINE
    profile.BASELINE = kept
    try:
        text = profile.render(plan, "org.agent-in-a-box.run.baseline-test", cwd)
    finally:
        profile.BASELINE = original
    return subprocess.run([PY, "-c", CONFINE, *argv], env={**env, "AIB_PROFILE": text}, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


def shows(result, text):
    if text == "abort":
        return result.returncode == -6
    return text in result.stdout + result.stderr


def test_every_entry_has_evidence():
    assert sorted(key(entry) for entry in os_baseline.BASELINE) == sorted(EVIDENCE)


@pytest.mark.parametrize("entry", os_baseline.BASELINE, ids=key)
def test_entry_is_needed(setting, entry):
    run, plan, env = setting
    evidence = EVIDENCE[key(entry)]
    full = confined(plan, env, run.workspace, evidence.argv)
    without = confined(plan, env, run.workspace, evidence.argv, without=entry)
    report = (f"full profile: exit {full.returncode}, {full.stdout[-300:]!r} {full.stderr[-300:]!r}"
              f"\nwithout the entry: exit {without.returncode}, {without.stdout[-300:]!r} "
              f"{without.stderr[-300:]!r}")
    assert not shows(full, evidence.shows), report
    assert shows(without, evidence.shows), report
