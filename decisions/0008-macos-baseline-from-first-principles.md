# 0008. The macOS baseline is authored from first principles, one reasoned rule at a time

Date: 2026-10-09
Status: accepted

## Context

A Seatbelt profile that starts from `(deny default)` must still let the workload start: load the dynamic loader and system libraries, read a little system data, use the null device, and look up its own user. These rules have nothing to do with the task, so PLAN.md requires them to be disclosed separately from task grants. The owner ruled on 2026-10-09 that the public tree holds no adapted third-party material, so the Milestone 0 baseline list had to be replaced with one we author ourselves.

## Decision

`src/agent_in_a_box/supervisor/backends/seatbelt/os_baseline.py` holds one `Entry` per rule. Each entry names the SBPL operation, its filter, and a one-sentence reason. The renderer prints every rule after its reason as an SBPL comment, so the installed profile explains itself. The list is derived from what a Python process and its shell children do at startup on macOS:

- process creation (`process-fork`) and signals only within the process tree (`signal (target same-sandbox)`);
- reading kernel parameters (`sysctl-read`), disclosed as broader than necessary and to be narrowed to named parameters in Milestone 1;
- reading the dynamic loader and on-disk system libraries (`/usr/lib`), system frameworks (`/System/Library`), and the dyld shared cache in the OS cryptex (`/System/Volumes/Preboot/Cryptexes/OS`);
- time zone data (`/usr/share/zoneinfo`, the `/private/etc/localtime` link, and its target under `/private/var/db/timezone`) and ICU data (`/usr/share/icu`);
- the null device (read and write) and `/dev/urandom` (read);
- metadata on `/` and on the `/etc`, `/var`, and `/tmp` symbolic links, which path lookup has to read;
- the directory-service Mach lookup that answers `getpwuid` and `getgrgid`.

Constraints, enforced by `tests/backends/test_seatbelt_profile.py`: every entry has a reason; no entry names a path under `/Users`, `/Volumes`, or `/private/var/folders`; the only writable baseline path is `/dev/null`; the baseline contains no network rule.

## Alternatives rejected

- **Importing Apple's shipped profile library (`(import "system.sb")`).** It is written for application sandboxes. It grants far more Mach services and paths than a command-line workload needs, and its contents change between releases without being visible in our profile text.
- **Granting broad system trees (`/usr`, `/Library`, `/private/var`).** These would be simpler and harder to explain, and they include writable or user-adjacent locations.

## Consequences

- The list is unconfirmed until Milestone 1 runs it on a Mac. Each missing rule found there is added with the failure that showed it was needed; each unnecessary rule is removed. STATUS.md records the macOS build on which the list was confirmed.
- The Linux backend will need its own baseline for its mount view; this ADR covers macOS only.
- macOS impact: this is the macOS backend's own baseline; no shared contract changes.

## Plan sections affected

None of PLAN.md's text changes; this implements Supervisor ("Disclose required Python and system-library access separately from task grants") and Filesystem grant extraction ("necessary runtime files") for the Seatbelt backend.
