"""The launcher: confine itself, check the confinement, then run the workload as init.

bubblewrap has already given this process its own namespaces, built its
filesystem view, loaded the seccomp filter, and made it PID 1 of the new PID
namespace. This program runs first inside, before any workload code:

  1. read the profile's Landlock rules (passed on a file descriptor)
  2. restrict itself with them; from here on it, and every process it
     starts, is confined, and nothing can undo that
  3. run the self-probes (probes.py): each must fail in exactly the expected way
  4. start the loopback relay to the proxy
  5. report to the supervisor
  6. start the workload as a child, which waits until the supervisor admits
     it, and stay as the namespace's init: reap whatever exits, and end with
     the workload's status, which ends every process left in the namespace

If any step before 6 fails, it reports the failure and exits; the workload
never runs. The launcher stays as PID 1 instead of becoming the workload so
that no process in the sandbox is less confined than the workload is
(decisions/0014).

    python -m agent_in_a_box.supervisor.backends.landlock.launcher \\
        --profile-fd N --report-fd M -- <workload command>
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import sys

from agent_in_a_box.supervisor.backends.landlock import probes, relay, syscalls

FORWARDED_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


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


def start_relay(proxy: dict, report_fd: int) -> None:
    """Listen on the proxy port on loopback, in a child process that forwards to the socket.

    The child keeps the listener and nothing else of the supervisor's: it closes
    its copy of the report pipe, so only this process writes the report.
    """
    listener = socket.create_server(("127.0.0.1", proxy["port"]))
    if os.fork() == 0:
        os.close(report_fd)
        relay.serve_inside(listener, proxy["socket"])
        os._exit(0)
    listener.close()


def confine(profile: dict, report_fd: int) -> dict:
    report: dict = {"ok": False}
    try:
        report["landlock"] = apply_landlock(profile["landlock"])
        report["probes"] = probes.run(profile["probes"])
        start_relay(profile["proxy"], report_fd)
        report["ok"] = all(probe["passed"] for probe in report["probes"])
    except Exception as error:  # any failure refuses the run
        report["error"] = f"{type(error).__name__}: {error}"
    return report


def start_workload(command: list[str]) -> int:
    """Start the workload as a child with stdin, stdout, and stderr only."""
    child = os.fork()
    if child == 0:
        os.closerange(3, os.sysconf("SC_OPEN_MAX"))
        os.execv(command[0], command)
    return child


def serve_as_init(workload: int) -> int:
    """Reap every process that exits until the workload does; return its exit status.

    PID 1 receives a signal from outside its namespace only if it handles it.
    The supervisor stops a sandbox with SIGKILL, which needs no handler; the
    handler is for an operator ending one by hand with SIGTERM or SIGINT, which
    is passed on to the workload. When this process exits, the kernel ends
    everything left in the namespace.
    """
    def forward(number: int, _frame: object) -> None:
        with contextlib.suppress(ProcessLookupError):  # the workload may be gone already
            os.kill(workload, number)

    for number in FORWARDED_SIGNALS:
        signal.signal(number, forward)
    while True:
        pid, status = os.wait()
        if pid == workload:
            code = os.waitstatus_to_exitcode(status)
            return code if code >= 0 else 128 - code  # ended by signal N: 128 + N, as shells say


def main() -> int:
    parser = argparse.ArgumentParser(description="Confine, check, then run the workload")
    parser.add_argument("--profile-fd", type=int, required=True)
    parser.add_argument("--report-fd", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    with os.fdopen(args.profile_fd) as source:
        profile = json.load(source)
    report = confine(profile, args.report_fd)
    with os.fdopen(args.report_fd, "w") as sink:
        json.dump(report, sink)
    if not report["ok"] or not command:
        return 3
    return serve_as_init(start_workload(command))


if __name__ == "__main__":
    sys.exit(main())
