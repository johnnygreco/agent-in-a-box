"""The pinned Sandbox schema, its names, and the shipped policy variants.

The names here are the only place Python code spells entity types and
actions, so a schema change shows up as a change to this file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_in_a_box.contracts import EntityRef, PolicyBundle

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_DIR = REPO_ROOT / "policies"
SCHEMA_PATH = POLICY_DIR / "sandbox.cedarschema"
VARIANT_DIR = POLICY_DIR / "variants"

PROCESS = "Sandbox::Process"
USER = "Sandbox::User"
GROUP = "Sandbox::Group"
FILESYSTEM_PATH = "Sandbox::FilesystemPath"
NETWORK_ENDPOINT = "Sandbox::NetworkEndpoint"
ACTION_TYPE = "Sandbox::Action"

READ_FILE = "ReadFile"
WRITE_FILE = "WriteFile"
NETWORK_CONNECT = "NetworkConnect"
HTTP_REQUEST = "HttpRequest"

# The one process entity the runtime builds per request. Every request in a run
# comes from the same sandboxed process tree, so one fixed identity is enough.
CURRENT_PROCESS = EntityRef(PROCESS, "current")
SANDBOX_USER = EntityRef(USER, "sandbox")
SANDBOX_GROUP = EntityRef(GROUP, "sandbox")

# Logical root of every FilesystemPath a task policy may name.
WORKSPACE_ROOT = "/workspace"


def action(name: str) -> EntityRef:
    return EntityRef(ACTION_TYPE, name)


def schema_text() -> str:
    return SCHEMA_PATH.read_text()


def variant_names() -> list[str]:
    return sorted(p.stem for p in VARIANT_DIR.glob("P*.cedar"))


def load_variant(name: str) -> PolicyBundle:
    """Load a shipped variant (P0 ... P6) with the pinned schema."""
    path = VARIANT_DIR / f"{name}.cedar"
    if not path.is_file():
        raise KeyError(f"unknown policy variant {name!r}; known: {variant_names()}")
    return PolicyBundle(name=name, schema_text=schema_text(), policy_text=path.read_text())


def bundle_from_text(name: str, policy_text: str) -> PolicyBundle:
    return PolicyBundle(name=name, schema_text=schema_text(), policy_text=policy_text)


def resolve_policy(ref: object) -> PolicyBundle:
    """A shipped variant by name ("P0") or authored text ({"name": ..., "text": ...})."""
    if isinstance(ref, str):
        return load_variant(ref)
    if isinstance(ref, Mapping) and set(ref) == {"name", "text"}:
        return bundle_from_text(str(ref["name"]), str(ref["text"]))
    raise ValueError(f"policy must be a variant name or {{name, text}}, not {ref!r}")
