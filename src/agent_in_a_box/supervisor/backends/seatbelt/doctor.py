"""Check that this Mac can run the Seatbelt backend, and say exactly why not if it cannot.

Every check must pass before native execution is enabled. A failed check
refuses the run; nothing falls back to running the workload unconfined.
The decisive check is a trial: a child process confines itself with the
baseline profile, the supervisor confirms from outside that the kernel
sees it confined and finds it by its marker, and the child then runs the
shell and a command that the profile must refuse.
"""

from __future__ import annotations

import os
import platform
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_in_a_box.contracts import DoctorCheck
from agent_in_a_box.supervisor.backends.seatbelt import accounting, sandbox
from agent_in_a_box.supervisor.backends.seatbelt.profile import baseline_lines, marker_lines

# The macOS releases on which the native suite has passed (decisions/0015). Others run
# if the trial passes, and the doctor says they are outside the validated matrix.
VALIDATED_RELEASES = ("15",)
TRIAL_TIMEOUT_S = 30.0

TRIAL = """
import os, sys
from agent_in_a_box.supervisor.backends.seatbelt import sandbox
sandbox.apply(os.environ["TRIAL_PROFILE"])
print("confined", flush=True)
sys.stdin.readline()
os.execv("/bin/sh", ["/bin/sh", "-c", "/bin/cat /dev/null && /bin/cat " + sys.argv[1]])
"""


def macos() -> DoctorCheck:
    return DoctorCheck("macOS host", sys.platform == "darwin", f"sys.platform is {sys.platform}")


def architecture() -> DoctorCheck:
    machine = platform.machine()
    validated = machine == "arm64"
    return DoctorCheck("architecture", True,
                       f"{machine} is in the validated matrix" if validated else
                       f"{machine} is outside the validated matrix (decisions/0015); "
                       "the trial below decides")


def release() -> DoctorCheck:
    version = platform.mac_ver()[0] or "unknown"
    build = subprocess.run(["/usr/bin/sw_vers", "-buildVersion"], capture_output=True,
                           text=True).stdout.strip()
    validated = version.split(".")[0] in VALIDATED_RELEASES
    detail = f"macOS {version} ({build})"
    detail += (" is in the validated matrix" if validated else
               " is outside the validated matrix (decisions/0015); the trial below decides")
    return DoctorCheck("macOS release", True, detail)


def library() -> DoctorCheck:
    try:
        lib = sandbox.library()
        found = all(hasattr(lib, name) for name in ("sandbox_init", "sandbox_check"))
    except OSError as error:
        return DoctorCheck("sandbox library", False, f"libSystem could not be loaded: {error}")
    return DoctorCheck("sandbox library", found, "sandbox_init and sandbox_check in libSystem"
                       if found else "sandbox_init or sandbox_check is missing")


def trial_profile(marker: accounting.Marker) -> str:
    executables = ("/bin/sh", "/bin/bash", "/bin/cat")
    rules = [f'(allow process-exec (literal "{path}"))' for path in executables]
    return "\n".join(["(version 1)", "(deny default)", *baseline_lines(), *rules,
                      *marker_lines(marker.marker)]) + "\n"


def trial() -> list[DoctorCheck]:
    """Confine a child with the baseline, check it from outside, then let it run."""
    marker = accounting.Marker.for_run(f"doctor-{secrets.token_hex(6)}")
    with tempfile.NamedTemporaryFile("w", delete=False) as secret:
        secret.write("not for the sandbox")
    target = os.path.realpath(secret.name)
    env = {**os.environ, "LANG": "C.UTF-8", "TRIAL_PROFILE": trial_profile(marker)}
    child = subprocess.Popen([sys.executable, "-c", TRIAL, target], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    assert child.stdin is not None and child.stdout is not None
    try:
        confined = child.stdout.readline().strip() == "confined"
        seen = confined and sandbox.is_sandboxed(child.pid)
        found = confined and accounting.carries(child.pid, marker)
        if confined:
            child.stdin.write("go\n")
            child.stdin.flush()
        _, stderr = child.communicate(timeout=TRIAL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        return [DoctorCheck("Seatbelt trial", False, "the trial did not finish in time")]
    finally:
        Path(target).unlink(missing_ok=True)
    refused = confined and child.returncode == 1 and "Operation not permitted" in stderr
    return [
        DoctorCheck("Seatbelt applies a profile", confined,
                    "a child confined itself with the baseline profile" if confined
                    else f"the child could not confine itself: {stderr.strip()[-300:]}"),
        DoctorCheck("the kernel reports the confinement", seen and found,
                    "sandbox_check sees the child confined and finds it by its marker"
                    if seen and found else "sandbox_check did not confirm the child"),
        DoctorCheck("the baseline runs the shell and refuses the rest", refused,
                    "sh and cat ran; reading a file outside the profile was refused" if refused
                    else f"exit {child.returncode}: {stderr.strip()[-300:]}"),
    ]


def process_listing() -> DoctorCheck:
    found = Path("/bin/ps").exists()
    return DoctorCheck("process listing", found, "/bin/ps lists processes for teardown"
                       if found else "/bin/ps is missing; teardown could not find processes")


def checks() -> tuple[DoctorCheck, ...]:
    found = [macos()]
    if not found[0].ok:
        return tuple(found)
    found += [architecture(), release(), library(), process_listing()]
    if all(check.ok for check in found):
        found += trial()
    return tuple(found)
