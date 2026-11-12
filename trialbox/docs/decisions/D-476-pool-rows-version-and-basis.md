# D-476 Pool rows are bound to their criteria version and to the basis of each answer

- **Task:** T-707 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1)
- **PR:** this branch (`agent/T-707-pool-version-basis`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** closes H1 and H3 of `docs/reviews/2026-11-12-architecture/decision.md` (card AD-3)
- **Builds on:** D-397 (MICROBATCH cadence and the night budget), D-95/D-97 (a single model never excludes), D-276
  (the re-tier uses the run's note-block decision), D-459 and D-460 (the two tests that measure wave D), TB-PLAN-06
  §7.4 (the pair invariant)

## Context

The candidate pool stores, per patient, the verdicts of the run that last evaluated the patient and the criteria
version of that run. MICROBATCH re-tiers the stored verdicts every week. Two defects (both confirmed by a run):

- **H1.** A sure "not met" given while a note answer may not exclude (no verifier, one model twice, a shut canary
  gate, `TB_NOTE_BLOCK=never`) was stored as `verdict: fail` with nothing that says it was not allowed to exclude.
  The next re-tier, on a night when the pair may exclude, took the stored answer as a pair's answer: the patient
  left the list although no second model ever agreed.
- **H3.** A pool row of version 1.0.0 was re-tiered under version 1.1.0: the criteria the amendment added were
  silently left out, the row could be `high`, and it was re-stamped with the new version.

## Decision

1. **A verdict says when it may not exclude.** `criterion_verdict` of `candidate_list` gains the optional field
   `final` (schema 1.3.0). `final: false` means: this answer was given when a note answer was not allowed to
   exclude, and it never excludes later, whatever the policy of a later run. The field is absent on every other
   verdict, so stored lists and goldens are unchanged. T-709 adds the answer's basis beside it and moves the rule
   into the one status function.
2. **Both pipelines write it.** The cascade writes `final: false` on a soft fail (`Outcome.hard` false); the v1
   evaluator writes it on a note fail of a run whose note-block decision is "no". `tier` treats a note fail with
   `final: false` as a reason for review, never as an exclusion.
3. **Rows stored before this decision.** A pool row whose stored tier is not `excluded` and that holds a note
   fail without the field was, by the tier rule of its run, not allowed to exclude on that answer (it would be
   `excluded` otherwise). MICROBATCH reads such a stored note fail as `final: false`.
4. **A pool row of another criteria version is screened again, not re-tiered.** MICROBATCH compares each row's
   stored version with the version in force. A row of another version is screened in full with the study's
   screening pipeline (the same call as a new patient), after the re-checks and before the new patients, inside
   the night budget; its pool row is replaced by the result, whatever the tier. A row the run does not reach (the
   budget, or the after-ingest run, which re-checks nobody) keeps its stored version in the pool and is listed as
   `review` with every criterion "not evaluated" and the action "not yet evaluated against version N": never
   `high`, never `excluded`, on verdicts of another version. The summary and the audit event `microbatch.budget`
   count both (`version_rescreened`, `version_carried`).
5. **No new limit.** The re-screens share the existing night budget (`TB_MICROBATCH_NIGHT_BUDGET`); nothing is cut
   silently (OD-10).

## Consequences

- After an amendment the first weekly MICROBATCH costs a full screen of the pool, within the night budget; the
  rest carry over and are shown as awaiting.
- `tests/property/test_judge_in_loop.py` loses its H1 line; `tests/property/test_path_independence.py` loses its
  H1 status line and its H3 lines.
- T-624's end-to-end case gains the amendment step when it is next touched (TB-PLAN-06.1 §4.2).
