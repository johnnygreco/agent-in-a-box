"""The pinned toolchain: manifest contents and refusal of altered binaries."""

from __future__ import annotations

import json
import shutil

import pytest

from agent_in_a_box.policy import toolchain

pytestmark = pytest.mark.toolchain


def test_manifest_records_pinned_versions_and_checksums():
    manifest = toolchain.manifest()
    lock = toolchain.lock()
    assert manifest["cedar_policy"] == lock["cedar"]["cedar_policy"] == "4.12.0"
    assert manifest["cedar_policy_symcc"] == "0.6.0"
    assert manifest["cedarpy"] == "4.12.1"
    assert manifest["cedarpy_bundled_cedar_policy"] == "4.12.0"
    assert "version 1.3.1" in manifest["cvc5"]
    assert set(manifest["binary_sha256"]) >= {"bridge", "cvc5"}
    assert len(manifest["schema_sha256"]) == 64


def test_altered_binary_is_refused(tmp_path, monkeypatch):
    real = toolchain.toolchain_dir()
    copy = tmp_path / "toolchain"
    shutil.copytree(real / "bin", copy / "bin")
    installed = json.loads((real / "installed.json").read_text())
    for entry in installed["binaries"].values():
        entry["path"] = str(copy / "bin" / entry["path"].split("/")[-1])
    installed["binaries"].pop("cedar_cli", None)
    (copy / "installed.json").write_text(json.dumps(installed))
    monkeypatch.setenv("AGENT_IN_A_BOX_TOOLCHAIN", str(copy))
    toolchain.load.cache_clear()
    try:
        assert toolchain.load().bridge.parent == copy / "bin"
        (copy / "bin" / "cvc5").write_bytes(b"#!/bin/sh\necho sat\n")
        toolchain.load.cache_clear()
        with pytest.raises(toolchain.ToolchainError, match="changed since bootstrap"):
            toolchain.load()
    finally:
        toolchain.load.cache_clear()


def test_missing_toolchain_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_IN_A_BOX_TOOLCHAIN", str(tmp_path / "nothing"))
    toolchain.load.cache_clear()
    try:
        with pytest.raises(toolchain.ToolchainError, match="bootstrap"):
            toolchain.load()
    finally:
        toolchain.load.cache_clear()
