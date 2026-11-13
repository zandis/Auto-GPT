# D-646 A share of a study's night allowance is kept for its excluded patients

- **Task:** NEW-LIFE-5, the follow-up of D-642 (NEW-LIFE-4); the owner's ruling of 2026-11-13, relayed by the
  integrator: "a share of each study's nightly budget is kept for re-screening its excluded patients, so re-checks
  and new patients cannot starve them; a declared setting with its reason (OD-10), default one quarter"
- **PR:** this branch (`agent/NEW-LIFE-5-excluded-share`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)

## Context

D-642 screens a study's excluded patients again each week, after the pool's re-checks and the new patients, inside
the job's allowance of the night budget. Measured for D-642 (the weekly load, synthetic site): screening excluded
patients again costs about 24 s of engine time and 20 to 40 model calls per 1,000; a study of GZQO's shape among
five, at 50,000 patients, fills its allowance with re-checks, so its excluded patients are never reached.

## Decision

1. **The setting.** `TB_MICROBATCH_EXCLUDED_PERCENT` (an integer from 0 to 100, default 25; declared in
   `libs/tb_common/config.py`): that part of a weekly job's allowance is kept for its excluded patients. The
   reason for a quarter: the measurement above; with a quarter, a full pass over a study's excluded patients takes
   four times as many runs as its allowance alone would need, and the re-checks keep three quarters.
2. **Kept only for somebody.** Before it spends anything the weekly run counts the excluded patients in the
   study's scope (the scope a screen would look at, the stored lists, the pool's excluded rows) and keeps
   `min(allowance x percent / 100, that count)` places. With no excluded patient in scope nothing is kept. The
   re-checks, the rows of another criteria version (D-476) and the new patients share the rest, in D-642's order.
3. **Nothing idle.** The excluded patients get what is kept and whatever the others leave. The count is taken
   before the run's own re-check, which can change who is excluded; a place kept and then not needed goes to a
   waiting new patient.
4. **What the run says.** The summary's line reads "Earlier excluded patients screened again: N of M in scope";
   when some are carried over it adds how many weekly runs a full pass takes at the share kept. The audit event
   `microbatch.budget` gains `excluded_in_scope`, `excluded_percent`, `excluded_kept` and
   `excluded_full_pass_runs` (null: nobody is in scope, or nothing is kept, so no run is sure to reach them; item 8).
5. **Where it does not apply.** The after-ingest run brings nobody back (D-642) and keeps nothing. With no night
   budget (0) everybody is reached in one run. With `incident=0` no new or excluded patient is screened, and
   nothing is kept. `0` restores D-642's order exactly.
6. **One scope query.** `orchestrator.scenarios.screen.screen_scope` gives the scope; the weekly run hands it to
   `run_screen(scope=...)` so the lake is not asked twice.

7. **From the review of this card.**
   - The number of places kept is fixed on the job's first run (option `excluded_kept`), as the allowance is
     (`night_left`): the count reads the pool's stored tiers, which the job's own re-check rewrites, so a resumed
     job counted otherwise and re-checked other patients.
   - A share that comes to less than one patient (an allowance of 3 or fewer at 25 %) keeps nothing: the summary
     says so, and no longer says the setting is 0. Rounding up was not chosen: with an allowance of one or two,
     it would give the excluded patients every place and the pool's re-checks none.
   - The sentence "a full pass takes N weekly runs" is printed only where the count of excluded patients in scope
     is itself printed (not small-cell suppressed): with the places a run keeps, N gives that count away. The
     audit holds the figure either way.

8. **The full-pass figure agrees with how the night went** (lane C2's finding in the review of its run page,
   2026-11-13, and the review of the first fix). The figure could say "1 run" while some were carried: the count
   before the run does not hold the patients the run's own re-check excludes, so fewer places were kept than the
   share allows. Now, in the audit and the summary:
   - nobody in scope, or the after-ingest run: null;
   - nobody carried: 1, the pass was made tonight (whatever the share, also 0);
   - somebody carried: the number in scope divided by what a run keeps once all of them are counted at its start
     (the share of the allowance, at most the number in scope), rounded up, and at least 2; null when that share
     is no place at all (a share of 0, or under one patient: the summary says which).
   It is not divided by the places tonight's run kept. That was the first fix, and it was wrong twice: the next
   run counts everybody and keeps more (seven in scope with one kept read "7 runs" where the pass ends in the
   second), and beside a printed number in scope the figure gave away how many had been counted before the run,
   a count the small-cell rule may hide.

## What this changes on a box updated in place

The default applies with no setting present. A study whose re-checks fill its allowance and that has excluded
patients in scope now carries up to a quarter of those re-checks to the next run (nearest visit first, as before),
and reaches its excluded patients instead. `TB_MICROBATCH_EXCLUDED_PERCENT=0` restores the order of D-642.

## What this does not do

- A place kept and then not needed (the run's own re-check took a patient off the excluded) goes to a waiting new
  patient, not to a carried re-check or a row of another version: those are done before the screen. It returns to
  the night's allowance for the next job.

- The share is per job, of the allowance the job reserved (D-458); it is not a separate budget of the night.
- The console's run page is lane C2's: it can show the four new fields of `microbatch.budget`; this card puts the
  figures in the summary text and the audit only.
- The figure "weekly runs for a full pass" assumes the allowance and the number in scope stay as they are tonight.

## Test

`tests/unit/test_excluded_share.py` (17 tests; the card began with nine, seven of which failed before the change); `test_weekly_recheck.py`,
`test_microbatch_cadence.py`, `test_pool_version_basis.py` unchanged in what they assert (their stand-in screens
take the new `scope` argument).
