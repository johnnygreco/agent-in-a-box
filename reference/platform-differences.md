# Platform differences

How one grant plan is translated into kernel enforcement on each supported backend, and where the resulting boundaries differ. macOS Seatbelt is the primary backend and the reference for the shared contract; the Linux backend conforms to it and discloses its gaps through capability flags and the doctor (PLAN.md, Platform decision; ADR 0001). Rows marked *confirmed* name the host where the probe suite passed. See [PLAN.md](../PLAN.md), Milestone 1 and Milestone 1-L, [ADR 0014](../decisions/0014-macos-launcher.md) for the macOS design, and [ADR 0010](../decisions/0010-linux-launcher.md) for the Linux design.

macOS confirmations below were made on 2026-10-09 on the GitHub-hosted `macos-15` runner (macOS 15.7.9, build 24G830, Apple M1 virtual machine) by `tests/backends/conformance/` and `tests/native/macos/` in the `macos-native` CI job ([ADR 0015](../decisions/0015-macos-supported-matrix.md)). Linux confirmations were made on 2026-10-09 on Debian 12, kernel 6.1.0-50-cloud-amd64, x86-64, Landlock ABI 2, bubblewrap 0.8.0, by `tests/backends/conformance/` and `tests/native/linux/`, and again on the `ubuntu-24.04` runner ([ADR 0012](../decisions/0012-linux-supported-matrix.md)).

## Mechanism mapping

