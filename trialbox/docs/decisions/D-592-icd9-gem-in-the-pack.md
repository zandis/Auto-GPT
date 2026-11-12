# D-592 The ICD-9-CM to ICD-10-CM map (CMS General Equivalence Mappings) is a source of the reference-data pack

- **Task:** NEW-STD-1, second half, part 1 (finding STD-001 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/11-standards.md`; D-586 "Not in this card")
- **PR:** this branch (`agent/NEW-STD-1b-icd9-gem-pack`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-586 (a Taiwanese diagnosis of the ICD-9-CM years says so), D-140 and D-170 (the reference-data
  pack and its registry of sources), D-317 (a version-pinned download is checked by its sha256)

## Context

Since D-586 a diagnosis keyed before 2016 carries the ICD-9-CM code system. No value set reads ICD-9-CM: an
inclusion on such a diagnosis is `unknown`, and an exclusion on it cannot fire. The repair D-586 names is an
ICD-10-CM coding beside the ICD-9-CM one wherever a public map gives exactly one. The repository held only a
60-row sample (`mapping/mimic/tables/icd9_to_icd10cm.csv`).

## Decision

1. **Source.** The 2018 ICD-10-CM General Equivalence Mappings of the Centers for Medicare & Medicaid Services
   (CMS), the file `2018_I9gem.txt` (ICD-9-CM to ICD-10-CM, 24,860 lines, 14,567 ICD-9-CM codes) in
   `2018-ICD-10-CM-General-Equivalence-Mappings.zip`. 2018 is the last edition: CMS stopped maintaining the GEMs
   after it. A work of the United States government: not subject to copyright in the United States (17 U.S.C.
   105). The pack item is `cms_gem_icd9_icd10cm`, kind `map`, distribution `ship`.
2. **Pinned.** The download is pinned by its sha256
   (`1c5e5f14026ace48437a0d1c485d282fb5d171c357c6ab4f7798fc0a1e3624a2`, fetched 2026-11-12): the vendor's fetch
   and build refuse another file. Nothing is fetched on a box: the pack carries the rows.
3. **Rows.** One map row per line that names a target: source `http://hl7.org/fhir/sid/icd-9-cm` (the code with
   its dot: `714.0`, `V58.69`, `E800.0`), target `http://hl7.org/fhir/sid/icd-10-cm` (`M06.9`). A "no map" line
   gives no row. The relation says what the file says:
   - `equivalent`: the only line of its ICD-9-CM code, flagged exact;
   - `inexact`: the only line of its code, flagged approximate, not part of a combination;
   - `relatedto`: one of several lines of its code (alternatives), or part of a combination (several ICD-10-CM
     codes together stand for the one ICD-9-CM code).
   Each row keeps the file's five flags and the number of lines its code has (`extra`).
4. **What may be used as "the" ICD-10-CM code** (for the next part, the nightly mapping): only `equivalent` and
   `inexact` rows, that is a code with exactly one target and no combination (10,765 of the 14,567 codes).
   `714.0` gives `M06.9`. `V58.69` has three alternatives and gives none: unknown stays unknown.

## Not in this card

- Using the map at night (an ICD-10-CM coding beside the ICD-9-CM one, tagged as mapped): the next part. It needs
  the reference data at mapping time, the same mechanism NEW-STD-5 (NHI drug code to ATC) needs.
- The reverse file (`2018_I10gem.txt`) and the procedure GEMs: not needed by any criterion.
