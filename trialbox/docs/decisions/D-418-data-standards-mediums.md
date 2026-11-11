# D-418 Data and standards Mediums: lab units and presence words after PR #70, D-275 and D-334

- **Task:** T-619c (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5), one pull request per part
- **Parts:** D-418a units of one kind in the engines (`agent/T-619c-data-mediums`); D-418b presence words from a
  FHIR feed (`agent/T-619c-bulk-presence`); D-418c the unit of a lab criterion checked at compile
  (`agent/T-619c-unitless-flag`). Each part stands alone; each pull request carries this whole file.
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-215 (PR #70, the row unit at the mapping step), D-275 (the engines' unit rule and
  `unit_mismatch`), D-334 (one conversion table, one presence reader), D-400 (the inbound FHIR contract)
- **Closes:** DATA-016 (what PR #70 and FG D-275 left); D-275 open point 3; the D-334 consequence "a `fhir_bulk`
  feed's `valueString` does not use the presence reader yet"

## Context

DATA-016: a plain lab criterion compared `value_num` without the row's unit. D-275 fixed the SQL and CQL engines,
and PR #70 and D-334 fixed the mapping step. Three gaps were left:

1. The engines converted only the five analytes of `tb_common.derived.UNITS`. A haemoglobin of 120 g/L against
   "Hb >= 9 g/dL", or a white count of 4500 /uL against "WBC >= 3.0 10*9/L", was unknown, although the two units
   are the same kind and a factor of 10 or 1,000 apart by definition. D-334 had the table (`SCALES`); only the
   adapter's check read it.
2. A `fhir_bulk` feed has no mapping step, so a qualitative result it sends as text (`valueString` 陽性, 陰性,
   Non-reactive) was never read. A hepatitis B, IGRA or pregnancy criterion on that feed was always unknown.
3. A numeric lab criterion extracted with no unit ("creatinine <= 1.5") reads only results with no unit, so it is
   unknown for every patient. Nobody was told (D-275 open point 3).

## Decision

**D-418a. Units of one kind convert in every engine.** `tb_common.labunit` now holds `UCUM` (the spellings) and
`SCALES` (the families), moved from `tb_common.labvalue`, which re-exports them: one table, two readers. The rule of
D-275 gains one step: when the row's unit and the criterion's unit are of one kind (mass, substance or number
concentration, enzyme activity, international units per volume), the number is converted by the units' definition,
whatever the analyte. The analytes' own factors are read first and agree. Python (`labunit.convert`), the SQL twin
(`value_sql`) and the CQL twin (`unit_function`) add the same arms (`labunit.scale_arms`). Two limits:

- Only within a factor of 1,000 (`MAX_SCALE`). Every engine rounds a converted value to 6 decimals (D-275), so a
  factor of 1e-6 or 1e-7 could round a real value to 0. Such pairs stay unknown. No site reports one analyte in
  both.
- Mass and substance (mg/dL and mmol/L) never convert in the engines; `labvalue.MOLAR` stays the adapter's check
  only. HbA1c % and mmol/mol never convert. Enzyme units and international units stay apart.

The factor is written as the shorter plain decimal (1000000000, not 0.000000001), so CQL, whose decimals stop at 8
places, holds it exactly. The shipped rulesets are not recompiled: the overlay guard of D-275 renders the new rule
beside the approved SQL and keeps an answer only where both agree. The goldens are identical from both lake sources.

**D-418b. A FHIR feed's presence words are read.** In the adapter, after `unit_defaults`, a `fhir_bulk`
Observation coded in LOINC whose `valueString` the shared presence reader (`labvalue.presence`) reads as positive or
negative becomes `valueCodeableConcept` with the LOINC answer the shipped lab lookups use (`LA6576-8` Positive,
`LA6577-6` Negative). The text stays in `valueCodeableConcept.text`, and the result is tagged
`urn:trialbox:value-source|presence-word`. A held or borderline word (判定保留, ±, equivocal), a word whose sign
disagrees, and any other text stay text: unknown. A result not coded in LOINC is left alone. The night's audit entry
counts them (`presence_words_read`). The mapped sources are unchanged: their lookups' `answers` decide (D-334). The
snapshot carries the answer, so the lake, the OMOP store and HAPI (the CQL engine) all read the same value.

**D-418c. The unit of a lab criterion is checked at compile.** `criteria_compiler.unit_check`, called from the
extraction's post-processing, looks up the usual unit of each LOINC analyte in the criterion's value set
(`catalogue/items.csv`, `unit_ucum`). A numeric atom is flagged for the reviewer, with `needs_review` and a warning
that names the usual unit, when:

- it has no unit and the analyte has a real unit: `value_unit_missing`;
- its unit cannot be converted from the analyte's usual unit by the engines' rule: `value_unit_unconvertible`
  (glucose in mmol/L where the catalogue says mg/dL).

A UCUM annotation (`{score}`, `{INR}`, `{pack-years}`) is a plain number, so such an analyte is never flagged for
having no unit. An analyte the catalogue does not list, a derived score, a coded answer and a multiple of the
reference range are not checked. The criterion itself is never changed: the reviewer adds the unit or accepts it.

## Consequences

- More lab results are compared in the criterion's unit, and fewer are `unit_mismatch`. A pair outside the families
  or the factor limit is unknown, as before.
- A Japanese or Taiwanese FHIR feed settles hepatitis B, IGRA and pregnancy criteria the way the SS-MIX2 and CSV
  sources do.
- A protocol line with a bare lab number reaches the reviewer flagged instead of compiling into a criterion that is
  unknown for every patient.

## Not done

- No molar-mass conversion in the engines (mg/dL to mmol/L). It needs an analyte table reviewed per analyte in all
  three engines; the adapter's check proposes the factor to the site instead (D-334).
- The presence reader is not applied to `component.valueString` of a FHIR feed.
- The shipped rulesets are not recompiled (T-613a owns that); the guard carries the new rule until then.

*Evidence.* D-418a: `tests/unit/test_unit_scales.py` (Python, SQL and CQL twins on every family unit, CQL factors
exact, a lake run deciding Hb in g/L and WBC in 10*4/uL and /uL); `tests/unit/test_criteria_safety.py` (the
10*4/uL line now converts; mass to substance stays unknown); goldens identical. D-418b:
`tests/unit/test_bulk_presence_words.py`. D-418c: `tests/unit/test_unit_check.py`.
