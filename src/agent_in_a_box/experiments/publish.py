"""The published website's data (PLAN.md, Product shape: Publishing rules).

The public site may show only two kinds of evidence:

  1. Analysis results produced here, at build time, by the pinned toolchain:
     solver outcomes, witnesses and their replays, task checks, and the
     bounded method x path matrix. No agent runs and nothing is confined,
     so every such result is labeled "analysis only".
  2. Native recordings: bundles in bundles/ produced under a native backend.
     A bundle whose enforcement includes "none" (the test backend) is refused,
     and the whole build stops.

A run panel with no native recording becomes a placeholder that says so.
A test-backend run is never substituted.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_in_a_box.contracts import CedarEvaluator, plain
from agent_in_a_box.experiments import bundle as bundles
from agent_in_a_box.experiments import records, views
from agent_in_a_box.experiments.steps import CHAPTER5, TRAILER, Chapter5, Trailer, steps_by_name
from agent_in_a_box.policy import analyzer, requests, schema, toolchain

PLACEHOLDER = ("No native recording yet. This run arrives with Milestone 1-L (Linux) or "
               "Milestone 1 (macOS).")
ANALYSIS_ONLY = "analysis only"
NATIVE_BUNDLES = schema.REPO_ROOT / "bundles"
TASK_REQUEST = requests.http_request("reference.fixture", 80, "GET", "/reference")


class PublishRefused(Exception):
    """Something the public site may not show was offered to it."""


def native_recordings(directory: Path = NATIVE_BUNDLES) -> list[dict]:
    """Every bundle in `directory`, each verified and accepted only as a native recording."""
    documents = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            documents.append(bundles.load(path, as_native=True))
        except bundles.BundleError as error:
            raise PublishRefused(f"{path.name}: {error}") from error
    return documents


def toolchain_versions() -> dict[str, str]:
    manifest = toolchain.manifest()
    solver = manifest["cvc5"].removeprefix("This is ").split(" [")[0].replace(" version", "")
    return {"cedar_policy": manifest["cedar_policy"], "symcc": manifest["cedar_policy_symcc"],
            "solver": solver, "cedarpy": manifest["cedarpy"]}


def provenance(enforcement: str, versions: dict[str, str]) -> dict[str, str]:
    return {"mode": "recorded", "enforcement": enforcement, **versions}


def analysis(old: str, new: str, evaluator: CedarEvaluator, versions: dict[str, str],
             solver: str = "default") -> dict[str, Any]:
    """One no-permission-expansion check, run now, in the shape the views read."""
    solver_args = {"default": analyzer.DEFAULT_SOLVER_ARGS,
                   "starved": analyzer.STARVED_SOLVER_ARGS}[solver]
    result = analyzer.check("no-permission-expansion", schema.load_variant(old),
                            schema.load_variant(new), evaluator, solver_args=solver_args)
    step = {"payload": {"old": old, "new": new},
            "result": {"analysis": {**plain(result),
                                    "replay": [record.to_json() for record in result.replay]}}}
    names = {schema.load_variant(name).policy_hash: name for name in (old, new)}
    return {**views.analysis_view(step, names),
            "provenance": provenance(ANALYSIS_ONLY, versions)}


def task_check(policy: str, evaluator: CedarEvaluator) -> str:
    _, label = analyzer.task_preserved(evaluator, schema.load_variant(policy), TASK_REQUEST)
    return label


def recorded_run(native: list[dict], experiment: str, step: str) -> dict[str, Any]:
    """The run from a native recording, or a placeholder that says there is none."""
    for document in native:
        found = steps_by_name(document, experiment)
        if step in found:
            run = views.run_view(found[step])
            versions = views.toolchain_versions(document)
            return {**run, "provenance": provenance(run["enforcement"], versions)}
    return {"placeholder": PLACEHOLDER}


def site_label(title: str, native: list[dict], versions: dict[str, str]) -> dict[str, Any]:
    enforcement = sorted({value for document in native for value in document["enforcement"]})
    return {
        "title": title, "published": True, "viewed_as": "recorded", "test_backend": False,
        "enforcement": enforcement or [ANALYSIS_ONLY],
        "native_bundles": [document["bundle_id"] for document in native],
        "built": time.strftime("%Y-%m-%d", time.gmtime()),
        "toolchain": versions,
    }


def chapter0(evaluator: CedarEvaluator, native: list[dict]) -> dict[str, Any]:
    versions = toolchain_versions()
    return {
        "label": site_label("Chapter 0", native, versions),
        "policies": {name: schema.load_variant(name).policy_text for name in ("P0", "P1")},
        "examples": {name: evaluator.evaluate(schema.load_variant(name), TASK_REQUEST).decision
                     for name in ("P0", "P1")},
        "run_p0": recorded_run(native, TRAILER, Trailer.RUN_P0),
        "run_p1": recorded_run(native, TRAILER, Trailer.RUN_P1),
        "verify": analysis("P0", "P1", evaluator, versions),
        "inspect": {"P0": recorded_run(native, TRAILER, Trailer.INSPECT_P0),
                    "P1": recorded_run(native, TRAILER, Trailer.INSPECT_P1)},
        "repair": analysis("P1", "P0", evaluator, versions),
        "task": task_check("P0", evaluator),
    }


def chapter5(evaluator: CedarEvaluator, native: list[dict]) -> dict[str, Any]:
    versions = toolchain_versions()
    variants = [schema.load_variant(name) for name in ("P0", "P1", "P2")]
    return {
        "label": site_label("Chapter 5", native, versions),
        "policies": {variant.name: variant.policy_text for variant in variants},
        "grid": records.matrix(evaluator, variants, ["GET", "POST", "PUT"],
                               ["/reference", "/missing"]),
        "grid_provenance": provenance(ANALYSIS_ONLY, versions),
        "p1": analysis("P0", "P1", evaluator, versions),
        "p2": analysis("P0", "P2", evaluator, versions),
        "p2_runs": {"P0": recorded_run(native, CHAPTER5, Chapter5.P2_WITNESS_UNDER_P0),
                    "P2": recorded_run(native, CHAPTER5, Chapter5.P2_WITNESS_UNDER_P2)},
        "repair": analysis("P1", "P0", evaluator, versions),
        "task_p0": task_check("P0", evaluator),
        "deny_all": analysis("P1", "P3", evaluator, versions),
        "task_p3": task_check("P3", evaluator),
        "starved": analysis("P0", "P1", evaluator, versions, solver="starved"),
    }
