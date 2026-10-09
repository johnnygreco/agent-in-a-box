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
    # 01 Follow a request (draft, recorded mode)

    Starts where chapter 1 ends. Pick an HTTP attempt from a recorded run.
    See what the agent proposed, the request the runtime built from it,
    Cedar's decision, and what the agent observed. Then edit a copy of the
    request and compare decisions.

    This notebook runs with your own permissions on this machine; it is
    not sandboxed agent code. In recorded mode it starts no workload,
    proxy, or solver.
    """)
    return


@app.cell
def _(mo):
    import os
    from pathlib import Path

    from agent_in_a_box.experiments import bundle as bundles
    from agent_in_a_box.experiments import records
    from agent_in_a_box.policy.evaluator import CedarpyEvaluator

    def newest_bundle() -> str:
        if os.environ.get("AGENT_IN_A_BOX_BUNDLE"):
            return os.environ["AGENT_IN_A_BOX_BUNDLE"]
        found = sorted(Path(".agent-in-a-box/bundles").glob("*.json"),
                       key=lambda p: p.stat().st_mtime)
        return str(found[-1]) if found else ""

    path = mo.ui.text(value=newest_bundle(), label="Bundle file", full_width=True)
    path
    return CedarpyEvaluator, bundles, path, records


@app.cell
def _(bundles, mo, path):
    mo.stop(not path.value, mo.md("No bundle yet. Make one with "
                                  "`agent-in-a-box trailer --test-backend`."))
    document = bundles.load(path.value)
    mo.md(f"**{document['title']}**. Shown as **{document['viewed_as']}**; enforcement: "
          f"**{', '.join(document['enforcement'])}**; bundle `{document['bundle_id'][:12]}`.")
    return (document,)


@app.cell
def _(document, mo, records):
    attempts = records.http_attempts(document)
    labels = {f"{a['command_id']}: {a['decision']['method']} {a['decision']['path']} "
              f"under {a['policy']} ({a['decision']['label']})": i
              for i, a in enumerate(attempts)}
    choice = mo.ui.dropdown(options=labels, value=next(iter(labels)), label="HTTP attempt")
    choice
    return attempts, choice


@app.cell
def _(attempts, choice, mo, records):
    attempt = attempts[choice.value]
    decision = attempt["decision"]
    cedar = next((c["decision"] for c in reversed(decision["checks"]) if c["decision"]), None)
    checks = ", ".join(f"{c['name']} {'passed' if c['passed'] else 'refused'}"
                       for c in decision["checks"])
    mo.vstack([
        mo.md(f"**Agent proposal** (agent-reported): `{attempt['proposal']}`"),
        mo.md("**The request the runtime built**, with who supplied each fact:"),
        mo.ui.table(records.provenance_rows(cedar), selection=None) if cedar else
        mo.md("Refused before Cedar was asked."),
        mo.md(f"**Proxy checks**: {checks}. Outcome: **{decision['label']}**."),
        mo.md(f"**Determining policies**: {cedar['determining'] if cedar else 'none'}"),
        mo.md(f"**Agent observation** (agent-reported): {attempt['observation']['detail']}"),
    ])
    return (cedar,)


@app.cell
def _(cedar, mo):
    mo.stop(cedar is None or cedar["request"]["action"]["id"] != "HttpRequest")
    edit = mo.ui.form(mo.ui.dictionary({
        "method": mo.ui.text(value=cedar["request"]["context"]["method"], label="method"),
        "path": mo.ui.text(value=cedar["request"]["context"]["path"], label="path"),
    }), label="Edit a copy of the request context, then submit")
    edit
    return (edit,)


@app.cell
def _(CedarpyEvaluator, cedar, document, edit, mo, records):
    mo.stop(edit.value is None, mo.md("Submit the form to evaluate the edited copy."))
    recorded_policy = records.policy(document, cedar["policy_hash"])
    edited = records.hypothetical(CedarpyEvaluator(), recorded_policy, cedar, dict(edit.value))
    mo.md(f"**hypothetical**: {edited.decision} (determining: {list(edited.determining)}). "
          f"Recorded: {cedar['decision']}. An edited request is not evidence that an agent can "
          "make the runtime send it: the proxy builds these facts itself.")
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Extension.** Write a function that takes a decision record and flags any
    request field whose `supplied by` entry names the agent. Run it over
    every attempt in the bundle. What does it find, and why?
    """)
    return


if __name__ == "__main__":
    app.run()
