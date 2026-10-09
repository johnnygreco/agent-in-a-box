# Architecture decision records

One file per decision, named `NNNN-short-title.md`, numbered in order. Write one whenever [PLAN.md](../PLAN.md)'s decision authority table says "record an ADR." Edit the affected PLAN.md or CURRICULUM.md section in the same change and cite the ADR number there.

Template:

```markdown
# NNNN. Title

Date: YYYY-MM-DD
Status: accepted | superseded by NNNN

## Context
What question had to be answered and why now.

## Decision
What was chosen.

## Alternatives rejected
Each with the reason.

## Consequences
What becomes easier, harder, or newly constrained. Any invariant touched.

## Plan sections affected
PLAN.md or CURRICULUM.md headings changed in this same revision.
```
