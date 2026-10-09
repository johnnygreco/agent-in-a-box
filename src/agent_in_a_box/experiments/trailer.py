"""The chapter 0 trailer, driven entirely through the gateway API.

    Predict -> Run -> Intervene -> Verify -> Inspect -> Repair -> Export

Each effect is a command whose ID is derived from the session name, so
running the trailer again with the same session retrieves stored results and
starts nothing. Labels are glossary terms (CURRICULUM.md).
"""

from __future__ import annotations

from collections.abc import Callable

from agent_in_a_box.client import GatewayClient
from agent_in_a_box.experiments.steps import (
    TRAILER, Session, Trailer, decision_label, http_summary, receipt_count, witness_context,
    witness_probe,
)


def run_trailer(client: GatewayClient, session: str, say: Callable[[str], None] = print) -> dict:
    steps = Session(client, session, TRAILER)
    say("Chapter 0 trailer: The examples pass. Did the agent gain permission?")

    say("Predict: will the agent's GET succeed? (yes / no / depends on the policy)")
    p0 = steps.submit(Trailer.RUN_P0, "run", {"policy": "P0"})["run"]
    say(f"Run under P0 [enforcement: {p0['enforcement']}]: {http_summary(p0)}")

    say("Intervene: P1 broadens get-reference from GET to GET or POST.")
    p1 = steps.submit(Trailer.RUN_P1, "run", {"policy": "P1"})["run"]
    say(f"Rerun under P1 [enforcement: {p1['enforcement']}]: {http_summary(p1)}")

    say("Predict: did permission expand? (no, the tests pass / yes / cannot tell from tests)")
    verify = steps.submit(Trailer.VERIFY, "analyze", {"old": "P0", "new": "P1"})["analysis"]
    witness = witness_context(verify)
    say(f"Verify (no permission expansion, P0 -> P1, {verify['domain']['name']}): "
        f"{verify['status'].upper()}; {' and '.join(verify['labels'])}: "
        f"{witness.get('method')} {witness.get('path')}")

    probe = witness_probe(verify)
    inspect_p0 = steps.submit(Trailer.INSPECT_P0, "run", {"policy": "P0", "probe": probe})["run"]
    inspect_p1 = steps.submit(Trailer.INSPECT_P1, "run", {"policy": "P1", "probe": probe})["run"]
    for policy, run in (("P0", inspect_p0), ("P1", inspect_p1)):
        say(f"Inspect under {policy}: {http_summary(run)}; fixture received "
            f"{receipt_count(run)} request(s)")

    say("Repair: restore P0.")
    repair = steps.submit(Trailer.REPAIR, "analyze", {"old": "P1", "new": "P0"})["analysis"]
    say(f"Repair check (P1 -> P0): {repair['status'].upper()}; {' and '.join(repair['labels'])}")
    task = steps.submit(Trailer.TASK, "task_check", {"policy": "P0"})
    say(f"Task check under P0, {task['operation']}: {task['label']}")

    exported = steps.export(Trailer.EXPORT, "Chapter 0 trailer")
    say(f"Export: bundle {exported['bundle_id'][:12]} at {exported['path']}")

    method = witness.get("method")
    path = witness.get("path")
    observed = {
        "get_allowed_under_p0": decision_label(p0, "GET", "/reference") == "allowed",
        "get_still_allowed_under_p1": decision_label(p1, "GET", "/reference") == "allowed",
        "solver_returned_post": verify["status"] == "sat" and method == "POST",
        "witness_confirmed_by_replay": "confirmed by replay" in verify["labels"],
        "witness_refused_under_p0": decision_label(inspect_p0, method, path) == "refused"
        and receipt_count(inspect_p0) == 0,
        "witness_allowed_under_p1": decision_label(inspect_p1, method, path) == "allowed"
        and receipt_count(inspect_p1) == 1,
        "repair_no_permission_expansion": "no permission expansion" in repair["labels"],
        "intended_task_preserved": task["label"] == "intended task preserved",
    }
    return {"observed": observed, "as_expected": all(observed.values()), "bundle": exported,
            "enforcement": sorted({p0["enforcement"], p1["enforcement"]})}
