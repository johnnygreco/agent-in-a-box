"""The launcher: confine itself, check the confinement, then become the workload.

The supervisor starts this program as an ordinary process, with the run's
profile on one file descriptor and a pipe for the report on another. It
runs before any workload code:

  1. read the profile (SBPL text) and its self-probes
  2. confine itself with sandbox_init; from here on it, and every process
     it starts, is confined, and nothing can undo that
  3. run the self-probes: each must fail in exactly the expected way
  4. report to the supervisor, then replace itself with the workload,
     which waits until the supervisor admits it

If any step fails, it reports the failure and exits; the workload never runs.

    python -m agent_in_a_box.supervisor.backends.seatbelt.launcher \
        --profile-fd N --report-fd M -- <workload command>
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import socket
import sys

from agent_in_a_box.supervisor.backends.seatbelt import sandbox

# Seatbelt refuses with EPERM. The other outcomes mean something else stopped
# the operation, so a probe that expects "denied" fails on them.
OUTCOMES = {
    errno.EPERM: "denied", errno.EACCES: "permission bits", errno.ENOENT: "absent",
    errno.ECONNREFUSED: "nothing listening", errno.ENETUNREACH: "unreachable",
    errno.EHOSTUNREACH: "unreachable", errno.ETIMEDOUT: "timed out",
}


def attempt(probe: dict) -> str:
    """Try one operation the profile must stop; return what happened."""
    operation, target = probe["op"], probe["target"]
    try:
        if operation == "listdir":
            os.listdir(target)
        elif operation == "create":
            with open(target, "x"):
                pass
        elif operation == "stat":
            os.stat(target)
        elif operation == "tcp":
            host, port = target.rsplit(":", 1)
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect((host.strip("[]"), int(port)))
        elif operation == "udp":
            host, port = target.rsplit(":", 1)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
                datagram.sendto(b"probe", (host, int(port)))
        elif operation == "unix":
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(target)
        elif operation == "socket":
            family, kind, protocol = (int(part) for part in target.split(","))
            socket.socket(family, kind, protocol).close()
        else:
            return f"unknown probe {operation!r}"
    except OSError as error:
        return OUTCOMES.get(error.errno, f"error: {error.strerror}")
    return "allowed"


def confine(launch: dict) -> dict:
    report: dict = {"ok": False}
    try:
        text = launch["profile"]
        report["profile_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        sandbox.apply(text)
        report["probes"] = []
        for probe in launch["probes"]:
            observed = attempt(probe)
            report["probes"].append({"name": probe["name"], "expected": probe["expect"],
                                     "observed": observed, "passed": observed == probe["expect"]})
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
        launch = json.load(source)
    report = confine(launch)
    with os.fdopen(args.report_fd, "w") as sink:
        json.dump(report, sink)
    if not report["ok"] or not command:
        return 3
    # The workload starts with stdin, stdout, and stderr only: nothing else is inherited.
    os.closerange(3, os.sysconf("SC_OPEN_MAX"))
    os.execv(command[0], command)


if __name__ == "__main__":
    sys.exit(main())
