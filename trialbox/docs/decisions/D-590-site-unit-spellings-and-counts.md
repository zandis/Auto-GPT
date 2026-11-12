# D-590 A unit written as the look-up declares it agrees; lost values are counted; a unit-less value must be plausible

- **Task:** NEW-DIN-9 (findings DIN-009 and DIN-017 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan v7.2 section 5, lane E)
- **PR:** this branch (`agent/NEW-DIN-9-site-units-counted`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** R-31 and D-215 (every lab row's unit is checked against the look-up's), D-149 (a row with no unit is
  read in the look-up's unit), D-334 (the mapping check lists unit pairs), D-585 (spellings labs print), D-580 (the
  night's counter of codes nobody knows)

## Context

The feed's unit reader knows a closed table of spellings. A row whose unit is not in it has no value, even when
the row's unit and the unit the site's look-up declares for that analyte are the same text (`COI`, `千/μL`,
`mL/分/1.73m2`). Safe, but the analyte is unknown at the site until a code release, and the night's report did not
say how many results were lost. And a row with **no** unit is read in the look-up's unit with no check: `CRE 88`
became 88 mg/dL, `HbA1c 0.072` became 0.072 %.

## Decision

1. **Same text as the look-up's declared unit agrees.** The site's lab look-up says per analyte which unit the
   source reports (`source_unit`, else `ucum` when the factor is 1). A row whose unit is that text (width and
   blanks folded, case kept) agrees, whether or not the shared table knows the spelling. The site's look-up is the
   site's data: the lab team adds the spelling there, with the factor to the unit the look-up writes. No code
   release.
2. **Anything else is as before**: two spellings agree only when the shared table reads both as one unit; else
   the row has no value (`unit_mismatch`).
3. **Lost values are counted every night**, per local lab code, with D-580's counter and its files
   (`completeness.json`, `unmapped_codes.json`, the night's audit event) under the names `unit_mismatch` and
   `no_unit_implausible`. Counts only; the pairs of spellings are in the mapping check.
4. **A value with no unit must be plausible in the unit it is read in.** For an analyte with a plausible range,
   a unit-less value outside it has no number: it stays text (unknown to the engines) and is counted. The range
   comes from the look-up (`plausible_low`, `plausible_high`, in the unit the look-up writes: the site's data) and
   else from a short table for four analytes whose other common unit differs by an order of magnitude
   (creatinine, urate, HbA1c, glucose: the ranges the sheet path already uses). A row that states its unit is
   not range-checked here: its unit was checked.

## Not in this card

- The engines' own unit table (`tb_common/labunit.py`, lane A): a unit the look-up *writes* (`ucum`) must still be
  one the engines know, or they read the value as unknown.
- `sitesetup/messy.py` keeps its own copy of the four ranges (another lane's folder); one table for both is a
  follow-up (sent to the integrator).

## Consequences

- A site can take a new unit spelling into use by a line in its look-up.
- A feed with a blank unit column and SI values no longer loads wrong numbers under a right-looking unit for the
  four analytes; for every other analyte D-149 stands as it was, and the site can add a range.
