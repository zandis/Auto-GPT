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
- **The sheet shows the built-in forms.** Below the cited items, the subject's values in TrialBox's own forms
  (consent, enrolment, visits, adverse events, deviations, withdrawal; `datacore.builtin.TITLES`), each with who
  entered it and when, and every change to them (old and new, who, when). Read-only; the `/api/v1` twin carries them
  as `forms` and `form_trail`. The consent facts, the deviations and the AE and SAE dates the review names are these
  forms' values.
- **Only the built-in forms.** A field of any other form (a REDCap dictionary's, the EDC's) is not shown here: the
  monitor sees those as cited items only (D-436 stands). The record's key (the screening number) is not a value.
  Identifier fields are never held (`datacore.forms`).
- **The data core's record read takes the monitor's row.** `GET /studies/{rs}/records/{record}` now takes
  `phi.view` or `monitor.read` (`tb_common.patient_reads`, `orchestrator.datacore_api`), as the monitor's four
  other reads do (D-389). The console signs it only inside the sheet, after the checks the sheet already makes: the
  grant, an enrolled subject, not opted out; and it asks by screening number, never by pseudonym. Every view is
  audited with the visit (`console.monitor_view`, now with the count of form values).
- The empty message for the cited items now says what it is about ("No value taken from the hospital's records has
  been confirmed in EDC prefill for this subject yet").

## Held by

`tests/console/test_the_monitors_entry_point_and_built_in_forms.py`; `tests/console/test_sdv.py` unchanged and green.

## Remains

The monitor still cannot open the screening log, the deviation list or the SAE register pages (403). The sheet now
carries what the review asked from them for enrolled subjects. A study-level, read-only view of those registers for
the monitor is a separate decision, because it shows non-enrolled patients.

## Dropped (D-311)

No sign-off step.
