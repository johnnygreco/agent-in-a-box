"""M0 exit: the trailer runs end to end via the CLI under the test backend,
every step labeled enforcement: none, and the bundle exports, imports, and
replays without effects."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from agent_in_a_box.experiments import bundle as bundles
from agent_in_a_box.policy.evaluator import CedarpyEvaluator

pytestmark = pytest.mark.toolchain
CLI = [sys.executable, "-m", "agent_in_a_box.experiments.cli"]


def trailer_argv(state):
    return [*CLI, "--state-dir", str(state), "trailer", "--test-backend", "--session", "t1"]


@pytest.fixture(scope="module")
def trailer(tmp_path_factory):
    state = tmp_path_factory.mktemp("state")
    result = subprocess.run(trailer_argv(state), capture_output=True, text=True,
                            timeout=300)
    return state, result


def test_trailer_runs_as_expected(trailer):
    _, result = trailer
    assert result.returncode == 0, result.stdout + result.stderr
    assert "as expected" in result.stdout
    assert "[enforcement: none]" in result.stdout
    assert "distinguishing input and confirmed by replay: POST /reference" in result.stdout
    assert "no permission expansion and proved for domain D" in result.stdout
    assert "intended task preserved" in result.stdout


def test_bundle_round_trip_and_effect_free_replay(trailer):
    state, _ = trailer
    path = next((state / "bundles").glob("chapter-0-trailer-*.json"))
    document = bundles.load(path)
    assert document["viewed_as"] == "recorded" and document["enforcement"] == ["none"]
    runs = [s["result"]["run"] for s in document["steps"] if s["kind"] == "run"]
    assert runs and all(e["enforcement"] == "none" for r in runs for e in r["events"])
    assert document["transport_mappings"][0]["endpoint"] == "reference.fixture:80"
    before = sorted((state / "runs").iterdir())
    report = bundles.replay(document, CedarpyEvaluator())
    assert report["mismatched"] == [] and report["decisions"] == report["matched"] > 0
    assert sorted((state / "runs").iterdir()) == before
    token = json.loads((state / "gateway.json").read_text())["token"]
    assert token not in path.read_text()


def test_test_backend_bundle_cannot_be_imported_as_native(trailer):
    state, _ = trailer
    path = next((state / "bundles").glob("chapter-0-trailer-*.json"))
    with pytest.raises(bundles.BundleError):
        bundles.load(path, as_native=True)


def test_modified_bundle_is_detected(trailer, tmp_path):
    state, _ = trailer
    path = next((state / "bundles").glob("chapter-0-trailer-*.json"))
    document = json.loads(path.read_text())
    document["steps"][0]["status"] = "refused"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(document))
    with pytest.raises(bundles.BundleError):
        bundles.load(tampered)


def test_rerunning_the_session_starts_nothing(trailer):
    state, _ = trailer
    before = sorted((state / "runs").iterdir())
    result = subprocess.run(trailer_argv(state), capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0 and sorted((state / "runs").iterdir()) == before


def test_doctor_refuses_native_execution_without_a_backend(tmp_path):
    result = subprocess.run([*CLI, "--state-dir", str(tmp_path), "doctor"], capture_output=True,
                            text=True, timeout=60)
    if sys.platform == "linux":
        assert result.returncode == 1 and "no fallback" in result.stdout


def test_bundle_cli_show_and_replay(trailer):
    state, _ = trailer
    path = next((state / "bundles").glob("chapter-0-trailer-*.json"))
    shown = subprocess.run([*CLI, "--state-dir", str(state), "bundle", "show", str(path)],
                           capture_output=True, text=True, timeout=60)
    assert "[recorded; enforcement: none" in shown.stdout
    replayed = subprocess.run([*CLI, "--state-dir", str(state), "bundle", "replay", str(path)],
                              capture_output=True, text=True, timeout=60)
    assert replayed.returncode == 0 and '"effects": "none"' in replayed.stdout


