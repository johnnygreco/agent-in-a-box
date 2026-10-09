"""Gateway v1: local-only Host, origin checks, session auth, idempotent commands, SSE.

Expectations come from PLAN.md, Gateway and Evidence, client commands, and replay.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from agent_in_a_box import composition
from agent_in_a_box.contracts import DoctorCheck, DoctorReport
from agent_in_a_box.experiments.controller import Controller
from agent_in_a_box.gateway.app import EventHub, create_app

PORT = 8123
TOKEN = "test-token-not-secret"
BASE = f"http://127.0.0.1:{PORT}"
EVALUATE = {"policy": "P0", "request": {"action": "HttpRequest", "host": "reference.fixture",
                                        "port": 80, "method": "POST", "path": "/reference"}}


def make(tmp_path, backend="none"):
    runtime = composition.assemble(composition.RuntimeConfig(
        backend=backend, allow_test_backend=backend == "none", runs_dir=tmp_path / "runs"))
    hub = EventHub()
    controller = Controller(runtime, hub.publish)
    return TestClient(create_app(controller, hub, TOKEN, PORT), base_url=BASE), controller


@pytest.fixture
def client(tmp_path):
    return make(tmp_path)[0]


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def post(client, body, headers=None):
    return client.post("/api/v1/commands", json=body, headers={**AUTH, **(headers or {})})


def wait(client, command_id):
    for _ in range(400):
        result = client.get(f"/api/v1/commands/{command_id}", headers=AUTH).json()
        if result["status"] != "running":
            return result
        import time

        time.sleep(0.05)
    raise AssertionError("command did not finish")


def test_health_needs_no_token_and_reports_enforcement(client):
    assert client.get("/api/v1/health").json()["enforcement"] == "none"


def test_commands_need_the_session_token(client):
    body = {"command_id": "c1", "kind": "evaluate", "payload": EVALUATE}
    assert client.post("/api/v1/commands", json=body).status_code == 401
    assert post(client, body, {"Authorization": "Bearer wrong"}).status_code == 401


def test_session_cookie_authorizes(client):
    assert client.post("/api/v1/session", json={}, headers=AUTH).status_code == 200
    body = {"command_id": "c-cookie", "kind": "evaluate", "payload": EVALUATE}
    assert client.post("/api/v1/commands", json=body).status_code in (200, 202)


def test_foreign_host_header_is_refused(client):
    response = client.get("/api/v1/health", headers={"Host": f"attacker.example:{PORT}"})
    assert response.status_code == 421


@pytest.mark.parametrize("headers,status", [
    ({"Origin": "http://attacker.example"}, 403),
    ({"Sec-Fetch-Site": "cross-site"}, 403),
])
def test_cross_site_state_changes_are_refused(client, headers, status):
    body = {"command_id": "c2", "kind": "evaluate", "payload": EVALUATE}
    assert post(client, body, headers).status_code == status


def test_non_json_state_change_is_refused(client):
    response = client.post("/api/v1/commands", content="command_id=c3",
                           headers={**AUTH, "Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 415


def test_same_id_returns_the_stored_result_and_runs_once(tmp_path):
    client, controller = make(tmp_path)
    body = {"command_id": "eval-1", "kind": "evaluate", "payload": EVALUATE}
    post(client, body)
    first = wait(client, "eval-1")
    calls = []
    original = controller.handlers["evaluate"]

    def counting(*arguments):
        calls.append(arguments)
        return original(*arguments)

    controller.handlers["evaluate"] = counting
    second = post(client, body).json()
    assert second == first and calls == []
    assert first["result"]["decision"]["decision"] == "denied"
    assert first["result"]["decision"]["hypothetical"] is True


def test_same_id_with_different_input_is_refused(client):
    post(client, {"command_id": "eval-2", "kind": "evaluate", "payload": EVALUATE})
    wait(client, "eval-2")
    changed = {**EVALUATE, "policy": "P1"}
    response = post(client, {"command_id": "eval-2", "kind": "evaluate", "payload": changed})
    assert response.json()["status"] == "refused"
    assert "different input" in response.json()["result"]["reason"]


def test_results_survive_a_new_controller(tmp_path):
    client, _ = make(tmp_path)
    post(client, {"command_id": "eval-3", "kind": "evaluate", "payload": EVALUATE})
    first = wait(client, "eval-3")
    again, _ = make(tmp_path)
    assert again.get("/api/v1/commands/eval-3", headers=AUTH).json() == first


def test_no_command_can_choose_the_backend(client):
    body = {"command_id": "run-x", "kind": "run", "payload": {"policy": "P0", "backend": "none"}}
    post(client, body)
    result = wait(client, "run-x")
    assert result["status"] == "refused" and "unknown fields" in result["result"]["reason"]


def test_native_runtime_refuses_runs_instead_of_falling_back(tmp_path, monkeypatch):
    """A native backend whose doctor fails refuses the run; nothing runs uncontained."""
    runtime = composition.assemble(composition.RuntimeConfig(runs_dir=tmp_path / "runs"))
    if runtime.backend is not None:
        failing = DoctorReport(runtime.backend.name,
                               (DoctorCheck("prerequisite", False, "missing in this test"),),
                               native_execution=False)
        monkeypatch.setattr(runtime.backend, "doctor", lambda: failing)
    hub = EventHub()
    client = TestClient(create_app(Controller(runtime, hub.publish), hub, TOKEN, PORT),
                        base_url=BASE)
    post(client, {"command_id": "run-native", "kind": "run", "payload": {"policy": "P0"}})
    result = wait(client, "run-native")
    if runtime.backend is None:
        assert result["status"] == "refused"
        return
    run = result["result"]["run"]
    assert run["status"] == "refused" and "doctor" in run["refusal"]
    assert not any(event["kind"] in ("launched", "admitted") for event in run["events"])


def test_run_events_stream_over_sse_labeled_none(client):
    post(client, {"command_id": "run-1", "kind": "run", "payload": {"policy": "P0"}})
    result = wait(client, "run-1")
    assert result["status"] == "succeeded"
    stream = client.get("/api/v1/events?follow=0", headers=AUTH).text
    envelopes = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
    evidence = [e["event"] for e in envelopes if e["type"] == "evidence"]
    assert evidence and {e["enforcement"] for e in evidence} == {"none"}
    assert any(e["kind"] == "proxy.decision" for e in evidence)
    assert envelopes[-1]["type"] == "command" and envelopes[-1]["result"]["command_id"] == "run-1"
    later = client.get(f"/api/v1/events?follow=0&after={len(envelopes)}", headers=AUTH).text
    assert later == ""
    assert TOKEN not in stream
