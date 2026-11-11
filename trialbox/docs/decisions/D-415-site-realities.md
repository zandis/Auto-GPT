# D-415 Site realities: a death record ends contact at once, another study is shown, the study type is required, a numeric chart-number column is refused

- **Task:** T-629 (`docs/plan/28-master-plan-v6.md` §6.2, wave 3; FIT-C10 of TB-DR-01 §6)
- **PR:** this branch (`agent/T-629-site-realities`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** FIT-U03, FIT-U04, FIT-U06 (the rest after D-277), FIT-U09. FIT-U08 is not built (see Open)
- **Builds on:** T-616 / D-400 (`patient.deceased`, lake schema 4), D-277 (SAE rule sets per study), D-301 and
  R-48 (`tb_common.chartno`), D-147 (opt-out removal on every list), D-386 (study state)

## Context

TB-DR-01 §4 lists needs nobody wrote down but every site has. Four of them are about safety. A patient who died after
the weekly run stayed on the Approach list until the next run, and a coordinator could call the family. A patient
already enrolled in another trial looked "ready". A study could open with no SAE reporting type, so its clock was the
country's default. A chart-number column that Excel stored as numbers lost its leading zeros, and the patient got a
second pseudonym without anyone noticing.

## Decision

1. **A death record ends contact at once (FIT-U04).** The console asks at every view of a list which of its
   pseudonyms the lake's current snapshot records as dead: a death date, or T-616's `patient.deceased` without one
   (orchestrator `POST /patients/deceased`, pseudonyms in and out, `orchestrator.scenarios.screen.deceased_now`).
   `console.home.week_bundle` leaves them out, as it does opted-out patients, so the week list, the candidates pages,
   the patient page, the call tasks and the morning mail all lose them together. A mark or a contact outcome for such
   a patient is refused (409 `patient.deceased`, audited `console.refused`). The pages say how many were left out.
   When the lake cannot be asked, the page says so in red and Approach and contact outcomes are refused (503
   `patient.death_unchecked`); other marks go on. Never a quiet "nobody died".
2. **The same patient in another study (FIT-U03).** From the candidate registries of the other approved trials: a
   registry status of candidate or contacted reads "also a candidate", consented or enrolled reads "consented or
   enrolled". The other study is named only to an account that may see it; others read "another study". Consented or
   enrolled elsewhere adds an open item ("check this protocol's rule on other trials"), so the patient sits on "needs
   information", never on "ready".
3. **The study type selects the SAE table and is required (FIT-U06).** The type for SAE reporting is D-277's rule set.
   The set-up page offers only the types of the site's country (from `site.tz`); a type of another country is
   refused (`SAE-COUNTRY`), since it would select another country's table. A trial or observational study does not
   move to "open" until its type is chosen and confirmed with no rule alert (`sstate.sae_type`); if the type cannot
   be read the move is refused too (`sstate.sae_unknown`). A registry study has no SAE register and is not gated.
4. **A numeric chart-number column is refused at import (FIT-U09).** `tb_common.chartno.column_refusal` gives the
   reason: `excel_number` when a value is written as Excel writes a number (`123456.0`, `1.2E+11`), `lost_zeros`
   when an all-digit value fails the site's pattern (`settings.mrn_regex`), written the site's way, but matches with
   leading zeros put back. The site set-up's sheets also refuse an XLSX chart-number column with a number cell.
   * Site set-up (`sitesetup.intake.refuse_chart_column`): the sheet is refused before anything is stored, and on a
     role change; the console names the column in English, Japanese and Chinese (`site.err.SHEET-CHARTNO`).
   * The nightly feed (`adapter.pipeline.chart_column_refused`): the patient key and every table's `mrn` column. The
     table is set aside whole, the error names the column as the export writes it, and the night is held.

## Consequences

* One more orchestrator read per list view (a single query on the patient table, pseudonyms only).
* The week bundle reads the registries of the other approved trials (one call each).
* A study that was opened before this change keeps its state; the gate applies to the next move to "open".

## Open

1. FIT-U08 (campus filter): the feed carries no campus or institution field, and the site surveys that would name it
   were dropped (D-311). It needs a lake column (`encounter` and `appointment` from `serviceProvider` or `location`)
   and a scope field; not built here.
2. FIT-U04's second half, "no visit in 12 months shows a flag", is not built.
3. FIT-U06's report names (the CIOMS, PMDA or TFDA form names per type) are not built; D-277 Open (1) stands.
4. FIT-U03 reads registries only; a patient on another study's latest list but not yet in its registry is not shown.
5. The morning mail (N1) leaves out the dead, but when the death check fails it still lists the rows.

*Evidence.* `tests/console/test_site_realities_t629.py` (one test per need).
