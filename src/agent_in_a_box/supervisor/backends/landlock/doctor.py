"""Check that this host can run the Landlock backend, and say exactly why not if it cannot.

Every check must pass before native execution is enabled. A failed check
refuses the run; nothing falls back to running the workload unconfined.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from agent_in_a_box.contracts import DoctorCheck
from agent_in_a_box.supervisor.backends.landlock import seccomp, syscalls

MINIMUM_ABI = 2


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


def bubblewrap() -> DoctorCheck:
    path = shutil.which("bwrap")
    if path is None:
        return DoctorCheck("bubblewrap", False, "bwrap is not installed")
    version = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    return DoctorCheck("bubblewrap", version.returncode == 0, f"{path}: {version.stdout.strip()}")


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
    """Actually create the namespaces the sandbox uses; a sysctl alone can mislead."""
    path = shutil.which("bwrap")
    name = "unprivileged user, PID, and network namespaces"
    if path is None:
        return DoctorCheck(name, False, "cannot test without bwrap")
    trial = subprocess.run(
        [path, "--unshare-user", "--unshare-pid", "--unshare-net", "--ro-bind", "/", "/",
         "--", "true"], capture_output=True, text=True, timeout=30)
    if trial.returncode == 0:
        return DoctorCheck(name, True, "bwrap created all three")
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
