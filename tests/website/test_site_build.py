"""The website scaffold builds chapters 0 and 5 from test-backend bundles (development only).

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
pytestmark = [
    pytest.mark.toolchain,
    pytest.mark.skipif(shutil.which("npm") is None or not (WEBSITE / "node_modules").exists(),
                       reason="Node or website/node_modules missing; run npm ci in website/"),
]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    state = tmp_path_factory.mktemp("state")
    for experiment in ("trailer", "chapter5"):
        subprocess.run([*CLI, "--state-dir", str(state), experiment, "--test-backend",
                        "--session", "web"], check=True, capture_output=True, timeout=300)
    trailer = next((state / "bundles").glob("chapter-0-*.json"))
    chapter5 = next((state / "bundles").glob("chapter-5-*.json"))
    subprocess.run([*CLI, "--state-dir", str(state), "site-data", "--test-backend", "--trailer",
                    str(trailer), "--chapter5", str(chapter5)], check=True, timeout=120)
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(out)], cwd=WEBSITE, check=True,
                   capture_output=True, timeout=300)
    return out


def text(path: Path) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", path.read_text(), flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def test_chapters_render_with_evidence_labels(site):
    zero, five = text(site / "chapters/0/index.html"), text(site / "chapters/5/index.html")
    for page in (zero, five):
        assert "Recorded evidence" in page and "Enforcement: none" in page
        assert "nothing was contained" in page
    assert "distinguishing input" in zero and "confirmed by replay" in zero
    assert "intended task preserved" in zero
    assert "PUT /reference" in five and "no conclusion" in five
    assert "This is testing" in five


def test_containment_is_not_used_for_the_proof_property(site):
    for page in ("chapters/0/index.html", "chapters/5/index.html"):
        assert "containment" not in text(site / page).lower()
