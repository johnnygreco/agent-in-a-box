"""The agent's tools: real file, search, shell, and HTTP operations.

They run inside the workload process, in the run's workspace. They check no
permissions themselves: the installed kernel profile bounds file and network
access, and the proxy decides each HTTP request. A failed or refused
operation comes back as an Observation the agent can react to.
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_in_a_box.contracts import Observation

MAX_OUTPUT = 8192


def _bounded(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n[output truncated]"


def _os_error(tool: str, exc: OSError, path: str) -> Observation:
    return Observation(tool, False, f"{type(exc).__name__}: {exc.strerror}",
                       {"path": path, "errno": exc.errno})


def read_file(args: Mapping[str, Any]) -> Observation:
    path = str(args["path"])
    try:
        text = Path(path).read_text(errors="replace")
    except OSError as exc:
        return _os_error("read_file", exc, path)
    return Observation("read_file", True, _bounded(text), {"path": path, "bytes": len(text)})


def write_file(args: Mapping[str, Any]) -> Observation:
    path = str(args["path"])
    content = str(args["content"])
    try:
        Path(path).write_text(content)
    except OSError as exc:
        return _os_error("write_file", exc, path)
    return Observation("write_file", True, f"wrote {len(content)} bytes to {path}",
                       {"path": path, "bytes": len(content)})


def search(args: Mapping[str, Any]) -> Observation:
    """Lines containing `pattern` in files under `path` (plain substring match)."""
    pattern = str(args["pattern"])
    root = str(args.get("path", "."))
    matches: list[str] = []
    unreadable: list[str] = []

    def note_unreadable(error: OSError) -> None:
        unreadable.append(str(error.filename))

    for directory, _, files in os.walk(root, onerror=note_unreadable):
        for name in sorted(files):
            file = os.path.join(directory, name)
            try:
                with open(file, errors="replace") as f:
                    matches += [f"{file}:{n}: {line.rstrip()}" for n, line in enumerate(f, 1)
                                if pattern in line]
            except OSError:
                unreadable.append(file)
    return Observation("search", True, _bounded("\n".join(matches)),
                       {"matches": len(matches), "unreadable": unreadable[:50]})


def bash(args: Mapping[str, Any]) -> Observation:
    """Run a real shell command. Children inherit whatever restrictions apply."""
    command = str(args["command"])
    timeout = float(args.get("timeout", 30))
    try:
        proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return Observation("bash", False, _bounded(str(output)), {"timed_out": True})
    return Observation("bash", proc.returncode == 0, _bounded(proc.stdout + proc.stderr),
                       {"exit_status": proc.returncode, "timed_out": False})


def http(args: Mapping[str, Any]) -> Observation:
    """An HTTP request through the configured proxy (HTTP_PROXY in the environment)."""
    method = str(args["method"])
    url = str(args["url"])
    body = args.get("body")
    request = urllib.request.Request(url, data=str(body).encode() if body is not None else None,
                                     method=method)
    detail: dict[str, Any] = {"method": method, "url": url, "status": None, "refused_by": None}
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            detail["status"] = response.status
            text = response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        detail.update(status=exc.code, refused_by=exc.headers.get("X-Agent-In-A-Box-Refused"))
        text = exc.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        detail["error"] = str(getattr(exc, "reason", exc))
        return Observation("http", False, f"request failed: {detail['error']}", detail)
    return Observation("http", 200 <= detail["status"] < 300, _bounded(text), detail)


TOOLS: dict[str, Callable[[Mapping[str, Any]], Observation]] = {
    "read_file": read_file,
    "write_file": write_file,
    "search": search,
    "bash": bash,
    "http": http,
}
