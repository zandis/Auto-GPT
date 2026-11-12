# D-585 The feed's unit reader takes the spellings Japanese and Taiwanese labs print, and IU/L as U/L for enzyme activity

- **Task:** NEW-STD-4 (findings STD-004 and DIN-009 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/11-standards.md` and `08-data-input.md`; plan v7.2 section 5, lane E, wave 1)
- **PR:** this branch (`agent/NEW-STD-4-unit-spellings`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-215 and R-31 (the row's own unit is checked against the unit the look-up declares; a mismatch is
  no value, never a converted one), D-334 (tested conversions only), D-418 (one unit table for the adapter and the
  engines)

## Context

A lab row is read only when its unit and the look-up's unit are the same unit. The reader knew a closed list of
spellings. `IU/L` against a table unit `U/L` (AST, ALT, ALP, LDH, CK, γ-GT), `×10^3/μL` with a multiplication
sign, `mL/分/1.73m2` and `秒` were not on it: the value was dropped as `unit_mismatch`. That is the safe direction
(unknown, never a wrong number), but a site that prints these spellings loses every liver-enzyme and blood-count
criterion.

## Decision

1. **Spelling, in the feed's reader (`tb_common.labvalue.ucum`).** Before a unit is looked up, the multiplication
   sign `×` is read as `x`, `分` as `min`, `秒` as `s` and `時` as `h`. So `×10^3/μL` is `10*3/uL`,
   `mL/分/1.73m2` is `mL/min/{1.73_m2}`, `秒` is `s`, `mm/時` is `mm/h`.
2. **More spellings of units already known**: `x10^4/µL`, `x10^6/µL`, `千/µL` (10*3/uL), `個/µL` (/uL). And one
   new unit, `10*2/uL` (`×10^2/μL`, used for white cells in Japan): it agrees with itself only; it is not
   converted to another count unit here.
3. **`IU/L` and `U/L` are one unit for enzyme activity, and only there.** For the analytes in
   `labvalue.ENZYME_ACTIVITY` (LOINC codes of catalytic activity per volume: AST, ALT, ALP, LDH, CK, γ-GT,
   amylase, lipase) the international unit of enzyme activity is the enzyme unit by definition (1 IU = 1 U = 1 µmol
   of substrate a minute). For every other analyte they stay apart, as D-215 has it (an IU of insulin or of a
   vitamin is not an enzyme unit).
4. **`G/L` is not added.** In a blood count it is giga per litre; in an upper-case export it is grams per litre.
   The reader cannot tell them apart, so it stays a mismatch (no value) and the site declares it per analyte in
   its look-up (`source_unit`).
5. **Nothing changes in the engines.** The compiled SQL and CQL of every ruleset stay byte for byte as they are: no
   spelling is added to the table the engines' scale conversions read. A CSV, SQL or SS-MIX2 row is stored in the
   look-up's unit once the reader has agreed, so the engines never see these spellings from a mapped feed.

## Not in this card

- The engines' own reading of a unit as written (`labunit.key`, its SQL twin, the scale families): a FHIR-fed row
  keeps its spelling, so `×10^3/μL` or `[IU]/L` for ALT is still unknown there. Changing it rewrites the compiled
  SQL of every ruleset (lane A, a ruleset regeneration the integrator calls): sent as a finding. No go-live site is
  FHIR-fed.
- Counting `unit_mismatch` per analyte in the night's report (DIN-009): it uses the counter of NEW-DIN-6.
- A site file of unit spellings (`unit_aliases.csv`, DIN-009): NEW-DIN-9.

## Consequences

- No golden moves: no synthetic feed prints these spellings.
- `tools/mapping_check.py` reads units the same way and still lists every pair it could not read.
