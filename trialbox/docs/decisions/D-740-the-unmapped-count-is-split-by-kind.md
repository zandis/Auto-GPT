# D-740 The count of values the mapping could not use is split by kind

- **Task:** NEW-B-39 (the owner's yes of 2026-11-13, relayed by the integrator: "split")
- **PR:** this branch (`agent/NEW-B-39-unmapped-split-by-kind`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-580 (the night counts rows holding a value the mapping could not use, per source table, the codes
  in `unmapped_codes.json`), D-590 (a value whose unit is not read is kept without it), D-593 (a code the reference
  data could not be asked for), D-708 (lane C2's night page shows the count)

## Context

The night's page (lane C2's #534) shows one number per source table: rows that hold a value the mapping could not
use. That number sums three different things, each for a different person:

- a code no look-up, list of known codes or map gives a single answer for: the steward's code tab;
- a value whose unit is not the look-up's, or implausible without one: the lab's unit spellings;
- a code the reference data could not be asked for: an outage of the reference data, not a fault of the feed.

## Decision

1. **The night keeps the split per source table**, beside the total: the night's audit detail gains
   `unmapped_kinds`, `{table: {"code_unknown": n, "unit_not_read": n, "reference_data_not_reached": n}}`, every kind
   present (zero included). Their sum is the table's `unmapped` total, which keeps its shape and its number.
2. **The kinds** (`tb_common.unmapped.KINDS`) are read from the counter's own names (`adapter.pipeline
   .unmapped_kind`): `<map>:unavailable` is `reference_data_not_reached`; `unit_mismatch` and `no_unit_implausible`
   are `unit_not_read`; a look-up's name, `column:<column>` and `map:<from>-><to>` are `code_unknown`.
3. **Every place the mapping engine counts is named with its kind** in a test that reads the engine's source, by
   the name as written and how many places write it: a new place, even one that writes a name the same way as
   another, fails it until its kind is named (the owner: a new kind is said, never folded into another). A second
   test fails when the counter is written anywhere but its one door (`Mapper._note_unmapped`).
4. **The batch row keeps it** (`datacore.dataops.DETAIL_KEYS`) and **the data-ops API answers it**: each entry of a
   batch's `unmapped` (`/api/v1/data/batches/{id}`) gains `kinds` with the three counts. A split that is not counts
   of the named kinds adding up to the table's total is not shown. **Field names for lane C2's page:** `unmapped_kinds` in the batch's detail;
   `kinds.code_unknown`, `kinds.unit_not_read`, `kinds.reference_data_not_reached` per table in the API.
5. Counts only: no code and no value in the split (the codes stay in `unmapped_codes.json`, D-580).

## What this does not do

- **The kind is read from the counter's name.** A look-up, a column or a code system is named by the site's mapping,
  and the mapping puts no rule on those names: a look-up named `unit_mismatch` would be counted as a unit not read,
  a name ending in `:unavailable` as the reference data not reached (and would also make D-538 read its table whole,
  as it already would). No mapping in the repository does either. A rule on the names belongs to the mapping's
  loader (lane E); said to the integrator.

- The page itself (showing the three numbers, their words in three languages) is lane C2's.
- The back-fill's report keeps its total only.
- The night's log line keeps its words (its second line already names a reference-data outage, D-593).

## Tests

`tests/unit/test_unmapped_kinds.py` (fail on the parent: the split does not exist):

- the kinds are named and sum to the total;
- every place the engine counts is named with its kind, by its written name and its number of places; the counter
  is written only through its one door;
- a real CSV night with two unknown lab codes and one unit not read keeps `{"code_unknown": 2, "unit_not_read": 1,
  "reference_data_not_reached": 0}` beside the total 3;
- the batch row is told to keep the split; a split that adds up to the total is answered; one that is not counts of
  the named kinds adding up to the total is not shown.

`tests/console/test_dataops_unmapped_kinds.py`: a night recorded through the data-ops store, then the API: each
table's `kinds` beside its `rows`; a night recorded before the split answers its total alone. No state change.

## Review

One adversarial, read-only review by a fresh agent, by running (mutants of the engine and the page in a copy, real
nights: full, delta, an ICD-9 outage, a D-538 whole re-read, a re-run, then the batch row and the API with a test
client). It verified: every counting place's kind; the sum equals the total on every path that writes the detail,
by construction; the back-fill writes no `unmapped` to any batch row; the batch row and the API carry the split;
nights recorded before it answer without `kinds`. Its findings, all taken: the place test guarded the distinct
written names only (a reused name or a direct write passed: now counted, and guarded); nothing tested the API's
`kinds` (now a test through a recorded night); the reader did not check the sum (now it does); a docstring named
the wrong module. Said, not changed: the names are not validated by the mapping's loader (above).
