# D-689 At night a Taiwanese medication with no ATC gains the ATC code the NHIA list gives

- **Task:** NEW-STD-5 (finding STD-005 of the deep review of 2026-11-12; plan v7.3 wave 1, lane E)
- **PR:** this branch (`agent/NEW-STD-5-nhi-drug-to-atc`)
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-170 (the NHIA drug list's NHI code to ATC map in the reference data, relation `wider`), D-593
  (`mapped_coding`: a code in another system only where the map says so), D-665 and D-660 (a map that is not
  loaded is "not asked": a night reads the table whole next time, a first load is held), D-130 (a code in a system
  no value set reads makes an inclusion unknown)

## Context

In Taiwan a medication's drug class comes only from the hospital's own ATC column. The NHIA drug list's map from
the NHI 藥品代號 to ATC is parsed and registered, but only the site set-up suggestion page read it. A medication
row with an NHI code and no ATC matched no drug value set: a drug exclusion could never fire on it, and a drug
inclusion became unknown. The CGRD research database states no ATC column in any of its dictionaries.

## Decision

1. **The shared TW mapping asks the reference data for the ATC of an NHI code when the row has no ATC.** It names
   the pack's system for the NHI code (`nhi_drug_list: urn:tw:nhi:drug`; the medication keeps its own coding under
   `nhi_drug`) and adds one `mapped_coding` element. A hospital's own ATC wins: the map is then not asked.
2. **Only the one answer the list gives is taken.** `mapped_coding` takes a relation an element names under
   `accept:`; the default stays `equivalent` / `equal` (the ICD-9-CM map is unchanged). The NHI-to-ATC element
   accepts `wider`, which is what the list says of every row: the product belongs to that ATC class. A load refuses
   any other word (`inexact`, `relatedto`: a candidate, never the code). Two answers, no entry, or a value that is
   not ATC-shaped (the parser drops it): no ATC, and the row is counted (`map:nhi_drug_list->atc`).
3. **The level is the list's.** A level-4 class (`C10AA`) is kept as given: a value set at that level or above
   reads it; a value set at level 5 does not, so such a criterion stays as it was without the map (unknown for an
   inclusion; an exclusion does not fire). Nothing finer than the list is ever written.
4. **The mapped coding says it is not the hospital's** (`userSelected: false`), and the hospital's NHI coding is
   kept first. The lake reads it as the drug's ATC.
5. **The night counts it**: the completeness report gives each table's rows that gained a mapped code (`mapped`)
   beside the rows left without one (`unmapped`), so a site sees, per night, how many medications got their class
   from its own column (the rest), from the list, and from neither.
6. **A box without the list loaded**: as D-665 says for any map. The rows that need it are "not asked": a night
   is not held and reads the table whole next time; **a first load is held until the reference pack is loaded**.
   A site whose every row has an ATC is never asked for the list.

## Consequences

- A CGRD night needs the reference pack's NHI list loaded before its first load.
- The shared mapping file changes, so every lake table's mapping version moves (goldens regenerated, no data column
  moves: the synthetic sites give every medication an ATC).
- `services/adapter/pipeline.py` (another lane's file) gains two lines writing the count into the completeness
  report.

## Known limits

- The OMOP store takes a mapped ATC as the drug's source value, as it does a recorded one; the hospital's NHI code
  is kept with the record (`extra.nhi_code`), and that the ATC was mapped is not kept there (D-597 did this for a
  mapped diagnosis; the same for drugs is a later card of this lane).
- The first load (`adapter/backfill.py`) counts unmapped codes but not mapped ones.
- The list gives the ATC of the newest validity period that states one; an NHI code whose class changed over time
  is read with today's class for every year.

## Evidence

`tests/unit/test_nhi_drug_to_atc_at_night.py` (each failed before): an NHI code mapped to its ATC, tagged and read
by the lake; the hospital's ATC wins and the map is not asked; two answers, another relation, no entry; no
reference data; could not ask; the ICD-9-CM map still takes only an exact entry; a mapping may accept only class or
identity relations; a night with the counts; a night before the list is loaded. `tests/unit/test_mapping_concept_maps.py`
lists the new map.
