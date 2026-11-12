# D-459 The path-independence test: one patient, one snapshot, every path that decides or counts patients

- **Task:** T-705 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; card AD-5 of
  `docs/reviews/2026-11-12-architecture/decision.md`)
- **PR:** this branch (`agent/T-705-path-independence-test`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** the "tests follow modules, not paths" cause of TB-PLAN-06.1 §2 for the decision path (R4 of the
  decision review); makes H1 to H4 and M1 to M5 of that review measurable
- **Builds on:** D-383 (the snapshot pin inside a job), D-441 (one opt-out register), D-448 (expected failures that
  name their card and fail when they start to pass), T-652 (the decision table)

## Decision

1. **One small lake, one scripted pair that reads.** `tests/judge_kit.py` holds a judge whose answer depends only on
   whether a criterion's decisive sentence is in the excerpts it is shown (`QuotingJudge`), a verifier that can agree,
   disagree or fail, and a pair built from both. The decisive sentence is configured per criterion. It is the judge
   of T-705 and T-706; its interface is small and documented in the module.
2. **Every path is driven in process on the same snapshot**: SCREEN v1, SCREEN cascade, MICROBATCH new patients,
   MICROBATCH re-check, NAV, CASE, FEAS and COHORT (`tests/property/test_path_independence.py`). The test asserts:
   the same patient gets the same verdict and the same status on every path; an opted-out patient is in no published
   bytes of any path (lists, pool, workbook, mail body, evidence files).
3. **Intended differences are a named table** in the test (`INTENDED`), one line per difference with its reason and
   decision number. A card that adds a path that decides or counts patients adds it to the test (plan v6.1 §5.1).
4. **Today's unintended differences are strict expected failures**, each naming its finding id (H1 to H4, M1 to M5).
   A card that fixes one removes its expected failure: an expected failure that starts to pass fails the test.
5. No product code changes. The module runs in the `unit` job (no docker, no pgvector).

## Consequences

- The table of expected failures only shrinks: T-707, T-708, T-709 and T-710 each remove the lines they fix.
