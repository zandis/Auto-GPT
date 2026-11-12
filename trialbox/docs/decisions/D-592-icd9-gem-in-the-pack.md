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
   The file names ten pairs twice (once alone, once inside a combination: `666.02` and `O72.0`); the pack holds
   one row per pair with both flag sets, and the vendor's build refuses a map that names a pair twice (the box's
   table would refuse it at the hospital).
4. **What the rows may be used for** (the rule for the next part, the nightly mapping; said here because the
   file's own guide says it: "an entry of the single type is not the same as a one-to-one mapping", and "GEMs
   are not crosswalks"):
   - an `equivalent` row (3,521 codes) may give the diagnosis its ICD-10-CM coding, tagged as mapped;
   - an `inexact` row (7,244 codes) is a candidate, not a meaning, as `tb_common.refdata.in_set_via_map` already
     treats the Taiwan edition map: it may turn "not in the value set" into `unknown`, and it must never let an
     exclusion answer "no" or an inclusion answer "yes" by itself. Examples from the file: `714.9` (unspecified
     polyarthropathy) goes to `M06.4`, inside the rheumatoid arthritis family; `070.42` goes to `B17.0`, another
     concept; `274.11` goes to `N20.0` and loses gout;
   - a `relatedto` row is never the code. Whole families are `relatedto`: `428.0`, 26 of the 40 diabetes codes
     `250.x`, hepatitis B `070.20` and `070.30`.
5. **Known limit: the edition.** The 2018 file lists the final ICD-9-CM edition only. A code of an older edition
   (`585`, `274.0`, `274.1`, `277.0` have no line) gets no row, and stays an ICD-9-CM diagnosis no value set reads.

## Not in this card

- Using the map at night (an ICD-10-CM coding beside the ICD-9-CM one, tagged as mapped): the next part. It needs
  the reference data at mapping time, the same mechanism NEW-STD-5 (NHI drug code to ATC) needs.
- The reverse file (`2018_I10gem.txt`) and the procedure GEMs: not needed by any criterion.
