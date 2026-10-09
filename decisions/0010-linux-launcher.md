# 0010. Linux launcher: bubblewrap, a Python launcher that applies Landlock, and a hand-built seccomp filter

Date: 2026-10-09
Status: accepted

## Context

Milestone 1-L needs a launcher that confines the workload on Linux before any workload code runs: a filesystem allow-list, a network limited to the per-run proxy, isolation of the process tree, and inheritance by every child. PLAN.md's default was bubblewrap for namespaces and the filesystem view, plus a small helper that applies a Landlock ruleset and a seccomp filter; a single dedicated helper only if bubblewrap got in the way. The owner's brief allowed Python with ctypes for Landlock and required that seccomp not block the milestone. This host: Debian 12, kernel 6.1.0-50-cloud-amd64, Landlock ABI 2, bubblewrap 0.8.0, unprivileged user namespaces enabled.

## Decision

**The launcher is bubblewrap plus a Python program; no compiled helper.** `native/linux/` stays empty.

1. **bubblewrap** (the distribution's package) creates user, PID, network, IPC, UTS, and cgroup namespaces, builds the filesystem view, and loads the seccomp filter (`--seccomp FD`) immediately before it starts the launcher. `--die-with-parent` and `--new-session` are always on. `--info-fd` reports the host PID of the namespace's init and the namespace inodes, which the supervisor uses for its outside checks and for cleanup.
2. **The filesystem view** mirrors the grant plan. Paths with read, execute, or metadata grants are mounted read-only; paths with write grants are mounted writable; nothing else exists inside, including the run's private directory and the toolchain. The Linux system baseline (`landlock/os_baseline.py`) lists each extra mount and rule with its reason, as the macOS baseline does (ADR 0008).
3. **The launcher** (`supervisor/backends/landlock/launcher.py`, the source route's launcher slot) runs first inside the sandbox. It calls `landlock_create_ruleset`, `landlock_add_rule`, and `landlock_restrict_self` through ctypes (`syscalls.py`) with `PR_SET_NO_NEW_PRIVS`. It governs every filesystem right the kernel's ABI knows and allows only the profile's rules. It then runs self-probes: an unlisted directory cannot be read; a mounted but ungranted directory refuses a new file; no route leaves the network namespace; seccomp refuses a netlink socket; and every protected path is absent. Next it starts the loopback relay, writes its report on a pipe, closes every other inherited descriptor, and replaces itself with the workload, which waits for the supervisor's admit.
4. **Confirmation from outside.** The supervisor admits the workload only if every inside probe passed and its own `/proc` checks pass. Those checks are that the sandbox's init has its own namespace of every kind, and that the workload process shows `NoNewPrivs: 1` and `Seccomp: 2`. A failure stops the sandbox and refuses the run.
5. **seccomp** is classic BPF built by hand (`seccomp.py`, 17 instructions on x86-64, tested instruction by instruction). It allows `socket` and `socketpair` only for AF_UNIX, AF_INET, and AF_INET6, refuses `io_uring_setup`, refuses x86-64's x32 syscalls, and kills a process that makes a syscall for a foreign architecture. The network namespace is the primary network boundary; the filter closes what a namespace does not, notably VSOCK. The exact program bytes are part of the hashed profile.
6. **The proxy is reached through a Unix socket.** A host relay in the supervisor listens on a socket in a private temporary directory and forwards to the proxy's TCP port. That directory is mounted read-only into the sandbox, and a relay inside listens on the plan's proxy port on the sandbox's own loopback. Both relays are byte pipes. The workload's `HTTP_PROXY` is the same as on every backend, so no shared contract changes.
7. **Cleanup** stops the PID namespace's init, which makes the kernel stop every process in the namespace, including detached ones. The supervisor then scans `/proc` for any process still in that namespace and reports the result as verified only if none remain.
8. **Landlock ABI 2 is the minimum**; the doctor refuses below it. At ABI 2 Landlock does not govern `truncate(2)`, but every path outside a write grant is on a read-only mount, so truncate is refused there on every ABI. Inside a write grant, truncate is permitted, as Seatbelt's `file-write*` permits it. The backend therefore reports `controls_truncate=True`, with a note that Landlock itself governs truncate from ABI 3. A Linux-only test checks truncate of a read-only granted file.
9. **CI** runs the native suite on `ubuntu-24.04` by installing bubblewrap and setting `kernel.apparmor_restrict_unprivileged_userns=0` with the runner's passwordless sudo, for that job only. The doctor names this setting when it refuses on a host that restricts it.

## Differences from Seatbelt, disclosed through capabilities and reference/platform-differences.md

- Executing a program requires reading it under Landlock (the kernel opens a program for reading to execute it), so an execute grant also lets the workload read that program's bytes. Seatbelt can grant execute without read.
- Landlock does not govern metadata (`stat`). Mounted paths can be looked up without a grant; unmounted paths do not exist.
- A Landlock rule always covers a path and everything beneath it, so a file-extent read grant on a directory also allows listing its subdirectories.
- A denied operation fails with ENOENT (not mounted), EACCES (Landlock), or EROFS (read-only mount), where Seatbelt reports EPERM. The outcome, blocked, is the same.

## A shared runtime grant fixed in the same change

A Python process started under the confinement must list the directory on its import path that holds the `agent_in_a_box` package, or it cannot import it (`src/` for this editable install). The runtime grant for harness code therefore moves from the package directory to its import root (`supervisor/grants.py`), which contains only the read-only package. This is not a Linux-specific need: Seatbelt also requires read access to a directory to list it, so the macOS harness would have failed the same way. macOS impact: the macOS profile gains read access to that one directory's listing, which it needs. No other macOS behavior, requirement, or default changes; the backend protocol, grant plan format, conformance suite, and evidence schema are unchanged.

## Alternatives rejected

- **One dedicated helper in C or Rust** doing namespaces, mounts, Landlock, and seccomp. It would be more native code to review than a widely packaged tool, and it would add a build step.
- **libseccomp through ctypes.** It adds a native dependency for a filter of 17 instructions.
- **A veth pair to reach the proxy.** It needs `CAP_NET_ADMIN` in the host's network namespace, which an unprivileged supervisor does not have.
- **slirp4netns or pasta.** They give the sandbox general network access, which the proxy-only design forbids.
- **Requiring Landlock ABI 3** so that Landlock itself governs truncate. Read-only mounts already refuse truncate outside write grants, and requiring ABI 3 would exclude kernels before 6.2, including Debian 12's.

## Consequences

- A host needs Landlock in its LSM list, ABI 2 or later, unprivileged user namespaces, bubblewrap, and seccomp on x86-64 or arm64. The doctor checks each and refuses with the exact reason otherwise.
- The launcher's Python startup runs inside the namespaces and under seccomp, but before Landlock; it is trusted code, and no workload code runs until the launcher has restricted itself and the supervisor has admitted the workload.
- The supported kernel and distribution matrix is recorded separately, once the suite has run on each.

## Plan sections affected

PLAN.md: Open questions and defaults (Linux launcher row); Milestone 1-L (approach); Supervisor (runtime grants, through this ADR's grant fix).
