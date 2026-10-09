"""What a Python process and its shell children need from macOS itself.

The Seatbelt profile starts from (deny default). Before the workload can run
at all, the process needs a few things that have nothing to do with the
task: the dynamic loader and system libraries, a little system data, the
null device, and the directory service that answers user lookups. This
module lists each such rule with the reason it is needed. It is disclosed
apart from the task grants and the runtime grants.

The list is deliberately small, and it is unconfirmed: nothing here has
run on a Mac yet. Milestone 1 runs it; any entry that turns out to be
missing is added with the failure that showed it was needed, and any entry
that turns out to be unnecessary is removed (decisions/0008).

Nothing here grants access to user data: no path under /Users, no
writable location except the null device, and no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Filter = Literal["subpath", "literal", "global-name", "target", "none"]


@dataclass(frozen=True)
class Entry:
    """One baseline rule: `(allow <operation> (<filter> "<value>"))`, and why."""

    operation: str
    filter: Filter
    value: str
    why: str


BASELINE: tuple[Entry, ...] = (
    # Processes
    Entry("process-fork", "none", "",
          "The shell and Python start child processes. Children inherit this profile."),
    Entry("signal", "target", "same-sandbox",
          "A process may signal processes in its own tree (a shell stopping a timed-out "
          "child), and nothing outside it."),
    Entry("sysctl-read", "none", "",
          "libc and Python read kernel parameters at startup (page size, CPU count, OS "
          "version). Read-only; no user data. To narrow to named parameters in Milestone 1."),

    # Loading code
    Entry("file-read*", "subpath", "/usr/lib",
          "The dynamic loader (/usr/lib/dyld) and the few system libraries that are "
          "files on disk rather than in the shared cache."),
    Entry("file-read*", "subpath", "/System/Library",
          "System frameworks and their resources, and the dyld shared cache on "
          "releases that keep it here."),
    Entry("file-read*", "subpath", "/System/Volumes/Preboot/Cryptexes/OS",
          "The dyld shared cache on releases that ship it in the OS cryptex."),

    # System data
    Entry("file-read*", "subpath", "/usr/share/zoneinfo",
          "Time zone rules, for converting timestamps to local time."),
    Entry("file-read*", "literal", "/private/etc/localtime",
          "The local time zone setting. It is a symbolic link; its target is below."),
    Entry("file-read*", "subpath", "/private/var/db/timezone",
          "Where the local time zone link points."),
    Entry("file-read*", "subpath", "/usr/share/icu",
          "Unicode and locale data that system string handling loads."),

    # Devices
    Entry("file-read*", "literal", "/dev/null", "Commands redirect output to the null device."),
    Entry("file-write*", "literal", "/dev/null", "Commands redirect output to the null device."),
    Entry("file-read*", "literal", "/dev/urandom",
          "Random bytes, for programs that read the device rather than call getentropy."),

    # Finding paths
    Entry("file-read-metadata", "literal", "/",
          "Every absolute path is looked up starting at the root directory."),
    Entry("file-read-metadata", "literal", "/etc",
          "/etc is a symbolic link to /private/etc; following it needs its metadata."),
    Entry("file-read-metadata", "literal", "/var",
          "/var is a symbolic link to /private/var; following it needs its metadata."),
    Entry("file-read-metadata", "literal", "/tmp",
          "/tmp is a symbolic link to /private/tmp; following it needs its metadata. "
          "Nothing below it is granted; the workload's TMPDIR is in the run directory."),

    # Services
    Entry("mach-lookup", "global-name", "com.apple.system.opendirectoryd.libinfo",
          "User and group lookups (getpwuid, getgrgid) are answered by the directory "
          "service over this Mach service; a shell looks up its own user at startup."),
)
