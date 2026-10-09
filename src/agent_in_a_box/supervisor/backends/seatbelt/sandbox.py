"""The narrow shim to macOS's sandbox library (PLAN.md, Backend module boundary).

Two calls, both in libsystem_sandbox, which every macOS process already has
loaded through libSystem. No compiled helper is involved (decisions/0014).

  apply(profile)   sandbox_init: confine this process with an SBPL profile.
                   Irreversible, and inherited by every process it starts.
  allows(pid, ...) sandbox_check: ask the kernel whether a process's profile
                   allows an operation, without performing it. The supervisor
                   uses it to confirm the workload's confinement from outside
                   and to find every process that carries a run's profile.

Both are declared in <sandbox.h>; Apple marks sandbox_init deprecated but
still ships and uses it. The doctor checks both work before any run.
"""

from __future__ import annotations

import ctypes
import os

# <sandbox.h>: the filter that names what `sandbox_check`'s extra argument is.
FILTER_NONE = 0
FILTER_PATH = 1
FILTER_GLOBAL_NAME = 2

_library: ctypes.CDLL | None = None


def library() -> ctypes.CDLL:
    """libSystem, which re-exports the sandbox calls. Loaded on first use."""
    global _library
    if _library is None:
        _library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        _library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64,
                                          ctypes.POINTER(ctypes.c_char_p)]
        _library.sandbox_init.restype = ctypes.c_int
        _library.sandbox_free_error.argtypes = [ctypes.c_char_p]
        _library.sandbox_free_error.restype = None
        # sandbox_check is variadic: three fixed arguments, then the filter's
        # argument. Declaring only the fixed three makes ctypes pass the fourth
        # the way Apple silicon passes variadic arguments.
        _library.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        _library.sandbox_check.restype = ctypes.c_int
    return _library


class SandboxError(RuntimeError):
    """The kernel refused the profile or the question."""


def apply(profile: str) -> None:
    """Confine the calling process with `profile` (SBPL text). Raises if refused."""
    lib = library()
    error = ctypes.c_char_p()
    if lib.sandbox_init(profile.encode(), 0, ctypes.byref(error)) != 0:
        message = error.value.decode(errors="replace") if error.value else "no message"
        if error.value:
            lib.sandbox_free_error(error)
        raise SandboxError(f"the kernel refused the profile: {message}")


def _no_report() -> int:
    """The flag that keeps a question from being logged as a violation."""
    return ctypes.c_int.in_dll(library(), "SANDBOX_CHECK_NO_REPORT").value


def is_sandboxed(pid: int) -> bool:
    """Whether the process runs under any Seatbelt profile."""
    ctypes.set_errno(0)
    answer = library().sandbox_check(pid, None, FILTER_NONE)
    if answer < 0:
        reason = os.strerror(ctypes.get_errno())
        raise SandboxError(f"sandbox_check failed for process {pid}: {reason}")
    return answer == 1


def allows(pid: int, operation: str, kind: int, argument: str) -> bool | None:
    """Whether process `pid`'s profile allows `operation` on `argument`.

    None when the kernel cannot answer, for example because the process has
    exited. An unconfined process is allowed everything.
    """
    ctypes.set_errno(0)
    answer = library().sandbox_check(pid, operation.encode(), kind | _no_report(),
                                     ctypes.c_char_p(argument.encode()))
    if answer < 0:
        return None
    return answer == 0
