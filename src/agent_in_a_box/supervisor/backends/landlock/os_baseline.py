"""What a Python process and its shell children need from Linux itself.

Two layers, each listed with the reason for every entry:

  MOUNTS   what exists in the sandbox's filesystem view (bubblewrap). A path
           that is not mounted does not exist for the workload at all.
  RULES    what the workload may do with what exists (Landlock). A mounted
           path with no rule can be looked up but not read or written.

Nothing here grants access to user data or to the network. Confirmed on
the host recorded in STATUS.md, "Last native validation".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mount:
    """One bubblewrap mount. `kind` is a bwrap option; `path` is the same inside and out."""

    kind: str
    path: str
    why: str


@dataclass(frozen=True)
class Rule:
    """One Landlock rule: `rights` allowed on `path` and beneath it."""

    path: str
    rights: tuple[str, ...]
    why: str


READ = ("read_file", "read_dir")

MOUNTS: tuple[Mount, ...] = (
    Mount("--ro-bind-try", "/usr", "Programs and shared libraries live under /usr."),
    Mount("--ro-bind-try", "/bin", "On merged-/usr systems a link to /usr/bin; scripts name it."),
    Mount("--ro-bind-try", "/lib", "On merged-/usr systems a link to /usr/lib."),
    Mount("--ro-bind-try", "/lib64", "Holds the dynamic loader's path on x86-64."),
    Mount("--ro-bind-try", "/etc/ld.so.cache", "The dynamic loader's index of libraries."),
    Mount("--ro-bind-try", "/etc/passwd", "Looking up the current user's name and home."),
    Mount("--ro-bind-try", "/etc/group", "Looking up the current user's groups."),
    Mount("--ro-bind-try", "/etc/nsswitch.conf", "Tells libc where user lookups come from."),
    Mount("--ro-bind-try", "/etc/localtime", "The local time zone setting."),
    Mount("--proc", "/proc", "A /proc for the sandbox's own process namespace only."),
    Mount("--dev", "/dev", "A minimal /dev: null, zero, random, urandom, and a tty."),
    Mount("--tmpfs", "/tmp", "An empty, private /tmp. Not writable: no rule grants it."),
)

RULES: tuple[Rule, ...] = (
    Rule("/usr/lib", READ, "Shared libraries; /lib is a link to it on merged-/usr systems."),
    Rule("/usr/share/zoneinfo", READ, "Time zone rules, for local timestamps."),
    Rule("/etc/ld.so.cache", ("read_file",), "The dynamic loader's index of libraries."),
    Rule("/etc/passwd", ("read_file",), "Looking up the current user's name and home."),
    Rule("/etc/group", ("read_file",), "Looking up the current user's groups."),
    Rule("/etc/nsswitch.conf", ("read_file",), "Tells libc where user lookups come from."),
    Rule("/etc/localtime", ("read_file",), "The local time zone setting."),
    Rule("/dev/null", ("read_file", "write_file", "truncate"),
         "Commands redirect output to /dev/null; `>` opens it for truncation."),
    Rule("/dev/urandom", ("read_file",), "Random bytes for programs that read the device."),
    Rule("/lib64/ld-linux-x86-64.so.2", ("execute", "read_file"),
         "The x86-64 dynamic loader, which the kernel opens to start every program."),
    Rule("/lib/ld-linux-aarch64.so.1", ("execute", "read_file"),
         "The arm64 dynamic loader, which the kernel opens to start every program."),
)
