"""Replace host-specific paths in a bundle with neutral roots (decisions/0013).

A bundle is meant to be shared and published. The paths a run records (its
run directory, the checkout, the Python installation, the toolchain) name
the machine it ran on: often the user's home directory and user name. Before
a bundle is written, every such path is rewritten to a fixed neutral root.
Run ids, hashes, and provenance are left exactly as recorded; a hash still
refers to the original artifact, whose host paths it was computed over.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOTS = {
    "/agent-in-a-box/runs/<run id>": "the run's own directory",
    "/agent-in-a-box/toolchain": "the pinned toolchain directory",
    "/agent-in-a-box/python": "the Python installation the runtime used",
    "/agent-in-a-box/checkout": "the repository checkout (virtual environment and code)",
    "/agent-in-a-box/home": "the home directory of the user who ran it",
}


def spellings(path: str | Path) -> set[str]:
    """A path as given and as resolved (macOS's /tmp is /private/tmp, for example)."""
    return {str(path), os.path.realpath(path)}


def host_roots(run_dirs: dict[str, str], checkout: Path, toolchain: Path) -> list[tuple[str, str]]:
    """(host prefix, neutral root) pairs, most specific first."""
    pairs = []
    for run_id, run_dir in run_dirs.items():
        pairs += [(spelling, f"/agent-in-a-box/runs/{run_id}") for spelling in spellings(run_dir)]
    pairs += [(spelling, "/agent-in-a-box/toolchain") for spelling in spellings(toolchain)]
    pairs += [(spelling, "/agent-in-a-box/python") for spelling in spellings(sys.base_prefix)]
    pairs += [(spelling, "/agent-in-a-box/checkout") for spelling in spellings(checkout)]
    pairs += [(spelling, "/agent-in-a-box/home") for spelling in spellings(Path.home())]
    meaningful = [(host, neutral) for host, neutral in pairs if host not in ("", "/")]
    return sorted(set(meaningful), key=lambda pair: len(pair[0]), reverse=True)


def rewrite(value: Any, roots: Iterable[tuple[str, str]]) -> Any:
    """`value` with every host prefix replaced, in every string, at any depth."""
    roots = list(roots)
    if isinstance(value, dict):
        return {key: rewrite(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite(item, roots) for item in value]
    if not isinstance(value, str):
        return value
    for host, neutral in roots:
        # Only whole path components: /home/ann must not match /home/anna.
        value = re.sub(re.escape(host) + r"(?=/|$|[^\w.\-])", neutral, value)
    return value
