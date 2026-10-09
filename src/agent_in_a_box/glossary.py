"""Claim words. Learner-facing labels use these terms verbatim (CURRICULUM.md).

Each term names the component that makes the claim. A label that is not in
TERMS must not appear as a result label in the CLI, website, or notebooks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    term: str
    means: str
    claimed_by: str
    evidence: str


TERMS: dict[str, Term] = {
    t.term: t
    for t in (
        Term(
            "allowed",
            "Cedar's decision on one constructed request",
            "Cedar authorizer",
            "Decision record with determining policy IDs and diagnostics",
        ),
        Term(
            "denied",
            "Cedar's decision on one constructed request",
            "Cedar authorizer",
            "Decision record with determining policy IDs and diagnostics",
        ),
        Term(
            "refused",
            "The proxy or bridge declined to forward after its checks, which include a "
            "Cedar deny and destination checks",
            "Proxy / model bridge",
            "Proxy decision record naming the check that refused",
        ),
        Term(
            "blocked",
            "The kernel profile stopped an operation",
            "Seatbelt",
            "Probe exit status, absence of any proxy event, and the matching profile rule",
        ),
        Term(
            "granted",
            "A path the installed profile lets the process tree read or write, derived "
            "from policy before launch",
            "Policy compiler + launcher",
            "Grant plan and installed profile hash",
        ),
        Term(
            "enforced",
            "What actually constrained the run: the installed profile plus the proxy's checks",
            "Supervisor",
            "Profile hash, proxy decision records, process accounting",
        ),
        Term(
            "checked against the schema",
            "The policy parsed and type-checked",
            "Cedar validator",
            "Validation output. Says nothing about safety",
        ),
        Term(
            "proved for domain D",
            "The solver returned UNSAT for a stated property over a stated domain and encoding",
            "Analyzer",
            "Property, domain inventory, solver status, tool manifest. Says nothing about "
            "the runtime integration",
        ),
        Term(
            "distinguishing input",
            "A solver witness that one policy set allows and the other denies",
            "Analyzer",
            "Raw witness",
        ),
        Term(
            "confirmed by replay",
            "The witness was evaluated concretely under both policy sets and still "
            "distinguishes them",
            "Evaluator",
            "Two decision records",
        ),
        Term(
            "no conclusion",
            "UNKNOWN, timeout, unsupported feature, or replay disagreement",
            "Analyzer",
            "Status and artifacts. Never aggregated into success",
        ),
        Term(
            "recorded",
            "Evidence imported from a bundle rather than produced in this session",
            "Bundle",
            "Bundle identity, mode, platform, hashes",
        ),
        Term(
            "contained",
            "The process tree is running under the installed kernel profile. Used only "
            "for the OS boundary",
            "Launcher",
            "Containment confirmation before workload admission",
        ),
        Term(
            "no permission expansion",
            "The proof property: every request the new policy allows, the old policy "
            "allowed. Never called \"containment\"",
            "Analyzer",
            "UNSAT for Domain(x) ∧ Allow(new, x) ∧ ¬Allow(old, x)",
        ),
        Term(
            "intended task preserved",
            "A named operation the task needs is still allowed under the repaired policy",
            "Evaluator",
            "A concrete positive decision",
        ),
    )
}

# Never used as learner-facing success labels.
FORBIDDEN_LABELS = ("secure", "safe", "verified agent", "sandboxed")


def label(term: str) -> str:
    """Return `term` if it is a glossary term; raise otherwise."""
    if term not in TERMS:
        raise KeyError(f"not a glossary term: {term!r}")
    return term
