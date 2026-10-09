"""Bundles shipped in bundles/ are native recordings with no host paths (decisions/0011, 0013).

The website publishes these. Each must be a native recording (never the test
backend), unmodified since export, in schema v2 with neutral path roots, and
free of any home directory, user directory, or temporary path.
"""

from __future__ import annotations

import re

import pytest

from agent_in_a_box.experiments import bundle as bundles
from agent_in_a_box.policy import schema

SHIPPED = sorted((schema.REPO_ROOT / "bundles").glob("*.json"))
HOST_PATHS = re.compile(r"/home/|/Users/|/root/|/private/var/folders/|/tmp/|/var/folders/")


@pytest.mark.parametrize("path", SHIPPED, ids=[path.name for path in SHIPPED])
def test_shipped_bundle(path):
    document = bundles.load(path, as_native=True)
    assert document["bundle_schema"] == bundles.SCHEMA
    assert "none" not in document["enforcement"]
    text = path.read_text()
    assert HOST_PATHS.search(text) is None, HOST_PATHS.search(text)


def test_bundles_directory_holds_only_bundles():
    for path in (schema.REPO_ROOT / "bundles").iterdir():
        assert path.suffix == ".json" or path.name == ".keep", path
