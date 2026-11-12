# D-572 One limit for the branch slug of a test root, in one place

- **Task:** PGLOCAL-SLUG (given to lane D by the integrator on 2026-11-12: `tools/pglocal.py` cut the slug at 60,
  `tests/unit/test_test_isolation.py` asserted 40, so `make cross-card` failed locally on a branch name over 40
  characters)
- **PR:** this branch (`agent/PGLOCAL-one-slug-limit`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-201 (every temporary root of a run derives from `TB_TEST_ROOT`, one per branch:
  `<scratch>/tb-tests-<branch slug>`), D-126 (`tools/pglocal.py`: a throwaway PostgreSQL cluster per test worker)

## Context

The branch's name becomes one path segment of the test root. Two numbers said how long it may be: the tool cut at
60, the test demanded 40. A branch name between 41 and 60 characters failed the cross-card list on a developer's
machine and passed in CI, where the checkout is detached and the slug is short.

## Decision

1. **One constant, `pglocal.SLUG_MAX = 40`, with its reason beside it.** A PostgreSQL socket path may be at most
   107 bytes (the kernel's limit for a Unix socket address). Under the default scratch folder the path is
   `/var/tmp/trialbox-<uid>/tb-tests-<slug>/pg-gw<n>/run/.s.PGSQL.<port>`: about 64 bytes beside the slug with a
   five-digit uid, a two-digit worker and a five-digit port. 40 leaves the rest; 60 does not.
2. **A longer name keeps its start and gains a short hash of the whole name**, so two branches that share their
   first 40 characters do not share a test root. A name of 40 characters or fewer is unchanged.
3. The test reads the constant; it holds no number of its own.

## Consequences

- A branch with a long name gets a test root named after its start and eight hex characters.
- No setting: the limit follows from the kernel's and from the layout of the root.
