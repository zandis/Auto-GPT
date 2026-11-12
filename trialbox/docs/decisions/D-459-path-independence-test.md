# D-459 The path-independence test: one patient, one snapshot, every path that decides or counts patients

- **Task:** T-705 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; card AD-5 of
  `docs/reviews/2026-11-12-architecture/decision.md`)
- **PR:** #283 (`agent/T-705-path-independence-test`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** the "tests follow modules, not paths" cause of TB-PLAN-06.1 §2 for the decision path (R4 of the
  decision review); makes the review's findings H1 to H4 and M1 to M5 measurable (none is fixed here)
- **Builds on:** D-383 (the snapshot pin inside a job), D-441 (one opt-out register), D-448 (expected failures that
  name their card and fail when they start to pass), D-276 (the scripted judges of `tests/judge_kit.py`)

## Decision

1. **A pair that reads.** `tests/judge_kit.py` gains `QuotingOracle`, `Decisive` and `quoting_pair`: two scripted
   models of different builds whose answer depends only on whether a criterion's decisive sentence is among the
   excerpts they are shown (the first sentence shown, in rule order, decides; none shown is `unknown`). The
   verifier agrees, disagrees, is unsure or is down. The oracle records what each question was shown (`asked`) and
   what a reader of the whole record answers (`full`). T-706 uses the same interface.
2. **One small lake, every path, in process.** `tests/property/test_path_independence.py` builds 17 planted patients
   as FHIR NDJSON (one lake snapshot, the lake's own rebuild), approved copies of one five-criterion ruleset under a
   trial manifest and an NHI manifest, and the in-process box (`tests/inproc_box.py`: gateway, orchestrator, job
   database). It runs SCREEN on the cascade (the reference) and on v1, the MICROBATCH re-check and its screen of new
   patients, NAV, CASE with the chart number for every patient, FEAS (its own `compute`, read through a spy) and
   COHORT (its own count functions at the run date), then the same paths with one model (`TB_SCREEN_JUDGE=single`)
   and after an amendment.
3. **What must hold.** Per patient: the path's status, read through the named table `INTENDED` (each line a reason
   and its decision: NAV's lists, CASE's sheet, counts read no notes, contact denial is not an opt-out, the FEAS
   and COHORT populations, the re-check's scope), equals the reference's; every verdict both paths publish is the
   same; the opted-out patient is in no published file of any path (zip members and PDF text read), no pool row and
   no mail.
4. **Today's differences are strict expected failures** in `KNOWN`, one line per (path, patient, aspect), each
   naming its finding: H1, H2, H3, H4, M1 (a, b), M2, M4 and CR-026; M3 (the console's register read) and M5 (the
   full-record limit) are their own strict expected failures. A line whose check passes fails the run; a line no
   check reads fails `test_every_known_difference_and_every_decision_is_used`.
5. **No product code changes.** The world is built once per run (about 45 s on one core; the xdist workers share it
   under a file lock) in the `unit` job: no docker, no pgvector, the throwaway PostgreSQL of the suite.

## Consequences

- The table only shrinks: T-707, T-708, T-709 and T-710 each remove the lines they fix, and a card that adds a path
  that decides or counts patients adds it (plan v6.1 §5.1).
- PR #275 (the cascade's left-out count) and PR #262 (stored scores) change what a path shows; when they merge, a
  line may start to pass or a new difference appear, and the merging card updates `KNOWN`.

## Open

- The COHORT job itself and the console's pages are not driven: COHORT publishes suppressed counts and compiles
  the cassette's trials (its membership is read from its count functions); the console's list is the stored list
  filtered by `OptOutRegister.active()`, which the M3 test calls directly.
- The cascade half of H4 (a note with no lexicon hit and no top-5 sentence is not counted as left out) is not
  planted: PR #275 owns it.
