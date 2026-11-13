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
   `excluded_full_pass_runs` (null: nothing is kept, so no run is sure to reach them).
5. **Where it does not apply.** The after-ingest run brings nobody back (D-642) and keeps nothing. With no night
   budget (0) everybody is reached in one run. With `incident=0` no new or excluded patient is screened, and
   nothing is kept. `0` restores D-642's order exactly.
6. **One scope query.** `orchestrator.scenarios.screen.screen_scope` gives the scope; the weekly run hands it to
   `run_screen(scope=...)` so the lake is not asked twice.

## What this does not do

- The share is per job, of the allowance the job reserved (D-458); it is not a separate budget of the night.
- The console's run page is lane C2's: it can show the four new fields of `microbatch.budget`; this card puts the
  figures in the summary text and the audit only.
- The figure "weekly runs for a full pass" assumes the allowance and the number in scope stay as they are tonight.

## Test

`tests/unit/test_excluded_share.py` (nine tests; seven failed before the change); `test_weekly_recheck.py`,
`test_microbatch_cadence.py`, `test_pool_version_basis.py` unchanged in what they assert (their stand-in screens
take the new `scope` argument).
