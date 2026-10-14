"""The self-probes: operations the confinement must stop, tried from inside.

The launcher runs these after restricting itself and before it reports. Each
probe names an operation, a target, and the one outcome the profile predicts;
anything else, success included, fails the probe and refuses the run. The
outcomes are the kernel's answers, named:

  denied       EACCES, EPERM, EROFS: a mount or a Landlock rule stopped it
  absent       ENOENT: the path is not in the sandbox's view at all
  unreachable  no route: the network namespace has nowhere to send it
  refused      EAFNOSUPPORT from the seccomp filter, or ENOSPC when the
               sandbox will not create another user namespace
"""

from __future__ import annotations

import errno
import os
import socket

OUTCOMES = {
    errno.EACCES: "denied", errno.EPERM: "denied", errno.EROFS: "denied",
    errno.ENOENT: "absent", errno.ENETUNREACH: "unreachable", errno.EHOSTUNREACH: "unreachable",
    errno.EAFNOSUPPORT: "refused", errno.ENOSPC: "refused",
}


def unshare_user_namespace() -> None:
    """Try to create a user namespace, in a child so this process stays as it is."""
    child = os.fork()
    if child == 0:
        try:
            os.unshare(os.CLONE_NEWUSER)
        except OSError as error:
            os._exit(error.errno)
        os._exit(0)
    _, status = os.waitpid(child, 0)
    code = os.waitstatus_to_exitcode(status)
    if code != 0:
        raise OSError(code, os.strerror(code))


def attempt(probe: dict) -> str:
    """Try one operation the confinement must stop; return what happened."""
    operation = probe["op"]
    target = probe["target"]
    try:
        if operation == "listdir":
            os.listdir(target)
        elif operation == "create":
            with open(target, "x"):
                pass
        elif operation == "stat":
            os.stat(target)
        elif operation == "connect":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect((target, 9))
        elif operation == "socket":
            socket.socket(int(target), socket.SOCK_RAW).close()
        elif operation == "unshare":
            unshare_user_namespace()
        else:
            return f"unknown probe {operation!r}"
    except OSError as error:
        return OUTCOMES.get(error.errno, f"error: {error.strerror}")
    return "allowed"


def run(probes: list[dict]) -> list[dict]:
    """Every probe's expected and observed outcome, and whether they agree."""
    results = []
    for probe in probes:
        observed = attempt(probe)
        results.append({"name": probe["name"], "expected": probe["expect"],
                        "observed": observed, "passed": observed == probe["expect"]})
    return results
