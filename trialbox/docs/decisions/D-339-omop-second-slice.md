# D-339 OMOP second slice: the adapter writes the CDM, the large tables are partitioned by year

**D-339 The OMOP schema keeps the name `omop`. Behind the flag `omop.dual_write` (default `off`) the adapter loads
each night that passed its checks into the OMOP CDM as soon as the snapshot's NDJSON is written, before and apart from
the lake rebuild; a refused or failed load is recorded and never holds the night. The seven large clinical tables are
partitioned by the year of their required date. After every dual-write load the Data Quality Relational checks
(foreign keys included) run, and their result is in the ingest report. The parity tool records wall time and memory.**
Task T-106 (TB-PLAN-06 wave 2; TB-ASSESS-01 T-106; closes the first half of CR-060 and part of CR-061). Builds on
D-151, D-207, D-271, D-301, D-312. Takes the place of the reservations D-303 (schema name) and D-304 (dual write).
Date 2026-11-10.

* **Schema name.** The plan's WS-03.4 says `cdm`; the code, the backups, the DQD, the goldens and every test say
  `omop` (D-151). It stays `omop`: renaming it would move every store of record for no reader's benefit, since OHDSI
  tools take the schema name as a setting. The plan text is what changes (WS-03.4 "the CDM schema" means `omop`).
  This was the owner's question in TB-ASSESS-01 (D-206); D-311 removed the gate, so the recommendation is taken.
* **Dual write** (`adapter.dual_write`, one hook in `adapter.pipeline.run_ingest`):
  * The flag `omop.dual_write` (`off`, `on`; seed variable `TB_OMOP_DUAL_WRITE`) is declared in
    `tb_common.flags` and changed on `/ops/flags` with a reason, like `lake.source`. It is read once per night.
  * Only a night that is not held is loaded. The batch is the snapshot's whole NDJSON folder (on a delta night the
    folder already holds the merge), named by the snapshot, in the lake's own store (`omop.schema.schema_for`): the
    lake's OMOP load of the same snapshot later finds every record `same`.
  * The load is `omop.load.load_batch`: one transaction, so all or nothing. A refusal (`OmopError`: an older batch,
    D-271's mass-tombstone guard, D-312's Data Quality hold) is `refused`; any other error is `failed`, rolled back,
    and kept as a `feed-failed` row in `tb_load`. Either way the night goes on as without the dual write: not held,
    `CURRENT` moves as before. A failure names only the error type, since a database message can quote a cell.
  * A feed file that arrives between nights runs as its own night with `rebuild_lake` off: its records reach `omop`
    within that run while `CURRENT` and screening stay on the last published night.
  * The summary (`OmopLoadSummary`) is the ingest report's new optional field `omop` (schema `ingest_report` 1.4.0)
    and, shortened, the `omop` entry of the night's `ingest.*` audit event.
* **Foreign keys as data, every night.** The official constraints file is still not applied (D-151). After each
  dual-write load `omop.dqd.relational_violations` runs every `isRequired`, `isPrimaryKey` and `isForeignKey` check of
  the loaded tables; the count of checks and the ones with violated rows go into the summary.
* **Partitions** (`omop.partitions`, `omop/ddl/partitions.sql`, migration 4 of the `omop` schema):
  `visit_occurrence`, `condition_occurrence`, `drug_exposure`, `procedure_occurrence`, `measurement`, `observation`
  and `note` are partitioned by range of their required date, one partition per year (`<table>_y<year>`), plus a
  default partition (`<table>_ydefault`) that takes the rows a store held before the migration. The loader makes each
  year's partition inside its own transaction before it writes rows of that year, and moves that year's rows out of the
  default partition first. The pinned official DDL is unchanged (migration 1 applies it byte for byte); migration 4
  rebuilds the tables with the same columns and the official indexes. The primary key becomes `(id, date)`, since
  PostgreSQL asks that a partitioned table's key holds the partition column; ids still come from one sequence and
  the DQD `isPrimaryKey` check still tests that the id alone is unique. `CLUSTER` is dropped (PostgreSQL does not
  cluster a partitioned table). A record whose date was imputed (no date in the source: the batch date, D-151) lands
  in the partition of that year and keeps its `tb_record.date_imputed` flag; there is no separate partition for it,
  because the CDM row has no column that says it.
* **Vocabulary version.** `cdm_source.vocabulary_version` is the active Athena release (its `tb_vocab_release`
  row with `vocabulary_id = 'None'`, T-105b), cut to the CDM's 20 characters; "TB local, no Athena" until a bundle
  is loaded.
* **Backups.** `pg_dump` of the schema carries the partitions; the backup drill now compares the partition layout and
  each partition's rows before and after the restore.
* **Timings.** `tools/omop_parity.py --profile ci|50k` records each lake rebuild's wall seconds, the loader's seconds
  per batch (`tb_load`) and the process's resident memory sampled every 50 ms during each rebuild (peak, growth),
  committed as `eval/omop_parity/report-ci.json` (and `report-50k.json` when run).

Not done here (card T-106 "Goal" items left for later cards): `NOTE` and `NOTE_NLP` rows from site set-up facts;
a loader whose memory stays flat at 50k (the batch is still read whole; streaming `COPY` is T-305b); the flip of
`lake.source` to `omop` (T-202).
