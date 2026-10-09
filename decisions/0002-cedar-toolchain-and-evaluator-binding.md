# 0002. Cedar toolchain and evaluator binding: cedarpy in process, a small bridge for SymCC, one Cedar version

Date: 2026-10-09
Status: accepted

## Context

Milestone 0 must pin Cedar, SymCC, and a solver, and choose how Python code reaches the concrete evaluator. PLAN.md's defaults were the newest `cedar-policy` that `cedar-policy-symcc` supports, evaluated through the official `cedar-policy-cli` with JSON output behind a thin adapter, with a small native bridge only if the CLI cannot give stable machine-readable diagnostics and witnesses. The owner then asked that the Python binding `cedarpy` be evaluated as the evaluator binding first, mainly because the proxy evaluates every request and an in-process call is far cheaper than spawning a process. The formal-methods review (F5) asks for one compatible dependency graph for evaluation and analysis, or explicitly separated version-specific conclusions, and warns against choosing by version numbers alone.

Facts established on 2026-10-09, each checked from source or by running it:

- `cedar-policy-symcc` 0.7.0 pins `cedar-policy =4.13.0`, the newest release. `cedar-policy-symcc` 0.6.0 pins `cedar-policy =4.12.0`. Both declare Cedar language version 4.5 and document cvc5 1.3.1 as their tested solver.
- `cedarpy` 4.12.1 (PyPI, Apache-2.0, k9securityio/cedar-py tag v4.12.1 at commit `1a8a2750734119277d44e3d0a65d74263fbd2ab9`) bundles `cedar-policy` **4.12.0**, not 4.12.1 or 4.13.0. Its sdist's `Cargo.lock` (sha256 `36a484d9…2397`) is byte-identical to the tagged commit's and records cedar-policy 4.12.0 with crates.io checksum `f73547a0…f962`. It exposes no runtime Cedar version.
- `cedarpy` API: `is_authorized` returns the decision (`Allow`, `Deny`, or `NoDecision` when the request, entities, schema, or policies fail to load), determining policies as Cedar's positional ids (`policy0`, …) plus a map to `@id` annotations, and evaluation errors as strings that name the positional id. `validate_policies` returns errors with positional ids and no warnings. `policies_to_json_str` returns each policy's JSON form keyed by positional id with its annotations. Entities and context are accepted as JSON. It has nothing for symbolic analysis.
- `cedarpy` builds from its sdist with maturin when no wheel matches (3 min 47 s on this host with Rust 1.95). Wheels exist for CPython 3.10–3.15 on manylinux x86_64 and macOS arm64; uv.lock pins every wheel's sha256.
- The official CLI's `symcc` subcommands (feature `analyze`) print a human-readable verdict and a pretty-printed counterexample, hardcode `--tlimit=60000` for cvc5, and report solver UNKNOWN only as an error string with a failure exit code. `authorize` prints `ALLOW`/`DENY` and, with `-v`, the determining policies by `@id` and any errors as text. No JSON output exists for either.
- Changes from cedar-policy 4.12.0 to 4.13.0 (upstream changelog): an inapplicable action scope ("unable to find an applicable action") moves from validation error to validation warning; a chained `has` converts to JSON as one node instead of a conjunction; experimental `tpe` and protobuf changes. Evaluation semantics and the language version are unchanged. SymCC 0.6.0 to 0.7.0 adds an SMT-LIB `(reset)` mode and renames eid selectors in emitted SMT-LIB.
- Measured on this host, P0 and a GET request: cedarpy 174 µs per request in process; the bridge 6.9 ms per request including process spawn.

## Decision

