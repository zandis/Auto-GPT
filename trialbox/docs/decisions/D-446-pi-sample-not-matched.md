# D-446 The weekly PI sample of "criteria not matched", send-back to the PI list, and the list held in PRODUCTION until the site's check

- **Task:** T-310a (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; the first part of TB-ASSESS-01's
  T-310, `docs/reviews/2026-11-09-assessment-and-tasks.md`)
- **PR:** this branch (`agent/T-310a-pi-sample-not-matched`)
- **Date:** 2026-11-11
- **Status:** proposed (accepted when merged)
- **Builds on:** D-143 (the list and "send to review"), D-351 (T-116: "criteria not matched", never "excluded"),
  D-147 and D-273 (opt-outs on no list), D-383 (T-305a: every job pinned to one snapshot), D-395 (T-310b: a record
  that opens a view, `auto`/`on`/`off` per environment), D-425 (T-102c: every call site asks `permit`), D-311
- **Closes:** CR-014, FIT-007, UX-032

## Context

URS-PI-05: the investigator sees the patients whose records did not match a criterion, with the criterion, the
evidence and its source; the list is shown only after the site's real-data check (the dry run) is within its
thresholds; and ten of these patients a week are sampled for the PI. Before this decision the list was open to every
role that reads patient rows, in every environment; there was no sample; and a patient "sent to review" stayed on the
not-matched page only: it never came back to the PI's weekly list (CR-014, FIT-007, UX-032).

## Decision

1. **The store.** Schema `tuned` of the trial database (`libs/tb_common/notmatched.py`), read and written by the
   console and the orchestrator and read by Study A (T-627). `tuned_patients`: one row per sampled patient (study,
   ISO week of the site's calendar, pseudonym, the screening run, **that run's snapshot**, the criteria version, the
   criteria not matched, who drew it and when, and the PI's answer with who, when and an optional note), unique per
   study, week and pseudonym. `not_matched_check`: the site's check as an event log (passed or not, the id of the
   check's record, a note, who, when); the latest row is the record.
2. **The draw.** Ten patients per study and week from the latest finished SCREEN's stored not-matched list
   (`excluded_*.json`), which the run made from the snapshot it pinned (D-383); the lake is never asked, so a night
   published since the run does not change what is drawn. Order: `sha256(study | week | job | pseudonym)`, first ten:
   fair, and the same ten for everyone. A patient on the opt-out register (`tb_common.optout.opted_out`, or the
   console's register read) is never drawn; a register that does not answer stops the draw. One sample per study and
   week: a second drawer keeps the first.
3. **Who draws.** The orchestrator's weekly job (`orchestrator.notmatched_sample.weekly`, timer
   `schedule.not_matched_sample`, default `MON 06:00` site time; audit `notmatched.sample`, `notmatched.held`). Where
   no timer runs (DEV is on demand) or it has not run yet this week, the first view of the sample page draws it the
   same way. The job is a timer function, not a new job type: no contract change.
4. **The answers.** On `/studies/{rs}/not-matched/sample` the PI answers each patient once: `agree` ("records do not
   match, as the run said") or `send_back`. The page shows the week's counter (answered of ten, sent back) and the
   study's totals. Audit `console.notmatched_answer` inside the store's transaction. A patient who opted out after
   the draw is not shown, cannot be answered, and is counted as removed.
5. **Send-back re-enters the PI list (CR-014).** A send-back from the sample, and "This is wrong, send to review" from
   the list, write the existing `excluded_review` row (D-143). The weekly list (`week_bundle`, so the page, the mail,
   `/api/v1/.../patients` and the mark path alike) adds every such patient who is on the latest run's not-matched
   list and not already listed, as tier `review` with the criteria not met, marked "sent back", until a mark takes
   them off as for any patient.
6. **Rights (D-425: `permit` only).** `notmatched.sample`: investigator `[pi, task:screen]`, every other role false.
   `notmatched.send_back`: coordinator true (the list's "send to review" of D-143 stays theirs), investigator
   `[pi, task:screen]`. `notmatched.check`: the steward only (FIT-007). The list page itself keeps its D-143/D-273
   rule. Every changing page route has an `/api/v1` twin, which checks the session, then the row, then reads the body
   (T-657's rule); the list's "send to review" gets its twin `POST /api/v1/studies/{rs}/not-matched/{pid}/review`.
7. **Held until the site's check (FIT-007).** `TB_NOT_MATCHED_GATE` (declared): `auto` (default) on in VALIDATION
   and PRODUCTION, `on` anywhere, `off` refused in VALIDATION and PRODUCTION; DEV and TEST read synthetic data only
   (D-311), so the list is open there. While held, the list page and the sample page say so and list nobody, no
   sample is drawn, and a send-back is refused (409). The steward records the check on
   `/studies/{rs}/not-matched/check`: "passed" needs the id of the check's record; "not passed" (taking it back)
   needs a note. Audit `console.notmatched_check`.
8. **Record.** R-22 in `docs/validation/record-inventory.md`.

## Not done here

- The check's thresholds are not computed by TrialBox: the dry-run record (T-315's `pq.dryrun_record`, wrong
  exclusions at most 2 %, PPV at least 0.6) does not exist yet; the steward types its id. When T-315 lands, the check
  can read the record instead.
- The sample is not in the morning mail N2 (FIT-007 says "page and N1"); a dry-run patient (S-09) is not left out,
  as there is no dry-run marker on a patient yet.
- The monthly override report is T-310c.
