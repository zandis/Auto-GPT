# D-1107 a protocol that fails before or in SCREEN is its own line, by class, and stays in the denominator

- **Task:** lane H, card H-3 (the scorer, S1 to S4 of the integrator's list on #649, 2026-11-16T11:52:42Z)
- **PR:** this branch (`claude/lane-h-3-scorer`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-1108 (a set with nothing screened is not scored, by name)

## Context

Launch P1b's sigir set had 103 protocols. The scorer said nothing about the 40 that gave no SCREEN: its pair and
criterion rates count only the rows the box answered, and a pair on a protocol that failed FEAS was one of the
"unanswered", next to pairs whose patient SCREEN simply did not scope. The record on #639 read "27 failed in FEAS, 2
approve failed, 1 FEAS timeout, 10 not run (time budget)". The stored states (`answers.json`) say otherwise for 8 of
the 27: FEAS and APPROVE were done and SCREEN failed (`reporting` ValidationError 3, `running` "no coded criterion,
set max_pairs" 4, `judging` a model that did not answer 1).

## Decision

1. The score has a `protocols` block per set: the protocols of the set (from the gold's `ids.json`), those in
   `answers.json`, screened, compiled (a compile-only set), cut by the time budget (`not_run_time_budget`), failed
   before SCREEN (FEAS, APPROVE), failed in SCREEN, unfinished, and not in `answers.json`.
2. A failure has a stable class, `<stage>_<step>`, read from the job's stored error, or the driver's outcome:
   `feas_equivalence`, `feas_ir_extract`, `feas_cql_translate`, `feas_timeout`, `feas_refused_by_tripwire`,
   `feas_refused_at_intake`, `feas_ended_<state>`, `approve_<state>`, `approve_refused_at_intake`, `screen_<step>`,
   `screen_refused_by_gateway`, `screen_refused_at_intake`. An answer of the in-process dry run (no `outcome`) is read
   the same way. Each class row names its rulesets and one error message.
3. A budget cut is not a failure and is not attempted. Attempted = screened + compiled + failed + unfinished. The
   failure share is failed / attempted, and failed-before-SCREEN / attempted is said beside it.
4. The target is the named boolean `fewer_than_one_in_ten_failed`: failed before *or in* SCREEN, under one in ten
   of those attempted. A protocol that failed in SCREEN gave no answer either, so it counts.
5. Each pair and criterion rate states its denominator (`denominators`). Every gold pair (`pairs_in_gold`) and gold
   criterion row (`rows_in_gold`) outside a denominator is counted by the status of its protocol
   (`unanswered_by_protocol`, `not_answered_by_protocol`), so rows on a protocol that never screened stay in sight.

## Test

`tests/unit/test_h3_scorer_2026_11_17.py`: P1b's stored outcomes (fixture, ids renamed) give 63 screened, 22 failed
before SCREEN, 8 in SCREEN, 10 cut, 30 of 93 attempted, eight classes, target not met; one case per driver outcome;
pairs and criterion rows on a failed or cut protocol are counted by status.
