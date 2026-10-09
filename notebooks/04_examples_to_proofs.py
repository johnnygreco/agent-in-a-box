import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    # 04 Examples to proofs (draft, recorded mode)

    Starts where chapter 5's first ladder ends: P0 was broadened to P1 and
    the unchanged GET examples still pass. Fill a bounded grid, read the
    recorded solver result, and replay its raw witness under both policies
    yourself. Then change the grid's inputs and the policies.

    Recorded mode loads a bundle and evaluates requests concretely. It
    starts no workload or solver, and claims no fresh proof. The live
    button at the end needs a running gateway and is off by default.
    """)
    return


@app.cell
def _(mo):
    import json
    import os
    from pathlib import Path

    from agent_in_a_box.experiments import bundle as bundles
    from agent_in_a_box.experiments import records
    from agent_in_a_box.policy.evaluator import CedarpyEvaluator

    evaluator = CedarpyEvaluator()

    def newest_bundle() -> str:
        if os.environ.get("AGENT_IN_A_BOX_BUNDLE"):
            return os.environ["AGENT_IN_A_BOX_BUNDLE"]
        found = sorted(Path(".agent-in-a-box/bundles").glob("*.json"),
                       key=lambda p: p.stat().st_mtime)
        return str(found[-1]) if found else ""

    path = mo.ui.text(value=newest_bundle(), label="Bundle file", full_width=True)
    path
    return Path, bundles, evaluator, json, path, records


@app.cell
def _(bundles, mo, path, records):
    mo.stop(not path.value, mo.md("No bundle yet. Make one with "
                                  "`agent-in-a-box trailer --test-backend`."))
    document = bundles.load(path.value)
    p0, p1 = records.policy_named(document, "P0"), records.policy_named(document, "P1")
    mo.md(f"**{document['title']}**: shown as **{document['viewed_as']}**; enforcement: "
          f"**{', '.join(document['enforcement'])}**.")
    return document, p0, p1


@app.cell
def _(mo):
    methods = mo.ui.text(value="GET, POST", label="methods in the grid")
    paths = mo.ui.text(value="/reference, /missing", label="paths in the grid")
    mo.hstack([methods, paths])
    return methods, paths


@app.cell
def _(evaluator, methods, mo, p0, p1, paths, records):
    def split(text):
        return [part.strip() for part in text.split(",") if part.strip()]

    grid = records.matrix(evaluator, [p0, p1], split(methods.value), split(paths.value))
    mo.vstack([mo.md("**Bounded grid: this is testing.** Which inputs are not in it?"),
               mo.ui.table(grid, selection=None)])
    return


@app.cell
def _(document, json, mo):
    analyses = [s for s in document["steps"] if s["kind"] == "analyze"]
    verify = next(s["result"]["analysis"] for s in analyses
                  if (s["payload"]["old"], s["payload"]["new"]) == ("P0", "P1"))
    mo.vstack([
        mo.md(f"**Recorded solver result**, no permission expansion P0 → P1 over "
              f"`{verify['domain']['name']}`: {verify['status'].upper()}; labels: "
              f"{', '.join(verify['labels'])}."),
        mo.md(f"Domain: {verify['domain']['description']} Condition: "
              f"`{verify['domain']['condition']}`"),
        mo.md("Raw witness (the solver's own choice, including values no policy reads):"),
        mo.md(f"```json\n{json.dumps(verify['witness']['request'], indent=1)}\n```"),
    ])
    return (verify,)


@app.cell
def _(evaluator, mo, p0, p1, records, verify):
    witness = records.request_from({"request": {**verify["witness"]["request"],
                                                "entities": verify["witness"]["entities"],
                                                "provenance": {"*": "solver witness"}}})
    now = {b.name: evaluator.evaluate(b, witness).decision for b in (p0, p1)}
    confirmed = now == {"P0": "denied", "P1": "allowed"}
    mo.md(f"Replayed now, concretely: P0 {now['P0']}, P1 {now['P1']}. "
          + ("**confirmed by replay**." if confirmed else "**no conclusion**: replay disagrees."))
    return


@app.cell
def _(Path, mo):
    state = Path(".agent-in-a-box/gateway.json")
    live = mo.ui.run_button(label="Run the solver again through the gateway",
                            disabled=not state.exists())
    mo.vstack([live, mo.md("Live mode needs `agent-in-a-box gateway serve`.")
               if not state.exists() else mo.md("Each click is a new command.")])
    return live, state


@app.cell
def _(live, mo, state):
    mo.stop(not live.value)
    from agent_in_a_box.client import GatewayClient

    fresh = GatewayClient.from_state(state).run("analyze", {"old": "P0", "new": "P1"})
    mo.md(f"Fresh result (live): {fresh.status}; {fresh.result['analysis']['labels']}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Extension.** Put P2 in the grid and predict the solver's answer before
    you look. Then write a property of your own (for example, that no
    policy set you write allows DELETE) and state its domain in one
    sentence. What does its result say about file writes?
    """)
    return


if __name__ == "__main__":
    app.run()
