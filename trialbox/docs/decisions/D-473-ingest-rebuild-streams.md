# D-473 The night's ingest and the lake rebuild in streams; memory caps sized from the patient count

- **Task:** T-692 (`docs/plan/28-master-plan-v6.md` §6.2.10; plan v6.1 `31-master-plan-v6.1-addendum.md` §3, "as
  written")
- **PR:** this branch (`agent/T-692-ingest-rebuild-streams`)
- **Date:** 2026-11-12
- **Status:** proposed (accepted when merged)
- **Closes:** scale review 2026-11-11 (`docs/reviews/2026-11-11-scale-timeouts.md`) F-05 (Blocker), for the paths
  listed under Decision; the rest is listed under Open
- **Builds on:** OD-10 (limits from the hardware and the size of the data), D-360 (every service has a `TB_MEM_*`
  cap), D-271 (merge over the last good night; refused rebuilds leave `CURRENT` alone), D-462 (the lake lock: not
  changed here), the backfill's spool and merge (`adapter/backfill.py`, which already streams)

## Decision

1. **The merge streams.** `adapter.ndjson.write_snapshot` no longer loads the previous snapshot of a type into a
   dict. The night's resources go to a spool on disk (`ndjson.Spool`), are sorted in runs of a bounded size and
   merged (`heapq.merge`) with the previous snapshot's file, which is already sorted by id. The output is the same
   bytes as before: sorted by id, the last record of an id winning, a tombstone dropping an id only when the night
   did not send it again, `tombstones.json` as before.
2. **The night's resources are not held.** `adapter.pipeline` writes every mapped resource to the spool as it is
   mapped. The unit defaults, presence words, site offset and merged chart numbers are applied to each resource as
   it is read back for writing; the validation sample, the JP Core sample, the missing-element counts and the unread
   elements are taken from that same stream (`heapq.nsmallest` over the hash, the same resources as the sort of the
   old code). The reports, the snapshot and the samples are the same as before.
3. **The CSV read streams.** `CsvSource.rows` reads rows from the file in the detected character set, one at a time.
   A file that is not a readable CSV, or holds U+FFFD, is still quarantined before any of its rows is given (a first
   pass parses it without keeping rows). The character-set detector still reads the file's bytes once (Open).
4. **The Parquet build streams.** With the lake source `legacy` (the default), the rebuild flattens each type's
   NDJSON as it reads it and writes each table's Parquet file in row groups (`pq.ParquetWriter`); the counts and the
   drop check read lines without parsing; the note chunks are made, stored and embedded in batches. Rows, order and
   values are the same as before.
5. **Run size from the hardware.** The spool's sort runs hold at most `TB_INGEST_SORT_MB` MB of lines; unset, a
   sixteenth of the process's memory cap (cgroup, else the host), so the bound follows the container, not a guess.
6. **Caps from the patient count.** `deploy/install.sh` sizes `TB_MEM_ADAPTER` and `TB_MEM_LAKE` from the number of
   patients (`tools/trialbox/memcaps.py`): the lake's `CURRENT` snapshot when there is one, else `TB_SITE_PATIENTS`
   (the hospital's size, a declared setting). The figures come from a measured record
   (`deploy/measured/ingest_memory.json`, fixed part plus a part per patient, measured by `memcaps --measure`), never
   from a constant in code. A cap the operator set by hand is kept. `trialbox doctor` fails when a cap is below what
   the patient count needs.

## Open

- Filled in as the card lands.
