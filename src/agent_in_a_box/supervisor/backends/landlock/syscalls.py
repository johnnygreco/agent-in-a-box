"""The Landlock system calls, called directly through ctypes.

Landlock is the Linux security module that lets an unprivileged process
restrict its own file access, and its children's, for the rest of their
lives. Three calls do it:

  landlock_create_ruleset   say which access rights the ruleset governs
  landlock_add_rule         allow some of those rights beneath one path
  landlock_restrict_self    apply the ruleset to this process, irreversibly

Any governed right not allowed by a rule is denied. Rights the running
kernel does not know (its ABI is too old) are not governed at all, so the
caller must account for them some other way (decisions/0010).
"""

from __future__ import annotations

import ctypes
import os
import struct

# Syscall numbers are the same on every architecture for these new calls.
SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

# Filesystem access rights, with the ABI version that introduced each one.
RIGHTS: dict[str, tuple[int, int]] = {
    "execute": (1 << 0, 1),
    "write_file": (1 << 1, 1),
    "read_file": (1 << 2, 1),
    "read_dir": (1 << 3, 1),
    "remove_dir": (1 << 4, 1),
    "remove_file": (1 << 5, 1),
    "make_char": (1 << 6, 1),
    "make_dir": (1 << 7, 1),
    "make_reg": (1 << 8, 1),
    "make_sock": (1 << 9, 1),
    "make_fifo": (1 << 10, 1),
    "make_block": (1 << 11, 1),
    "make_sym": (1 << 12, 1),
    "refer": (1 << 13, 2),
    "truncate": (1 << 14, 3),
    "ioctl_dev": (1 << 15, 5),
}
# Rights that make sense on a file rather than a directory.
FILE_RIGHTS = {"execute", "write_file", "read_file", "truncate", "ioctl_dev"}

_libc = ctypes.CDLL(None, use_errno=True)


def _check(result: int) -> int:
    if result < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return result


def abi_version() -> int:
    """The Landlock ABI the running kernel offers, or 0 if Landlock is unavailable."""
    result = _libc.syscall(ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET), ctypes.c_void_p(None),
                           ctypes.c_size_t(0), ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION))
    return max(result, 0)


def known_rights(abi: int) -> set[str]:
    """The filesystem rights a kernel with this ABI can govern."""
    return {name for name, (_, since) in RIGHTS.items() if since <= abi}


def mask(names: set[str]) -> int:
    value = 0
    for name in names:
        value |= RIGHTS[name][0]
    return value


def create_ruleset(governed: set[str]) -> int:
    """A new ruleset that governs `governed` rights. Returns its file descriptor."""
    attribute = struct.pack("<Q", mask(governed))  # handled_access_fs only
    return _check(_libc.syscall(ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET),
                                ctypes.c_char_p(attribute), ctypes.c_size_t(len(attribute)),
                                ctypes.c_uint32(0)))


def allow_beneath(ruleset: int, path: str, rights: set[str]) -> None:
    """Allow `rights` on `path` and everything beneath it."""
    path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        rule = struct.pack("<Qi", mask(rights), path_fd)  # packed path_beneath_attr
        _check(_libc.syscall(ctypes.c_long(SYS_LANDLOCK_ADD_RULE), ctypes.c_int(ruleset),
                             ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH), ctypes.c_char_p(rule),
                             ctypes.c_uint32(0)))
    finally:
        os.close(path_fd)


def restrict_self(ruleset: int) -> None:
    """Apply the ruleset to this process and every process it starts. Irreversible."""
    _check(_libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
    _check(_libc.syscall(ctypes.c_long(SYS_LANDLOCK_RESTRICT_SELF), ctypes.c_int(ruleset),
                         ctypes.c_uint32(0)))
    os.close(ruleset)
