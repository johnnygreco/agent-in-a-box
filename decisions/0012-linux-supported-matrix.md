# 0012. Supported Linux matrix: the hosts where the native suite has passed

Date: 2026-10-09
Status: accepted

## Context

PLAN.md requires the supported platform matrix to be decided from native results, never extrapolated (Open questions and defaults; Milestone 1-L exit). The Linux backend (ADR 0010) needs Landlock ABI 2 or later in the LSM list, unprivileged user namespaces, bubblewrap, and seccomp on x86-64 or arm64; its doctor checks each. On 2026-10-09 the shared conformance suite and the Linux-only extras passed on two hosts.

## Decision

The Linux backend is supported on exactly these configurations, each recorded with the suite that passed:

| Host | Distribution | Kernel | Landlock ABI | bubblewrap | Architecture | Host setting | Suite |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Development workspace (KVM, AMD EPYC 7B12) | Debian 12 (bookworm) | 6.1.0-50-cloud-amd64 | 2 | 0.8.0 | x86-64 | none | `tests/backends/conformance` (10 probes) and `tests/native/linux` (9 checks) |
| GitHub-hosted runner `ubuntu-24.04` | Ubuntu 24.04.5 LTS | 6.17.0-1022-azure | 7 | 0.9.0 | x86-64 | `kernel.apparmor_restrict_unprivileged_userns=0` | The same, required to run (CI job `linux-native`) |

The two hosts sit at either end of the ABI range the backend handles. At ABI 2, read-only mounts refuse truncate outside write grants. At ABI 7, Landlock itself also governs truncate and device ioctls. Both passed unchanged after `/dev/null` gained the truncate right that shell redirection needs from ABI 3.

Any other host may run the backend if its doctor passes, but it is not called supported until the suite has passed there and a row is added here. arm64 is untested: the seccomp program has an arm64 variant, checked only by the instruction-level unit tests.

## Alternatives rejected

- **Declaring support by kernel version alone** (for example "6.1 or later"). That would extrapolate from two data points across distributions with different AppArmor, user-namespace, and LSM defaults.
- **Requiring ABI 3 or later.** It would drop the Debian 12 host, which passes as specified (ADR 0010).

## Consequences

- Release notes and lesson text that mention Linux name these configurations, and render platform limits from `BackendCapabilities` rather than from this table.
- Ubuntu hosts with the default AppArmor restriction on unprivileged user namespaces are refused by the doctor, which names the setting. Lifting the restriction is the operator's choice; the project does not do it outside CI.
- macOS is not covered by this ADR; Milestone 1 records its own matrix.

## Plan sections affected

PLAN.md: Open questions and defaults (Supported platform matrix row); Milestone 1-L (exit).
