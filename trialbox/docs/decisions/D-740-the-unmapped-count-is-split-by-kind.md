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
3. **Every place the mapping engine counts is named with its kind** in a test that reads the engine's source: a new
   place fails it until its kind is named (the owner: a new kind is said, never folded into another).
4. **The batch row keeps it** (`datacore.dataops.DETAIL_KEYS`) and **the data-ops API answers it**: each entry of a
   batch's `unmapped` (`/api/v1/data/batches/{id}`) gains `kinds` with the three counts. A split that is not counts
   of the named kinds is not shown. **Field names for lane C2's page:** `unmapped_kinds` in the batch's detail;
   `kinds.code_unknown`, `kinds.unit_not_read`, `kinds.reference_data_not_reached` per table in the API.
5. Counts only: no code and no value in the split (the codes stay in `unmapped_codes.json`, D-580).

## What this does not do

- The page itself (showing the three numbers, their words in three languages) is lane C2's.
- The back-fill's report keeps its total only.
- The night's log line keeps its words (its second line already names a reference-data outage, D-593).

## Tests

`tests/unit/test_unmapped_kinds.py` (fail on the parent: the split does not exist): the kinds are named and sum to
the total; every place the engine counts is named with its kind; a real CSV night with two unknown lab codes and
one unit not read keeps `{"code_unknown": 2, "unit_not_read": 1, "reference_data_not_reached": 0}` beside the total
3, with no code in it; the batch row keeps the split and the page's total is unchanged; a split that is not counts
of the named kinds is not shown. No state change.
