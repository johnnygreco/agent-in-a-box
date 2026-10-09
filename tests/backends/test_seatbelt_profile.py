"""The SBPL renderer, tested as text. Untested natively until Milestone 1.

Expectations follow PLAN.md (Filesystem grant extraction, Network mediation)
and the renderer's documented shape: separate read and write rules, canonical
literal paths, exec as process-exec plus metadata, only the proxy port for
network, protected paths denied last.
"""

from __future__ import annotations

import pytest

from agent_in_a_box.contracts import Access, Extent, GrantPlan, PathGrant
from agent_in_a_box.supervisor.backends.seatbelt.profile import render, sbpl_path


def grant(path, access, extent=Extent.SUBTREE, origin="policy", logical=None):
    return PathGrant(path, access, extent, origin, ("p",), logical)


PLAN = GrantPlan(
    task=(grant("/r/ws/measurements.csv", Access.READ, logical="/workspace/measurements.csv"),
          grant("/r/ws/results", Access.WRITE, logical="/workspace/results")),
    runtime=(grant("/usr/bin/python3", Access.EXECUTE, Extent.FILE, "runtime"),
             grant("/opt/py", Access.READ, origin="runtime")),
    protected=("/r/private",),
    proxy_port=4123,
    policy_hash="abc",
)


def test_profile_shape():
    text = render(PLAN)
    lines = text.splitlines()
    assert lines[0] == "(version 1)"
    assert "(deny default)" in lines
    assert '(allow file-read* (subpath "/r/ws/measurements.csv"))' in lines
    assert '(allow file-write* (subpath "/r/ws/results"))' in lines
    assert '(allow process-exec (literal "/usr/bin/python3"))' in lines
    assert '(allow file-read-metadata (literal "/usr/bin/python3"))' in lines
    assert '(allow network-outbound (remote ip "localhost:4123"))' in lines


def test_write_grant_does_not_grant_read():
    text = render(PLAN)
    assert '(allow file-read* (subpath "/r/ws/results"))' not in text


def test_write_root_identity_is_pinned():
    text = render(PLAN)
    assert '(deny file-write-unlink (literal "/r/ws/results"))' in text
    assert '(deny file-write-create (literal "/r/ws/results"))' in text


def test_only_one_network_rule():
    network = [line for line in render(PLAN).splitlines() if "network" in line and "(" in line]
    assert network == ['(allow network-outbound (remote ip "localhost:4123"))']


def test_protected_paths_are_denied_last():
    lines = [line for line in render(PLAN).splitlines() if line.startswith("(")]
    assert lines[-1] == '(deny file-read* file-write* (subpath "/r/private"))'


def test_ancestors_get_metadata_only():
    text = render(PLAN)
    assert '(allow file-read-metadata (literal "/r/ws"))' in text
    assert '(allow file-read* (literal "/r/ws"))' not in text


def test_rendering_is_deterministic():
    assert render(PLAN) == render(PLAN)


@pytest.mark.parametrize("path", ["relative", "/a/../b", "/a/", "/a\nb", "/a\x00b", "//a"])
def test_unsafe_paths_are_refused(path):
    with pytest.raises(ValueError):
        sbpl_path(path)


def test_quotes_and_backslashes_are_escaped():
    assert sbpl_path('/a"b\\c') == '"/a\\"b\\\\c"'


def test_execute_must_name_a_file():
    bad = GrantPlan((), (grant("/usr/bin", Access.EXECUTE),), (), 1, "h")
    with pytest.raises(ValueError):
        render(bad)


@pytest.mark.parametrize("port", [0, 70000])
def test_proxy_port_range(port):
    with pytest.raises(ValueError):
        render(GrantPlan((), (), (), port, "h"))


def test_every_baseline_rule_is_rendered_after_its_reason():
    from agent_in_a_box.supervisor.backends.seatbelt.os_baseline import BASELINE
    from agent_in_a_box.supervisor.backends.seatbelt.profile import baseline_rule

    lines = render(PLAN).splitlines()
    for entry in BASELINE:
        rule = baseline_rule(entry)
        assert rule in lines
        assert lines[lines.index(rule) - 1] == f";; {entry.why}"


def test_baseline_grants_no_user_data_and_writes_only_the_null_device():
    from agent_in_a_box.supervisor.backends.seatbelt.os_baseline import BASELINE

    for entry in BASELINE:
        assert entry.why
        assert not entry.value.startswith(("/Users", "/Volumes", "/private/var/folders"))
        if entry.operation.startswith("file-write"):
            assert entry.value == "/dev/null"
        assert not entry.operation.startswith("network")


def test_ancestors():
    from agent_in_a_box.supervisor.backends.seatbelt.profile import ancestors

    assert ancestors("/r/ws/results") == ["/r/ws", "/r", "/"]
    assert ancestors("/a") == ["/"]
