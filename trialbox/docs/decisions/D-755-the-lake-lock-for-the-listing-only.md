# D-755 The backup holds the lake's lock for the listing only

- **Task:** PERF-011 and ENG-011 (build-vs-reuse 5.6; plan v7 wave 3), lane B2 · **PR:** `agent/PERF-011-lake-lock-listing-only` · **Date:** 2026-11-15 · **Status:** accepted

1. The backup lists the lake's served files (`db/`, `parquet/`) under the lake's lock as before (D-455), but there only opens each file and reads each sidecar; the bytes are read through the open files after the lock is let go. A rebuild's swap waits for the listing, not for hundreds of GB of reads; a file it renames or removes meanwhile is still read whole through its handle, so the backup stays one state.
2. A served file is never written in place: one whose size or time changed while it was read fails the backup, and every file is still checked against its sidecar after the read.
3. Without a lock file (a lake never rebuilt), or when the process may not hold every file open (its open-file limit, raised to the hard limit, less 256 kept free), the files are read under the lock, as before.
4. ENG-011: `lake/source.jsonl` (a line per rebuild) joins the audit chain's day files as append-only: taken up to its last whole line while it grows (T-728, D-493), never a failed backup.
5. Not in this card: PERF-010, the incremental backup (asked on #639: our own format, or the restic and pgBackRest spike first). Tests: `test_backup_without_pause.py` (the swap test now runs the swap before any byte is read and finds the backup all old; the fallback under the lock; the append-only rule).
