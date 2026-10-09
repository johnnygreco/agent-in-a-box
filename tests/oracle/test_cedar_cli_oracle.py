"""Our evaluators against the official Cedar CLI (decisions/0009).

Expected outcomes in cedar_cli_cases.json were produced by the official CLI,
an independent implementation, through tooling/generate_oracle_cases.py,
which never imports our package. This file only checks our evaluators against
them. If a policy variant changes, its cases are stale: regenerate the file
and review the diff before trusting the result.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agent_in_a_box.contracts import CedarRequest, EntityRef, PolicyBundle, plain, sha256_text
from agent_in_a_box.policy import requests, schema, toolchain
from agent_in_a_box.policy.bridge_evaluator import BridgeEvaluator
from agent_in_a_box.policy.evaluator import CedarpyEvaluator

pytestmark = pytest.mark.toolchain

ORACLE_FILE = Path(__file__).with_name("cedar_cli_cases.json")
ORACLE = json.loads(ORACLE_FILE.read_text())
GENERATOR = schema.REPO_ROOT / "tooling" / "generate_oracle_cases.py"
EVALUATORS = [CedarpyEvaluator(), BridgeEvaluator()]


def policy_text(policy_set: str) -> str:
    if policy_set == "P0+overflow":
        return schema.load_variant("P0").policy_text + ORACLE["overflow_policy"]
    return schema.load_variant(policy_set).policy_text


def cedar_request(case: dict) -> CedarRequest:
    asked = case["request"]
    return CedarRequest(
        principal=EntityRef(**asked["principal"]),
        action=EntityRef(**asked["action"]),
        resource=EntityRef(**asked["resource"]),
        context=asked["context"],
        entities=tuple(asked["entities"]),
        provenance={"*": "oracle case"},
    )


def case_id(case: dict) -> str:
    asked = case["request"]
    context = asked["context"]
    what = f"{context['method']}{context['path']}" if context else asked["resource"]["id"]
    return f"{case['policy_set']}-{asked['action']['id']}-{what}"


def test_oracle_is_the_pinned_cli_and_current_schema():
    assert ORACLE["oracle"] == f"cedar-policy-cli {toolchain.pinned('cedar_cli', 'version')}"
    assert ORACLE["schema_sha256"] == sha256_text(schema.schema_text())


def test_generator_never_imports_our_package():
    tree = ast.parse(GENERATOR.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("agent_in_a_box") for name in imported)


@pytest.mark.parametrize("case", ORACLE["cases"], ids=case_id)
def test_case_is_current(case):
    """A changed policy variant makes its cases stale until they are regenerated."""
    assert case["policy_sha256"] == sha256_text(policy_text(case["policy_set"]))


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=["cedarpy", "bridge"])
@pytest.mark.parametrize("case", ORACLE["cases"], ids=case_id)
def test_evaluator_agrees_with_the_cli(case, evaluator):
    bundle = PolicyBundle(case["policy_set"], schema.schema_text(),
                          policy_text(case["policy_set"]))
    record = evaluator.evaluate(bundle, cedar_request(case))
    expected = case["cli"]
    assert record.raw == expected["decision"]
    assert list(record.determining) == expected["determining"]
    assert sorted(error.policy_id for error in record.errors) == expected["error_policy_ids"]
    # The runtime allows only when Cedar allows and reports no evaluation error.
    enforced = expected["decision"] == "allow" and not expected["error_policy_ids"]
    assert record.decision == ("allowed" if enforced else "denied")


@pytest.mark.parametrize("case", ORACLE["cases"][:18], ids=case_id)
def test_runtime_builds_the_same_request_the_oracle_describes(case):
    """Our request construction agrees with the oracle's independent description."""
    asked = case["request"]
    host, port = asked["resource"]["id"].rsplit(":", 1)
    if asked["action"]["id"] == "HttpRequest":
        built = requests.http_request(host, int(port), asked["context"]["method"],
                                      asked["context"]["path"])
    else:
        built = requests.network_connect(host, int(port))
    assert built.principal.to_json() == asked["principal"]
    assert built.resource.to_json() == asked["resource"]
    assert dict(built.context) == asked["context"]
    def canonical(entities) -> list[str]:
        return sorted(json.dumps(entity, sort_keys=True) for entity in entities)

    assert canonical(plain(built.entities)) == canonical(asked["entities"])
