# D-395 The IRB-text record on the study set-up page; the cross-department candidate view waits for it

- **Task:** T-310b (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; the second part of TB-ASSESS-01's
  T-310, `docs/reviews/2026-11-09-assessment-and-tasks.md`)
- **PR:** this branch (`agent/T-310b-irb-text-gate`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-147 (the whole-hospital candidate view), D-311 (no development gates), D-366 (one permission
  function), D-386 (T-622, the study state page)
- **Closes:** the "per-study IRB-text gate" of WS-06.5 (RSK-42)

## Context

D-147 lets the PI and delegated sub-investigators open, for a candidate from any department, the cited record and
the chart number before the treating doctor is asked. The legal basis for that view is the site's care relationship
together with the committee's approval of the recruitment method. RSK-42 and WS-06.5 ask that the view is enabled
per study only when the study's approved IRB text covers "identified pre-screening across departments by the
investigator before referral", recorded on the study set-up page by the PI.

This is a product feature: the box records the site's own approval and refuses the view without it. It is not a
review step on the developers (D-311): building and testing use synthetic data and need no such record.

## Decision

1. **The record.** Table `study_irb_text` in schema `site` (site store version 6), an event log; the latest row is
   the record. Each row says whether the approved text covers the sentence, the approval number of that text
   (required to say "covers"), its version and approval date (optional; not in the future), a note (required to take
   the record back), the sentence id (`cross_dept_identified_v1`), who and when. A later wording of the sentence is
   a new id, so an older record never counts for it.
2. **Where and who.** A section of the study set-up page `/studies/{rs}/state` (T-622's page), shown to everyone who
   reads the set-up, with the sentence in the page's language and the English original. Only the study's PI records
   it: `permit(role, "study.irb_text", standing)` (a matrix row: investigator `[pi]`, every other role false). The
   route is `POST /studies/{rs}/irb-text`.
3. **Audited.** Each record writes `console.irb_text` (covers, sentence, approval number, version, date, note) inside
   the store's transaction, so a record is never kept without its audit event.
4. **The gate.** Without a record that covers the sentence, a candidate's page (`/studies/{rs}/candidates/{pid}`,
   with or without a purpose), its chart number (`.../reveal`) and `GET /api/v1/studies/{rs}/candidates/{pid}` are
   refused with 403 `irbt.refused`, which names the study and where the record is, in English, Japanese and
   Traditional Chinese. The refusal is audited (`console.denied`, reason `irb_text`). The candidate list stays
   (pseudonyms only) and says why the pages are closed, with a link to the record; the API list carries
   `candidate_view`. Taking the record back closes the view again.
5. **Where it applies.** `TB_IRB_TEXT_GATE`: `auto` (default) is on in VALIDATION and PRODUCTION and off in DEV and
   TEST, where only synthetic data is read (D-311); `on` turns it on anywhere; `off` is refused in VALIDATION and
   PRODUCTION. The page says when the gate is off in the environment.
6. **Not a state gate.** Moving a study to open (D-386) does not wait for this record: the owner chose warnings, not
   gates, for the IRB approval itself (D-147 item 4). Only the cross-department identified view waits.
7. **Record.** R-05 in `docs/validation/record-inventory.md`.

## Not done here

- The patient page's reveal (`/studies/{rs}/patients/{pid}`) is not held by this record: it is the study's own list
  (D-143). If a study's "who to screen" is the whole hospital, that page reaches other departments' patients too; a
  later card may hold it the same way.
- Break-glass (RSK-57's extension of the per-study gate) is not covered.
- The weekly sample (T-310a) and the override report (T-310c).
