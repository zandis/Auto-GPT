# D-407 Trial lifecycle Mediums: contact limit, randomisation, possible deviations, the request for the doctor

- **Task:** T-620 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-620-lifecycle-mediums`); builds on T-623 (D-387)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-108 (contact outcomes), D-134 (lifecycle), D-143 (the one reveal path), D-147 (referrals),
  D-277 (rules per study on the set-up page), D-387 (screening-log detail), D-311 (no development gates)
- **Closes:** LIFE-017, LIFE-020, LIFE-025, UX-034

## Context

The deep review of 2026-11-10 found four Medium gaps in the trial lifecycle. "Not reached" could repeat without end:
no attempt limit and no days between attempts (LIFE-017). The treating doctor, who has no account by the owner's
decision, got nothing from the box, so the coordinator retold the request by phone (LIFE-017, UX-034). Randomisation
was not a field: "enrolled" covered both "consented and eligible" and "randomised" (LIFE-020). Deviations were typed
by hand although the box holds the facts that reveal the common ones, and the form had no major/minor class and no
sponsor-report date (LIFE-025).

## Decision

1. **Contact attempts per study (LIFE-017).** The lifecycle keeps a contact rule per study (`contact_rule`, data-core
   version 7): the maximum attempts and the minimum days between two, three and one day until the study sets its
   own on the set-up page (the coordinator, audited `life.contact_rule`). An attempt is an outcome that tries to
   reach the patient (reached and booked, reached and declined, not reached). A further attempt at the limit is
   refused with a plain reason (`outcome.limit`), and one sooner than the days asked is refused with the first day
   allowed (`outcome.too_soon`); the page and `/api/v1` refuse alike and the refusal is audited. The outcomes that
   close the contact (not approached, lost contact) are never refused. The patient page shows "Contact attempts: n
   of N"; at the limit it tells the coordinator that the investigator decides, and the investigator's own view of the
   patient asks for a decision.
2. **The request for the treating doctor (LIFE-017, UX-034).** The owner's decision stands: the doctor has no account
   and nothing is sent by the box. Each open referral on the referral page has a "Copy request for the doctor" text
   and a one-page print in Japanese, Chinese or English: the study, the patient's code and screening number, the
   inclusion criteria the records meet (count and labels; never a note's words), what is asked, and the study
   contact (the requesting coordinator's name and contact from the staff directory). The chart number is a blank
   line, filled in by the study team, unless the coordinator reveals it on the print page through the one reveal
   path (D-143: reason, both audit records, the per-person cap), recorded as a candidate view for the referral.
   Every print is audited (`console.referral`, action `printed`, with or without the chart number).
3. **Randomisation fields (LIFE-020).** The enrolment form gains `en_rand` (randomised in the sponsor's IRT: yes,
   no, not a randomised study), `en_rand_date` and `en_rand_no`. No arm is stored anywhere (blinding). The fields
   export in CSV, XLSX and ODM like every built-in field. The screening log shows "Randomised" and the day on the
   enrolled cell; its XLSX gains a `randomisation_date` column.
4. **Possible deviations (LIFE-025).** The lifecycle proposes, from its own facts: a visit done outside its window
   (or answered "outside the window" on the visit form), a consent on a form version other than the one in force
   (the study's IRB record), an enrolment dated before consent, and an enrolment while the screening log says not
   eligible. A proposal is never a deviation by itself. On the new "Possible deviations" page the coordinator
   confirms it, which writes the next deviation entry (`dvN`: day, kind, what happened; source
   `trialbox:proposed`), or dismisses it with a reason; one answer per proposal (`deviation_call`, audited
   `life.deviation_call` and `console.deviation_call`). The deviation form gains a class (major, minor, not yet
   classed) and the day reported to the sponsor.
5. **Wording.** A proposal is "possible"; the request names criteria "met in the hospital records" and leaves the
   clinical judgement to the doctor; no verdict word (T-116).

## Consequences

- Acceptance: a fourth attempt on a limit of three is refused with a plain reason
  (`tests/unit/test_lifecycle_mediums.py::test_a_fourth_attempt_on_a_limit_of_three_is_refused`,
  `tests/console/test_lifecycle_mediums_pages.py::test_a_fourth_attempt_on_a_limit_of_three_is_refused`); the
  randomisation fields export in ODM (`test_randomisation_fields_export_in_odm_and_reach_the_log`).
- New tables `contact_rule` and `deviation_call` are part of record R-10.
- The contact-attempt part overlaps card T-626 ("contact-attempt limit"); T-626 builds its contact outcomes on this
  rule instead of a second one.
- The built-in form rows are appended in one block at the end of `forms.csv` to keep parallel merges simple; the
  reader groups fields by form, so the forms and the ODM export are unchanged in shape. A REDCap import of the raw
  dictionary wants a form's fields together: sort by form before such an import.
