# D-1126 the judged-pair store's hit rate and a second run's saving are read offline from a stored run

- **Task:** lane H, card H-16 (the judged-pair store's hit rate from a run's records; lane A2's store, D-908, the
  owner's D-519)
- **PR:** this branch (`claude/lane-h-16-pair-store-hits`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-908 (the judged-pair store), D-1111 (the offline replay and its safe extractor)

## Context

From train 43, SCREEN keeps each model's parsed answer to a note question, so the same question asked again of the
same build is read, not asked. Launch P1b (commit `3b2f5e38`, master train 44 in lane G's driver) ran with the store
on. Nobody knew how often the store answered, or what a second run of a set would save, without a paid run.

## Decision

1. `python -m tools.public_accuracy.pair_store RUN ...` reads stored sets, as the replay reads them. Tarballs go
   through `replay.safe_extract` into a new empty folder outside the repository; nothing in them is run. The tool
   prints a table, and with `--json` it writes a report (`schema_version` 1). It calls no model, no network and no
   GPU, and exits 0 when it ran (2 on an input it will not read).
2. **(a) The run's own record:** each SCREEN report's `cascade.judged_store` (`on`, `read`, `live`) and
   `metrics.pairs_judged`. The hit rate is `read / (read + live)`, with numerator and denominator. Beside it come the
   traced note-question calls (prompt `judge@n`), by model alias, with schema repairs counted apart, and the jobs
   whose store count differs from their traced questions.
3. **(b) A second run of the same set on the same box** finds again each question whose answer the store would have
   kept, except the first question of each model in each job (D-908: a model that has not answered live in the job
   reads nothing). Two of the store's own functions are imported, never copied:
   - `orchestrator.judged_store.parsed` decides which answers are kept;
   - `JudgedPairs.key` gives the store's own key when a trace carries the cascade's question (`tb.asking`).
   Otherwise questions are told apart by the part of the key the traces hold: the model alias, the build, the served
   prompt and `matching.cascade.judge.question_digest` of the traced input. The parts not recorded are named. Time
   and US$ (at US$2.74 a VM hour) are an estimate: each job's span of note-question traces, divided by its questions.
   The seconds of one call are "not measured".
4. **(c)** A question asked again in the same run, in its job or a later one, is counted by protocol, together with
   the repeats the store should have answered by its own rule.
5. **(d)** What the records could not tell is printed by name. A saving that cannot be derived is never claimed.

## Figures

On P1b (`docs/plan/measurements/pair-store-2026-11-17.md`):

- the store was on in all 65 SCREEN reports;
- the run's hit rate was 0 of 1,050, and no question was asked twice;
- a second run at the same index date would find again 989 of 1,057 questions (999 gateway calls), about 312 s and
  US$0.24, an estimate.

## Test

`tests/unit/test_h16_pair_store_2026_11_17.py`, on made-up runs in the records' real shape. It covers:

- the hit rate's arithmetic;
- repairs counted apart;
- a second run's saving and its first-live rule;
- the time estimate;
- a repeat in a later job, and one before the model's first answer;
- the missing key parts named;
- the store's own key equal to the one SCREEN's guarded client writes;
- a run with no store records;
- the safe extractor's refusals.
