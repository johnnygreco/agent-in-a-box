# Platform differences

How one grant plan is translated into kernel enforcement on each supported backend, and where the resulting boundaries differ. macOS Seatbelt is the primary backend and the reference for the shared contract; the Linux backend conforms to it and discloses its gaps through capability flags and the doctor (PLAN.md, Platform decision; ADR 0001). Rows marked *to confirm* are authored expectations that the native probe suite must confirm before they are stated as fact anywhere else. See [PLAN.md](../PLAN.md), Milestone 1 and Milestone 1-L.

## Mechanism mapping

| Boundary need | macOS Seatbelt (`SeatbeltBackend`) | Linux (`LandlockBackend`, secondary) | Status |
| --- | --- | --- | --- |
| Filesystem grants per subtree | SBPL `file-read*` / `file-write*` with `subpath` | Landlock ruleset applied before exec | To confirm on both |
| Minimal filesystem view | SBPL deny-by-default | bubblewrap mount namespace plus Landlock deny-by-default | To confirm |
| Proxy-only network | `network-outbound` to the data-plane listener only | Network namespace with loopback only; proxy via bind-mounted Unix socket or one veth | To confirm on both |
| Socket-family lockdown | SBPL network rules | seccomp-bpf on `socket(2)` | To confirm |
| Child inheritance | Automatic | Automatic | To confirm on both |
| Process tree cleanup | Supervisor process accounting | PID namespace init | To confirm on both |
| Truncate | Controlled by `file-write*` | Controlled from Landlock ABI 3 (kernel 6.2) | ABI 2 hosts: uncontrolled, disclosed by the doctor |
| Mach IPC, sysctl, signals | SBPL rules | Not applicable; IPC namespace and seccomp where relevant | Documented, not emulated |
| Executable and ancestor attribution | Not provided | Not provided | Both reject policies needing it |

## Known semantic differences

| Topic | Seatbelt | Landlock + namespaces | Teaching use |
| --- | --- | --- | --- |
| Profile language | Scheme-like SBPL, regex and subpath filters | Access-right bitmasks over path hierarchies | Chapter 6: two translations of one grant plan |
| WriteFile-only grant | Mapping decided per PLAN.md; rejected if not separable | Landlock separates read and write rights | Documented per backend |
| Reaching the proxy | Allowed TCP port on loopback | Unix socket or veth inside the namespace | Chapter 4 probe expectations differ in failure mode, not in outcome |
| Process isolation | None beyond the profile | PID namespace hides other processes | Linux-only probe |
| Availability | Always present; `sandbox-exec` deprecated | Needs Landlock LSM, unprivileged userns, bubblewrap | Doctor output |

## Host probe results

| Date | Host | Kernel | Landlock ABI | Unprivileged userns | bubblewrap | seccomp | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-09 | Development workspace (Debian cloud) | 6.1.0-50-cloud-amd64 | 2 | Yes (user, net, pid, mount) | Installed | Enabled | Feasible; truncate uncontrolled at ABI 2 |

No macOS host has been probed.
