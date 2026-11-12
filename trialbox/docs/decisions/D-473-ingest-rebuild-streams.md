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
   mapped, and each source table's normalized rows to a file it reads back for each pass (`_TableRows`); the
   duplicate keys are counted over the keys sorted in runs. Only the data contracts (`TB_DATA_CONTRACTS`, off by
   default) still read a table's raw rows in memory. The unit defaults, presence words, site offset and merged chart
   numbers are applied to each resource as it is read back for writing; the validation sample, the JP Core sample,
   the missing-element counts and the unread elements are taken from that same stream (`validator.Sampler`: a heap
   of the k smallest hashes per type, the same resources as the sort of the old code). The reports, the snapshot and the samples are the same as before.
3. **The CSV read streams.** `CsvSource.rows` reads rows from the file in the detected character set, one at a time.
   A file that is not a readable CSV, or holds U+FFFD, is still quarantined before any of its rows is given (a first
   pass parses it without keeping rows). A UTF-8 file's character set is checked in chunks (`encoding.file_codec`, the same answer as
   `encoding.decode`); a legacy character set is still decided over all of the file's bytes (Open).
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

## What is still held (bounded by the patient count or by a batch, not by the night)

- Per patient: the patient ids (merged chart numbers), the pid-map pairs and identities, the lake's patient rows
  (one per pid). Measured: 13.6 KB per patient in the lake, about 0 in the adapter (`ingest_memory.json`).
- Per batch: `INSERT_BATCH` (4,096) rows per Parquet row group and notes per chunk and embedding batch; a sort run
  (`TB_INGEST_SORT_MB`); a read chunk of 1 MB in the character-set check.
- The validation sample: 1 % of each type with at least 3 (T-693 adds the absolute cap, F-06 rest).

## Open

- **The OMOP lake source** (`lake.source` = `omop`, not the default) still loads the whole snapshot into lists
  (`omop_rows`); its streaming is the OMOP load at scale (T-702, F-17).
- **A legacy character set** (Big5, Shift_JIS) is still decided over the whole file's bytes (`encoding.decode`): the
  detector weighs every reading of all of it. A UTF-8 export is checked in chunks.
- **The data contracts** (`TB_DATA_CONTRACTS`) still read a table's raw rows in memory (`governance.check_table`).
- `load_fhir.sync_snapshot` keeps one hash per resource for the fhir-store ledger (only with `TB_FHIR_BASE_URL`) and
  the SS-MIX2 reader lists the storage tree each night: not changed here.
- Proven at small sizes only (N and 4N); the 50,000-patient night under the default caps is T-687's nightly gate.
