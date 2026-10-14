# Status

Working state for the implementing agent. Update at the end of every working session. [PLAN.md](PLAN.md) explains how this file is used.

## Current milestone

M0 is closed and pushed, with CI green on `ubuntu-24.04` and `macos-15`. Milestone 1-L (Linux backend) is complete: every gate item below is checked, natively, on two hosts (ADR 0012), except the 2026-10-14 hardening item, which has run on the ubuntu-24.04 runner and an Ubuntu 22.04 host and is pending on Debian 12. The GitHub Pages site is live at https://johnnygreco.dev/agent-in-a-box/ (ADR 0011). Next: Milestone 1, the macOS Seatbelt backend, which CI's `macos-15` runner can now exercise (PLAN.md). Platform-independent Milestone 2 work can proceed alongside it. On 2026-10-14 the Linux backend and the data plane were hardened as follow-ups (ADRs 0014 and 0015): the launcher is the sandbox's init, user namespaces are disabled inside, the proxy requires a run credential, the fixture requires the proxy's stamp, unusual request-target spellings are refused, and a `probe` command runs one tool call and attributes the evidence it leaves.

Run everything with `uv run pytest` after `uv sync --locked --extra notebooks`, `python3 tooling/bootstrap.py --with-cli`, and `npm ci` in `website/` (see README.md). Last result (2026-10-09, the Debian 12 checkout): 821 passed, 11 skipped. The skips are the 10 Seatbelt conformance probes (no macOS here) and 1 source-route entry for code not yet written (the model bridge). The Landlock conformance probes and Linux-only extras ran natively. The count includes 48 local cases from the git-ignored working folder; a public checkout skips that module. On 2026-10-14, on the Ubuntu 22.04 host below with the toolchain bootstrapped, the native backend required, no local cases, and no website Node modules: 837 passed, 19 skipped (the 10 Seatbelt probes, 6 website build tests, the marimo notebooks, the local cases, and the model bridge), after the panel review's ten rounds of fixes.

## Last native validation

