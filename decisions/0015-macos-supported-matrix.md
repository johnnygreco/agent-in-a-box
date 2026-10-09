# 0015. Supported macOS matrix: the configuration where the native suite has passed

Date: 2026-10-09
Status: accepted

## Context

PLAN.md requires the supported platform matrix to be decided from native results, never extrapolated (Open questions and defaults; Milestone 1 exit). The Seatbelt backend (ADR 0014) needs `sandbox_init` and `sandbox_check` in libSystem and `/bin/ps`; its doctor checks them and then runs a trial: a child confines itself with the baseline profile, the supervisor confirms the confinement from outside, and the child runs the shell and a command the profile must refuse. No Mac was available to the project; the GitHub-hosted `macos-15` runner is the native validation PLAN.md names.

## Decision

The Seatbelt backend is supported on exactly this configuration, recorded with the suites that passed:

| Host | macOS | Build | Kernel | Hardware | Runner image | Suites |
| --- | --- | --- | --- | --- | --- | --- |
| GitHub-hosted runner `macos-15` | 15.7.9 | 24G830 | Darwin 24.6.0 | Apple M1 (Virtual), `VirtualMac2,1`, arm64 | `macos15` 20260907.0337.1 | `tests/backends/conformance` (10 probes), `tests/native/macos` (baseline: one check per entry; extras: 12 checks), required to run (CI job `macos-native`, `AGENT_IN_A_BOX_REQUIRE_NATIVE=seatbelt`) |

The runner is a virtual machine with System Integrity Protection disabled. Seatbelt is enforced by the kernel either way, and nothing in the backend depends on SIP; a physical Mac with SIP enabled has not been tried.

Any other Mac may run the backend if its doctor passes: the doctor reports the release and architecture, says when they are outside this matrix, and lets its trial decide. Such a Mac is not called supported until the suites have passed there and a row is added here. Untested: macOS 14 and earlier, macOS 26, Intel Macs (the pinned toolchain has no Intel macOS build either), and physical hardware.

## Alternatives rejected

- **Refusing every release but macOS 15 in the doctor.** The baseline's evidence is per entry and re-checked natively, and the doctor's trial runs the same baseline on the host, so a release where the baseline is insufficient is refused by the trial with the failure named. A version gate would refuse learners on newer releases without evidence that anything fails there.
- **Declaring "macOS 13 or later"** from the APIs' availability. That would extrapolate from headers, not from runs.

## Consequences

- Release notes and lesson text that mention macOS name this configuration, and render platform limits from `BackendCapabilities` rather than from this table.
- Adding a release is a CI matrix entry (for example a `macos-26` runner) plus a row here once the suites pass on it.
- Linux is covered by ADR 0012.

## Plan sections affected

PLAN.md: Open questions and defaults (Supported platform matrix row); Milestone 1 (exit).
