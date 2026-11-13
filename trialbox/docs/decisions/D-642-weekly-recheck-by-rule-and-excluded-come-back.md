# D-642 The weekly run re-checks by rule, not by a model's flag, and excluded patients come back

- **Task:** NEW-LIFE-3 and NEW-LIFE-4 (TB-PLAN-07 v7.3, wave 1, lane A); deep review 2026-11-12, findings LIFE-003
  and LIFE-004 (both High)
- **PR:** this branch (`agent/NEW-LIFE-3-4-weekly-recheck`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train and one adversarial review)
- **Changes:** D-397 item 3 ("a patient excluded by SCREEN is not screened again until the next SCREEN")
- **Builds on:** D-397 (the cadence), D-458 (the night budget, reserved), D-476 (rows of another criteria version)

## Context

Screening over time had two holes, one failure seen from two sides.

- **LIFE-003.** The weekly re-check evaluated only the criteria flagged `time_sensitive`. The flag is a model's
  output at compile time. All 16 RA-JAK criteria carry `false`, "serious infection within 30 days", pregnancy and
  eGFR among them, so RA-JAK's weekly re-check evaluated nothing. A pool patient with sepsis last week stayed on
  the PI's clinic list as passing.
- **LIFE-004.** A patient a SCREEN excluded was never looked at again until a person ran SCREEN; nothing schedules
  one. Exclusions that end by time (a drug stopped 90 days ago, an infection 30 days ago, an age) or by a new result
  (eGFR, DAS28) never brought the patient back. Over a two-year recruitment the list decays without notice.

## Decision

1. **The re-check set is derived** (`microbatch.recheck_ids`): every inclusion or exclusion the compiled SQL
   decides (class structured or mixed), and a note criterion flagged `time_sensitive`. `time_sensitive` stays in
   the IR as a label and still asks a flagged note criterion again; it no longer decides whether a coded criterion
   is re-checked. Who is re-checked is unchanged: pool patients with a visit in the window, nearest first, inside
   the night budget.
2. **Excluded patients are screened again by the weekly run.** An excluded patient is one in the study's scope (the
   scope query of SCREEN, today) whom a run has looked at since the last SCREEN and who is not in the pool: on that
   SCREEN's excluded list, or screened and not listed by an earlier weekly run. They are screened in full (the same
   `run_screen` as a new patient: the opt-out register and the consent rule apply), after the re-checks, the rows
   of another criteria version and the new patients, inside the night budget.
3. **Fair under a small budget.** The micro-batch record (`new_screened_*.json`) gains `again`: pid to the day a
   weekly run last screened it again. The one never screened again goes first, then the oldest day, then the
   nearest visit. So a budget that reaches ten of them a week reaches all of them in turn. What does not fit is
   counted (`excluded_carried`) and said in the summary, as for re-checks and new patients.
4. **One who is listed now** goes to the pool and, with a visit in the window, on the week's list, marked changed
   as a new candidate is. One who stays excluded is recorded as looked at and is not listed.
5. **Not after an ingest, not with `incident=0`.** The after-ingest run still looks only at new booked patients,
   and `incident=0` is still a re-check only.
6. **A resumed job** screens again the patient it brought back, as it does its own new patients: the pool row this
   job wrote for a patient on SCREEN's excluded list is not counted as the pool's (`pool_as_received`).
7. **What the run says.** The summary's second line counts new patients as before; a third line says how many
   earlier excluded patients were screened again and how many are back on the list. The audit event
   `microbatch.budget` gains `excluded_rescreened`, `excluded_back`, `excluded_carried`; its `new_screened` counts
   the new patients only. The words "time-sensitive criteria re-evaluated" become "criteria re-evaluated".

No new setting and no new limit: the bound is the night budget (`TB_MICROBATCH_NIGHT_BUDGET`).

## What this does not do

- **Cost is not measured.** The review asks for seconds per 1,000 patients re-checked at the 50,000-patient site and
  whether the weekly run of every open study fits the night budget (its open check 3). A mixed criterion whose
  codes do not settle it asks the model, as at SCREEN; an excluded patient screened again may reach the note
  stage. With the default budget of 2,000 patients a night the work is bounded; with the budget set to 0 (no
  limit) every excluded patient in scope is screened every week.
- A patient the earlier weekly run brought back, in a job resumed after that write: where the patient was in an
  earlier record and not on SCREEN's excluded list, the resumed job counts the row as the pool's (it is on the
  list; it is not shown as "changed" again).
- The week page does not yet show "last full screen: N days ago" (the console, lane C).
- A pool patient with no visit in the window is still not re-checked (as before).
- Not every exclusion can end; this card does not tell which. Each excluded patient in scope is screened again.

## Test

`tests/unit/test_weekly_recheck.py`: the re-check set of RA-JAK, GZQO, AD-MAB and RA-BIO is every coded criterion
plus the flagged ones; RA-JAK has no flag and "serious infection" is in its set; a new coded exclusion the model
had not flagged takes a pool patient off the week's list; a patient excluded at SCREEN and in scope is screened
again, one out of scope is not; one an earlier weekly run excluded comes back; the budget holds and the order is
never, then oldest; nobody comes back after an ingest or with `incident=0`; one who stays excluded is recorded and
not listed; a resumed job. Two cases of `tests/unit/test_microbatch_cadence.py` asserted the old rule and are
changed on purpose, each saying why.
