# D-597 In OMOP a mapped ICD-9-CM diagnosis keeps the hospital's code as its source value

- **Task:** D-593's known limit (the review of #397), ordered by the integrator on 2026-11-12 for the first site
- **PR:** this branch (`agent/NEW-STD-1d-omop-source-value`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-151 (the feed loaded into OMOP: every code kept verbatim in `*_source_value`), D-593 (an
  ICD-9-CM diagnosis gains an ICD-10-CM coding where the map calls them the same, marked `userSelected: false`)

## Context

The OMOP load took a diagnosis's code from the lake flattener's reading: the first coding. For a mapped
diagnosis (D-593) that is the ICD-10-CM code the map gave, so `condition_source_value` held `N18.3` where the
hospital recorded `585.3`. The load's own rule is "every code is kept verbatim in `*_source_value`", and the store
of record must say what the source said.

## Decision

1. **`condition_source_value` and `condition_source_concept_id` are the hospital's own code** (the coding that is
   not marked `userSelected: false`): `585.3`, ICD-9-CM.
2. **`condition_concept_id` is found through the mapped code** (ICD-10-CM `N18.3`): the vocabulary has no
   ICD-9-CM, so the hospital's code alone would give 0.
3. **The lake reads the mapped code**, as D-593 decided and as the lake built from the feed reads it: the mapped
   code and its system are kept in the record's `extra` (`code`, `system`), which the lake export already puts
   over the OMOP reading. Both lake sources stay the same row for row.
4. **Only the pair the map makes is read this way**: a first coding in ICD-10-CM marked `userSelected: false`
   with the hospital's ICD-9-CM coding after it. Every other shape loads exactly as before: a first coding another
   source flags for its own reasons, a mapped coding alone, a hospital code too long to be a source concept.
5. **The record goes to the table of the mapped code's domain**, as a diagnosis recorded with that code does
   (STD-031): a V code mapped to an ICD-10-CM Z code of the Observation domain is an OBSERVATION row, with the
   V code as its source value.

## Consequences

- A criterion over the lake sees what it saw (the ICD-10-CM code); OMOP itself now says both: what the hospital
  recorded and the standard concept it stands for.
- One full load after this version: a mapped diagnosis loaded before keeps the mapped code as its source value
  until its record is loaded again (the loader replaces a changed record in place).
