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

Filled in at the end of the card (see the PR).
