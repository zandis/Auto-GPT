# D-679 The lake keeps its snapshots within a byte budget

- **Task:** NEW-B-38 (deep review 2026-11-13, DATA-025, High; placed with lane B by the owner on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-38-lake-byte-budget`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** SPEC §10.3 (the last N nightly snapshots and each month's last one for M months), D-403 (a job's
  hold keeps its snapshot), D-462 (a snapshot being rebuilt is left alone), D-529 (a night refused before it reads),
  T-611 (only nights that passed count)

## Context

The lake kept its snapshots by count only: 3 nightly and up to 36 month-end ones (NDJSON, Parquet, DuckDB and
generations each). The review measured a dense patient at 0.55 MB of NDJSON, 0.05 MB of Parquet and 0.23 MB of
DuckDB a snapshot: about 41 GB a snapshot at 50,000 patients, 1.6 TB for 39 of them against a 2 TB disk. Nothing
looked at the bytes, and nothing checked the free space before a night wrote its snapshot: a full disk was found
by the night that failed on it.

## Decision

1. **A byte budget for the lake's folder**: `TB_LAKE_BUDGET_MB` (declared); unset, **half the disk the lake is on**
   (`LAKE_DISK_SHARE`). The other half is for what shares that disk on a box (the database, the backup's staging,
   the logs) and for a night's build while the last one is still kept.
2. **After the count's pruning, while the lake is over its budget**, in this order:
   1. the **NDJSON of the oldest month-end snapshot** goes, then the next: its DuckDB and Parquet stay, so the lake
      still serves it (feasibility and cohort history read the DuckDB); it can no longer be rebuilt from its
      NDJSON (after a lake schema change, `LAKE-SCHEMA` refuses it and it stays unread until a back-fill);
   2. when every month-end NDJSON is gone, the **oldest month-end snapshot whole**, then the next.
3. **Never dropped for the budget**: the served snapshot (`CURRENT`), the N nightly ones (the delta's merge base is
   the newest of them), and a snapshot a job holds (D-403). A snapshot being rebuilt is skipped, as before.
4. **A budget that cannot be met** (what must stay is larger) is logged as an error and kept in the night's audit
   event (`lake_budget`: the budget, the bytes used, the month-end NDJSON and snapshots removed, `unmet`, the
   sentence). The night is not held for it: its data is right; the disk is the steward's to grow.
5. **The room for tonight**: before a night reads or writes anything, the free space on the lake's volume is
   compared with what the newest earlier snapshot took. Less refuses the night (`NoRoomForNight`, "not enough free
   disk for tonight's snapshot: about X MB needed ..., Y MB free"), audited as `ingest.failed` with `refused:
   disk`, as a night of the future is (D-529). The first night has nothing to measure by.

## What a person sees differently

On a box over its budget: month-end snapshots that lost their NDJSON (said in the log and the night's event), and
in time fewer month-end snapshots. On a full disk: a night refused with the two numbers, instead of a night that
fails while writing. A box within its budget sees nothing new.

## What this does not do

- The owner's brief names "an erasure hold": no such hold exists on master. An erasure (opt-out) rewrites or
  withholds records; it does not hold a snapshot. Held generations are covered by the job holds (D-403), which name
  the date of the generation they hold. If an erasure hold is made, it joins the snapshots that are never dropped.
- Month-end NDJSON is not compressed (the review measured 263 MB to 23 MB gzipped): every reader of NDJSON would
  have to read it; a separate card if the budget is often unmet.
- The budget counts the lake's folder only (a file with several names once), not the database or the backups.

## Tests

`tests/unit/test_lake_byte_budget.py` (11 tests; they fail on the parent, which has no budget):

- within the budget the count alone decides;
- over it, month-end NDJSON goes first, the oldest first, the DuckDB kept; then whole month-end snapshots, the
  oldest first; the nightly ones untouched;
- a budget that cannot be met keeps what must stay, logs and returns the sentence;
- a held month-end snapshot is never dropped;
- `prune_snapshots` still answers the snapshots removed whole;
- unset, the budget is half the lake's disk; a budget that is not a whole number of MB above 0 is refused;
- a night with less free space than the last snapshot took is refused before anything is written, and audited.

The existing pruning, hold, retention and ingest tests pass unchanged (101 with the new ones). No state change of
its own: a refused night writes nothing, the pruning deletes as it did.
