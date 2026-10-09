"""Start and stop the per-run proxy: a separate, supervisor-managed process."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_in_a_box.contracts import RunSpec
from agent_in_a_box.network.proxy import Route
from agent_in_a_box.policy.compiler import CompiledPolicy

READY_TIMEOUT_S = 20.0


class DataPlaneError(RuntimeError):
    pass


@dataclass
class ProxyHandle:
    port: int
    process: subprocess.Popen[str]
    decisions_path: Path


def _await_ready(process: subprocess.Popen[str], what: str) -> int:
    """Read the child's `READY <port>` line; refuse if it never comes."""
    assert process.stdout is not None
    line = process.stdout.readline().strip()
    if not line.startswith("READY "):
        process.kill()
        raise DataPlaneError(f"{what} did not start: {line!r}")
    return int(line.split()[1])


def start_proxy(run: RunSpec, compiled: CompiledPolicy, routes: dict[str, Route],
                evaluator: str) -> ProxyHandle:
    private = Path(run.private)
    bundle = compiled.bundle
    (private / "policy.cedar").write_text(bundle.policy_text)
    (private / "sandbox.cedarschema").write_text(bundle.schema_text)
    decisions = private / "proxy-decisions.jsonl"
    decisions.touch()
    config = {
        "run_id": run.run_id, "policy_name": bundle.name, "evaluator": evaluator,
        "policy_path": str(private / "policy.cedar"), "policy_sha256": bundle.policy_hash,
        "schema_path": str(private / "sandbox.cedarschema"), "schema_sha256": bundle.schema_hash,
        "eligible": [{"endpoint": e.endpoint, "policy_ids": list(e.policy_ids)}
                     for e in compiled.proxy.eligible],
        "routes": [{"endpoint": r.endpoint, "host": r.host, "port": r.port}
                   for r in routes.values()],
        "decisions_path": str(decisions),
        "confdir": str(private / "mitmproxy"),
    }
    (private / "proxy.json").write_text(json.dumps(config, indent=2))
    with open(private / "proxy-stderr.txt", "w") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "agent_in_a_box.network.proxy_server", "--config",
             str(private / "proxy.json")],
            stdout=subprocess.PIPE, stderr=stderr, text=True,
        )
    return ProxyHandle(_await_ready(process, "proxy"), process, decisions)


def stop(process: subprocess.Popen[str], timeout_s: float = 5.0) -> int | None:
    process.terminate()
    try:
        return process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()
