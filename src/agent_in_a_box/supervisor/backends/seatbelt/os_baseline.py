"""What a Python process and its shell children need from macOS itself.

The Seatbelt profile starts from (deny default). Before the workload can run
at all, its programs need a few things that have nothing to do with the
task. This module lists each such rule with the reason it is needed. It is
disclosed apart from the task grants and the runtime grants.

Every entry was confirmed on macOS 15 on Apple silicon (decisions/0014): the
native suite runs the workload's programs under the profile with one entry
removed at a time, and each entry here is either one whose removal broke
something, named in its reason, or one the programs read whose loss the
runner cannot show (noted in its reason). Entries the first draft guessed and
the runner showed unnecessary were removed (decisions/0008): the on-disk
system libraries, the dyld shared cache, ICU data, /dev/urandom, /tmp, and
the notification and logging services. Programs load system code from the
shared cache, which the kernel maps before the profile applies.

Nothing here grants access to user data: no path under /Users, no writable
location except the null device, and no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Filter = Literal["subpath", "literal", "global-name", "target", "sysctl-name",
                 "sysctl-name-prefix", "none"]


@dataclass(frozen=True)
class Entry:
    """One baseline rule: `(allow <operation> (<filter> "<value>" ...))`, and why."""

    operation: str
    filter: Filter
    value: str | tuple[str, ...]
    why: str

    @property
    def values(self) -> tuple[str, ...]:
        return (self.value,) if isinstance(self.value, str) else self.value


# Kernel parameters programs read when they start or describe the host.
# Process listings and other processes' arguments are deliberately absent.
SYSCTL_NAMES = (
    "kern.ostype", "kern.osrelease", "kern.version", "kern.hostname",  # uname(3)
    "kern.osproductversion", "kern.ngroups", "kern.bootargs", "kern.osvariant_status",
    "kern.secure_kernel", "security.mac.lockdown_mode_state", "machdep.cpu.brand_string",
)

BASELINE: tuple[Entry, ...] = (
    # Processes
    Entry("process-fork", "none", "",
          "The shell and Python start child processes; without this, bash fails with "
          "'fork: Operation not permitted'. Children inherit this profile."),
    Entry("signal", "target", "same-sandbox",
          "A process may signal processes under this same profile (a shell stopping its own "
          "background job), and nothing outside it."),
    Entry("sysctl-read", "sysctl-name", SYSCTL_NAMES,
          "Named kernel parameters that programs read at startup or to describe the host "
          "(uname, the OS version); without them os.uname() fails. No process listings."),
    Entry("sysctl-read", "sysctl-name-prefix", "hw.",
          "Hardware description: CPU count and features, page size, machine type. Python "
          "and OpenSSL read these to size thread pools and pick instructions."),

    # Starting programs
    Entry("file-read-data", "literal", "/",
          "The dynamic loader lists the root directory as every program starts; without this, "
          "every program aborts before main. It shows only the names of top-level directories."),

    # System data
    Entry("file-read*", "literal", "/private/etc/localtime",
          "The local time zone setting, read by Python and ls. The runner's zone is UTC, so "
          "losing it changes nothing there; elsewhere times would show in UTC."),
    Entry("file-read*", "subpath", "/private/var/db/timezone",
          "The time zone rules the local time zone setting points to."),
    Entry("file-read-metadata", "literal", "/etc",
          "/etc is a symbolic link to /private/etc; programs reach the time zone setting "
          "through it."),
    Entry("file-read-metadata", "literal", "/var",
          "/var is a symbolic link to /private/var; the time zone setting points through it "
          "to the rules."),
    Entry("file-read*", "subpath", "/usr/share/locale",
          "Character tables for LANG=C.UTF-8, which the workload's environment sets; without "
          "them programs fall back to ASCII."),
    Entry("file-read*", "literal", "/System/Library/CoreServices/SystemVersion.plist",
          "The macOS version, read by Python's platform module."),
    Entry("file-read*", "literal", "/private/etc/ssl/openssl.cnf",
          "The system TLS library's configuration; curl refuses to start without it."),
    Entry("file-read-metadata", "literal", "/private/var/select/sh",
          "/bin/sh reads this link to choose the shell it runs; without it, sh reports an "
          "error on every start."),

    # Devices
    Entry("file-read*", "literal", "/dev/null", "Commands read from the null device."),
    Entry("file-read-data", "literal", "/dev/fd",
          "Python lists its own open descriptors here before starting a process, to close the "
          "rest; without it, it closes every possible descriptor, 0.3 s per process on the "
          "runner. It lists only the calling process's descriptors."),
    Entry("file-write-data", "literal", "/dev/null",
          "Commands redirect output to the null device; without this, bash reports "
          "'/dev/null: Operation not permitted'."),

    # Services
    Entry("mach-lookup", "global-name", "com.apple.system.opendirectoryd.libinfo",
          "User and group lookups (getpwuid) are answered by the directory service over this "
          "Mach service; without it Python cannot name the current user."),
)
