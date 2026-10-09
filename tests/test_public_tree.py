"""The public tree names no third-party project as a source of inspiration or reference.

Owner rule, 2026-10-09 (PLAN.md, Keeping records). Such material lives only
in the git-ignored inspiration/ folder. This test greps every file git would
publish (tracked, or untracked and not ignored) and fails on any hit. It
excludes exactly one file: itself, because it has to spell the pattern.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve().relative_to(REPO).as_posix()
PATTERN = re.compile(
    r"openshell|vishwa|strands|dogwood|twotimespi|huggingface|\btau\b|mini-coding-agent"
    r"|rasbt|256d49eb|83075dfd|\bthe fork\b|fork's",
    re.IGNORECASE,
)


def publishable_files() -> list[str]:
    """Every file git would publish: tracked, or untracked and not ignored."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO, capture_output=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout; the gate runs where git can list publishable files")
    return [name for name in listing.decode().split("\0") if name]


def test_no_file_names_a_third_party_source():
    hits = []
    for name in publishable_files():
        if name == THIS_FILE or name.startswith("inspiration/"):
            continue
        path = REPO / name
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                hits.append(f"{name}:{number}: {line.strip()[:120]}")
    assert hits == [], "\n".join(hits)


def test_inspiration_folder_is_ignored():
    gitignore = (REPO / ".gitignore").read_text().splitlines()
    assert "inspiration/" in gitignore
