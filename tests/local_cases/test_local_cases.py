"""Extra contract cases kept only in a local, git-ignored working folder.

If `inspiration/cases/` exists in this checkout, each case file there is run
against our implementation; otherwise this module is skipped. The public
oracle cases are in tests/oracle/ (decisions/0009). A failing local case is
reviewed by hand; its expectation is never regenerated from our code.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from agent_in_a_box.contracts import plain
from agent_in_a_box.policy import requests, schema
from agent_in_a_box.policy.bridge_evaluator import BridgeEvaluator
from agent_in_a_box.policy.compiler import PolicyRejected, compile_policy
from agent_in_a_box.policy.evaluator import CedarpyEvaluator

CASE_DIR = schema.REPO_ROOT / "inspiration" / "cases"
CASES = []
for case_file in sorted(CASE_DIR.glob("*.json")) if CASE_DIR.is_dir() else []:
    CASES += json.loads(case_file.read_text())["cases"]
if not CASES:
    pytest.skip("no local working cases in this checkout", allow_module_level=True)

EVALUATOR = CedarpyEvaluator()


def of_kind(*kinds: str) -> list[dict]:
    return [case for case in CASES if case["kind"] in kinds]


def compiled(case: dict):
    bundle = schema.bundle_from_text(case["id"], case["ours"]["policy"])
    return compile_policy(bundle, EVALUATOR)


def request_for(case: dict):
    asked = case["ours"]["request"]
    if asked["action"] == "NetworkConnect":
        request = requests.network_connect(asked["host"], asked["port"])
    else:
        request = requests.http_request(asked["host"], asked["port"], asked["method"],
                                        asked["path"])
    if "user" not in asked:
        return request
    # A hypothetical identity: the runtime itself only builds the sandbox user and group.
    entities = []
    for entity in plain(request.entities):
        if entity["uid"]["type"] == schema.PROCESS:
            entity["attrs"] = {
                "user": {"__entity": {"type": schema.USER, "id": asked["user"]}},
                "group": {"__entity": {"type": schema.GROUP, "id": asked["group"]}},
            }
        if entity["uid"]["type"] == schema.USER:
            entity["uid"]["id"] = asked["user"]
        if entity["uid"]["type"] == schema.GROUP:
            entity["uid"]["id"] = asked["group"]
        entities.append(entity)
    return dataclasses.replace(request, entities=tuple(entities))


@pytest.mark.parametrize("case", of_kind("rejects"), ids=lambda case: case["id"])
def test_rejected_at_load(case):
    with pytest.raises(PolicyRejected):
        compiled(case)


@pytest.mark.parametrize("case", of_kind("grants", "routes"), ids=lambda case: case["id"])
def test_derived_configuration(case):
    result = compiled(case)
    expect = case["ours"]["expect"]
    if "grants" in expect:
        assert [[grant.logical, grant.access.value] for grant in result.grants] == expect["grants"]
    if "routes" in expect:
        assert [eligible.endpoint for eligible in result.proxy.eligible] == expect["routes"]


@pytest.mark.toolchain
@pytest.mark.parametrize("evaluator", [EVALUATOR, BridgeEvaluator()], ids=["cedarpy", "bridge"])
@pytest.mark.parametrize("case", of_kind("decision"), ids=lambda case: case["id"])
def test_decisions(case, evaluator):
    expect = case["ours"]["expect"]
    record = evaluator.evaluate(compiled(case).bundle, request_for(case))
    assert record.decision == expect["decision"]
    if "raw" in expect:
        assert record.raw == expect["raw"]
    if "error_policy_ids" in expect:
        assert [error.policy_id for error in record.errors] == expect["error_policy_ids"]
