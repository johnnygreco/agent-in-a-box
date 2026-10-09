"""The official `cedar` CLI as an independent decision oracle (tests only).

It parses the policy text itself (no code under test touches its input) and,
like our adapters, names each policy by its @id annotation in `-v` output.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from agent_in_a_box.contracts import CedarRequest, PolicyBundle, plain


def cli_decide(cli: Path, bundle: PolicyBundle, request: CedarRequest) -> tuple[str, list[str]]:
    """Return ("allow" | "deny" | "error", determining @ids) from `cedar authorize -v`."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "p.cedar").write_text(bundle.policy_text)
        (d / "s.cedarschema").write_text(bundle.schema_text)
        (d / "e.json").write_text(json.dumps(plain(request.entities)))
        (d / "c.json").write_text(json.dumps(plain(request.context)))
        proc = subprocess.run(
            [str(cli), "authorize", "-v", "--policies", str(d / "p.cedar"),
             "--schema", str(d / "s.cedarschema"), "--schema-format", "cedar",
             "--entities", str(d / "e.json"), "--context", str(d / "c.json"),
             "-l", str(request.principal), "-a", str(request.action),
             "-r", str(request.resource)],
            capture_output=True, text=True, timeout=30,
        )
    lines = proc.stdout.split()
    decision = "allow" if "ALLOW" in lines else "deny" if "DENY" in lines else "error"
    _, _, listed = proc.stdout.partition("following policies:")
    return decision, sorted(listed.split())
