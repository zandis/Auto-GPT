# D-1270 A WHO-only ICD-10 code reaches ICD-10-CM only through a row whose ICD-10-CM code is wider (amends D-314)

- **Task:** lane M, card SDR2 part 1 (finding SDR1-01; the integrator's rulings on #639, comments 7102870311,
  7103067815 and 7103362435, and the follow-up asked in 7103427616) · **Date:** 2026-11-23
- **Status:** reserved for SDR2 part 1 (the integrator flips the row when merged)
- **Builds on:** D-314 (Japan's ICD-10 is WHO ICD-10; ICD-10-CM only for the same code), D-173 (the WHO-to-CM category
  bridge and its meaning of "wider"), D-135 and D-1233 (the `verify` basis tag), D-130 (unknown, never false)

## Decision

1. **The SS-MIX2 reader** gives a diagnosis its ICD-10-CM code in this order: the very same code when ICD-10-CM has
   it (D-314, unchanged), else the row of `services/adapter/mapping/jp_core/who_icd10_to_icd10cm.csv`, else none.
   The WHO code and its URI stay on the record, unchanged, in every case.
2. **A row is allowed only when its ICD-10-CM code holds all of the WHO code's meaning** (relation `wider`, in
   D-173's sense). A target that would say more than the WHO code says has no row: E14 (diabetes, type not stated)
   has no ICD-10-CM code that does not state a type; I64 (stroke not stated as haemorrhage or infarction) has none
   that does not state one. Those codes stay WHO-only and read unknown through the groupers, as D-314 decided.
3. **No category fallback.** A WHO code X.Y with no row does not take the category X.
4. **The rows come from public sources only**: the ICD-10-CM Alphabetic Index and Tabular List FY2026 (CMS, public
   domain), code strings only, no WHO ICD-10 text. The first rows: F00, F00.0 to F00.2 and F00.9 to G30.9; F01.9 to
   F01.5; A16.0 to A16.2 to A15.0. Each is marked `verify`.
5. **A `verify` row is applied** (as the 病名 sample rows are) and reported apart: the reader counts
   `diagnosis:ICD-10-CM from the WHO-to-CM table (applied, not verified)`; the night tags the resource with D-135's
   `verify` basis (`adapter.pipeline`, a `VerifyRule` on the diagnosis table), so the lake's `site_fact` lists every
   fact that rests on one; `tools/mapping_coverage.py` prints "applied, not verified" with a count.
6. **A code with neither the same code nor a row** is counted in the reader's `missed` (`diagnosis:<WHO code>`), so
   it reaches `reader.json`'s unmapped list and the mapping check's list; it is never dropped.

## Why

Finding SDR1-01: every shipped diagnosis value set is ICD-10-CM, so a Japanese record coded F00.1 (dementia in
Alzheimer's disease) or A16.2 (tuberculosis of lung, not confirmed) could only read unknown, although ICD-10-CM has a
code that holds all of its meaning. A row that holds all of the meaning can make a criterion true where the record
says so, and never false where it does not. A row that says more (E14 to E11.9, as the Alphabetic Index's default
does) would make a record of an unstated type read as type 2: false on a type 1 exclusion, true on a type 2
inclusion, with nothing in the record to say so.

## Not chosen

- **The Alphabetic Index's default code for every WHO-only code** (E14 to E11.9, I64 to I63.9): a coding convention,
  not what the record says (point 2).
- **A category fallback** (X.Y to X): ICD-10-CM narrowed or moved parts of many categories (D-173's note), so a
  category is not always wider.
- **Applying only verified rows** (as for PRB-14): no row is verified yet, so nothing would change; the integrator
  ruled to apply them and report them apart.

## Proof

`tests/unit/test_mapping_coverage.py` (the table's rows, the reader's columns and counts, a whole SS-MIX2 night that
tags the fact and lists the unmapped code); `tests/unit/test_japan_icd10.py` (the reader and the JP mapping, as
amended under the integrator's ruling).
