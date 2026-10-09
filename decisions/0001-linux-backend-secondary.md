# 0001. Schedule a Linux enforcement backend as a secondary target; macOS Seatbelt remains primary

Date: 2026-10-09
Status: accepted

## Context

The plan's native backend is macOS Seatbelt. The development workspace is Linux, and an autonomous implementing agent on it could complete all platform-independent work but could never close a native gate. The learner persona may not own a Mac. The owner asked whether a Linux substitute for Seatbelt exists and whether the project could work 1:1 on both platforms.

A host probe on 2026-10-09 found this workspace capable: kernel 6.1, Landlock ABI 2 enabled in the LSM list, unprivileged user, network, PID, and mount namespaces working, bubblewrap installed, seccomp filtering enabled. No single Linux mechanism matches Seatbelt; Landlock, a network namespace, seccomp, and bubblewrap together reproduce the boundary this project needs. Parity is achievable at the contract level (same grant plan, probe outcomes, evidence schema, conformance suite), not at the mechanism level.

## Decision

Schedule the Linux backend as Milestone 1-L, a secondary track alongside Milestone 1. macOS Seatbelt is the primary backend and the product. The macOS experience is never reduced, delayed, or reshaped for Linux parity. The backend boundary is a narrow protocol with per-backend packages, per-platform native directories, capability flags, and one conformance suite parameterized over backends.

The owner's words: "the macOS Seatbelt implementation is the top priority. We should never sacrifice any part of the macOS experience for parity on Linux. It also needs to be very cleanly modular as a backend."

## Alternatives rejected

- **macOS only.** Rejected because it leaves an autonomous agent on this workspace unable to close any native gate and excludes learners without a Mac.
- **Linux first or co-equal.** Rejected because the owner's priority is the macOS experience, and co-equal status would let Linux limits shape shared contracts.
- **A Linux-specific semantic shell or container-based boundary.** Rejected because it would not share the grant plan and probe contract with Seatbelt and would drift from the teaching model.

## Consequences

- PLAN.md gains invariant 11 (macOS primacy), six primacy rules under Platform decision, a Backend module boundary section with the protocol and capability flags, and a scheduled Milestone 1-L.
- The SBPL renderer and SeatbeltBackend define what the conformance suite expects; LandlockBackend conforms. Linux gaps are expected-fail with reasons, never removed tests.
- Shipped bundles and figures come from macOS whenever a macOS run exists.
- Release 1 ships on macOS gates; Linux is included only if its gate has passed, otherwise labeled experimental.
- Any shared-contract change motivated by Linux needs an ADR stating macOS impact is nil; otherwise the implementing agent stops and asks.
- The doctor must check Landlock ABI and disclose that ABI 2 hosts do not control truncate, or require ABI 3 or later.

## Plan sections affected

PLAN.md: Status; Definition of done; Invariants; Decision authority; Working on Linux; Platform decision; Open questions; Architecture diagram label; Scope limits and explicit non-claims; Modularity (table and Backend module boundary); Repository layout; Milestones and gates (ordering, M1-L, M2). STATUS.md: M1-L gate. reference/platform-differences.md: primacy note.
