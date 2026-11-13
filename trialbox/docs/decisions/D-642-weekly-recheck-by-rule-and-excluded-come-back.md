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
   scope query of SCREEN, today) whom a run has looked at since the last SCREEN and who is not listed: on that
   SCREEN's excluded list, screened and not listed by an earlier weekly run, or an excluded row of the pool (a
   re-check or a version re-screen leaves one; the review of this card found "not in the pool" missed it). They are screened in full (the same
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
6. **A resumed job** screens again the patient it brought back, as it does its own new patients. The record gains
   `out`: the patients a weekly run screened and did not list, as that run left them. The pool's own rows are the
   ones on SCREEN's candidate list, or screened and listed by an earlier weekly run; a row this job wrote for
   anybody else is one it brought back (`pool_as_received`). A row's first-added time cannot tell this: a re-run's
   copy of the pool stamps it with the row's last evaluation (found when the byte-identical re-run test failed on
   the first attempt at this fix). A record written before this card has no `out`: its patients count as listed,
   as before.
8. **A model that was not asked changes nothing.** The wider re-check asks the model for a mixed criterion the
   codes do not settle. Under a hold, with no judge, or with the model down, the answer is "unknown" with the
   reason `not_evaluated` or `model_down`: it says nothing about the patient. Such an answer no longer replaces a
   stored pass or fail and is not a change on the list. An unknown the data gives (a data gap) still does.
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
- **Excluded patients come last in the night.** A study whose share of the budget is used up every week by
  re-checks and new patients never reaches them; the summary and the audit say how many were carried over. No
  slice is reserved for them: that would be a new limit, and its size is the owner's to set once the cost is known.
- **A whole-hospital scope.** Where SCREEN's scope is most of the hospital, nearly all of it is "excluded", so every
  weekly run fills what is left of its share with full screens, note stage included, week after week. That is what
  the night budget is for, but it is new load from the first run after this card.
- A patient SCREEN took out by the consent rule is on its excluded list, so the weekly run looks at him again each
  week (and takes him out again): a budget slot, and a count in "screened again".
- The record's `again` is never pruned (as its `pids` never was): the same object, class and erasure rule.
- Two weekly jobs of one study in one night: the second does not see the first's record (as before this card).
- The week page does not yet show "last full screen: N days ago" (the console, lane C).
- A pool patient with no visit in the window is still not re-checked (as before).
- Not every exclusion can end; this card does not tell which. Each excluded patient in scope is screened again.

## Test

`tests/unit/test_weekly_recheck.py`: the re-check set of RA-JAK, GZQO, AD-MAB and RA-BIO is every coded criterion
plus the flagged ones; RA-JAK has no flag and "serious infection" is in its set; a new coded exclusion the model
had not flagged takes a pool patient off the week's list; a patient excluded at SCREEN and in scope is screened
again, one out of scope is not; one an earlier weekly run excluded comes back; the budget holds and the order is
never, then oldest; nobody comes back after an ingest or with `incident=0`; one who stays excluded is recorded and
not listed; a resumed job. From the review: a resumed job of a later week; a model that was not asked does not
replace a stored answer, an unknown from the data does; an excluded row of the pool comes back and is listed
once. Two cases of `tests/unit/test_microbatch_cadence.py` asserted the old rule and are changed on purpose, each
saying why.