| Boundary need | macOS Seatbelt (`SeatbeltBackend`) | Linux (`LandlockBackend`, secondary) | Status |
| --- | --- | --- | --- |
| Filesystem grants per subtree | SBPL `file-read*` / `file-write*` with `subpath`, applied by the launcher with `sandbox_init` | Landlock ruleset applied by the launcher before exec; read and write rights kept separate | Both confirmed (a write-only grant cannot be read back; an ungranted file is refused) |
| Minimal filesystem view | SBPL `(deny default)`; the baseline in `seatbelt/os_baseline.py`, each entry checked natively | bubblewrap mount namespace: read-only mounts for read, execute, and metadata grants, writable mounts for write grants, nothing else | Both confirmed (canaries, outside paths, and the private directory are refused on macOS and absent on Linux) |
| Proxy-only network | `network-outbound` TCP to `localhost:PORT` only; the backend holds `[::1]:PORT` so nothing else listens there | Network namespace with loopback only; the proxy reached through a mounted Unix socket and two byte relays | Both confirmed (direct IPv4, IPv6, alternate loopback, outside addresses, UDP, Unix sockets, and DNS all fail) |
| Socket-family lockdown | SBPL: `system-socket` and Unix-socket connections are not allowed | seccomp filter: `socket`/`socketpair` only for AF_UNIX, AF_INET, AF_INET6; `io_uring_setup` refused | Both confirmed (macOS: kernel-control, routing, and raw sockets refused; Linux: vsock, packet, netlink, and io_uring refused) |
| Child inheritance | Automatic | Automatic for Landlock, seccomp, and namespaces | Both confirmed (bash and child Python inherit; on macOS a grandchild reports itself confined) |
| Process tree cleanup | Supervisor process accounting: every process carrying the run's marker is frozen, then killed (ADR 0014) | PID namespace: stopping its init ends every process in it | Both confirmed (`nohup` and a new-session grandchild are stopped; no survivor) |
| Process visibility | `process-info*` refused except about the process itself; signals only within the sandbox | PID namespace hides host processes | Both confirmed (macOS: another process's arguments and environment, the process list, and signals to the supervisor are refused; Linux: `kill -0` of a host PID reports no such process) |
| Truncate | Controlled by `file-write*` | Refused outside write grants by read-only mounts on every ABI; Landlock itself governs it from ABI 3 | Both confirmed (append, truncate, replace, and remove of a read-only granted file fail) |
| Widening from inside | A second `sandbox_init` fails; the first profile stays | Landlock and seccomp can only add restrictions; namespaces cannot be left | macOS confirmed; Linux by construction |
| Mach IPC, sysctl, signals | SBPL rules: one Mach service (the directory service), named kernel parameters, signals within the sandbox | Not applicable; IPC and UTS namespaces; signals reach only the sandbox's own processes | Documented, not emulated |
| Executable and ancestor attribution | Not provided | Not provided | Both reject policies needing it |

## Known semantic differences

| Topic | Seatbelt | Landlock + namespaces | Teaching use |
| --- | --- | --- | --- |
| Profile language | Scheme-like SBPL, regex and subpath filters | JSON profile: namespaces, mounts, access-right sets over path hierarchies, and a BPF program | Chapter 6: two translations of one grant plan |
| WriteFile-only grant | `file-write*` without `file-read*`: write-only stays write-only | Landlock separates read and write rights: write-only stays write-only | Confirmed on both |
| Execute grant | `process-exec` plus metadata; the program's bytes stay unreadable | The kernel opens a program for reading to execute it, so Landlock needs read as well as execute: the program's bytes are readable | Disclosed in capabilities |
| Metadata | Governed: `file-read-metadata`. Inside a protected directory a missing name reports ENOENT and an existing one EPERM, so names can be probed but not read | Not governed by Landlock: a mounted path can be looked up without a grant; unmounted paths do not exist | Disclosed in capabilities |
| Directory listings outside grants | The root directory (the loader lists it as every program starts) and the working directory (`getcwd` opens it) can be listed | Neither can be listed | Disclosed in capabilities |
| Here-documents in bash | macOS's `/bin/bash` 3.2 writes them to `/var/tmp`, `/tmp`, or the working directory, ignoring `TMPDIR`, so they fail unless the working directory is writable | bash writes them to `TMPDIR` or the sandbox's own `/tmp`; they work | Disclosed in capabilities; `printf` or the write tool work on both |
| A read grant on a directory | `literal` covers that directory's listing only | Landlock rules cover a path and everything beneath it, so subdirectories can be listed too | Disclosed in capabilities |
| How a denial looks | EPERM | ENOENT (not mounted), EACCES (Landlock), EROFS (read-only mount), connection refused or network unreachable (network namespace) | Chapter 4 probe expectations differ in failure mode, not in outcome |
| Reaching the proxy | Allowed TCP port on loopback | The sandbox's own loopback, relayed through a mounted Unix socket | Same `HTTP_PROXY` for the workload on both |
| Availability | Always present; `sandbox_init` and `sandbox-exec` both marked deprecated; the doctor confines a trial child with the baseline before any run | Needs Landlock in the LSM list (ABI 2 or later), unprivileged user namespaces, bubblewrap, and seccomp on x86-64 or arm64 | Doctor output |

## Expected failures in the shared conformance suite

None on either backend: every shared probe passes as authored (`EXPECTED_FAIL` in `tests/backends/conformance/test_conformance.py` is empty). A blocked probe must also name what was refused, so a program that fails to start does not pass as blocked.

## What the macOS kernel accepted and refused (macos-15 runner, ADR 0014)

Recorded so nobody has to rediscover it:

- The network host in an SBPL address must be `*` or `localhost`; `(remote tcp "127.0.0.1:PORT")` is rejected with "host must be * or localhost in network address". `localhost` covers 127.0.0.1 and ::1, not 127.0.0.2.
- `(remote ip "localhost:PORT")` also allows UDP to that port; `(remote tcp ...)` does not.
- `(deny default)` does not cover `process-info*`. `(deny process-info*)` alone makes bash abort; following it with `(allow process-info* (target self))` works. `(deny process-info* (target others))` and denying the `kern.procargs2` sysctl name both leave another process's arguments and environment readable.
- Without `file-read-data` on `/`, every program aborts (SIGABRT) before `main`.
- `sandbox_check` with a path filter answers "refused" for a path that does not exist, even for an unconfined process; with a Mach global name it answers exactly.
- Descriptors opened before `sandbox_init` stay usable afterwards; a second `sandbox_init` fails.
- `file-map-executable` was not needed for Python's extension modules; system libraries come from the dyld shared cache with no rule.

## Host probe results

macOS:

| Date | Host | macOS | Build | Hardware | Note |
| --- | --- | --- | --- | --- | --- |
| 2026-10-09 | GitHub-hosted runner `macos-15`, image `macos15` 20260907.0337.1 | 15.7.9 | 24G830 | Apple M1 (Virtual), arm64 | Native suite passes; SIP disabled on the runner |

Linux:

| Date | Host | Kernel | Landlock ABI | Unprivileged userns | bubblewrap | seccomp | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-09 | Development workspace (Debian 12) | 6.1.0-50-cloud-amd64 | 2 | Yes (user, net, pid, mount) | 0.8.0 | Enabled | Native suite passes; truncate controlled by read-only mounts |
