# D-364 Amendment handling: effective date and IRB record per version, the version on every mark, the re-screen list, schedule versions

- **Task:** T-621 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; was T-404 of the deep review)
- **PR:** this branch (`agent/T-621-amendments`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-08 (approval tags), D-101 (approval record), D-108 (marks), D-134 (lifecycle), D-311 (no
  development gates)
- **Closes:** LIFE-009, LIFE-010 (re-screen list and marks), LIFE-012; LIFE-011 is not closed here (step-up at
  Approve waits for T-205's mechanism)

## Context

A new criteria version screened the moment the investigator approved it. It had no effective date and no reference
to the IRB approval of the amendment, so a site could screen on amended criteria before the amendment was in force
(LIFE-009). A "Not suitable" mark hid a patient for ever and did not store the version it was made under; nothing
looked again at set-aside patients after a criterion was relaxed (LIFE-010). The visit schedule was replaced in
place, so an amendment that moved a window re-judged visits done under the old one (LIFE-012).

## Decision

1. **The manifest records the amendment.** `effective_from`, `irb_reference`, `irb_approved_on` (and
   `protocol_date`) in `schemas/ruleset_manifest.schema.json`; the same three on `ApproveRequest`. The approver gives
   them on the approval page or on the APPROVE line (`effective=`, `irb=`, `irbdate=`). No effective date means in
   force from the approval, as before. The effective date is never before the day of approval; the IRB date never
   after it. Each version states its own record: nothing is carried over from the version before.
2. **The IRB fields are a record, not a gate (D-311).** They are printed with the approval and in the audit event;
   empty is allowed; nothing checks them against an IRB.
3. **Screening uses the version in force on the run day.** `load_approved(..., on=day)`: when the newest approved
   version's effective date is later, the newest earlier approved version in force that day is read from its
   approval tag in the rulesets repository. None in force: a plain refusal. An explicit request for the newer version
   before its date is refused. Approval checks and pages that show the newest approved version pass no day.
4. **Every mark keeps its criteria version**: the version of the candidate list it was made on (`pi_marks.version`,
   site store version 4, additive; old marks have none and count as earlier than any version). The audit event
   carries it too.
5. **The re-screen list** (`/studies/{rs}/rescreen`, `console.studies.rescreen_list`) compares the latest list with
   the latest list of an earlier version. Three groups: *back for a new look* (set aside under an earlier version, or
   a screen failure in the log, and better now: off the old list or a criterion that did not pass passes now; the
   reason "criteria changed in v<new>" with those criteria), *no longer meet the criteria* (approached, need info,
   candidate or contacted, and excluded now), *in screening* (consented, to confirm against the new version). A mark
   on a list of the new version takes a patient off. Without a list of an earlier version the list is empty.
6. **Schedule versions.** Every saved schedule is a numbered version with an effective date (datacore version 5,
   table `schedule_version`); the `schedule` table stays the newest saved. A visit done is judged by the version in
   force on the visit day; a visit not done by the version in force today. A schedule saved with no effective date
   applies from the start: a correction, which judges every visit as before. The first versioned save keeps a schedule
   saved before versions as version 1.

## Consequences

- The PUT `/studies/{rs}/schedule` API takes `effective_from`; the console's schedule form does not offer it yet.
- A job that waits for approval of a version approved with a later effective date resumes and is refused with the
  date, until that day.
- The weekly list itself is unchanged: a set-aside patient comes back through the re-screen list, where the
  investigator marks again.
