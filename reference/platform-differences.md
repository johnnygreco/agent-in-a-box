# Platform differences

How one grant plan is translated into kernel enforcement on each supported backend, and where the resulting boundaries differ. macOS Seatbelt is the primary backend and the reference for the shared contract; the Linux backend conforms to it and discloses its gaps through capability flags and the doctor (PLAN.md, Platform decision; ADR 0001). Rows marked *to confirm* are authored expectations that the native probe suite must confirm before they are stated as fact anywhere else. Rows marked *confirmed* name the host where the probe suite passed. See [PLAN.md](../PLAN.md), Milestone 1 and Milestone 1-L, and [ADR 0010](../decisions/0010-linux-launcher.md) for the Linux design.

Linux confirmations below were made on 2026-10-09 on Debian 12, kernel 6.1.0-50-cloud-amd64, x86-64, Landlock ABI 2, bubblewrap 0.8.0, by `tests/backends/conformance/` and `tests/native/linux/`.

## Mechanism mapping

| Boundary need | macOS Seatbelt (`SeatbeltBackend`) | Linux (`LandlockBackend`, secondary) | Status |
| --- | --- | --- | --- |
| Filesystem grants per subtree | SBPL `file-read*` / `file-write*` with `subpath` | Landlock ruleset applied by the launcher before exec; read and write rights kept separate | macOS: to confirm. Linux: confirmed (a write-only grant cannot be read back; a mounted but ungranted file is denied) |
| Minimal filesystem view | SBPL deny-by-default | bubblewrap mount namespace: read-only mounts for read, execute, and metadata grants, writable mounts for write grants, nothing else | macOS: to confirm. Linux: confirmed (canaries, outside paths, and the private directory do not exist inside) |
| Proxy-only network | `network-outbound` to the data-plane listener only | Network namespace with loopback only; the proxy reached through a mounted Unix socket and two byte relays | macOS: to confirm. Linux: confirmed (direct IPv4, IPv6, alternate loopback, outside addresses, UDP, and host abstract sockets all fail) |
| Socket-family lockdown | SBPL network rules | seccomp filter: `socket`/`socketpair` only for AF_UNIX, AF_INET, AF_INET6; `io_uring_setup` refused | macOS: to confirm. Linux: confirmed (vsock, packet, netlink, and io_uring refused) |
| Child inheritance | Automatic | Automatic for Landlock, seccomp, and namespaces | macOS: to confirm. Linux: confirmed (bash and child Python inherit) |
| Process tree cleanup | Supervisor process accounting | PID namespace: stopping its init ends every process in it | macOS: to confirm. Linux: confirmed (`nohup` and a new-session descendant are both stopped; teardown finds no survivor in the namespace) |
| Process visibility | Not isolated | PID namespace hides host processes | Linux-only. Confirmed (`kill -0` of a host PID reports no such process) |
| Truncate | Controlled by `file-write*` | Refused outside write grants by read-only mounts on every ABI; Landlock itself governs it from ABI 3 | macOS: to confirm. Linux: confirmed at ABI 2 (append and truncate of a read-only granted file fail) |
| Mach IPC, sysctl, signals | SBPL rules | Not applicable; IPC and UTS namespaces; signals reach only the sandbox's own processes | Documented, not emulated |
| Executable and ancestor attribution | Not provided | Not provided | Both reject policies needing it |

## Known semantic differences

| Topic | Seatbelt | Landlock + namespaces | Teaching use |
| --- | --- | --- | --- |
| Profile language | Scheme-like SBPL, regex and subpath filters | JSON profile: namespaces, mounts, access-right sets over path hierarchies, and a BPF program | Chapter 6: two translations of one grant plan |
| WriteFile-only grant | Mapping decided per PLAN.md; rejected if not separable | Landlock separates read and write rights: write-only stays write-only | Confirmed on Linux |
| Execute grant | `process-exec` plus metadata; the program's bytes stay unreadable | The kernel opens a program for reading to execute it, so Landlock needs read as well as execute: the program's bytes are readable | Disclosed in capabilities |
| Metadata | Governed: `file-read-metadata` | Not governed by Landlock: a mounted path can be looked up without a grant; unmounted paths do not exist | Disclosed in capabilities |
| A read grant on a directory | `literal` covers that directory's listing only | Landlock rules cover a path and everything beneath it, so subdirectories can be listed too | Disclosed in capabilities |
| How a denial looks | EPERM | ENOENT (not mounted), EACCES (Landlock), EROFS (read-only mount), connection refused or network unreachable (network namespace) | Chapter 4 probe expectations differ in failure mode, not in outcome |
| Reaching the proxy | Allowed TCP port on loopback | The sandbox's own loopback, relayed through a mounted Unix socket | Same `HTTP_PROXY` for the workload on both |
| Availability | Always present; `sandbox-exec` deprecated | Needs Landlock in the LSM list (ABI 2 or later), unprivileged user namespaces, bubblewrap, and seccomp on x86-64 or arm64 | Doctor output |

## Expected failures in the shared conformance suite

None on Linux: every shared probe passes as authored (`EXPECTED_FAIL` in `tests/backends/conformance/test_conformance.py` is empty).

## Host probe results

| Date | Host | Kernel | Landlock ABI | Unprivileged userns | bubblewrap | seccomp | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-09 | Development workspace (Debian 12) | 6.1.0-50-cloud-amd64 | 2 | Yes (user, net, pid, mount) | 0.8.0 | Enabled | Native suite passes; truncate controlled by read-only mounts |

No macOS host has been probed.
