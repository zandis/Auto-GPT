# D-460 The judge-in-the-loop property: no cut, lost note, failed verifier, re-tier, replay or batch split excludes a patient the full record keeps

- **Task:** T-706 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1)
- **PR:** this branch (`agent/T-706-judge-in-the-loop-property`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** H1, H2, H4 of `docs/reviews/2026-11-12-architecture/decision.md` (card AD-6); closes the gap of its
  answer 4 (the safety properties ran with a judge that ignores the text it is shown)
- **Builds on:** TB-PLAN-06 §7.4 ("cutting a record never turns unknown or kept into not matched"; "an unknown stays
  unknown"), D-276 (the pair, notes left out), D-95/D-97 (a single model never excludes), T-650 (the safety
  properties as tables), TB-PLAN-06.1 §5 rule 2 (a safety property must be able to fail)

## Decision

1. **An oracle pair that reads the text it is shown.** The scripted model of each test answers only from the
   excerpts in its prompt: "met" when the criterion's decisive sentence is there, otherwise a confident "not met"
   with a quote from what it was shown. The oracle knows each synthetic patient's truth from the full record. A
   patient may be excluded on a path only when the full record makes the patient ineligible and two different
   models agree; every other exclusion is a violation.
2. **Charts are generated, the operations are named.** Patients have one to four window notes of varying length,
   the decisive sentence of the inclusion and of the exclusion in any of them (or absent). The generator is plain
   Python with a fixed seed (`hypothesis` is not in the test lock; T-737 turns it into a strategy). Operations:
   the retrieval or excerpt ranking puts the decisive text last; the index lost the decisive note; the lexicon
   routes to another note; a small excerpt budget; no verifier, a verifier that is down, disagrees or is the same
   build; a SCREEN row re-tiered by MICROBATCH under another note-block decision; a replay of the recorded answers;
   the patients split into batches.
3. **Every path that reads notes, through its own entry point.** SCREEN v1 (`evaluate_scope`), SCREEN cascade
   (`screen_with_cascade`), MICROBATCH re-tier (`microbatch.run` on a pool row SCREEN wrote), NAV (`nav.run` up to
   publishing) and CASE (`evaluate_case`), each on a real lake (`tests/judge_kit.py: note_lake`).
4. **Today's defects are strict expected failures by finding id.** A case that fails today is marked with its
   finding (H1, H2, H4) and fails the suite when it starts passing, so the card that fixes it removes the mark. At
   the end of wave D (T-709, T-710) the table is empty. The cascade's S2b cut (H4, S2b half) is fixed on PR #275's
   branch: whichever of the two merges second removes that mark.
5. **Unit job, no model, no database.** The test runs in about a minute in the `unit` job.

## Consequences

- No product code changes. The table of expected failures is the measure of wave D.
- `tests/property/` is new; the unit job collects it as it collects `tests/unit/`.
