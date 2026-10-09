"""Put the kernel's own denial messages in a native test's failure output.

Native suites run on CI runners nobody can log in to, so a failure has to
explain itself. On macOS, Seatbelt reports each refused operation to the
unified log ("Sandbox: bash(123) deny(1) file-read-data /path"); a failing
test appends the denials logged while it ran. Landlock logs nothing an
unprivileged process can read, so on Linux the failure says that instead.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import time

LIMIT = 80


def seatbelt_denials(since: float) -> list[str]:
    """Sandbox denials logged since `since` (a time.time() value), most recent last."""
    if shutil.which("log") is None:
        return ["(the log command is not available)"]
    start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since - 1))
    shown = subprocess.run(["log", "show", "--start", start, "--style", "compact",
                            "--predicate", 'sender == "Sandbox"'],
                           capture_output=True, text=True, timeout=120)
    return [line for line in shown.stdout.splitlines() if " deny" in line][-LIMIT:]


def kernel_denials(backend: str, since: float) -> str:
    if backend == "seatbelt":
        lines = seatbelt_denials(since)
        heading = f"Seatbelt denials logged during this test ({len(lines)}, newest last):"
        return "\n".join([heading, *lines]) if lines else "No Seatbelt denials were logged."
    if backend == "landlock":
        return "Landlock does not log denials where an unprivileged process can read them."
    return ""


@contextlib.contextmanager
def denials_on_failure(backend: str):
    """Re-raise an assertion failure with the kernel's denials appended."""
    since = time.time()
    try:
        yield
    except AssertionError as failure:
        raise AssertionError(f"{failure}\n\n{kernel_denials(backend, since)}") from failure


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
