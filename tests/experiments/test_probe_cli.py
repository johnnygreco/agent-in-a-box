"""The probe command: one tool call as the workload, then the evidence attributed by layer.

Chapter 4's live mode and the capstone need learners to run probes of their
own. Under the test backend nothing is contained, so a kernel outcome here is
only the program's own; the attribution text still follows the evidence, and
a direct request that reaches the fixture is reported as having reached it.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

CLI = [sys.executable, "-m", "agent_in_a_box.experiments.cli"]


def probe(state, *arguments):
    return subprocess.run([*CLI, "--state-dir", str(state), "probe", "--test-backend", *arguments],
                          capture_output=True, text=True, timeout=180)


def test_a_bash_probe_with_no_proxy_event_is_attributed_to_the_kernel_or_program(tmp_path):
    result = probe(tmp_path, "--bash", "cat measurements.csv")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[enforcement: none" in result.stdout and "observation: ok" in result.stdout
    assert "fixture receipts: 0" in result.stdout
    assert "layer: no proxy event: the kernel permitted the operation" in result.stdout


def test_a_refusal_by_a_forbid_names_the_determining_policy(tmp_path):
    result = probe(tmp_path, "--policy", "P2", "--http", "POST",
                   "http://reference.fixture/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "proxy decision 1: refused at check 'request'; determining forbid-post" in result.stdout
    assert ("layer: the proxy refused it at the request check: the determining policies are "
            "forbid-post") in result.stdout


def test_a_default_deny_says_that_no_permit_matched(tmp_path):
    result = probe(tmp_path, "--http", "POST", "http://reference.fixture/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fixture receipts: 0" in result.stdout
    assert ("layer: the proxy refused it at the request check: no permit matched, so Cedar's "
            "default deny applied") in result.stdout


def test_a_route_refusal_is_attributed_after_cedar_allowed_the_connection(tmp_path):
    """P6 names its endpoint only in a condition: Cedar says yes, the derived routes say no."""
    result = probe(tmp_path, "--policy", "P6", "--http", "GET",
                   "http://reference.fixture/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "refused at check 'route'" in result.stdout
    assert "layer: Cedar allowed the connection, but the proxy had no route" in result.stdout


def test_an_uncontained_direct_probe_is_reported_as_having_reached_the_fixture(tmp_path):
    result = probe(tmp_path, "--bash", "curl -sS --fail --noproxy '*' --max-time 5 "
                   "http://{direct}/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    # Nothing contains the test double, so the request reaches the fixture, which refuses
    # it for lacking the proxy's stamp: no receipt, and an attribution that says so.
    assert "observation: not ok" in result.stdout and "fixture receipts: 0" in result.stdout
    assert "layer: no proxy event: the request reached the fixture directly" in result.stdout


def test_a_run_that_ends_before_the_tool_call_returns_is_reported_not_crashed(tmp_path):
    result = probe(tmp_path, "--deadline", "2", "--bash", "sleep 8")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "no observation: ran out of time (deadline 2s) before the tool call returned" in (
        result.stdout)
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("url", ["not-a-url", "http://reference.fixture/a b",
                                 "file:///etc/hostname", "http://[::1/x"])
def test_a_bad_url_is_an_observation_not_a_harness_crash(tmp_path, url):
    result = probe(tmp_path, "--http", "GET", url)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "observation: not ok" in result.stdout and "request failed" in result.stdout
    assert "layer: no proxy event and no receipt" in result.stdout


def test_a_workload_that_dies_is_reported_with_its_signal(tmp_path):
    """Under the test double the supervisor sees the signal itself; the native init reports
    a signalled workload as 128 plus the signal, which the report explains in that case."""
    result = probe(tmp_path, "--bash", "kill -9 $PPID")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "no observation: the workload ended by signal 9 before the tool call returned" in (
        result.stdout)
    assert "Traceback" not in result.stderr


def test_an_https_url_is_refused_at_the_proxys_tunnel_with_a_recorded_decision(tmp_path):
    result = probe(tmp_path, "--http", "GET", "https://reference.fixture/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "refused at check 'protocol'" in result.stdout
    assert "layer: the proxy refused it before asking Cedar: opaque CONNECT tunnels" in (
        result.stdout)


def test_the_help_states_the_deadline_default_and_the_bash_timer():
    result = subprocess.run([*CLI, "probe", "--help"], capture_output=True, text=True, timeout=60)
    unwrapped = " ".join(result.stdout.split())  # argparse wraps to the terminal's width
    assert result.returncode == 0 and "(default 45)" in unwrapped and "after 30 s" in unwrapped


def test_an_unknown_policy_or_variant_name_is_refused_by_the_parser(tmp_path):
    result = probe(tmp_path, "--policy", "P9", "--bash", "true")
    assert result.returncode == 2 and "invalid choice: 'P9'" in result.stderr
    result = probe(tmp_path, "--variant", "nope", "--bash", "true")
    assert result.returncode == 2 and "invalid choice: 'nope'" in result.stderr
