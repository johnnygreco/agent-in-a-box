# 0014. The launcher is the sandbox's init, and the sandbox cannot create user namespaces

Date: 2026-10-14
Status: accepted; amends ADR 0010 (items 1, 3, 4, and 7)

## Context

ADR 0010 let bubblewrap install its own reaper as PID 1 of the sandbox's PID namespace, and had the launcher replace itself with the workload. That reaper ran with no-new-privileges and the seccomp filter, which bubblewrap applies in its init as well as before the command, but without a Landlock ruleset, which only the launcher applies and only to itself and its descendants. So one process in the sandbox was under a different confinement from the workload, and the records did not say so.

What that reaper could have been used for was checked during the review that produced this ADR, and it is less than the review's first draft claimed. Landlock scopes ptrace from its first ABI: a restricted process may trace only processes in its own domain or one nested in it, so the workload could not attach to the unrestricted reaper whatever the host's Yama setting, and could not read its memory through /proc either. The draft's claims that the reaper lacked seccomp and that only Yama stood in the way were wrong; they are corrected here and in STATUS.md. What stayed true: the statement "every process in the sandbox is under the installed confinement" had an exception, and the boundary against that exception rested on one Landlock rule about ptrace rather than on there being nothing to reach.

Separately, a sandboxed process could create a user namespace of its own, which gives it every capability over a private copy of the mount tree. Landlock refuses mount operations to any restricted process, so the copy could not be rearranged and no write deny could be undone; verified on 2026-10-14 (kernel 6.8, Landlock ABI 4): the namespace is created, and `mount` answers EPERM. But a nested PID namespace could have hidden processes from the teardown scan, and nothing inside should hold a capability it has no use for.

## Decision

1. **bubblewrap runs with `--as-pid-1`: the launcher is PID 1.** It applies Landlock to itself, runs the probes, starts the relay, reports, and then forks the workload and stays as init, reaping whatever exits and ending with the workload's status. Every process in the namespace, init included, is under the same Landlock ruleset and seccomp filter: the statement holds without exception. The workload and PID 1 now share one Landlock domain, so Landlock no longer separates them. What refuses an attach from the workload is Yama's restricted scope on hosts that set it, as Ubuntu does; what makes an attach harmless on any host is that PID 1 is confined exactly as the workload is and holds no descriptor the workload lacks. The pending Debian 12 run records that host's Yama setting. The supervisor stops a sandbox with SIGKILL, which PID 1 cannot ignore; the init passes SIGTERM, SIGINT, and SIGHUP on to the workload for an operator ending one by hand.
2. **bubblewrap runs with `--disable-userns`.** bubblewrap limits the outer sandbox user namespace to one child namespace and places the sandbox in it, so the count is already at the limit: a user namespace cannot be created inside, and the kernel answers ENOSPC. The launcher probes this from inside. The doctor requires bubblewrap 0.8.0 or later, which added the option, and its namespace trial uses both flags so that it exercises what the backend uses.
3. **The outside checks change.** The supervisor checks that the init was started as `<interpreter> -m <launcher module>`, positionally, because bubblewrap's own reaper carries the same module name later in its argument list; and that every process in the namespace shows `NoNewPrivs: 1` and `Seccomp: 2`. Whether a process has a Landlock domain is not visible in /proc: that PID 1 has one rests on the launcher's own report and on the launcher applying the ruleset before it forks anything. Members are found by walking each process's PID namespace up through its parents, so a process in a nested namespace would be counted; with item 2 none can exist inside, so this is defense in depth.
4. **The probes move to `probes.py`**, a concept file of its own on the source route with a budget of 100 lines, so that the launcher keeps its narrative and its 150-line budget.

## Alternatives rejected

- **Leaving the reaper as it was and relying on Landlock's ptrace scoping.** Correct today, but it makes the confinement claim conditional on one rule a learner has to know about, and the records had not stated the exception.
- **A nested PID namespace made by the launcher, with an inner init.** It needs a second user namespace, which is exactly what the sandbox is now denied, and it adds a second init to explain.
- **Refusing `unshare` and `clone` with the user-namespace flag in the seccomp filter as well.** Belt and braces, left for later: bubblewrap's limit plus Landlock's refusal of mounts already close the path, and the filter stays small enough to read instruction by instruction.

## Consequences

- Supported hosts need bubblewrap 0.8.0 or later; both hosts in ADR 0012 (0.8.0 and 0.9.0) qualify by version. The change ran natively on the ubuntu-24.04 CI runner (bubblewrap 0.9.0, Landlock ABI 7) and on an Ubuntu 22.04 host with bubblewrap 0.9.0 built from source (STATUS.md). The Debian 12 host (bubblewrap 0.8.0, ABI 2) has not run it yet; STATUS.md lists that run as pending.
- The shipped recordings in `bundles/` were made on 2026-10-09 under ADR 0010's launcher, and their containment events name that design's probes. They are to be re-recorded on a supported host; STATUS.md says so until they are.
- Chapter 4's explanation gains two Linux-only probes (the probe table is the shared contract and is unchanged): a user namespace cannot be created inside, and PID 1 is as confined as the workload. Chapter 6 gains an example of two layers failing differently: a bind-mount-only sandbox, which a nested namespace defeats, against Landlock, which refuses the mount.
- The teardown report lists processes in nested PID namespaces too.
- macOS impact: none. The change is inside the Linux backend package and its tests; no shared contract, grant plan field, or evidence schema changes.

## Plan sections affected

PLAN.md: Open questions and defaults (Linux launcher row); Modularity (Readable source route budgets). reference/platform-differences.md: mechanism rows. CURRICULUM.md: chapter 4 explanation and Source row; chapter 9 route.
