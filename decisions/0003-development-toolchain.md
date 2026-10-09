# 0003. Development toolchain: Python 3.12.15 with uv, Rust for the Cedar bridge, Node deferred

Date: 2026-10-09
Status: accepted

## Context

PLAN.md defaults to Python 3.12 or later with `uv` and `pytest`, a pinned Node LTS for the website, and an ADR for the Python and Node versions. Milestone 0 also introduced a Rust bridge (ADR 0002), which needs a Rust toolchain. This host has system Python 3.11.2, which is too old, and Rust 1.95.0 installed with rustup under the user's home.

## Decision

- **Python 3.12.15**, installed by uv into the user's uv directory (no system change), recorded in `.python-version`; `requires-python = ">=3.12"`. 3.12 is the oldest version mitmproxy 12 supports, which keeps the macOS and Linux matrices widest.
- **uv 0.12.24**, installed into `~/.local/bin` from the GitHub release archive after checking its published sha256 (`b4dfaef4…3da6` for Linux x86_64). `uv.lock` pins every Python dependency with hashes; `uv sync` reproduces the environment.
- **pytest 9.1.1** and **ruff 0.16.10** in the `dev` dependency group. Ruff's import-sorting rule is disabled because it rewrites wrapped imports one name per line, which inflates the teaching source route's line budgets; imports are kept sorted by hand.
- **Rust: minimum 1.89** (the declared minimum of cedar-policy 4.12.0 and cedar-policy-symcc 0.6.0), built and tested with 1.95.0 from rustup. Required for `native/cedar-bridge` and, on platforms without a wheel, for building cedarpy.
- **Node: deferred** to the website scaffold; decided later the same day in ADR 0006 (Node 24.21.0 LTS).
- Tool binaries for Cedar live in `.toolchain/` inside the repository (ignored by version control), installed by `python3 tooling/bootstrap.py`. Nothing is installed system-wide.

## Alternatives rejected

- **Python 3.13.** Equally available through uv, but 3.12 widens support with no feature we need from 3.13.
- **System Python 3.11.** Below the plan's minimum and below mitmproxy 12's.
- **Ruff's import sorting with a forced single-line style.** It cannot keep long imports compact under a 100-column limit.

## Consequences

- Setup needs uv and rustup, both user-local. The README states this.
- A CI configuration (`.github/workflows/ci.yml`) is written but not run, because the repository has no remote; see STATUS.md, Questions for the owner.

## Plan sections affected

PLAN.md: Open questions and defaults (Python and Web rows).