1. **One Cedar version everywhere: cedar-policy 4.12.0.** We pin the analyzer stack to match the binding rather than keep separate version-specific conclusions. Concrete evaluation, witness replay, policy validation, and symbolic analysis all run cedar-policy 4.12.0 (language 4.5).
2. **Concrete evaluation: `cedarpy` 4.12.1, in process** (`agent_in_a_box.policy.evaluator.CedarpyEvaluator`). It is the runtime default for the proxy, the inspector, and witness replay. The adapter requires an `@id` on every policy, maps positional ids to `@id` for determining policies and errors, treats `NoDecision` as raw `no-decision` (denied), and rewrites positional ids in messages to the authored names.
3. **Symbolic analysis: `agent-in-a-box-cedar`, a small Rust bridge** (`native/cedar-bridge/`, about 400 lines) linking `cedar-policy =4.12.0` and `cedar-policy-symcc =0.6.0` in one Cargo graph with a committed `Cargo.lock`. It speaks one JSON command per process: `version`, `validate`, `authorize`, `request_envs`, `analyze`. It returns raw SymCC counterexamples serialized with Cedar's own JSON encoders plus SymCC's own text rendering, a distinct `unknown` status, caller-chosen cvc5 limits (so a deliberate UNKNOWN is reproducible with a resource limit), and optionally the exact SMT-LIB script for disclosure. It adds no policy semantics.
4. **The bridge is also the interchangeable evaluator** (`BridgeEvaluator`). Both adapters implement `CedarEvaluator` and must pass the same contract cases (`tests/policy/test_evaluator_contract.py`, hand-authored expectations, also checked against the official CLI). On 2026-10-09 they agreed on every case, on an ad hoc sweep of 63 variant-by-request decisions, and on every policy's JSON form.
5. **Solver: cvc5 1.3.1**, the version SymCC 0.6.0 documents, non-GPL static builds, pinned by archive sha256 and, on Linux x86_64, binary sha256 (`tooling/toolchain.lock.json`).
6. **The official CLI (`cedar-policy-cli` 4.12.0 with `analyze`) is an independent oracle in tests only.** It never sits on a runtime path. Installed by `tooling/bootstrap.py --with-cli`.
7. **Version checks are behavioral as well as declared.** The tool manifest records the bridge's compiled-in `cedar-policy` version, cvc5's own version string, cedarpy's package version and its locked bundled Cedar version, every binary's checksum, and the schema hash. Because cedarpy reports no Cedar version at run time, a known-answer canary checks 4.12 behavior directly: a policy whose action scope cannot apply must fail validation (it would only warn under 4.13).

## Alternatives rejected

- **The official CLI as the evaluator and analyzer adapter.** No JSON output; witnesses would have to be parsed from pretty-printed text; UNKNOWN is indistinguishable from other failures without parsing stderr; the 60 s solver limit cannot be changed, so a deliberate UNKNOWN would need a wrapper script around cvc5; a process per request on the proxy path. Kept as a test oracle.
- **cedarpy 4.12.0 for evaluation, SymCC 0.7.0 with cedar-policy 4.13.0 for analysis, conclusions kept separate.** Uses the newest release for analysis, but every replay and every "proved for domain D" card would cross a version boundary that learners would have to be taught about, for no semantic gain (same language version).
- **The bridge for evaluation too, as a long-lived process.** Workable and version-coherent, but the owner prefers an in-process binding on the request path, and cedarpy gives that with a maintained, widely used package.
- **Our own PyO3 binding to cedar-policy 4.13.0.** More native code to review and maintain than the bridge; revisit only if cedarpy stops tracking Cedar releases.
- **Choosing SymCC 0.7.0 because 4.13.0 is newest.** Rejected: the binding constrains the newest common version to 4.12.0, and the measured differences do not affect our schema, policies, or lessons.

## Consequences

- PLAN.md's open-question default changes: the newest Cedar version supported by all three of cedarpy, SymCC, and the official CLI. Today that is 4.12.0. We move all three together, by a new ADR, when cedarpy ships a 4.13 build; the canary test will fail until the canary is updated, which is intended.
- Difference from 4.13.0, kept explicit: an inapplicable action scope is a load error under 4.12.0 and a warning under 4.13.0. Our loader would keep rejecting it after an upgrade by treating that warning as an error.
- cedarpy reports no validator warnings, so the bridge's `validate` is the one that shows warnings (for example "policy is impossible"); the contract cases compare errors and policy JSON, not warnings.
- Two native artifacts carry Cedar: the cedarpy wheel (built by its maintainers' CI, pinned by hash) and the bridge (built locally from a locked graph). Both are compiled from the same crates.io source checksum; we do not claim byte-identical builds.
- The bridge adds a Rust toolchain to setup (rustup, user-local). cedarpy needs Rust only on platforms without a wheel.
- Invariants 2 and 6 are served: bridge failures and `NoDecision` deny; UNKNOWN, timeouts, and bridge errors are "no conclusion"; nothing is labeled proved without UNSAT from the pinned stack.

## Plan sections affected

PLAN.md: Open questions and defaults (Cedar version, Evaluator binding, Solver rows); Formal verification as a core learning feature (pinned stack note); Repository layout (`native/cedar-bridge/`); Modularity table (CedarEvaluator and PolicyAnalyzer rows).
