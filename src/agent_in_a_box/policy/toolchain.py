"""Locate and verify the pinned Cedar toolchain, and emit the tool manifest.

The toolchain is installed by `python3 tooling/bootstrap.py` into .toolchain/
(or $AGENT_IN_A_BOX_TOOLCHAIN). Every binary is checked against the checksum the
bootstrap recorded, so a replaced binary is refused rather than used. Versions
are checked against tooling/toolchain.lock.json, never inferred from names.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import subprocess
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

from agent_in_a_box.policy.schema import REPO_ROOT, SCHEMA_PATH

LOCK_PATH = REPO_ROOT / "tooling" / "toolchain.lock.json"


class ToolchainError(RuntimeError):
    """The pinned toolchain is missing, altered, or not the pinned version."""


@dataclass(frozen=True)
class Toolchain:
    bridge: Path
    cvc5: Path
    cedar_cli: Path | None
    lock: dict[str, Any]
    installed: dict[str, Any]


def toolchain_dir() -> Path:
    return Path(os.environ.get("AGENT_IN_A_BOX_TOOLCHAIN", REPO_ROOT / ".toolchain"))


def lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text())


def pinned(*keys: str) -> str:
    """A value from tooling/toolchain.lock.json, for example pinned("cedar", "cedar_policy")."""
    value: Any = lock()
    for key in keys:
        value = value[key]
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@functools.cache
def load() -> Toolchain:
    """Return the installed toolchain after checking every binary's checksum."""
    record = toolchain_dir() / "installed.json"
    if not record.is_file():
        raise ToolchainError(f"{record} not found; run: python3 tooling/bootstrap.py")
    installed = json.loads(record.read_text())
    paths: dict[str, Path] = {}
    for name, entry in installed["binaries"].items():
        path = Path(entry["path"])
        if not path.is_file():
            raise ToolchainError(f"{name} missing at {path}; rerun tooling/bootstrap.py")
        if sha256_file(path) != entry["sha256"]:
            raise ToolchainError(f"{name} at {path} changed since bootstrap; refusing to use it")
        paths[name] = path
    if "bridge" not in paths or "cvc5" not in paths:
        raise ToolchainError("bridge or cvc5 not installed; rerun tooling/bootstrap.py")
    return Toolchain(paths["bridge"], paths["cvc5"], paths.get("cedar_cli"), lock(), installed)


def _run(argv: list[str], stdin: str = "") -> str:
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=30).stdout


@functools.cache
def manifest() -> dict[str, Any]:
    """The tool manifest recorded with every analysis result and bundle."""
    tc = load()
    pins = tc.lock
    bridge = json.loads(_run([str(tc.bridge)], json.dumps({"op": "version"})))["result"]
    if (bridge["cedar_policy"], bridge["cedar_policy_symcc"]) != (
        pins["cedar"]["cedar_policy"],
        pins["cedar"]["cedar_policy_symcc"],
    ):
        raise ToolchainError(f"bridge reports {bridge}, lock pins {pins['cedar']}")
    cvc5_version = _run([str(tc.cvc5), "--version"]).splitlines()[0]
    if f"version {pins['cvc5']['version']} " not in cvc5_version + " ":
        raise ToolchainError(f"cvc5 reports {cvc5_version!r}, lock pins {pins['cvc5']['version']}")
    cedarpy_version = package_version("cedarpy")
    if cedarpy_version != pins["cedarpy"]["version"]:
        raise ToolchainError(f"cedarpy {cedarpy_version} installed, lock pins {pins['cedarpy']}")
    binaries = {name: entry["sha256"] for name, entry in tc.installed["binaries"].items()}
    return {
        "cedar_policy": pins["cedar"]["cedar_policy"],
        "cedar_language": bridge["cedar_language"],
        "cedar_policy_symcc": bridge["cedar_policy_symcc"],
        "bridge": bridge["bridge"],
        "bridge_cargo_lock_sha256": tc.installed["bridge_cargo_lock_sha256"],
        "cedarpy": cedarpy_version,
        "cedarpy_bundled_cedar_policy": pins["cedarpy"]["bundled_cedar_policy"],
        "cvc5": cvc5_version,
        "binary_sha256": binaries,
        "schema_sha256": sha256_file(SCHEMA_PATH),
        "platform": f"{platform.platform()} {platform.machine()}",
        "feature_flags": {"bridge": [], "cedar_cli": pins["cedar_cli"]["features"]},
    }
