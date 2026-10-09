"""Learner-facing labels are CURRICULUM.md glossary terms, verbatim (invariant 5)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agent_in_a_box import glossary

REPO = Path(__file__).resolve().parents[1]


def curriculum_terms() -> set[str]:
    text = (REPO / "CURRICULUM.md").read_text()
    table = text.split("## Glossary of claim words", 1)[1].split("\n## ", 1)[0]
    terms = set()
    for row in re.findall(r"^\| ([^|]+) \|", table, re.MULTILINE)[2:]:
        terms |= {t.strip() for t in row.split("/")}
    return terms


def test_glossary_matches_curriculum_verbatim():
    assert set(glossary.TERMS) == curriculum_terms()


def test_label_refuses_non_terms():
    with pytest.raises(KeyError):
        glossary.label("secure")


def test_forbidden_success_labels_are_not_string_literals_in_source():
    found = []
    for path in (REPO / "src").rglob("*.py"):
        if path.name == "glossary.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and node.value in glossary.FORBIDDEN_LABELS:
                found.append((str(path), node.value))
    assert found == []
