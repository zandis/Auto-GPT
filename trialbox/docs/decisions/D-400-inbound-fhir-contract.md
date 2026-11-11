# D-400 Inbound FHIR contract: what the box reads, a death without a date, the drug by reference

- **Task:** T-616 (`docs/plan/28-master-plan-v6.md` §6.2.5, lane 2B)
- **PR:** this branch (`agent/T-616-fhir-inbound-contract`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** STD-013 (FHIR half; the SS-MIX2 half is T-615a), STD-012 (read side), STD-014, STD-015, register S-17
- **Builds on:** T-106b (lake schema 3, row provenance), D-275 (record states), D-315 (no default zone)

## Context

The FHIR reader took a narrow subset and nobody had written it down. A patient flagged `deceasedBoolean: true`
without a date stayed alive in the lake and could be listed and contacted. A drug named by `medicationReference`
had no code. An Observation dated by `effectivePeriod` only had no date. A source time with an offset lost its time.
Elements the box did not read vanished without a count.

## Decision

1. **The contract is a table.** `lake.flatten.READ` lists the top-level elements read per resource type; DATA §1
   ("The inbound FHIR contract") is the same table in words. The lake and the OMOP loader read through the one
   flattener, so both paths stay identical (the parity test and goldens).
2. **Death.** The lake `patient` table gets `deceased BOOLEAN` (lake schema 4): true when the record gives
   `deceasedDateTime` or `deceasedBoolean: true`; never false (a "not deceased" flag is no evidence). The compiled
   base cohort and the SCREEN scope add `(p.deceased_date IS NOT NULL OR p.deceased IS NOT TRUE)`: a death with no
   date leaves the patient out at every index date; a dated death decides by its date, as before. A snapshot built
   before schema 4 reads `deceased` as unknown through a temporary view (`lake.store._compat_views`), so a pinned
   older snapshot still runs today's SQL.
3. **OMOP death.** OMOP requires a `death_date`. A death with no date gets the night of the batch that loaded it (the
   latest it can be) and the type concept `2000000013` (TB-SHARED `death-date-imputed`). The export reads that date
   back as unknown and `deceased` as true.
4. **The drug.** `medicationCodeableConcept` first; else `medicationReference` to a contained Medication (`#id`) or
   one in the snapshot (`Medication/id`). A dangling reference keeps the record with no code. MedicationStatement
   fills the `medication` table after the orders (`effectivePeriod`, `dateAsserted`; `not-taken` and `intended` are
   void, `unknown` is undated). The OMOP export orders drug records by resource type to keep that order.
5. **Therapy period (STD-012, read side).** `dosageInstruction[0].timing.repeat.boundsPeriod`, then
   `dispenseRequest.validityPeriod`, then `authoredOn` plus `expectedSupplyDuration` in days or weeks.
6. **Times.** An Observation is dated by `effectiveDateTime`, `effectiveInstant` or `effectivePeriod.start`. The
   mapping engine parses a source date-time that states an offset (`+09:00`, `+0900`, `Z`) with that offset and keeps
   it; only a naive time takes the mapping's `tz`.
7. **Unread elements.** `ingest_report.json` gets `fhir_unread` (schema 1.5.0): per resource type, how many resources
   carry each element not read; `*` for a type not read at all. Names only, never values.

## Consequences

- Every committed ruleset's SQL gains one line in its base; the goldens were regenerated (lake schema 4, the new
  column). No funnel moves: the synthetic data has no death without a date.
- Not done here: emitting `boundsPeriod` from the TW Core mapping (STD-012 emit side; the old element stays read);
  preferred-system choice for Condition codes, `abatement[x]`, `onsetPeriod` (counted as unread); reading
  AllergyIntolerance, Immunization and the other types listed as not read.
