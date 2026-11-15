# D-754 The export back from OMOP is streamed

- **Task:** T-702, the rest (F-17 of `docs/reviews/2026-11-11-scale-timeouts.md`; D-678 left the export whole), lane B2 · **PR:** `agent/T-702-omop-export-streamed` · **Date:** 2026-11-15 · **Status:** accepted

1. `omop.export` reads the store through a server-side cursor, 5,000 rows a round trip (`tb_common.db.Tx.iterdicts`, `ITER_BATCH`), each row passed on as it is read (`_emit_all`); `export_rows` still gives lists, the same rows in the same order.
2. `omop.export.export_spool` writes the rows table by table into files as they are read, one line a row with each value's type (the loader's typed JSON, D-678), and gives them back as re-readable streams; the lake's streaming path (`lake.source.lake_rows(stream=True)`, the OMOP source) uses it, the spool in the lake's scratch folder (`lake.store.temp_dir`) and removed once the streams are dropped.
3. The observation pass sorted every row in Python; its order (the hospital's rows, then the site's, by file position and part) is now the query's `ORDER BY`, so it streams too.
4. Still whole: the id maps, the open conflicts and the local concept codes (as large as the patients, staff and local codes, not the records), and the site facts (the site's own inputs).
5. Tests: `tests/unit/test_omop_export_streamed.py` (4: the spooled export equals the export, read twice; no query of it reads a table whole, at a batch of 7; the spool goes with its streams; the lake's stream path gives spooled streams on the lake's volume equal to the export).
