"""PLAN.md, Backend module boundary: each rule enforced by a test.

1. Core packages import no backend package; only composition.py names them.
2. Backend packages import core contracts only, and never another backend.
3. No platform checks outside backend packages and composition.py.
4. Platform-specific native code lives only in native/macos and native/linux
   (native/cedar-bridge is platform-neutral, decisions/0002).
5. One conformance suite, parameterized over the registered native backends.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_in_a_box import composition

SRC = Path(composition.__file__).resolve().parent
REPO = SRC.parent.parent
BACKENDS = SRC / "supervisor" / "backends"
CORE = ["supervisor", "gateway", "harness", "policy", "network", "experiments", "models",
        "client"]
PLATFORM_CHECKS = {
    ("sys", "platform"), ("os", "uname"), ("platform", "system"), ("platform", "mac_ver"),
    ("platform", "uname"), ("platform", "release"), ("platform", "version"),
    ("platform", "freedesktop_os_release"), ("platform", "libc_ver"),
}


def modules(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py")) if root.exists() else []


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def backend_names() -> list[str]:
    return sorted(p.name for p in BACKENDS.iterdir() if (p / "__init__.py").exists())


def test_core_packages_import_no_backend():
    offenders = []
    for package in CORE:
        for path in modules(SRC / package):
            if BACKENDS in path.parents:
                continue
            bad = {m for m in imports(path) if m.startswith("agent_in_a_box.supervisor.backends.")}
            if bad:
                offenders.append((path.relative_to(SRC), sorted(bad)))
    assert offenders == []


def test_backends_import_only_contracts_and_themselves():
    offenders = []
    for name in backend_names():
        own = f"agent_in_a_box.supervisor.backends.{name}"
        for path in modules(BACKENDS / name):
            for module in imports(path):
                if not module.startswith("agent_in_a_box"):
                    continue
                if module.split(".")[:2] == ["agent_in_a_box", "contracts"]:
                    continue
                if module == own or module.startswith(own + "."):
                    continue
                offenders.append((path.relative_to(SRC), module))
    assert offenders == []


def test_no_platform_checks_outside_backends_and_composition():
    offenders = []
    for path in modules(SRC):
        if BACKENDS in path.parents or path.name == "composition.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and (node.value.id, node.attr) in PLATFORM_CHECKS):
                offenders.append((path.relative_to(SRC), f"{node.value.id}.{node.attr}"))
        if {"distro"} & imports(path):
            offenders.append((path.relative_to(SRC), "distro"))
    assert offenders == []


def test_native_code_is_confined():
    allowed = {"macos", "linux", "cedar-bridge"}
    present = {p.name for p in (REPO / "native").iterdir() if p.is_dir()}
    assert present <= allowed


def test_backends_are_registered_by_name_in_composition():
    assert set(composition.BACKENDS) <= set(backend_names())
    assert "none" in composition.BACKENDS


def test_one_conformance_suite_over_native_backends():
    suite = REPO / "tests" / "backends" / "conformance"
    assert (suite / "test_conformance.py").exists()
    from tests.backends.conformance.test_conformance import NATIVE_BACKENDS

    assert set(NATIVE_BACKENDS) == {"seatbelt", "landlock"}
