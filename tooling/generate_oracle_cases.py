#!/usr/bin/env python3
"""Generate the Cedar authorization oracle cases from the official Cedar CLI.

    python3 tooling/generate_oracle_cases.py

For every shipped policy variant and a fixed list of requests, ask the
official `cedar` CLI (cedar-policy-cli, installed by tooling/bootstrap.py
--with-cli) for its decision, determining policies, and evaluation errors,
and write them to tests/oracle/cedar_cli_cases.json. Our evaluators are then
tested against that file (tests/oracle/test_cedar_cli_oracle.py).

This script is the oracle's only author. It uses the standard library and
the CLI, and it never imports the agent_in_a_box package, so no expected
outcome is produced by the implementation under test (PLAN.md, invariant 6).
It describes each request in Cedar's own terms, independently of the
runtime's request construction. Rerun it only when the policies, the
requests, or the pinned CLI change, and review the diff like code.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "policies" / "sandbox.cedarschema"
VARIANTS = ROOT / "policies" / "variants"
OUTPUT = ROOT / "tests" / "oracle" / "cedar_cli_cases.json"
INSTALLED = ROOT / ".toolchain" / "installed.json"

# A policy that passes validation but can fail at evaluation time (integer
# overflow). Cedar skips an erroring policy when it decides; our runtime
# denies whenever any policy reports an error.
OVERFLOW = (
    '\n@id("overflow")\n'
    'permit (principal, action == Sandbox::Action::"HttpRequest", resource)\n'
    "when { resource.port * 9223372036854775807 > 0 };\n"
)

HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "HEAD")
HTTP_PATHS = ("/reference", "/reference/", "/missing")
CONNECT_ENDPOINTS = (("reference.fixture", 80), ("reference.fixture", 8080),
                     ("collector.example", 80))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned_cli() -> tuple[Path, str]:
    """The installed CLI, after checking it is the binary bootstrap recorded."""
    installed = json.loads(INSTALLED.read_text())
    entry = installed["binaries"].get("cedar_cli")
    if entry is None:
        sys.exit("the cedar CLI is not installed; run: python3 tooling/bootstrap.py --with-cli")
    cli = Path(entry["path"])
    if sha256(cli.read_bytes()) != entry["sha256"]:
        sys.exit(f"{cli} changed since bootstrap; refusing to use it")
    return cli, entry["sha256"]


def entities(host: str, port: int) -> list[dict]:
    """The process, its user and group, and the endpoint, in Cedar's entity JSON."""
    endpoint_id = f"{host}:{port}"
    return [
        {"uid": {"type": "Sandbox::Process", "id": "current"},
         "attrs": {"user": {"__entity": {"type": "Sandbox::User", "id": "sandbox"}},
                   "group": {"__entity": {"type": "Sandbox::Group", "id": "sandbox"}}},
         "parents": []},
        {"uid": {"type": "Sandbox::User", "id": "sandbox"}, "attrs": {}, "parents": []},
        {"uid": {"type": "Sandbox::Group", "id": "sandbox"}, "attrs": {}, "parents": []},
        {"uid": {"type": "Sandbox::NetworkEndpoint", "id": endpoint_id},
         "attrs": {"host": host, "port": port, "host_port": endpoint_id},
         "parents": []},
    ]


def request(action: str, host: str, port: int, context: dict) -> dict:
    return {
        "principal": {"type": "Sandbox::Process", "id": "current"},
        "action": {"type": "Sandbox::Action", "id": action},
        "resource": {"type": "Sandbox::NetworkEndpoint", "id": f"{host}:{port}"},
        "context": context,
        "entities": entities(host, port),
    }


def requests() -> list[dict]:
    found = []
    for method in HTTP_METHODS:
        for path in HTTP_PATHS:
            context = {"method": method, "path": path}
            found.append(request("HttpRequest", "reference.fixture", 80, context))
    for host, port in CONNECT_ENDPOINTS:
        found.append(request("NetworkConnect", host, port, {}))
    return found


def entity_text(entity: dict) -> str:
    return f'{entity["type"]}::{json.dumps(entity["id"])}'


def ask_cli(cli: Path, policy_text: str, asked: dict) -> dict:
    """The CLI's decision, determining policies, and erroring policies for one request."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        (folder / "policies.cedar").write_text(policy_text)
        (folder / "entities.json").write_text(json.dumps(asked["entities"]))
        (folder / "context.json").write_text(json.dumps(asked["context"]))
        completed = subprocess.run(
            [str(cli), "authorize", "-v",
             "--policies", str(folder / "policies.cedar"),
             "--schema", str(SCHEMA), "--schema-format", "cedar",
             "--entities", str(folder / "entities.json"),
             "--context", str(folder / "context.json"),
             "--principal", entity_text(asked["principal"]),
             "--action", entity_text(asked["action"]),
             "--resource", entity_text(asked["resource"])],
            capture_output=True, text=True, timeout=60,
        )
    lines = completed.stdout.splitlines()
    if "ALLOW" in lines:
        decision = "allow"
    elif "DENY" in lines:
        decision = "deny"
    else:
        sys.exit(f"unexpected CLI output:\n{completed.stdout}\n{completed.stderr}")
    errors = re.findall(r"^error while evaluating policy `([^`]+)`", completed.stdout, re.M)
    _, _, listed = completed.stdout.partition("due to the following policies:")
    return {"decision": decision, "determining": sorted(listed.split()),
            "error_policy_ids": sorted(errors)}


def one_case_per_line(document: dict) -> str:
    """JSON with one case per line, so a regenerated file diffs case by case."""
    header = {key: value for key, value in document.items() if key != "cases"}
    lines = ["{"]
    for key, value in header.items():
        lines.append(f" {json.dumps(key)}: {json.dumps(value)},")
    lines.append(' "cases": [')
    rows = [f"  {json.dumps(case, sort_keys=True)}" for case in document["cases"]]
    lines.append(",\n".join(rows))
    lines.append(" ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    cli, cli_sha256 = pinned_cli()
    version = subprocess.run([str(cli), "--version"], capture_output=True, text=True,
                             check=True).stdout.strip()
    policy_sets = [(path.stem, path.read_text()) for path in sorted(VARIANTS.glob("P*.cedar"))]
    p0_text = (VARIANTS / "P0.cedar").read_text()
    policy_sets.append(("P0+overflow", p0_text + OVERFLOW))

    cases = []
    for name, policy_text in policy_sets:
        for asked in requests():
            cases.append({
                "policy_set": name,
                "policy_sha256": sha256(policy_text.encode()),
                "request": asked,
                "cli": ask_cli(cli, policy_text, asked),
            })
    document = {
        "generated_by": "tooling/generate_oracle_cases.py",
        "oracle": version,
        "oracle_sha256": cli_sha256,
        "schema_sha256": sha256(SCHEMA.read_bytes()),
        "overflow_policy": OVERFLOW,
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(one_case_per_line(document))
    print(f"wrote {len(cases)} cases from {version} to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
