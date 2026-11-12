# D-590 A site declares its unit spellings; lost values are counted; a unit-less value must be plausible

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

1. **The site mapping declares its own spellings**: `unit_spellings: {"萬/μL": "10*4/uL"}` (top level): a unit as
   the source writes it (width and blanks folded, case kept) and the UCUM code it stands for. The code must be
   one the shared unit table knows; a spelling the table already reads cannot be given another meaning; else the
   mapping does not load. No code release for a new spelling of a known unit.
2. **D-215's rule stands as it is**: a row has a value only when its unit and the look-up's are one UCUM code. The
   first design of this card let "the same text on both sides" agree; four existing tests guard the rule against
   exactly that (`test_labvalue.py`), and they are unchanged. A unit with no UCUM code in the shared table (`COI`,
   `S/CO`, `/HPF`) therefore still gives no value: it is now counted (point 3), and the code is added to the
   shared table when a site needs it.
3. **Lost values are counted every night**, per local lab code, with D-580's counter and its files
   (`completeness.json`, `unmapped_codes.json`, the night's audit event) under the names `unit_mismatch` and
   `no_unit_implausible`. Counts only; the pairs of spellings are in the mapping check.
4. **A value with no unit must be plausible in the unit it is read in.** For an analyte with a plausible range,
   a unit-less value outside it has no value at all (the same shape as a unit mismatch, reason
   `no_unit_implausible`, the text as written kept in a note) and is counted. It is not kept as text: the lake
   reads a text result back as a number. The range comes from the look-up (`plausible_low`, `plausible_high`,
   in the unit the look-up writes: the site's data; a range stated badly stops the mapping from loading) and
   else from a short table for four analytes (creatinine, urate, HbA1c, glucose: the ranges the sheet path
   already uses). A row that states its unit is not range-checked here: its unit was checked.
5. **What the range does and does not do.** It catches the gross cases (`CRE 88`, `HbA1c 0.072`, `HbA1c 53`,
   `UA 360`). It does not catch every value in another unit: glucose `25` (mmol/L), urate `0.55` (mmol/L),
   HbA1c `20` (mmol/mol) and creatinine `20` (µmol/L) lie inside and are given numbers, as before this card.
   And a real extreme reported without a unit is refused: glucose over 800 mg/dL (a hyperosmolar state) or
   under 20, creatinine over 20 mg/dL, urate under 0.5 mg/dL (rasburicase), HbA1c over 20 %. Those become
   unknown and are counted (a person looks), never a failed comparison. A feed that states its units is
   untouched; the lasting repair for a feed without them is the unit column.
6. A site mapping that `extends` another adds its `unit_spellings` to the base's; two spellings that fold to one
   key cannot mean two units (the mapping does not load).

## Not in this card

- The engines' own unit table (`tb_common/labunit.py`, lane A): a unit the look-up *writes* (`ucum`) must still be
  one the engines know, or they read the value as unknown.
- `sitesetup/messy.py` keeps its own copy of the four ranges (another lane's folder); one table for both is a
  follow-up (sent to the integrator).

## Consequences

- A site can take a new spelling of a known unit into use by a line in its mapping; the mapping check reads it
  as the night does.
- A feed with a blank unit column and SI values no longer loads the grossly wrong numbers of the four analytes
  under a right-looking unit (point 5 says what still passes); for every other analyte D-149 stands as it was,
  and the site can add a range.
- The night's log line and audit total for D-580's counter call these rows "dropped" and "unmapped"; they are
  kept, without a value (`adapter/pipeline.py`, lane B: sent to the integrator).
