"""Put the kernel's own denial messages in a native test's failure output.

Native suites run on CI runners nobody can log in to, so a failure has to
explain itself. On macOS, Seatbelt reports each refused operation to the
unified log ("Sandbox: bash(123) deny(1) file-read-data /path"); a failing
native test's report gets a "Seatbelt denials" section with the denials
logged while it ran (tests/conftest.py). Landlock logs nothing an
unprivileged process can read.
"""

from __future__ import annotations

import shutil
import subprocess
import time

LIMIT = 80


def seatbelt_denials(since: float, pid: int | None = None, limit: int | None = LIMIT) -> list[str]:
    """Sandbox denials logged since `since` (a time.time() value), most recent last.

    With `pid`, only that process's denials. At most `limit` lines, the newest.
    """
    if shutil.which("log") is None:
        return ["(the log command is not available)"]
    start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since - 1))
    predicate = 'sender == "Sandbox"'
    if pid is not None:
        predicate += f' AND eventMessage CONTAINS "({pid}) deny"'
    shown = subprocess.run(["log", "show", "--start", start, "--style", "compact",
                            "--predicate", predicate],
                           capture_output=True, text=True, timeout=120)
    lines = [line for line in shown.stdout.splitlines() if " deny" in line]
    return lines[-limit:] if limit else lines


def kernel_denials(backend: str, since: float) -> str:
    if backend == "seatbelt":
        lines = seatbelt_denials(since)
        heading = f"Seatbelt denials logged during this test ({len(lines)}, newest last):"
        return "\n".join([heading, *lines]) if lines else "No Seatbelt denials were logged."
    if backend == "landlock":
        return "Landlock does not log denials where an unprivileged process can read them."
    return ""


def explain(record) -> str:
    """Why a run did not complete: the refusal, failed containment probes, agent stderr."""
    from agent_in_a_box.contracts import plain

    lines = [f"status {record.status}: {record.refusal}"]
    for event in record.events:
        payload = plain(event.payload)
        if event.kind == "containment":
            lines += [f"  probe failed: {probe['name']}: expected {probe['expected']}, "
                      f"observed {probe['observed']}"
                      for probe in payload.get("probes", []) if not probe.get("passed")]
        if event.kind == "agent.stderr":
            lines.append("  agent stderr: " + payload.get("text", "")[-1500:])
    return "\n".join(lines)
