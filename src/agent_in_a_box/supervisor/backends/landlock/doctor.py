"""Check that this host can run the Landlock backend, and say exactly why not if it cannot.

Every check must pass before native execution is enabled. A failed check
refuses the run; nothing falls back to running the workload unconfined.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from agent_in_a_box.contracts import DoctorCheck
from agent_in_a_box.supervisor.backends.landlock import seccomp, syscalls

MINIMUM_ABI = 2
# --disable-userns, which keeps the sandbox from creating user namespaces, arrived in 0.8.0.
MINIMUM_BUBBLEWRAP = (0, 8, 0)


def read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def linux() -> DoctorCheck:
    return DoctorCheck("Linux host", sys.platform == "linux", f"sys.platform is {sys.platform}")


def landlock_enabled() -> DoctorCheck:
    modules = read("/sys/kernel/security/lsm")
    if modules is None:
        return DoctorCheck("Landlock in the LSM list", syscalls.abi_version() > 0,
                           "/sys/kernel/security/lsm is unreadable; judged by the ABI check")
    enabled = "landlock" in modules.split(",")
    return DoctorCheck("Landlock in the LSM list", enabled, f"active modules: {modules}")


def landlock_abi() -> DoctorCheck:
    abi = syscalls.abi_version()
    detail = f"Landlock ABI {abi}; at least {MINIMUM_ABI} is required"
    if abi >= MINIMUM_ABI and abi < 3:
        detail += ("; Landlock itself does not govern truncate before ABI 3, so truncate is "
                   "refused by read-only mounts outside write grants")
    return DoctorCheck("Landlock ABI", abi >= MINIMUM_ABI, detail)


def bubblewrap_version(text: str) -> tuple[int, ...] | None:
    """The version in `bwrap --version` output ("bubblewrap 0.9.0"), or None."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in match.groups()) if match else None


def bubblewrap() -> DoctorCheck:
    path = shutil.which("bwrap")
    if path is None:
        return DoctorCheck("bubblewrap", False, "bwrap is not installed")
    version = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    found = bubblewrap_version(version.stdout)
    detail = f"{path}: {version.stdout.strip()}"
    if version.returncode != 0 or found is None:
        return DoctorCheck("bubblewrap", False, f"{detail}; its version could not be read")
    if found < MINIMUM_BUBBLEWRAP:
        minimum = ".".join(str(part) for part in MINIMUM_BUBBLEWRAP)
        return DoctorCheck("bubblewrap", False,
                           f"{detail}; at least {minimum} is required for --disable-userns, "
                           "which keeps the sandbox from creating user namespaces")
    return DoctorCheck("bubblewrap", True, detail)


def userns_restriction() -> str:
    """The host setting most likely to block unprivileged user namespaces, if any."""
    if read("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") == "1":
        return "AppArmor restricts them (kernel.apparmor_restrict_unprivileged_userns=1)"
    if read("/proc/sys/kernel/unprivileged_userns_clone") == "0":
        return "they are disabled (kernel.unprivileged_userns_clone=0)"
    if read("/proc/sys/user/max_user_namespaces") == "0":
        return "they are disabled (user.max_user_namespaces=0)"
    return "the host refused to create them"


def namespaces() -> DoctorCheck:
    """Actually create the namespaces the sandbox uses; a sysctl alone can mislead.

    The trial also disables user namespaces inside, as the profile does, and
    bubblewrap itself checks that this worked before it runs the command.
    """
    path = shutil.which("bwrap")
    name = "unprivileged user, PID, and network namespaces"
    if path is None:
        return DoctorCheck(name, False, "cannot test without bwrap")
    trial = subprocess.run(
        [path, "--unshare-user", "--unshare-pid", "--unshare-net", "--disable-userns",
         "--as-pid-1", "--ro-bind", "/", "/", "--", "true"],
        capture_output=True, text=True, timeout=30)
    if trial.returncode == 0:
        return DoctorCheck(name, True, "bwrap created all three, with user namespaces disabled "
                                       "inside")
    reason = trial.stderr.strip().splitlines()[-1] if trial.stderr.strip() else "no message"
    return DoctorCheck(name, False, f"{userns_restriction()}: bwrap said {reason!r}")


def seccomp_filter() -> DoctorCheck:
    machine = seccomp.supported_machine()
    status = read("/proc/self/status") or ""
    supported = "Seccomp:" in status
    kernel = "present" if supported else "absent"
    detail = f"architecture {machine or 'unsupported'}; kernel seccomp {kernel}"
    return DoctorCheck("seccomp socket filter", machine is not None and supported, detail)


def checks() -> tuple[DoctorCheck, ...]:
    if sys.platform != "linux":
        return (linux(),)
    return (linux(), landlock_enabled(), landlock_abi(), bubblewrap(), namespaces(),
            seccomp_filter())
