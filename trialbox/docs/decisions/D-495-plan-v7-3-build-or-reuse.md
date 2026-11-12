# D-495 Plan v7.3: build or reuse; what stays ours and which cards use an open project

- **Task:** none (the plan itself; `docs/plan/33-plan-v7.md`, TB-PLAN-07, version 7.3, section 3.4)
- **PR:** by merge train (branch `docs/plan-v7.3-reuse`)
- **Date:** 2026-11-12
- **Status:** accepted; the owner's rule of 2026-11-12
- **Builds on:** D-494 (plan v7.1), D-577 (the embedding server tested, ours kept), D-186 (the release gates)

## Context

The review `docs/reviews/2026-11-12-build-vs-reuse.md` sorted every mechanism of the product into three groups: an
open project can replace it, an open project does part of it, nobody does it. The owner then set the rule.

## Decision

1. What is built and verified stays, unless an open project is clearly better. Evidence decides: the embedding
   server was the review's first candidate, lane D tested it the same day, and ours stays (D-577).
2. A card not yet started uses an open project where that fulfils the plan. Plan section 3.4 names the five cards.
3. No dependency is added without a reuse proposal in the card's pull request: the project, its licence, its
   pinned version and what the release gates say about it. Every new pull request carries a "Reuse check" line.
4. Four home-made pieces get no new feature before go-live (plan section 3.4).
5. A third-party image a bundle carries is in the release gates' image list. Where its newest published version
   fails, the owner alone accepts findings: dated entries scoped to the pinned image, each with the reason the
   finding cannot be reached as the box runs it, and a review date.

## Consequences

The dates of plan section 4 do not move. The saving is the review's estimate, not a measurement. Not proven:
restic at the dense profile (a spike in wave 2), DPAPI under the boot task's sign-in type (NEW-WIN-8's first test),
and the tokenisers' effect on the tripwire's false refusals (measured on the first day of NEW-LLM-3).
