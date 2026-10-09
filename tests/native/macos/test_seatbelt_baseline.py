"""The macOS baseline, confirmed one entry at a time on a real Mac (decisions/0008, 0014).

For every baseline entry this test renders the run's profile without that
entry, runs a program under it, and checks the evidence the entry's reason
names: either a visible failure (an error message, an abort), or, where the
loss is invisible on the runner, the kernel's own denial of the path the
program tried to read. The same program under the full profile must not
fail that way. An entry with no evidence here fails the test, so the
baseline cannot grow by guesswork.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import pytest

from agent_in_a_box.contracts import Access, Extent, GrantPlan, PathGrant
from agent_in_a_box.supervisor import grants, runs
from agent_in_a_box.supervisor.backends.seatbelt import os_baseline, profile
from tests.native.diagnostics import seatbelt_denials
from tests.native.required import native_runtime_or_skip

pytestmark = [pytest.mark.native,
              pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only checks")]

PY = sys.executable
TIME_ZONE = [PY, "-c", "import time; print(time.strftime('%Z'))"]
CONFINE = ("import os, sys\n"
           "from agent_in_a_box.supervisor.backends.seatbelt import sandbox\n"
           "sandbox.apply(os.environ.pop('AIB_PROFILE'))\n"
           "os.execv(sys.argv[1], sys.argv[1:])\n")


@dataclass(frozen=True)
class Visible:
    """Without the entry, the program's output or exit shows this."""
    argv: list[str]
    shows: str  # text in stdout or stderr, or "abort" for SIGABRT


@dataclass(frozen=True)
class Logged:
    """Without the entry, the kernel logs a denial naming this path."""
    argv: list[str]
    path: str


EVIDENCE = {
    "process-fork": Visible(["/bin/bash", "-c", "/bin/echo a; /bin/echo b"],
                            "fork: Operation not permitted"),
    "signal same-sandbox": Visible(["/bin/bash", "-c", "sleep 5 & kill $!; wait $!"],
                                   "kill: ("),
    "sysctl-read kern.ostype": Visible([PY, "-c", "import os; os.uname()"], "PermissionError"),
    "sysctl-read hw.": Visible([PY, "-c", "import os; os.uname()"], "PermissionError"),
    "file-read-data /": Visible(["/bin/echo", "x"], "abort"),
    "file-read* /private/etc/localtime": Logged(TIME_ZONE, "/private/etc/localtime"),
    "file-read* /private/var/db/timezone": Logged(TIME_ZONE, "/private/var/db/timezone"),
    "file-read-metadata /etc": Logged(TIME_ZONE, "/etc"),
    "file-read-metadata /var": Logged(TIME_ZONE, "/var"),
    "file-read* /usr/share/locale": Logged(["/bin/ls"], "/usr/share/locale"),
    "file-read* /System/Library/CoreServices/SystemVersion.plist": Visible(
        [PY, "-c", "import platform; print('version=' + platform.mac_ver()[0])"], "version=\n"),
    "file-read* /private/etc/ssl/openssl.cnf": Visible(
        ["/usr/bin/curl", "-sS", "--max-time", "2", "http://127.0.0.1:9/"],
        "configuration file"),
    "file-read-metadata /private/var/select/sh": Visible(["/bin/sh", "-c", "true"],
                                                         "Error opening /private/var/select/sh"),
    "file-read* /dev/null": Visible(["/bin/cat", "/dev/null"], "Operation not permitted"),
    "file-write-data /dev/null": Visible(["/bin/bash", "-c", "echo x > /dev/null"],
                                         "/dev/null: Operation not permitted"),
    "file-read-data /dev/fd": Logged(
        [PY, "-c", "import subprocess; subprocess.run(['/bin/ls'], capture_output=True)"],
        "/dev/fd"),
    "mach-lookup com.apple.system.opendirectoryd.libinfo": Visible(
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


def naming(path, since):
    """(time, line) for each denial since `since` that names `path` or a path below it.

    Not filtered by process: the denial may come from a child the program
    forked, as Python's subprocess does before it runs a program.
    """
    found = []
    for line in seatbelt_denials(since, limit=None):
        if line.rstrip().endswith(f" {path}") or f" {path}/" in line:
            stamp = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f").timestamp()
            found.append((stamp, line))
    return found


def denied_after(path, since, after):
    """Wait for the log to show a denial of `path` after time `after`."""
    deadline = time.monotonic() + 20  # the unified log can lag the kernel
    while True:
        found = naming(path, since)
        if any(stamp >= after for stamp, _ in found) or time.monotonic() > deadline:
            return found
        time.sleep(1)


def test_every_entry_has_evidence():
    assert sorted(key(entry) for entry in os_baseline.BASELINE) == sorted(EVIDENCE)


@pytest.mark.parametrize("entry", os_baseline.BASELINE, ids=key)
def test_entry_is_needed(setting, entry):
    run, plan, env = setting
    evidence = EVIDENCE[key(entry)]
    since = time.time()
    full = confined(plan, env, run.workspace, evidence.argv)
    between = time.time()
    without = confined(plan, env, run.workspace, evidence.argv, without=entry)
    report = (f"full profile: exit {full.returncode}, {full.stdout[-300:]!r} {full.stderr[-300:]!r}"
              f"\nwithout the entry: exit {without.returncode}, {without.stdout[-300:]!r} "
              f"{without.stderr[-300:]!r}")
    if isinstance(evidence, Visible):
        assert not shows(full, evidence.shows), report
        assert shows(without, evidence.shows), report
    else:
        found = denied_after(evidence.path, since, between)
        lines = "\n".join(line for _, line in found)
        assert any(stamp >= between for stamp, _ in found), (
            f"{report}\nno denial of {evidence.path} was logged without the entry")
        assert not any(stamp < between for stamp, _ in found), (
            f"{report}\nthe full profile was refused it too:\n{lines}")
