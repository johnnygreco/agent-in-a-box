"""Chapter 5's experiment, driven through the gateway API: the testing-to-proof ladder.

    P0 -> P1 (POST); P0 -> P2 (a method other than GET or POST, then run under
    both policies); repair P1 -> P0 with the task check; deny-all P1 -> P3
    with the task check; and one deliberate "no conclusion".

Command IDs derive from the session name, so a rerun retrieves stored results.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_in_a_box.client import GatewayClient
from agent_in_a_box.experiments.steps import (
    CHAPTER5, Chapter5, Session, decision_label, receipt_count, witness_context, witness_probe,
)

Say = Callable[[str], None]


def expansion_check(steps: Session, say: Say, step: str, old: str, new: str,
                    solver: str = "default") -> dict:
    """Submit one no-permission-expansion check, report it, and return the analysis."""
    payload = {"old": old, "new": new, "solver": solver}
    result = steps.submit(step, "analyze", payload)["analysis"]
    witness = witness_context(result)
    line = (f"No permission expansion {old} -> {new}: {result['status'].upper()}; "
            f"{' and '.join(result['labels'])}")
    if witness:
        line += f": {witness['method']} {witness['path']}"
    say(line)
    return result


def run_chapter5(client: GatewayClient, session: str, say: Say = print) -> dict:
    steps = Session(client, session, CHAPTER5)
    say("Chapter 5: The examples still pass. Did the agent gain permission?")
    p1 = expansion_check(steps, say, Chapter5.P0_TO_P1, "P0", "P1")
    p2 = expansion_check(steps, say, Chapter5.P0_TO_P2, "P0", "P2")

    probe = witness_probe(p2)
    method = witness_context(p2)["method"]
    under_p0 = steps.submit(Chapter5.P2_WITNESS_UNDER_P0, "run", {"policy": "P0", "probe": probe})
    under_p2 = steps.submit(Chapter5.P2_WITNESS_UNDER_P2, "run", {"policy": "P2", "probe": probe})
    for policy, run in (("P0", under_p0["run"]), ("P2", under_p2["run"])):
        say(f"{method} /reference under {policy}: {decision_label(run, method, '/reference')}; "
            f"fixture received {receipt_count(run)} request(s)")

    repair = expansion_check(steps, say, Chapter5.REPAIR, "P1", "P0")
    task_p0 = steps.submit(Chapter5.TASK_P0, "task_check", {"policy": "P0"})
    say(f"Task check under P0: {task_p0['label']}")
    deny_all = expansion_check(steps, say, Chapter5.DENY_ALL, "P1", "P3")
    task_p3 = steps.submit(Chapter5.TASK_P3, "task_check", {"policy": "P3"})
    say(f"Task check under P3 (deny-all): {task_p3['label']}")
    starved = expansion_check(steps, say, Chapter5.STARVED, "P0", "P1", solver="starved")

    exported = steps.export(Chapter5.EXPORT, "Chapter 5 examples and proofs")
    say(f"Export: bundle {exported['bundle_id'][:12]} at {exported['path']}")

    run_p0 = under_p0["run"]
    run_p2 = under_p2["run"]
    observed = {
        "p1_witness_is_post": p1["status"] == "sat" and witness_context(p1)["method"] == "POST",
        "p2_witness_is_neither_get_nor_post": p2["status"] == "sat"
        and method not in ("GET", "POST"),
        "p2_witness_confirmed_by_replay": "confirmed by replay" in p2["labels"],
        "p2_witness_refused_under_p0": decision_label(run_p0, method, "/reference") == "refused"
        and receipt_count(run_p0) == 0,
        "p2_witness_allowed_under_p2": decision_label(run_p2, method, "/reference") == "allowed"
        and receipt_count(run_p2) == 1,
        "repair_proved": "no permission expansion" in repair["labels"],
        "repair_task_preserved": task_p0["label"] == "intended task preserved",
        "deny_all_passes_expansion": "no permission expansion" in deny_all["labels"],
        "deny_all_fails_task": task_p3["label"] != "intended task preserved",
        "starved_is_no_conclusion": starved["labels"] == ["no conclusion"],
    }
    return {"observed": observed, "as_expected": all(observed.values()), "bundle": exported}
