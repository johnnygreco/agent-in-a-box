"""The website builds, and the published build shows only publishable evidence.

Published mode (decisions/0011): analysis results produced at build time and
native recordings from bundles/. A test-backend bundle is refused. A run
with no native recording is a placeholder. Every link carries the base path.

Skipped when Node or website/node_modules is missing (run `npm ci` in website/).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WEBSITE = Path(__file__).resolve().parents[2] / "website"
CLI = [sys.executable, "-m", "agent_in_a_box.experiments.cli"]
BASE = "/agent-in-a-box/"
PLACEHOLDER = "No native recording yet."
pytestmark = [
    pytest.mark.toolchain,
    pytest.mark.skipif(shutil.which("npm") is None or not (WEBSITE / "node_modules").exists(),
                       reason="Node or website/node_modules missing; run npm ci in website/"),
]


def build(out: Path) -> Path:
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(out)], cwd=WEBSITE, check=True,
                   capture_output=True, timeout=300)
    return out


def text(path: Path) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", path.read_text(), flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


@pytest.fixture(scope="module")
def test_backend_bundles(tmp_path_factory):
    state = tmp_path_factory.mktemp("state")
    for experiment in ("trailer", "chapter5"):
        subprocess.run([*CLI, "--state-dir", str(state), experiment, "--test-backend",
                        "--session", "web"], check=True, capture_output=True, timeout=300)
    return state / "bundles"


@pytest.fixture(scope="module")
def published_site(tmp_path_factory):
    empty = tmp_path_factory.mktemp("no-bundles")
    subprocess.run([*CLI, "site-data", "--published", "--bundles", str(empty)], check=True,
                   capture_output=True, timeout=300)
    return build(tmp_path_factory.mktemp("dist"))


def test_published_mode_refuses_a_test_backend_bundle(test_backend_bundles, tmp_path):
    offered = tmp_path / "bundles"
    offered.mkdir()
    shutil.copy(next(test_backend_bundles.glob("chapter-0-*.json")), offered)
    result = subprocess.run([*CLI, "site-data", "--published", "--bundles", str(offered),
                             "--out", str(tmp_path / "data")],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 1
    assert "Refused to publish" in result.stderr and "enforcement: none" in result.stderr
    assert not (tmp_path / "data" / "chapter0.json").exists()


def test_published_build_shows_analysis_and_placeholders(published_site):
    zero = text(published_site / "chapters/0/index.html")
    five = text(published_site / "chapters/5/index.html")
    for page in (zero, five):
        assert "recorded evidence" in page and "analysis only" in page
        assert "Cedar 4.12.0" in page and "cvc5 1.3.1" in page
        assert PLACEHOLDER in page
        assert "enforcement: none" not in page
    assert zero.count(PLACEHOLDER) == 4 and five.count(PLACEHOLDER) == 2
    assert "Witness: POST /reference" in zero and "confirmed by replay" in zero
    assert "Witness: PUT /reference" in five and "no conclusion" in five
    assert "intended task preserved" in five and "This is testing" in five


def test_published_pages_claim_no_containment_or_enforcement(published_site):
    """Until a native bundle is published, no page may say anything was contained or enforced.
    The glossary is excluded: it defines these words rather than claiming them."""
    for page in published_site.rglob("*.html"):
        if page.parent.name == "glossary":
            continue
        words = re.findall(r"\b(contained|containment|enforced|sandboxed)\b", text(page), re.I)
        assert words == [], page


def test_every_internal_link_carries_the_base_path(published_site):
    offenders = []
    for page in published_site.rglob("*.html"):
        for link in re.findall(r'(?:href|src)="(/[^"]*)"', page.read_text()):
            if not link.startswith(BASE):
                offenders.append((page.relative_to(published_site), link))
    assert offenders == []
    assert (published_site / "banner.svg").exists()


def test_development_build_from_test_backend_bundles(test_backend_bundles, tmp_path_factory):
    trailer = next(test_backend_bundles.glob("chapter-0-*.json"))
    chapter5 = next(test_backend_bundles.glob("chapter-5-*.json"))
    subprocess.run([*CLI, "site-data", "--trailer", str(trailer), "--chapter5", str(chapter5)],
                   check=True, timeout=120)
    try:
        site = build(tmp_path_factory.mktemp("dev-dist"))
        zero = text(site / "chapters/0/index.html")
        assert "Development build from test-backend bundles" in zero
        assert "enforcement: none" in zero and PLACEHOLDER not in zero
    finally:  # leave publishable data behind, never development data
        subprocess.run([*CLI, "site-data", "--published"], check=True, capture_output=True,
                       timeout=300)
