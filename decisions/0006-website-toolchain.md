# 0006. Website toolchain: Node 24.21.0 LTS, Astro 7.3.8 with MDX, telemetry off

Date: 2026-10-09
Status: accepted

## Context

PLAN.md specifies Astro with MDX and TypeScript islands on a pinned Node LTS, recorded by ADR. ADR 0003 deferred the Node version until the website scaffold started. The M0 scaffold renders chapters 0 and 5 from development bundles produced under the test backend.

## Decision

- **Node 24.21.0** (Krypton, the current Active LTS on 2026-10-09), installed user-locally with nvm, which verified the archive checksum. Pinned in `website/.nvmrc` and in `engines` (`>=24.21.0 <25`).
- **Astro 7.3.8** and **@astrojs/mdx 8.0.3**, exact versions in `website/package.json`, with every transitive package pinned in `website/package-lock.json`.
- **Astro telemetry is disabled** in every npm script (`ASTRO_TELEMETRY_DISABLED=1`), per invariant 8.
- **No TypeScript islands yet.** The scaffold is static. Predictions are `<details>` reveals, so nothing is stored or scored. Islands arrive with hosted interactivity in Milestone 2.
- **Evidence logic stays in Python.** `agent-in-a-box site-data` builds view models from bundles (`experiments/views.py`). The site renders them and computes no evidence itself. A result label that is not a glossary term fails the build (`components/Label.astro`).
- Generated data in `website/src/data/` is ignored by version control. Test-backend bundles are never shipped.

## Alternatives rejected

- **Node 26.** It is current, not LTS, until late October 2026.
- **Computing views in TypeScript from raw bundles.** That would duplicate evidence logic in two languages.

## Consequences

- Website builds need Node; `tests/website/test_site_build.py` skips without `website/node_modules`.
- Upgrading Node or Astro is a new ADR.

## Plan sections affected

PLAN.md: Open questions and defaults (Web row).
