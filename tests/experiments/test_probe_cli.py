"""The probe command: one tool call as the workload, then the evidence attributed by layer.

Chapter 4's live mode and the capstone need learners to run probes of their
own. Under the test backend nothing is contained, so a kernel outcome here is
only the program's own; the attribution text still follows the evidence.
"""

from __future__ import annotations

import subprocess
import sys

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


def test_an_http_probe_refused_by_cedar_names_the_determining_policy(tmp_path):
    result = probe(tmp_path, "--http", "POST", "http://reference.fixture/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "proxy decision 1: refused at check 'request'" in result.stdout
    assert "fixture receipts: 0" in result.stdout
    assert "layer: the proxy refused it" in result.stdout


def test_a_direct_probe_substitutes_the_fixture_address(tmp_path):
    result = probe(tmp_path, "--bash", "curl -sS --fail --noproxy '*' --max-time 5 "
                   "http://{direct}/reference")
    assert result.returncode == 0, result.stdout + result.stderr
    # Uncontained, the direct request reaches the fixture, which refuses it: no stamp.
    assert "observation: not ok" in result.stdout and "fixture receipts: 0" in result.stdout
    assert "layer: no proxy event and no receipt" in result.stdout
