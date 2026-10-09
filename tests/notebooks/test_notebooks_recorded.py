"""Notebook drafts 01 and 04 run in recorded mode: they load a bundle and
start no workload, proxy, gateway command, or solver (PLAN.md, Marimo
developer experience)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

pytest.importorskip("marimo")
pytestmark = pytest.mark.toolchain

NOTEBOOKS = __import__("pathlib").Path(__file__).resolve().parents[2] / "notebooks"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    state = tmp_path_factory.mktemp("state")
    subprocess.run([sys.executable, "-m", "agent_in_a_box.experiments.cli", "--state-dir",
                    str(state), "trailer", "--test-backend", "--session", "nb"],
                   check=True, capture_output=True, timeout=300)
    return state, next((state / "bundles").glob("*.json"))


def run_notebook(name, bundle_path, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_IN_A_BOX_BUNDLE", str(bundle_path))
    monkeypatch.chdir(tmp_path)  # no gateway state here, so live controls stay disabled
    spec = importlib.util.spec_from_file_location(name, NOTEBOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app.run()[1]


def test_01_follow_a_request(bundle, monkeypatch, tmp_path):
    state, path = bundle
    runs_before = sorted((state / "runs").iterdir())
    defs = run_notebook("01_follow_a_request", path, monkeypatch, tmp_path)
    assert defs["document"]["viewed_as"] == "recorded"
    assert defs["cedar"]["decision"] == "allowed"
    assert sorted((state / "runs").iterdir()) == runs_before


def test_04_examples_to_proofs(bundle, monkeypatch, tmp_path):
    state, path = bundle
    runs_before = sorted((state / "runs").iterdir())
    defs = run_notebook("04_examples_to_proofs", path, monkeypatch, tmp_path)
    assert defs["confirmed"] is True
    assert any(row["method"] == "POST" and row["P1"] == "allowed" and row["P0"] == "denied"
               for row in defs["grid"])
    assert defs["live"].value is False
    assert sorted((state / "runs").iterdir()) == runs_before
