# D-772 The monitor finds the page, and the sheet shows the built-in forms

- **Task:** NEW-JRN-8 (the deep review of 2026-11-12, JRN-008; `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-JRN-8-the-monitors-entry-point-and-built-in-forms`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-303 (D-436: the monitor's SDV pages, enrolled subjects only, the cited items), D-380 (FIT-002: a
  CRO account reads a study only under a monitor grant of the delegation log), D-389 (the monitor's reads take its
  own row, `monitor.read`), NEW-SEC-1 (D-717: every patient read at the orchestrator checks the signed person)

## The problem

The monitor's journey had a dead start and a thin end. After sign-in a CRO account saw only "Feasibility reports";
nothing linked to `/studies/{rs}/monitor`, which worked only as a typed address. And the source-reference sheet
showed only values a person confirmed in EDC prefill: for a subject whose consent, visit and adverse event were typed
into TrialBox's built-in forms it said "No CRF value of this subject has been confirmed yet", so a monitoring visit
could not be done in the product for a study on the built-in forms. **Confirmed by tests** before the change (kept
failing output: `jrn8-fail.txt`).

## The decision

- **The monitor finds the page.** Under a monitor grant that holds today, the reports page says "Monitoring: GZQO
  (visit MV-12, until 2099-12-31)" with the link, and the menu has "Monitoring · GZQO"
  (`console.team.monitor_grants`, read through `h.stand`, the one permission function). An account without a grant,
  or with one that has ended, sees neither.
- **The sheet shows the built-in forms.** Below the cited items, the subject's coded values, dates and numbers in
  TrialBox's own forms (consent, enrolment, visits, adverse events, deviations, withdrawal; `datacore.builtin.TITLES`),
  each with who entered it and when, and every change to them (old and new, who, when). Read-only; the `/api/v1`
  twin carries them as `forms` and `form_trail`. The consent facts, the deviations' kinds and dates and the AE and SAE
  dates, grades and seriousness the review names are among these values.
- **Never free text.** A note, a reason, a name or the AE term can carry a chart number or a narrative, which the
  sheet never shows (D-436): only fields of kind choice, multi, date, dateTime, integer and decimal are shown
  (`sdv_page.SHOWN_KINDS`).
- **Only the built-in forms, as typed in TrialBox.** A field of any other form (a REDCap dictionary's, the EDC's), or
  a built-in field another source owns, is not shown here: the monitor sees those as cited items only (D-436 stands).
  The record's key (the screening number) is not a value.
  Identifier fields are never held (`datacore.forms`).
- **The data core's record read takes the monitor's row.** `GET /studies/{rs}/records/{record}` now takes
  `phi.view` or `monitor.read` (`tb_common.patient_reads`, `orchestrator.datacore_api`), as the monitor's four
  other reads do (D-389). The console signs it only inside the sheet, after the checks the sheet already makes: the
  grant, an enrolled subject, not a pseudonym-keyed record. Every view is audited with the visit (`console.monitor_view`, now with
  the count of form values).
- **A subject keyed by the pseudonym is never listed or opened.** The data core takes a pseudonym as a record key too
  (a form typed for a pid). Such a subject is on no monitor list; its sheet is 404, audited (`console.denied`,
  `why: pseudonym_key`), and refused before any read by that key.
- **An enrolled subject who opted out stays on the sheet (D-762).** An opt-out of research reuse does not end a trial
  subject's trial (D-441), so the monitor still verifies their trial data. They are listed and their sheet opens with
  the day of the opt-out, as D-762 (#601) set; their built-in form values are shown like anyone's. This record first
  refused them (404, `opted_out`), and refused a subject whose pseudonym the box cannot tell (`unknown_patient`); both
  refusals were the rule D-762 replaced, and they are dropped (the integrator's train 18 found the two rules opposite).
  The pseudonym now serves only to show the opt-out day.
- The empty message for the cited items now says what it is about ("No value taken from the hospital's records has
  been confirmed in EDC prefill for this subject yet").

## Adversarial review

NOT SOUND on the first pass:
1. An opted-out subject whose record is keyed by the pseudonym was listed and opened. The opt-out check never
   matched it, and the new section would have read its record by the pseudonym. The record said "never by pseudonym",
   which was false. (The listing and opening are D-436's; the review reproduced it.)
2. Free-text fields (a note, a reason, the AE term) could put a chart number or a narrative on the sheet.
3. The sheet's help text still said nothing else of the record is shown.

Also taken: a built-in field another source owns is not shown; the trail does not carry its source; the monitor's
grants are read once per page and for a study of any kind. All are fixed and held by tests, including a CRO account
under a grant being refused the other record pages and the `/api/v1` records twin.

## Held by

`tests/console/test_the_monitors_entry_point_and_built_in_forms.py`; `tests/console/test_sdv.py` unchanged and green;
`tests/console/test_t102b_roles.py`'s fake data core answers the two reads the sheet now makes (no assertion moved).

## Remains

The monitor still cannot open the screening log, the deviation list or the SAE register pages (403). The sheet now
carries the coded values and dates the review asked from them for enrolled subjects; the AE term and other free text
are not on it (see above). A study-level, read-only view of those registers for
the monitor is a separate decision, because it shows non-enrolled patients.

## Dropped (D-311)

No sign-off step.
