"""The launcher: confine itself, check the confinement, then become the workload.

bubblewrap has already given this process its own namespaces, built its
filesystem view, and loaded the seccomp filter. This program runs first
inside, before any workload code:

  1. read the profile's Landlock rules (passed on a file descriptor)
  2. restrict itself with them; from here on it, and every process it
     starts, is confined, and nothing can undo that
  3. run the self-probes: each must fail in exactly the expected way
  4. start the loopback relay to the proxy
  5. report to the supervisor, then replace itself with the workload,
     which waits until the supervisor admits it

If any step fails, it reports the failure and exits; the workload never runs.

    python -m agent_in_a_box.supervisor.backends.landlock.launcher \
        --profile-fd N --report-fd M -- <workload command>
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import socket
import sys

from agent_in_a_box.supervisor.backends.landlock import relay, syscalls

OUTCOMES = {
    errno.EACCES: "denied", errno.EPERM: "denied", errno.EROFS: "denied",
    errno.ENOENT: "absent", errno.ENETUNREACH: "unreachable", errno.EHOSTUNREACH: "unreachable",
    errno.EAFNOSUPPORT: "refused",
}


def apply_landlock(rules: list[dict]) -> dict:
    """Restrict this process to the profile's rules. Returns what was applied."""
    abi = syscalls.abi_version()
    if abi < 1:
        raise OSError("Landlock is not available in this kernel")
    governed = syscalls.known_rights(abi)
    ruleset = syscalls.create_ruleset(governed)
    applied, skipped = [], []
    for rule in rules:
        path = rule["path"]
        if not os.path.exists(path):
            skipped.append({"path": path, "reason": "not in the sandbox's view"})
            continue
        if os.path.isdir(path):
            wanted = set(rule["if_directory"])
        else:
            wanted = set(rule["if_file"]) & syscalls.FILE_RIGHTS
        rights = wanted & governed
        if not rights:
            skipped.append({"path": path, "reason": "no rights Landlock governs at this ABI"})
            continue
        syscalls.allow_beneath(ruleset, path, rights)
        applied.append({"path": path, "rights": sorted(rights)})
    syscalls.restrict_self(ruleset)
    every_right = set(syscalls.RIGHTS)
    return {"abi": abi, "ungoverned": sorted(every_right - governed),
            "applied": applied, "skipped": skipped}


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
        else:
            return f"unknown probe {operation!r}"
    except OSError as error:
        return OUTCOMES.get(error.errno, f"error: {error.strerror}")
    return "allowed"


def start_relay(proxy: dict) -> None:
    """Listen on the proxy port on loopback, in a child process that forwards to the socket."""
    listener = socket.create_server(("127.0.0.1", proxy["port"]))
    if os.fork() == 0:
        relay.serve_inside(listener, proxy["socket"])
        os._exit(0)
    listener.close()


def confine(profile: dict) -> dict:
    report: dict = {"ok": False}
    try:
        report["landlock"] = apply_landlock(profile["landlock"])
        report["probes"] = []
        for probe in profile["probes"]:
            observed = attempt(probe)
            report["probes"].append({"name": probe["name"], "expected": probe["expect"],
                                     "observed": observed, "passed": observed == probe["expect"]})
        start_relay(profile["proxy"])
        report["ok"] = all(probe["passed"] for probe in report["probes"])
    except Exception as error:  # any failure refuses the run
        report["error"] = f"{type(error).__name__}: {error}"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Confine, check, then run the workload")
    parser.add_argument("--profile-fd", type=int, required=True)
    parser.add_argument("--report-fd", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    with os.fdopen(args.profile_fd) as source:
        profile = json.load(source)
    report = confine(profile)
    with os.fdopen(args.report_fd, "w") as sink:
        json.dump(report, sink)
    if not report["ok"] or not command:
        return 3
    # The workload starts with stdin, stdout, and stderr only: nothing else is inherited.
    os.closerange(3, os.sysconf("SC_OPEN_MAX"))
    os.execv(command[0], command)


if __name__ == "__main__":
    sys.exit(main())
