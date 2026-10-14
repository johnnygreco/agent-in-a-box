"""`layer()` reads three pieces of evidence and gives each combination one honest sentence.

The combinations follow the proxy's check order (protocol, connect, route,
request) and chapter 4's checklist: a proxy decision record, a fixture
receipt, and the observation's own status, errno, or exit status.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_in_a_box.experiments.cli import layer, no_observation


def decision(label, name, determining=(), cedar=True, detail="why"):
    check = {"name": name, "passed": label == "allowed", "detail": detail,
             "decision": {"determining": list(determining)} if cedar else None}
    return {"seq": 1, "label": label, "checks": [check]}


OK = {"ok": True, "output": "", "detail": {"status": 200}}
NOT_OK = {"ok": False, "output": "", "detail": {"exit_status": 1}}
ALLOWED = decision("allowed", "request")
RECEIPT = {"seq": 1}


def test_a_protocol_refusal_is_before_cedar():
    text = layer(NOT_OK, [decision("refused", "protocol", cedar=False, detail="dot segment")], [])
    assert text == "the proxy refused it before asking Cedar: dot segment"


def test_a_route_refusal_comes_after_cedar_allowed_the_connection():
    text = layer(NOT_OK, [decision("refused", "route", cedar=False, detail="no transport")], [])
    assert text == ("Cedar allowed the connection, but the proxy had no route for that endpoint: "
                    "no transport")


def test_a_forbid_names_the_determining_policies():
    text = layer(NOT_OK, [decision("refused", "request", ["forbid-post"])], [])
    assert text == ("the proxy refused it at the request check: the determining policies are "
                    "forbid-post")


def test_a_default_deny_names_the_check_and_says_no_permit_matched():
    assert layer(NOT_OK, [decision("refused", "connect")], []).startswith(
        "the proxy refused it at the connect check: no permit matched")


def test_allowed_and_answered():
    assert layer(OK, [ALLOWED], [RECEIPT]) == "allowed by the proxy and answered by the fixture"


def test_allowed_with_an_application_status():
    missing = {"ok": False, "output": "", "detail": {"status": 404}}
    assert layer(missing, [ALLOWED], [RECEIPT]).endswith("the application answered 404: "
                                                        "nothing refused it")


def test_allowed_with_a_shell_command_names_the_exit_status_not_none():
    via_curl = {"ok": False, "output": "curl: (22) The requested URL returned error: 404",
                "detail": {"exit_status": 22}}
    assert layer(via_curl, [ALLOWED], [RECEIPT]).endswith(
        "the application answered, and the program exited 22: nothing refused it")


def test_allowed_without_a_receipt_is_the_fixture_or_the_forward_not_the_kernel():
    text = layer(NOT_OK, [ALLOWED], [])
    assert text.startswith("allowed by the proxy, but the fixture left no receipt: it refused")


def test_no_event_and_ok_is_the_kernel_permitting():
    assert layer(OK, [], []) == "no proxy event: the kernel permitted the operation"


def test_a_403_with_no_decision_means_the_request_reached_the_fixture():
    via_urllib = {"ok": False, "output": "", "detail": {"status": 403, "refused_by": None}}
    via_curl = {"ok": False, "output": "curl: (22) The requested URL returned error: 403",
                "detail": {"exit_status": 22}}
    printed_body = {"ok": True, "output": "this fixture answers only the run's proxy",
                    "detail": {"exit_status": 0}}  # curl without --fail prints the 403's body
    for observation in (via_urllib, via_curl, printed_body):
        assert layer(observation, [], []).startswith(
            "no proxy event: the request reached the fixture directly")


def test_reading_the_fixtures_source_is_not_taken_for_reaching_the_fixture():
    """The refusal sentence counts only as a whole output line, which is how curl prints the
    body; a grep or cat of the course's own source carries it with a prefix."""
    source_read = {"ok": True, "detail": {"exit_status": 0},
                   "output": 'fixture_service.py:40:REFUSAL = "this fixture answers only the '
                             'run\'s proxy"'}
    assert layer(source_read, [], []) == "no proxy event: the kernel permitted the operation"


def test_a_407_with_no_decision_means_the_request_reached_the_proxy_without_credential():
    via_curl = {"ok": False, "output": "curl: (22) The requested URL returned error: 407",
                "detail": {"exit_status": 22}}
    assert layer(via_curl, [], []).startswith(
        "no proxy event: the request reached the proxy without the run's credential")


def test_no_event_and_not_ok_is_the_kernel_or_the_program():
    assert layer(NOT_OK, [], []).startswith("no proxy event and no receipt: the kernel stopped it")


def record_of(*events):
    return SimpleNamespace(events=[SimpleNamespace(kind=kind, payload=payload)
                                   for kind, payload in events])


def test_the_lifecycle_decides_how_a_run_ended_and_a_refused_line_is_reported_beside_it():
    deadline_and_text = record_of(("agent.text", {"text": "garbage"}),
                                  ("deadline_reached", {"deadline_s": 2}))
    text = no_observation(deadline_and_text, 2)
    assert text.startswith("no observation: ran out of time (deadline 2s)")
    assert text.endswith("the supervisor refused as not a JSON event")
    returned = record_of(("agent.oversized", {"bytes": 20000}),
                         ("workload_exited", {"exit_status": 0}))
    assert "the supervisor refused the harness's observation line as oversized" in (
        no_observation(returned, 30))


def test_a_signal_reads_as_a_signal_under_the_double_and_as_its_status_natively():
    killed = record_of(("workload_exited", {"exit_status": -9}))
    assert "the workload ended by signal 9" in no_observation(killed, 30)
    native = record_of(("workload_exited", {"exit_status": 137}),
                       ("agent.stderr", {"text": "Killed\n"}))
    text = no_observation(native, 30)
    assert "exited with status 137 (a status above 128" in text and "| Killed" in text
