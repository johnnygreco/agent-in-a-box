# 0013. Bundle schema v2: host paths rewritten to neutral roots

Date: 2026-10-09
Status: accepted

## Context

The owner approved publishing Linux native recordings on the website (primacy rule 4: labeled `enforcement: landlock`, replaced by macOS recordings when they exist), on the condition that published bundles name nothing from the home directory, the user name, or the toolchain location. Schema v1 bundles recorded host paths verbatim in several places:
- each run's directory;
- the grant plan's paths (workspace, the Python installation under the home directory, the checkout's virtual environment and code, the toolchain);
- the launcher's command line;
- the profile path;
- the names of the containment probes for protected paths.

## Decision

Bundle schema **v2** (`agent-in-a-box-bundle/2`). Before a bundle's id is computed, `experiments/neutral_paths.py` rewrites every string in it, at any depth, replacing these host prefixes with fixed neutral roots, most specific first:

| Host prefix | Neutral root |
| --- | --- |
| each run's directory | `/agent-in-a-box/runs/<run id>` |
| the toolchain directory | `/agent-in-a-box/toolchain` |
| the Python installation (`sys.base_prefix`) | `/agent-in-a-box/python` |
| the repository checkout | `/agent-in-a-box/checkout` |
| the home directory | `/agent-in-a-box/home` |

Both the given and the resolved spelling of each prefix are rewritten (macOS's `/tmp` is `/private/tmp`). Only whole path components match, so `/home/ann` never rewrites `/home/anna`. The bundle carries a `path_roots` table that describes each root, without its original value.

Unchanged: run ids, command ids, every hash (policy, schema, fixture, profile, binaries, bundle), the tool manifest, decisions, witnesses, and evidence order. A recorded hash still refers to the original artifact, which was hashed with its host paths in place. The bundle id is computed after the rewrite, so the import check still detects any later edit. Schema v1 bundles can still be read; new bundles are always v2.

Tests:
- an exported bundle contains neither the home directory, the checkout, the toolchain directory, or the state directory (given or resolved), nor the user name as a word (`tests/experiments/test_trailer_cli.py`);
- run ids and hashes survive the rewrite, and replay still matches;
- every bundle shipped in `bundles/` loads as a native v2 recording with no `/home/`, `/Users/`, `/root/`, `/tmp/`, or `/var/folders/` path (`tests/experiments/test_shipped_bundles.py`).

## Alternatives rejected

- **Relative paths.** These would lose the information that the grant plan names canonical absolute paths, which the profile lessons rely on.
- **Removing path fields from published bundles.** This would hide the grant plan and the launcher's command, which the inspector shows on purpose.
- **Rewriting at publish time only.** Every bundle is meant to be shareable, not only published ones. Rewriting at export keeps one format.

## Consequences

- The first native recordings are shipped: `bundles/chapter-0-trailer-9c02bb88ca3a.json` and `bundles/chapter-5-examples-and-proofs-8b064c18e62b.json`. They were recorded on 2026-10-09 on the Debian 12 host in ADR 0012, with `enforcement: landlock`, and the website's run panels now show them.
- Paths shown on the website and in notebooks for recorded runs are neutral roots, not the recording machine's paths.
- Primacy rule 4: when macOS recordings exist, they replace these in `bundles/`.

## Plan sections affected

PLAN.md: Evidence, client commands, and replay (bundle contents).
