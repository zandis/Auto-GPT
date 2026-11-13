# D-598 A draft eCRF value is read only from a record whose code is of the item's code system

- **Task:** a finding of lane A2's adversarial review of #426 in `services/edc`, sent by the integrator on 2026-11-13
- **PR:** this branch (`agent/EDC-prefill-code-system`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-160 (EDC prefill: a draft value always has a citation; unknown never excludes), D-643 (the same
  rule for the facts of an NHI draft)

## Context

`edc.prefill` read observation and condition rows from the lake without their `system` column and matched an item
by the code's text alone: an observation exactly, a diagnosis by an ICD-10 prefix of three characters or more. A
hospital's own code whose text is also a LOINC code or begins like an ICD-10 code was offered to the coordinator as
the item's value, with a citation. Shown by a test with one house-coded row before the change.

## Decision

1. **A lab, vital sign or diagnosis row counts for an item only when its code system is one the box reads for that
   source** (`edc.mapping.SYSTEMS`): LOINC or the box's own clinical-score system for an observation; ICD-10-CM
   (also under a TW Core edition's name) or WHO ICD-10 for a diagnosis.
2. **A row that names no system is of none**: it is not a record for the item. The item stays unknown
   (`no_record`), which never becomes "No".
3. **A map row's `system` narrows the item to that one system when it is one the box reads for the source.** Any
   other value narrows nothing and is not a problem of the map: a suggestion's LOINC is kept on a row whose source
   the coordinator changes to a diagnosis, the map page shows no input for it, and a refused map would stop every
   draft of the study.
4. **A medicine is unchanged**: it is read by column (the ATC column, the hospital's drug code column, matched
   whole), not by a code with a system.
5. **Chart facts are unchanged**: a `site_fact` carries no system. A confirmed one labels a citation, a proposed
   one gives the reason `only_proposed`; neither is a value by itself.

## Consequences

- An item drafted today from a row whose system is empty or another one is no longer drafted; the coordinator
  enters it as before. No signed value changes: a draft becomes a value only when a person confirms it.
- An item map row's hash does not change (the map is not rewritten), and no stored map is refused by this version.
- Known limits, not closed here: a FHIR feed that sends ICD-10-CM first under a name not listed (a version suffix,
  an OID) is not drafted (unknown, not wrong); the lake puts a code in its ATC column when the system's name
  contains "atc" (`lake/flatten.py`, lane B).