**Linux (`LandlockBackend`), 2026-10-09 on the two hosts below; the ADR 0014 launcher reconfirmed on 2026-10-14 on the ubuntu-24.04 runner and on the Ubuntu 22.04 host, with the Debian 12 run pending.** Suites: `tests/backends/conformance` (10 shared probes from CURRICULUM.md's table, `enforcement: landlock`) and `tests/native/linux` (13 Linux-only checks; 9 on 2026-10-09), all passing. Approach: bubblewrap namespaces and filesystem view, a Python launcher applying Landlock and serving as the namespace's init, and a seccomp socket-family filter (ADRs 0010, 0014).
- Debian 12 (bookworm), kernel 6.1.0-50-cloud-amd64, Landlock ABI 2, bubblewrap 0.8.0, x86-64 KVM guest (AMD EPYC 7B12, 8 vCPUs): the development workspace.
- Ubuntu 24.04.5 LTS, kernel 6.17.0-1022-azure, Landlock ABI 7, bubblewrap 0.9.0, x86-64 GitHub-hosted runner, with `kernel.apparmor_restrict_unprivileged_userns=0`: CI job `linux-native`, required to run rather than skip.
- Ubuntu 22.04.5 LTS, kernel 6.8.0-1069-gcp, Landlock ABI 4, bubblewrap 0.9.0 built from source (the packaged 0.6.1 is below the doctor's floor), x86-64 GCP guest, 2026-10-14: both suites pass with the launcher as init (ADR 0014). Not added to ADR 0012's matrix: a host whose packaged bubblewrap is below 0.8.0 is not supported as shipped.
- Pending: the Debian 12 host (bubblewrap 0.8.0, ABI 2) has not run the ADR 0014 launcher. Its bubblewrap has both options, but the combination and the ENOSPC probe outcome under 0.8.0 are unexercised there.

The shipped recordings in `bundles/` (2026-10-09, Debian 12) predate ADRs 0014 and 0015: their containment events name the earlier design's probes. They are to be re-recorded on a supported host.

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
- [x] Hardening follow-ups, 2026-10-14: every process in the sandbox, its init included, is confined, and no user namespace can be created inside (ADR 0014); the proxy and the fixture accept only this run's requests, and unusual request-target spellings are refused (ADR 0015). Run natively on the ubuntu-24.04 runner and an Ubuntu 22.04 host; the Debian 12 run is pending (see Last native validation)

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

- Milestone 3, decided 2026-10-14: give the harness a summary of its grants in its task context, and let the supervisor annotate a denied observation with the nearest grant, labelled as supervisor inference and never as a kernel event. Built with the live model (chapter 8).
- Run `tests/backends tests/native/linux` on the Debian 12 workspace under the ADR 0014 launcher and record the date, the LSM list, and `kernel.yama.ptrace_scope` in Last native validation.
- The supervisor accepts an agent event line of at most 16384 characters while the harness bounds tool output at 8192 characters before JSON escaping; the harness now emits without ASCII escaping, but control characters still expand sixfold, so output heavy in them can be refused as `agent.oversized`; bound the serialised line in the harness (pre-existing).
- Re-record the shipped bundles on a supported host under ADRs 0014 and 0015, and record the git revision in each bundle's `source` so the design a recording reflects can be read off it.
- The uncontained contrast recording (PLAN.md, chapter 4) needs a design now that the fixture refuses unstamped requests: a separate log of unstamped requests that counts as evidence only in that recording (ADR 0015).
- seccomp rules refusing `unshare` and `clone` with the user-namespace flag, as belt and braces behind bubblewrap's limit (ADR 0014).
- Attribution of a proxy decision to the tool call that made it, carried in the proxy username and labelled agent-claimed (ADR 0015).
- mitmproxy's `body_size_limit` is unset, so a local client, authenticated or not, can make the proxy buffer a large request body; set it near the fixture's 1 MiB limit (pre-existing).
- `lifecycle.observe` has no try/finally, so an interrupt during the observe phase can leave the proxy process running (pre-existing; the sandbox dies with its parent and the fixture with the scenario).
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
- 0014: The launcher is the sandbox's init and user namespaces are disabled inside; every process in the namespace is under the same confinement, and the outside checks say so (the init check is positional; Landlock on a process is not visible in /proc). Amends ADR 0010.
- 0015: The data plane carries a run credential (proxy) and a forward stamp (fixture); unusual request-target spellings are refused rather than normalized.

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
| 2026-10-14 | Hardening after a review of the Linux boundary. The sandbox's PID 1 was bubblewrap's own reaper: no-new-privileges and seccomp on, but no Landlock ruleset, an exception the records had not named. The launcher is now the init (`--as-pid-1`), the probes moved to `probes.py`, and the outside checks require every process in the namespace to be confined (ADR 0014). User namespaces are disabled inside (`--disable-userns`, bubblewrap 0.8.0 floor in the doctor); verified that Landlock refuses mounts from a nested namespace regardless. The proxy requires a per-run credential and the fixture requires the proxy's stamp, so neither another user's process nor the contained workload can add to a run's evidence; request targets with dot or empty segments or encoded slashes are refused (ADR 0015). New `probe` CLI command. Native suite reconfirmed on the ubuntu-24.04 runner and on Ubuntu 22.04, kernel 6.8, ABI 4, bubblewrap 0.9.0; Debian 12 pending. A four-reviewer panel then found and fixed: the first draft of ADR 0014 wrongly said the reaper lacked seccomp and that only Yama prevented a ptrace attach (Landlock scopes ptrace itself); the new init check could not tell the launcher from the reaper until made positional; the `probe` attribution text was wrong for route refusals, allowed-but-unanswered requests, and an uncontained direct request, and crashed when a run ended without an observation; the shared conformance verdict for the direct probe had to require a connection failure once the fixture answered 403 to bypasses; and a dozen smaller record and test gaps. A second round confirmed those fixes and left lows: the `probe` command's report of a run that ends without an observation, a 407 attribution, the fixture refusing an oversize body with 413 before reading it, host-naming residue in the reference, and the README example. A third round found one regression from the second round's fixes (the fixture's refusal text matched a plain read of the fixture's source), one pre-existing crash the second round had only half fixed (the http tool on a `file:` or malformed URL), and one pre-existing gap (a chunked request body reached the fixture unread, so its receipt described an empty body); the proxy now refuses chunked bodies before Cedar, the fixture refuses undeclared or bad lengths before reading, and the match requires the sentence as a whole output line. A fourth round found the bash tool's timeout path crashing when a timed-out command had printed (pre-existing), the fixture overriding a client's `Connection: close`, a bracketed-host URL escaping the http tool's new guard, and the macOS job failing on a Linux-only test; https now goes to the proxy too, so its CONNECT refusal is recorded instead of attempted directly, the proxy caps request bodies at the fixture's limit, the probe's report lets the lifecycle decide how a run ended over any agent-reported line and documents its exit codes, a fifth round found the timed-out attribution naming the kernel, in-bound non-ASCII tool output refused as oversized because the harness escaped it, ADR 0004's status and ADR 0015's credential paragraph behind the code, and a fixture traceback on a client reset, all fixed with a non-ASCII case added to the timeout test; and a sixth round found that the harness's unescaped output had exposed the supervisor's framing of agent lines to U+2028, U+2029, and NEL (it now frames on the newline byte), that the timed-out attribution still overclaimed in two compositions, and that `--deadline` had no help text and a default equal to the bash tool's own timer (now 45 s); a seventh round confirmed those and left one more timed-out composition (an allowed upload the timer cut before the fixture read it) and a stale key in a test fixture, both fixed, with the probe's stated timer now taken from the tool's own constant, the http tool's unreadable answer named by its error, and a deadline below the timer told why no such observation can arrive; an eighth round found the timed-out no-receipt sentence had dropped its 413 hedge and the deadline cue firing for http probes and not at a deadline equal to the timer, both fixed, and asked for a help-text assertion, added; a ninth round found that the help-text assertion depended on the terminal width, fixed by comparing unwrapped text, and the same commit pinned the whole timed-out upload sentence in its test and reworded the deadline cue; a tenth round found this row crediting the seventh round with the eighth's extension of that cue to a deadline equal to the timer, corrected here. |
