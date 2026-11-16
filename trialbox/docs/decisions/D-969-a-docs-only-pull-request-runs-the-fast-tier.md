# D-969 a docs-only pull request runs the fast tier

- **Task:** CI THROUGHPUT, lane D (the integrator, #639, 2026-11-16: "CI is now the project's bottleneck"); change A
  of the measurement posted on #639 the same day
- **PR:** this branch (`agent/CI-DOCS-docs-only-prs-run-the-fast-tier`)
- **Date:** 2026-11-16
- **Status:** accepted
- **Builds on:** D-564 (the tiers), D-578 (a proved master push runs the fast tier)

## Context

Measured over 24 hours (682 runs): a full CI run is 118 to 182 runner-minutes (median 141) across 23 to 24 jobs, and
the limit is concurrency, not money. A card's pull request that changes only documents ran all 24 jobs, because the
`changes` job said `trialbox=true` for any `trialbox/**` file. Only the box rehearsal already skipped such a pull
request.

## Decision

1. `tools/ci_docs_only.py` (standard library; the `changes` job runs it with the runner's python3) decides whether
   every changed file of a pull request is a document:
   - A document is any file under `trialbox/docs/`, or any `.md` file.
   - The exceptions are the documents code reads (`CODE_READS`): the licence register, which the licence check reads
     and the image carries, and the model change protocol, which the image carries for `qualify`. A test checks that
     every `docs/` path either Dockerfile copies counts as code.
2. A card's pull request that is docs-only runs the **fast tier** (D-564), as a draft does. A merge train (`train/*`),
   master and a run by hand run the full tier, whatever they hold, so nothing reaches master untested. No check is
   removed from the train.
3. The tests that read the changed documents still run on the card. The tool lists the test files that name a
   changed document by its path below `trialbox/`, its file name, or its folder (`docs/runbook`; not `docs` alone).
   The fast tier's `cross-card` job runs them through the same `make cross-card` recipe (`CROSS_CARD_TESTS` given),
   with PostgreSQL. The `checks` job (doclint, decision numbers, data scan) runs as on every push.
4. `tests/unit/test_ci_tiers.py` reads the tier step's environment exactly. It now expects `DOCS_ONLY` and has the
   docs-only cases.

Saving (estimated from the measurement): about 133 runner-minutes for each docs-only push; about 2,100 a day if one
full run in ten is docs-only.

Not here, and waiting on the integrator's yes:
- skipping goldens, e2e-simple or demo-boot on a pull request that changes only `deploy/`, `tools/` or `.github/`
  (these guard screening results);
- running the full tier on the train only.

## Test

`tests/unit/test_ci_docs_only.py`:
- what counts as docs-only;
- the documents an image carries are not;
- the test selection (path, file name, folder, not `docs` alone, test files only), and on this tree a runbook page
  has its tests;
- the command line;
- standard library only;
- the workflow's wiring.

`tests/unit/test_ci_tiers.py`: the docs-only cases (a card runs the fast tier; a train, master and a run by hand run
the full tier).
