# 0007. Split the backend's `teardown` into `wait` and `stop`

Date: 2026-10-09
Status: accepted

## Context

PLAN.md's `SupervisorBackend` protocol ended with `teardown(process, deadline_s) -> TeardownReport`. As implemented in Milestone 0, that one call meant "wait for the workload to exit by itself, up to the deadline, then stop the tree". A chapter 9 reader would not guess both phases from the name. It also forced the lifecycle module to run `teardown` on a helper thread while polling for evidence. The owner's reviewer raised this before the contracts freeze at Milestone 2.

## Decision

Replace `teardown` with two methods:

```python
def wait(self, process: ContainedProcess, deadline_s: float) -> int | None: ...
def stop(self, process: ContainedProcess) -> TeardownReport: ...
```

`wait` returns the exit status, or None if the workload is still running after `deadline_s`. `stop` stops the whole process tree, descendants included, and reports what it stopped, what survived, and what it could not verify. `supervisor/lifecycle.py` now reads as a sequence: poll evidence, `wait` briefly, repeat until exit or the deadline, then record which happened, then `stop`.

The change is motivated by readability, not by either platform. macOS impact: none. The Seatbelt backend's responsibilities are unchanged (it still must stop detached descendants by process accounting), and no requirement, guarantee, test, or default is weakened. Both phases existed before; they are now named.

## Alternatives rejected

- **Keep one method and rename it** (for example `wait_then_stop`). This would still need a thread in the lifecycle module to collect evidence while it blocks.
- **An asynchronous protocol.** That is more machinery than one supervisor per run needs.

## Consequences

- Run records gain a `workload_exited` or `deadline_reached` lifecycle event before `workload_stopped`.
- The conformance probe "detach and sleep, killed at teardown" keeps its CURRICULUM.md wording; it is checked against `stop`'s report.

## Plan sections affected

PLAN.md: Modularity and careful abstractions, Backend module boundary (protocol listing and the paragraph after it).
