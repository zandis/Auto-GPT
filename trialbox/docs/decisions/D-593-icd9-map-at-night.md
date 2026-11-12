# D-593 At night, an ICD-9-CM diagnosis gains its ICD-10-CM code only where the map says the two are the same

- **Task:** NEW-STD-1, second half, part 2 (finding STD-001 of the deep review of 2026-11-12; D-586 and D-592 "Not in
  this card")
- **PR:** this branch (`agent/NEW-STD-1c-icd9-map-at-night`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-586 (a Taiwanese diagnosis of the ICD-9-CM years carries ICD-9-CM), D-592 (the CMS General
  Equivalence Mappings in the reference-data pack, and what each relation may be used for), D-130 and the coverage
  rule (a diagnosis in a code system no value set reads makes a FALSE inclusion `unknown`)

## Context

Since D-586 a diagnosis keyed before the site's `icd9cm_before` is ICD-9-CM, which no value set reads: an
inclusion on it is `unknown` (a person looks), and an exclusion on it cannot fire. D-592 put the public map in the
pack and set the rule: only an `equivalent` entry may give the code; an `inexact` entry is a candidate, not a
meaning.

## Decision

1. **The mapper may ask the reference data** (`Mapper(..., concept_map=...)`: system and code to the map's rows).
   The night and the back-fill pass the box's own reference data (`tb_common.refdata.map_targets_or_empty`); a
   mapper without it (the mapping check, a box with no pack loaded) maps nothing, and the diagnosis stays as
   D-586 left it.
2. **One new builder, `mapped_coding`**: the coding of a column's code in another system, only when the map has
   exactly one row for that code into that system and its relation is `equivalent` (or `equal`). The ICD-9-CM
   code is looked up with its dot (`7140` and `714.0` are one code).
3. **The shared mapping** gives an ICD-9-CM diagnosis that coding first and its ICD-9-CM coding second. The lake
   keeps one code per diagnosis, the first: such a diagnosis is read as the ICD-10-CM code, and the record keeps
   both. The mapped coding says it was not the hospital's own (`userSelected: false`).
4. **Everything else stays ICD-9-CM, and is counted**: an `inexact` entry, several alternatives, a combination,
   no entry. The diagnosis keeps its ICD-9-CM coding only; the coverage rule reads it as before (`unknown` for an
   inclusion, a person looks). Each such row is counted with D-580's counter under `map:icd9cm->icd10cm`, with
   the code, so a site sees which of its old codes are not carried over. Nothing is guessed.
5. **A mapping without `icd9cm_before` is unchanged** (no diagnosis is ICD-9-CM there).

## Consequences

- For the 3,521 ICD-9-CM codes with an exact entry (`042`, `585.x`, `001.0`), history criteria work again: an
  inclusion can be met and an exclusion can fire on a diagnosis of the ICD-9-CM years.
- For every other code nothing changes: an exclusion on such a diagnosis still cannot fire. That stays said, as in
  D-586. Whole families are outside (`428.0`, most of `250.x`, `070.20`, `070.30`, `714.0`).
- The shared mapping file changes, so the mapping version of every lake table changes (the goldens' version and
  table hash, no data column: the synthetic sites have no ICD-9-CM years).

## Not in this card

- Using `inexact` entries towards `unknown` for an exclusion or a "no history of" inclusion: that is the
  matching side (the coverage rule reads positive atoms only), another lane's file.
