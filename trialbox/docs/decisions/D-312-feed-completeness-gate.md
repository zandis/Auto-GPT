# D-312 The feed completeness gate: a partial night is held, never published

**D-312 A nightly ingest is checked per source table against the last good night before anything is published. A
missing or emptied table, a full night's table with more than `feed_completeness.max_table_drop_pct` (default 10) %
fewer rows, or a patient who left the feed while their records stayed holds the night. An OMOP feed batch that makes
a Relational Data Quality check fail on more rows than before is refused. Held nights never count towards the
snapshots retention keeps.**
Task T-611 (TB-PLAN-06 wave 1; deep review TB-DR-06 DATA-001, DATA-009, DATA-017). Builds on D-271. Date 2026-11-10.

* **Where.** `adapter.pipeline.completeness_check`, called in `run_ingest` after the NDJSON is written and before
  validation. A held night is not loaded into the fhir-store or the lake, so `CURRENT` stays, OMOP (loaded through
  the lake) writes no tombstone, and retention does not run.
* **Per table.** Each night writes `completeness.json` in its NDJSON folder: per mapping table, whether the export
  holds it (`present`; the CSV reader tells a missing file from an empty one, other readers say nothing), its rows,
  duplicate source keys, and the rows of the last good night. `reference` is the row count a later night compares
  with: a full night's own rows; a delta night carries its base's forward.
* **Holds** (each named in the ingest report, the `ingest.held` audit record under `incomplete`, and `held.json` in
  the folder):
  * a table in `feed_completeness.required_tables` missing, or empty on a full night (checked on the first night too);
  * a table the last good night had rows of that is missing now (full or delta night), or has no rows (full night);
  * a full night's table with more than `max_table_drop_pct` % fewer rows than the last good night, when that is more
    than `feedguard.FLOOR` (5) rows;
  * a patient of the last good night whose row left the feed while records pointing at them stayed (orphans).
  Tables in `feed_completeness.optional_tables` may go missing or empty. D-271's resource-type guard still runs: a
  table whose loss removes every record of a type is held by it even when optional.
* **Counted only.** Duplicate source keys per table (the last row wins, as before); every record that points at a
  patient the snapshot does not hold.
* **Override.** D-271's `TB_FEED_DROP_OVERRIDE='<snapshot>: <reason>'` lets that one night through this gate too; the
  reason is in the audit record (`drop_override`).
* **OMOP.** `omop.load` runs `omop.dqd.relational_violations` (isRequired, isPrimaryKey, isForeignKey) inside a feed
  batch's transaction before and after its writes. A check with more violated rows after is a refusal: the
  transaction rolls back, a `feed-refused` row is kept in `tb_load`, the lake answers 409 and the night is held. The
  same override names the batch.
* **Retention.** `tb_common.retention.snapshots_to_keep(..., good=)` counts only nights that passed (`passed.json`, a
  DuckDB, or `CURRENT`). The last N good nights are kept, and held nights newer than the oldest of them stay for the
  steward. Three bad nights no longer push the good snapshots out.
* **Readiness page.** For the hospital workspace, the newest `ingest.*` audit record (last 7 day files) is read. When
  it is `ingest.held`, question 2 shows "the last night of the hospital feed was held" with the tables named and a
  link to Admin > Sources.
* **Settings.** `feed_completeness: {max_table_drop_pct, required_tables, optional_tables}` in
  `schemas/settings.schema.json`. All are optional; the defaults are 10, none and none.

*Tests.* `tests/unit/test_feed_completeness.py`: the four bad feeds of the TB-DR-06 trace held with `CURRENT`, the
lake and the good snapshot unchanged; the same on a real lake; one missing-table test per mapping table; emptied
tables; a 15 % drop held and a 2 % drop passed; the band as a setting; an optional table; a required table on the
first night; the override; a delta night missing a table file; a vanished patient with orphans held; duplicates
counted; retention with held nights; the readiness item. `tests/unit/test_omop_core.py`: a batch that removes a
patient but keeps their facts is refused by the DQD check and passes with an override naming it.

*Not done.* A rise in volume (a doubled export) is not checked. Duplicate keys do not hold. The SQL and SS-MIX2
readers cannot tell a missing table from an empty one. The lake's own "Publish" does not read `held.json`. No steward
notice is sent beyond the audit record and the readiness item.
