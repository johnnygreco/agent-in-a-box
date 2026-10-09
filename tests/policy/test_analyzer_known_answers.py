"""Known-answer tests for the pinned SymCC + cvc5 stack (M0 gate).

Expectations come from the lesson property catalog (PLAN.md, Formal
verification) and from reading the policy text: P1 adds POST to /reference;
P2 permits any method on /reference except POST; P3 forbids every HTTP
request; P5 refactors P0 without changing decisions; P6 moves the connection
endpoint into a condition. None was produced by running the analyzer first.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_in_a_box.contracts import plain
from agent_in_a_box.policy import analyzer, domains, schema
from agent_in_a_box.policy import requests
from agent_in_a_box.policy.bridge import BridgeError
from agent_in_a_box.policy.evaluator import CedarpyEvaluator

pytestmark = pytest.mark.toolchain

EV = CedarpyEvaluator()
P = {name: schema.load_variant(name) for name in schema.variant_names()}
GET_REFERENCE = requests.http_request("reference.fixture", 80, "GET", "/reference")


def expansion(old, new, **kw):
    return analyzer.check("no-permission-expansion", P[old], P[new], EV, **kw)


def test_invalid_implication_p0_to_p1_returns_post_and_replays():
    result = expansion("P0", "P1")
    assert result.status == "sat"
    request = result.witness["request"]
    assert request["context"] == {"method": "POST", "path": "/reference"}
    assert request["resource"] == {"type": "Sandbox::NetworkEndpoint", "id": "reference.fixture:80"}
    new, old = result.replay
    assert (new.decision, old.decision) == ("allowed", "denied")
    assert new.hypothetical and old.hypothetical
    assert result.labels == ("distinguishing input", "confirmed by replay")
    assert result.error is None


def test_p0_to_p2_finds_a_method_other_than_get_or_post():
    result = expansion("P0", "P2")
    assert result.status == "sat"
    method = result.witness["request"]["context"]["method"]
    assert method in requests.SUPPORTED_METHODS and method not in ("GET", "POST")
    assert result.labels == ("distinguishing input", "confirmed by replay")


def test_whole_schema_domain_admits_witnesses_no_client_sends():
    """Without the proxy's method set, the solver may pick any string."""
    schema_wide = dataclasses.replace(domains.D_HTTP, name="schema", condition=None)
    result = expansion("P0", "P2", domain=schema_wide)
    assert result.status == "sat"
    assert result.witness["request"]["context"]["method"] not in ("GET", "POST")


def test_valid_implication_after_repair_is_unsat():
    result = expansion("P1", "P0")
    assert result.status == "unsat"
    assert result.labels == ("no permission expansion", "proved for domain D")
    assert result.witness is None and result.replay == ()


def test_deny_all_repair_passes_expansion_and_fails_task_preservation():
    result = expansion("P1", "P3")
    assert result.labels == ("no permission expansion", "proved for domain D")
    record, label = analyzer.task_preserved(EV, P["P3"], GET_REFERENCE)
    assert (record.decision, label) == ("denied", "denied")
    record, label = analyzer.task_preserved(EV, P["P0"], GET_REFERENCE)
    assert (record.decision, label) == ("allowed", "intended task preserved")


@pytest.mark.parametrize("other", ["P5", "P6"])
def test_refactors_are_cedar_equivalent_to_p0(other):
    result = analyzer.check("equivalence", P["P0"], P[other], EV)
    assert result.status == "unsat"
    assert result.labels == ("proved for domain D",)


def test_equivalence_fails_for_p0_and_p1_with_a_replayed_witness():
    result = analyzer.check("equivalence", P["P0"], P["P1"], EV)
    assert result.status == "sat"
    assert result.labels == ("distinguishing input", "confirmed by replay")


def test_deliberate_unknown_is_no_conclusion():
    result = expansion("P0", "P1", solver_args=analyzer.STARVED_SOLVER_ARGS)
    assert result.status == "unknown"
    assert result.labels == ("no conclusion",)
    assert result.witness is None


def test_connect_domain_shows_p6_and_p0_agree():
    result = analyzer.check("equivalence", P["P0"], P["P6"], EV, domain=domains.D_CONNECT)
    assert result.status == "unsat"


def test_solver_input_can_be_disclosed():
    result = expansion("P0", "P1", emit_smtlib=True)
    assert result.smtlib and "(check-sat)" in result.smtlib


def test_witness_is_preserved_unchanged(monkeypatch):
    seen = {}
    real_call = analyzer.bridge.call

    def spy(command, **kw):
        seen["out"] = real_call(command, **kw)
        return seen["out"]

    monkeypatch.setattr(analyzer.bridge, "call", spy)
    result = expansion("P0", "P1")
    assert plain(result.witness) == seen["out"]["witness"]


def test_corrupted_witness_is_a_replay_disagreement(monkeypatch):
    real_call = analyzer.bridge.call

    def corrupt(command, **kw):
        out = real_call(command, **kw)
        out["witness"]["request"]["context"]["method"] = "GET"
        return out

    monkeypatch.setattr(analyzer.bridge, "call", corrupt)
    result = expansion("P0", "P1")
    assert result.status == "sat"
    assert result.labels == ("no conclusion",)
    assert "replay disagreement" in result.error


@pytest.mark.parametrize("kind", ["timeout", "crash"])
def test_bridge_failure_is_no_conclusion(monkeypatch, kind):
    def fail(command, **kw):
        raise BridgeError(kind, "simulated")

    monkeypatch.setattr(analyzer.bridge, "call", fail)
    result = expansion("P0", "P1")
    assert result.status == ("timeout" if kind == "timeout" else "error")
    assert result.labels == ("no conclusion",)


def test_every_result_label_is_a_glossary_term():
    from agent_in_a_box.glossary import TERMS

    results = [expansion("P0", "P1"), expansion("P1", "P0"),
               expansion("P0", "P1", solver_args=analyzer.STARVED_SOLVER_ARGS)]
    labels = {label for r in results for label in r.labels}
    labels.add(analyzer.task_preserved(EV, P["P0"], GET_REFERENCE)[1])
    labels.add(analyzer.task_preserved(EV, P["P3"], GET_REFERENCE)[1])
    assert labels <= set(TERMS)
