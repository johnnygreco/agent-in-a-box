# Status

Working state for the implementing agent. Update at the end of every working session. [PLAN.md](PLAN.md) explains how this file is used.

## Current milestone

M0 is closed and pushed, with CI green on `ubuntu-24.04` and `macos-15`. Milestone 1-L (Linux backend) is complete: every gate item below is checked, natively, on two hosts (ADR 0012). The GitHub Pages site is live at https://johnnygreco.dev/agent-in-a-box/ (ADR 0011). Next: Milestone 1, the macOS Seatbelt backend, which CI's `macos-15` runner can now exercise (PLAN.md). Platform-independent Milestone 2 work can proceed alongside it.

Run everything with `uv run pytest` after `uv sync --locked --extra notebooks`, `python3 tooling/bootstrap.py --with-cli`, and `npm ci` in `website/` (see README.md). Last result (2026-10-09, this checkout): 821 passed, 11 skipped. The skips are the 10 Seatbelt conformance probes (no macOS here) and 1 source-route entry for code not yet written (the model bridge). The Landlock conformance probes and Linux-only extras ran natively. The count includes 48 local cases from the git-ignored working folder; a public checkout skips that module.

## Last native validation

**Linux (`LandlockBackend`), 2026-10-09.** Suites: `tests/backends/conformance` (10 shared probes from CURRICULUM.md's table, `enforcement: landlock`) and `tests/native/linux` (9 Linux-only checks), all passing. Approach: bubblewrap namespaces and filesystem view, a Python launcher applying Landlock, and a seccomp socket-family filter (ADR 0010).
- Debian 12 (bookworm), kernel 6.1.0-50-cloud-amd64, Landlock ABI 2, bubblewrap 0.8.0, x86-64 KVM guest (AMD EPYC 7B12, 8 vCPUs): the development workspace.
- Ubuntu 24.04.5 LTS, kernel 6.17.0-1022-azure, Landlock ABI 7, bubblewrap 0.9.0, x86-64 GitHub-hosted runner, with `kernel.apparmor_restrict_unprivileged_userns=0`: CI job `linux-native`, required to run rather than skip.

**macOS (`SeatbeltBackend`): none.** No Seatbelt behavior has been exercised. No macOS enforcement claim may be made anywhere in this repository until this section names a macOS build, hardware, date, and the passing test suite.

## Gate checklist

### M0 — Platform-independent core
- [x] Repository skeleton, locked Python environment, test runner, lint (Python 3.12.15, uv.lock, pytest, ruff; `.github/workflows/ci.yml` written, never run: no remote)
- [x] Cedar, SymCC, and solver pinned; tool manifest emitted; known-answer tests pass (valid implication, invalid implication with replayed witness, deliberate UNKNOWN). cedar-policy 4.12.0 via cedarpy 4.12.1 and the bridge; SymCC 0.6.0; cvc5 1.3.1 (ADR 0002). `tests/policy/test_analyzer_known_answers.py`, `test_toolchain.py`
- [x] `contracts.py` immutable records and `composition.py` assembly
- [x] Policy package: pinned schema, evaluator adapter with diagnostics, analyzer adapter, filesystem subset compiler producing a grant plan and SBPL text. Two interchangeable evaluators pass the same contract cases, checked against the official CLI. SBPL is untested natively
- [x] Harness: agent loop, read/write/search/bash tools, scripted adapter driven by the CURRICULUM.md strategy table (`src/agent_in_a_box/models/strategy.yaml`), plus a one-call probe model
- [x] `NoEnforcementBackend` test double, labeled `enforcement: none`, unreachable from gateway commands (no command selects a backend; a native runtime refuses runs rather than falling back)
- [x] Fixture service and per-run proxy decision path for plain HTTP; refused requests never reach the fixture handler (mitmproxy, ADR 0004; `tests/network/test_proxy_integration.py`)
- [x] Gateway v1 API, SSE, session auth, idempotent commands; typed Python client; CLI runner
- [x] Evidence bundle schema v1 with export, import, and replay (replay re-evaluates every recorded decision without effects)
- [x] Oracle contract cases in the public tree, with expected outcomes from the official Cedar CLI or authored from the plan (ADR 0009): `tests/oracle/cedar_cli_cases.json` (144 cases from cedar-policy-cli 4.12.0 via `tooling/generate_oracle_cases.py`, which never imports our package) checked against both evaluators; compiler subset rules hand-authored from PLAN.md in `tests/policy/test_compiler.py`. The earlier local cases run from `inspiration/cases/` through `tests/local_cases/` and skip when absent
- [x] Trailer runs end to end on Linux under the test backend via the CLI (`agent-in-a-box trailer --test-backend`; also `chapter5`)
- [x] Website scaffold renders chapters 0 and 5 from test-backend bundles (development only; Astro, ADR 0006)
- [x] Notebooks 01 and 04 drafted in recorded mode

### M1 — Native boundary feasibility (macOS; the GitHub `macos-15` runner counts)
- [ ] Launcher approach chosen and recorded as an ADR
- [ ] Profile applies; Bash and child Python inherit it
- [ ] Declared grants work; canaries, protected state, and symlink/replacement cases are blocked
- [ ] Proxy-only egress; direct IPv4/IPv6, UDP, alternate loopback, and IPC paths blocked as specified
- [ ] Cleanup covers detached descendants; limits and gaps recorded
- [ ] Supported macOS matrix recorded as an ADR
- [ ] Doctor command passes on the named configuration

### M1-L — Linux enforcement backend (scheduled, secondary)
Scheduled 2026-10-09 by the owner (decisions/0001). macOS is primary; see PLAN.md, Platform decision, primacy rules. Any shared-contract change motivated here needs an ADR stating macOS impact is nil.
- [x] Owner scheduled this milestone (ADR 0001)
- [x] Launcher approach chosen (bubblewrap plus Landlock/seccomp helper by default) and recorded as an ADR (ADR 0010: bubblewrap, a Python launcher using the Landlock system calls, a hand-built seccomp filter; no compiled helper)
- [x] Backend module boundary rules pass in CI (no core imports of backends, no platform checks outside backends and composition, conformance suite parameterized)
- [x] Every Linux expected-fail in the conformance suite has a documented reason in reference/platform-differences.md (there are none; every shared probe passes as authored)
- [x] Landlock ruleset applies; Bash and child Python inherit it
- [x] Declared grants work; canaries, protected state, and symlink/replacement cases are blocked
- [x] Network namespace with proxy-only reachability; direct IPv4/IPv6, UDP, alternate loopback, and IPC paths blocked
- [x] seccomp socket-family filter in place and tested
- [x] PID namespace cleanup covers detached descendants (including a new-session descendant)
- [x] Doctor checks Landlock LSM, ABI version, unprivileged user namespaces, and bubblewrap (and seccomp; it names the AppArmor restriction when that is the cause)
- [x] Supported kernel and distribution matrix recorded as an ADR (ADR 0012)
- [x] `reference/platform-differences.md` rows confirmed by the probe suite (Linux rows; macOS rows stay to confirm)

### M2 — First complete experiment and pilot gate
- [x] GitHub Pages deployment: CI builds the site with the project base path and deploys it from `main` after tests pass; the publishing step refuses `enforcement: none` bundles; lessons without a native recording say so; site live at https://johnnygreco.dev/agent-in-a-box/ (owner request, 2026-10-09; may land before M1-L completes) Live since 2026-10-09 (ADR 0011): chapters 0 and 5 show analysis results produced at build time and placeholders for runs without a native recording.
- [ ] `SeatbeltBackend` wired; trailer runs live on the Mac
- [ ] Shipped recorded bundles produced on the Mac with full provenance
- [ ] Chapters 0, 1, 3 (minimal), 5 complete with hosted interactivity
- [ ] Notebooks 01, 02 (minimal), 04 ship; recorded-mode CI passes
- [ ] Website, CLI, and marimo bundle parity for the trailer
- [ ] Pilot gate: two of three developers complete the five explanations

### M3 — Model bridge, inspected HTTPS, middle chapters
- [ ] Trusted model bridge with bound credentials; Responses, Chat, and legacy protocol fixtures
- [ ] Inspected HTTPS with per-run CA; unsupported traffic fails explicitly
- [ ] Chapters 2, 4, 8; notebooks 03, 06
- [ ] Controlled probe set confirmed on the Mac; contrast bundle recorded

### M4 — Lifecycle, verification-boundary lessons, capstone, release
- [ ] Network-only generation reload and restart comparison
- [ ] Chapters 3 (full), 6, 7, 9, capstone; notebooks 02 (full), 05
- [ ] Source route within budgets; chapter 9 written against it
- [ ] Packaging, native CI, licenses, provenance, reproducible exports
- [ ] Definition of done in PLAN.md satisfied

## Blockers

- **Milestone 1 (macOS Seatbelt) needs a Mac.** The SBPL renderer exists and is tested only as text; the launcher, probes, and doctor are not written. The conformance suite skips Seatbelt here because its doctor refuses on Linux.

## Follow-ups (implementing agent)

- arm64 Linux is untested natively; the seccomp program's arm64 variant is checked only by unit tests (ADR 0012).
- Redirect handling and its tests are scheduled with Milestone 3's bypass tests (ADR 0004).
- The `SeatbeltBackend` OS baseline (`os_baseline.py`) was rewritten from first principles, one reasoned rule per entry (ADR 0008). It must be confirmed on a Mac in Milestone 1, and `sysctl-read` narrowed to named parameters there.
- The schema's vocabulary (entity types, actions, endpoint attributes) was designed in the first session with an external schema in view. Its comments are now our own, and no source is named. If the owner wants the vocabulary itself redesigned independently, that is a schema change with an ADR (see Questions).
- Error-freedom checks (`never_errors`) are implemented in the bridge but not yet exposed by the analyzer adapter (Milestone 4 lesson).

## Questions for the owner

All four questions from the first session were answered on 2026-10-09:

1. **Version control:** yes. A local git repository was initialized on `main` (identity: Johnny Greco). No commit yet: the first commit waits for the public-tree scrub below.
2. **Remote and CI:** GitHub. The public repository `johnnygreco/agent-in-a-box` exists and is empty; `origin` points at it. Nothing is pushed until the scrub gate passes.
3. **License:** Apache-2.0. `LICENSE` added at the repository root.
4. **Chapter 4 probe:** a fixture variant `missing` whose `/reference` answers 404, run under P0, so the request is allowed by policy and fails at the application. CURRICULUM.md updated.

New owner rule, 2026-10-09: the public tree names no third-party project as a source of inspiration or reference, in documents, code, comments, tests, or lock files. Such material lives only in the git-ignored `inspiration/` folder. A CI grep gate enforces this (`tests/test_public_tree.py`, passing).

Open questions:

5. **Schema vocabulary.** `policies/sandbox.cedarschema` keeps the entity and action names chosen in the first session (`Sandbox::Process`, `FilesystemPath`, `NetworkEndpoint` with `host`, `port`, `host_port`; actions `ReadFile`, `WriteFile`, `NetworkConnect`, `HttpRequest`). No source is named anywhere, and the comments are rewritten. Is the vocabulary itself acceptable to keep, or should it be redesigned? Redesign touches every policy, lesson snippet, and oracle case.

6. **Publishing Linux recordings:** answered 2026-10-09: yes, under primacy rule 4, with host paths rewritten to neutral roots (ADR 0013). Shipped.

## Decisions

See `decisions/`.

- 0001: Linux backend scheduled as secondary; macOS Seatbelt primary and never reduced for parity.
- 0002: Cedar toolchain. cedarpy 4.12.1 in process for evaluation; a Rust bridge (cedar-policy 4.12.0, SymCC 0.6.0) for analysis and as an interchangeable evaluator; cvc5 1.3.1; the official CLI only as a test oracle. One Cedar version everywhere; differences from the newer 4.13.0 release are recorded.
- 0003: Development toolchain. Python 3.12.15, uv 0.12.24, pytest, ruff; Rust 1.89 or later.
- 0004: Proxy component. mitmproxy 12.2.3 in regular mode, with our decision path deciding before anything goes upstream.
- 0005: Analysis domains. A schema request environment narrowed by one stated condition, encoded exactly as a forbid on both sides; D_http is the set of requests the proxy can construct.
- 0006: Website toolchain. Node 24.21.0 LTS, Astro 7.3.8 with MDX, telemetry off.
- 0007: Backend `teardown` split into `wait` and `stop`; lifecycle reads as a sequence. macOS impact: none.
- 0008: macOS baseline authored from first principles, each rule with its reason.
- 0009: Oracle cases from the official Cedar CLI (generator never imports our package) and hand-authored compiler cases.
- 0010: Linux launcher. bubblewrap namespaces and view, a Python launcher applying Landlock, a hand-built seccomp filter, the proxy through a mounted Unix socket; the harness import root becomes the runtime read grant.
- 0011: Published website. GitHub Pages from CI, built only from analysis produced at build time and native bundles; test-backend bundles refused.
- 0012: Supported Linux matrix. Debian 12 (6.1, ABI 2) and Ubuntu 24.04 (6.17, ABI 7).
- 0013: Bundle schema v2. Host paths rewritten to neutral roots; ids, hashes, and provenance unchanged.

## Session log

| Date | Summary |
| --- | --- |
| 2026-10-09 | Plan revised for pedagogy and autonomous implementation. No code written. |
| 2026-10-09 | Probed this Linux host: kernel 6.1, Landlock ABI 2 enabled, unprivileged user/net/pid/mount namespaces work, bubblewrap installed, seccomp enabled. Recorded in reference/platform-differences.md. Linux backend remains unscheduled pending owner decision. |
| 2026-10-09 | Owner scheduled the Linux backend as a secondary target with macOS primacy and a strict backend module boundary (ADR 0001). Plan, STATUS, and reference updated. |
| 2026-10-09 | M0 implemented on Linux under the test backend. Pinned the Cedar toolchain after evaluating cedarpy at the owner's request (ADR 0002): cedarpy 4.12.1 bundles cedar-policy 4.12.0, so the bridge was pinned to 4.12.0 and SymCC 0.6.0 to keep one Cedar version. Built the contracts, composition, policy package (schema, two evaluators, analyzer with witness replay, subset compiler, SBPL renderer), harness with scripted and probe models, NoEnforcementBackend, fixture and mitmproxy decision path, supervisor lifecycle, gateway with SSE and session auth, client, CLI, bundles v1, 37 reference cases, trailer and chapter 5 experiments, website scaffold, and notebook drafts 01 and 04. ADRs 0002 to 0006. 297 tests pass; native probes skip. Nothing native was exercised. |
| 2026-10-09 | Owner naming decision applied: package `agent_in_a_box`, CLI `agent-in-a-box`, bridge binary `agent-in-a-box-cedar`, state directory `.agent-in-a-box/`. |
| 2026-10-09 | Owner decisions: git initialized on `main`; public GitHub repo `johnnygreco/agent-in-a-box` created as `origin` (nothing pushed); license Apache-2.0; chapter 4 probe uses the `missing` fixture variant; all inspiration and reference material moved to git-ignored `inspiration/` and removed from public documents. Code-side scrub, oracle-case rework, and `os_baseline.py` rewrite handed to the implementer. |
| 2026-10-09 | Review fixes: plain code on the teaching route (no tuple-assignment chains, closures over mutable locals, or lambdas in dicts); new concept files `network/protocol.py`, `policy/authored_ids.py`, `policy/domains.py`, `policy/policy_json.py`, `experiments/steps.py`, `models/report.py`; named trigger functions in the scripted model; explicit command dispatch; structured checks in the experiment scripts with step names defined once; agent events ordered by supervisor read time; evaluator names derived from the lock; backend `wait`/`stop` (ADR 0007). Owner items: public tree scrubbed of third-party names with a grep gate; macOS baseline rewritten (ADR 0008); public oracle cases from the official CLI (ADR 0009); Apache-2.0 in pyproject; `missing` fixture variant and its conformance probe; README banner. First local commit made; not pushed. |
| 2026-10-09 | First push to `johnnygreco/agent-in-a-box`. CI: Linux job passed; macOS job failed on two process-group tests because macOS refuses `killpg(group, 0)` where Linux does not. Fixed by enumerating group members with `pgrep -g` and signalling per process when the group signal is refused; the teardown report now lists actual survivors. Recorded in PLAN.md that GitHub's Apple silicon macOS runner satisfies the native gates, so the work can be finished from this Linux machine. |
| 2026-10-09 | Owner decision: publish the pedagogical website to GitHub Pages. Pages enabled on the repository with GitHub Actions as the source. Publishing rules added to PLAN.md (Product shape); deployment pipeline handed to the implementer as the next item. |
| 2026-10-09 | Milestone 1-L complete. `LandlockBackend`: bubblewrap namespaces and a filesystem view mirroring the grant plan, a Python launcher that applies Landlock and probes the confinement, a hand-built seccomp socket-family filter, the proxy through a mounted Unix socket, and PID-namespace teardown with a verified-empty check (ADR 0010). The shared conformance suite and 9 Linux-only checks pass natively on Debian 12 / 6.1 / ABI 2 and on the ubuntu-24.04 runner (6.17, ABI 7), where CI requires them (ADR 0012). Found and fixed: Landlock needs read with execute, `> /dev/null` needs truncate from ABI 3, and a new Python process needs to list its import root (shared runtime grant, ADR 0010). GitHub Pages pipeline added and the site deployed to https://johnnygreco.dev/agent-in-a-box/ with build-time analysis and native-recording placeholders (ADR 0011). |
| 2026-10-09 | Bundle schema v2 rewrites host paths to neutral roots (ADR 0013). First native recordings shipped in `bundles/` (trailer and chapter 5, `enforcement: landlock`, Debian 12 host); the website's run panels now show them. Next: Milestone 1 (Seatbelt) on the macos-15 runner. |
