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

1. **A lab, vital sign or diagnosis row counts for an item only when its code system is the item's.** The item's
   system is the one its map row names; a row with no `system` reads the box's own for that source: LOINC for an
   observation, ICD-10-CM or WHO ICD-10 for a diagnosis (`edc.mapping.SYSTEMS`).
2. **A row that names no system is of none**: it is not a record for the item. The item stays unknown
   (`no_record`), which never becomes "No".
3. **The map check refuses a system the box does not read for that source** (`system`), so a mistyped system
   cannot leave an item silently empty.
4. **A medicine is unchanged**: it is read by column (the ATC column, the hospital's drug code column, matched
   whole), not by a code with a system.
5. Facts a person confirmed (`site_fact`) are unchanged: they carry no system and a person stands for them.

## Consequences

- An item drafted today from a row whose system is empty or another one is no longer drafted; the coordinator
  enters it as before. No signed value changes: a draft becomes a value only when a person confirms it.
- An item map row's hash does not change (the map is not rewritten), so no open draft is superseded by this
  version alone.
- The console's map page has no input for the system; a map saved there reads the box's own systems.
