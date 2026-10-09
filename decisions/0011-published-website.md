# 0011. The published website: GitHub Pages from CI, built only from publishable evidence

Date: 2026-10-09
Status: accepted

## Context

The owner decided to publish the course website early, at https://johnnygreco.dev/agent-in-a-box/ (a GitHub Pages project site; the owner's user site carries the custom domain, and the `github.io` address redirects there). PLAN.md's publishing rules say the site may show only platform-independent analysis results generated in CI with the pinned toolchain, and native-recorded bundles. A test-backend bundle must be refused, a lesson without a native recording must say so, and every published result must carry its evidence label and tool manifest. No native bundle exists yet.

## Decision

**Deployment.** A `pages` job in `.github/workflows/ci.yml` runs on pushes to `main` after the `platform-independent` job passes on both runners. It:
- bootstraps the pinned toolchain;
- generates the published data;
- builds the Astro site;
- deploys it with `actions/configure-pages@v6.0.0`, `actions/upload-pages-artifact@v5.0.0`, and `actions/deploy-pages@v5.0.1`.

The job has only `contents: read`, `pages: write`, and `id-token: write`. Its `concurrency` group allows one deployment at a time: a newer push replaces an older pending deployment, and a deployment already running finishes.

**Base path.** Astro's `site` is `https://johnnygreco.dev` and `base` is `/agent-in-a-box`. Both can be overridden by environment variables for local previews. Every internal link and asset goes through `website/src/lib/url.ts`, and a build test fails on any root-relative link that misses the base path. The README banner is copied from `assets/banner.svg` into the site at build time (ignored by git), so there is one source.

**Published data** (`agent-in-a-box site-data --published`, `experiments/publish.py`):
1. *Analysis, produced at build time.* These are real results from the pinned toolchain, independent of any backend:
   - chapter 5's ladder: P0→P1 with the POST witness and its two-sided replay; P0→P2 with its PUT witness; the repair P1→P0; deny-all P1→P3 with both task checks; and the deliberately starved "no conclusion";
   - chapter 0's verify and repair checks;
   - the bounded method × path matrix for P0, P1, and P2;
   - Cedar's decision on the original GET under P0 and P1.
   
   Each result is labeled recorded, with "analysis only: no agent ran", and the Cedar, SymCC, and solver versions from the tool manifest.
2. *Native recordings* are read from `bundles/` with the importer's native mode. It refuses an empty enforcement or any `none`, and the publish step stops with "Refused to publish" and the bundle's name. Development bundles are never read.
3. *Placeholders.* Every run panel without a native recording renders "No native recording yet. This run arrives with Milestone 1-L (Linux) or Milestone 1 (macOS)."

The page banner states the build date and toolchain, says that the results are analysis only, and says that no native run has been published yet. Until a native bundle is published, no chapter page uses the words contained, containment, enforced, or sandboxed; a build test checks this.

**Development mode** (`site-data --trailer … --chapter5 …`) still renders full run panels from test-backend bundles for local work. Its banner says it is a development build, and it is never deployed.

## Alternatives rejected

- **Committing generated site data.** It would go stale against the toolchain and policies, and could carry development results by mistake. The data is generated in CI from the pinned toolchain instead, and `website/src/data/*.json` stays ignored.
- **Showing test-backend runs labeled `enforcement: none`.** The publishing rules forbid it: a learner could read a test-double run as evidence of a boundary.
- **A separate deployment workflow.** It would need its own copy of the toolchain setup; one workflow with `needs:` keeps the tests as the gate.

## Consequences

- Each push to `main` redeploys the site, and build-time analysis is recomputed with the toolchain pinned in that commit.
- When Milestone 1-L records native bundles into `bundles/`, run panels fill in automatically with `enforcement: landlock`. Per primacy rule 4, macOS recordings replace them when they exist.
- Hosted Cedar interactivity (WebAssembly or precomputed tables) is still Milestone 2 work. The published site is read-only.

## Plan sections affected

PLAN.md: Product shape (Publishing rules; Website design, Deployment bullet); Milestone 2 deliverables (the Pages pipeline).
