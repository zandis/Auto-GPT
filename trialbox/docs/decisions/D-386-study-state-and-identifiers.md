# D-386 Study state and identifiers: start-up, open, paused, closed; lists and mails follow the state; registry ids

- **Task:** T-622 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; was T-405 of the deep review)
- **PR:** this branch (`agent/T-622-study-state`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-108 (marks, notices), D-126 (trial database), D-311 (no development gates), D-364 (T-621, the
  site store's version 4), D-366 (one permission function)
- **Closes:** LIFE-008, LIFE-013 (the go-live part: registry ids on the study, validated and printed)

## Context

A study had no state. The only switch was the ruleset's draft or approved status, so a closed study kept screening
and mailing until someone removed the approval (LIFE-008). Sponsor, protocol number and the site initiation visit
(SIV) date were not study fields. Only ClinicalTrials.gov ids existed; Japanese specified clinical trials are
registered in jRCT, many with no NCT number, and Taiwan studies in the Taiwan registry (LIFE-013).

## Decision

1. **Four states.** `startup`, `open`, `paused`, `closed`. Moves: start-up to open or closed; open to paused or
   closed; paused to open or closed; closed is final (a study that recruits again is set up again). The review's
   fifth state (`closed_to_recruitment`) is `paused` or `closed` here: a pause stops recruitment, a close ends it.
2. **The state is an event log.** Table `study_state` in schema `site` (site store version 5): one row per change
   with the state before, the reason, who and when; the latest row is the state. Pausing or closing takes a reason.
   The audit event `console.study_state` is written inside the same transaction, so a change is never kept without
   it (as D-273 does for marks).
3. **No recorded state means open.** Studies running before D-386 keep their lists and mails. A new study is put in
   start-up by its coordinator when it is set up; the box does not guess.
4. **Lists follow the state.** SCREEN, MICROBATCH and COHORT run only for an open study.
   `orchestrator.scheduler.study_state` reads the console's table (read only; the console writes it). The timer
   skips a study that is not open and audits `scheduler.held`; a state that cannot be read holds the job (no list
   rather than a list for a paused study). A list job asked for by hand, by mail or on the console, fails at its
   first step with the reason (`require_open`). Lists made before stay readable in every state. FEAS, NAV,
   CALIBRATION and the rest are not list jobs and are not held.
5. **Mails follow the state.** N1 and N2 leave out a study that is not open: no list rows, marks, calls or new
   pre-screens. A paused study still mails its enrolled participants' visits and unacknowledged serious AEs, because
   a pause stops recruitment, not the care of those already enrolled; start-up and closed mail nothing. So a paused
   study with no visit or serious AE due gives no mail.
6. **Identifiers.** Table `study_identity`: sponsor, protocol number, SIV date and registry ids, all optional; what
   is filled in must have its format. Registry ids by the registries' public formats: ClinicalTrials.gov `NCT` and 8
   digits; jRCT `jRCT` and 10 digits, or `jRCT`, a category letter and 9 digits (`jRCTs...`), as the identifier
   pattern published for jRCT (`^jRCT\w?\d+$`) bounded to the lengths in use; UMIN-CTR `UMIN` and 9 digits. The
   Taiwan registry publishes no single id pattern we could confirm, so its id is checked for shape only: 4 to 40
   letters, digits and `. / _ -`, starting with a letter or digit, and not another registry's id (a jRCT or NCT id
   typed into the Taiwan field is refused). Every change is audited (`console.study_identity`).
7. **Printed on the log.** The screening log page shows the state and the identifiers; its XLSX "about" sheet prints
   the identifiers, the state and every state change with its date, who and why.
8. **Who changes them.** `tb_common.authz.permit(role, "study.state", standing)`: the coordinator, and the
   investigator who is the study's PI (the delegation log); not the administrator, a viewer, a CRO account or the
   steward. Everyone who reads the study's set-up reads the page `/studies/{rs}/state`.
9. **Record.** R-27 in `docs/validation/record-inventory.md`.

## Not done here

- The activation checklist of the review (a list, not a gate).
- The identifiers on the feasibility pack, and an offline jRCT or Taiwan extract for competing trials (LIFE-013's
  later part; T-618).
- The Taiwan id pattern, once the registry's own format is confirmed.
- A per-study retention period that starts at close (T-305c reads this state).
