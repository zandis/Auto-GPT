# 9. All-history back-fill and held snapshots

A site's first load is every year its hospital system holds, not one night (owner decision C-02, MR-129). The
nightly full load holds the whole night in memory, so the first load runs as a **back-fill** instead
(`services/adapter/backfill.py`, T-305b, D-403):

    python -m adapter.cli backfill --source csv --path /data/export --snapshot 2026-11-10 --first-years 5

- **The same snapshot, by year.** The back-fill reads the source once and writes each record to a spool file of its
  clinical year (`<lake>/backfill/<snapshot>/spool/<year>/`); patients, staff, sites and undated records go to
  `base`. It then sorts `base` and the years one at a time, newest first, and merges them into the snapshot's NDJSON.
  The result is the same bytes the nightly full load writes for the same source (test
  `tests/unit/test_backfill.py`). A record dated after the snapshot's year (a booked appointment) is in that year.
- **A Data Quality report per year.** `runs/<year>/dq.json`: records per type, missing required elements, orders
  with no date. Rows the mapping cannot read are counted per table; more than 1 % of a table holds the back-fill, as
  on a nightly run.
- **Recent years first.** With `--first-years 5` the snapshot is published once `base` and the newest five years are
  in, so screening runs on recent data while older years load, and again when every year is in. Each publish checks
  a structural sample and the drop guard (D-271), loads OMOP when the dual write is on, rebuilds the lake and writes
  `passed.json`; `backfill.json` beside the NDJSON says which years it holds.
- **Resumable.** A back-fill stopped at any point is run again with the same command. A finished spool for the same
  source, mapping and snapshot is kept; a year with its `dq.json` is not sorted again; a publish is repeated whole.
  `progress.json` says where it is. The audit gets one `ingest.backfill` event per run.
- **Memory.** The back-fill holds one year of one type's ids while sorting, and the patient list; the CSV reader
  still reads one table file at a time. Measured on stacked copies of the synthetic site:
  `docs/plan/measurements/backfill-2026-11-11.md`.
- **Not in the back-fill.** Data contract row checks, the completeness gate against the last night, the JP Core
  sample and the fhir-store load run on the nightly loads that follow.

**Deletes say why.** In OMOP (§7) a tombstone event carries a reason: `deleted at the source` when the night's
`tombstones.json` lists the record (a delta night's SS-MIX2 flag, FHIR `deleted[]` or CSV `deleted` row), else
`left the feed`.

**Held snapshots (FR-REP-02).** A job that pinned a snapshot (T-305a, D-383) also *holds* it on the lake
(`<lake>/holds/<job id>.json`, `POST /holds` on the lake service) until it ends or waits no more:

- the lake refuses to rebuild a held snapshot (`SnapshotHeld`, HTTP 409): nothing is written and `CURRENT` stays;
  it checks when the rebuild starts and again at the swap (D-462): a rebuild builds beside the served files
  (`db/<snapshot>.building`, `parquet/.building/`) and, if a job came to hold the snapshot during the build, discards
  the build and is refused, so the job reads the bytes it pinned to its end;
- `hold`, `release`, the pruning and a rebuild's start and swap take one lock (`<lake>/.rebuild.lock`, `flock`),
  which holds across the lake's worker processes;
- one rebuild of a snapshot runs at a time (`<lake>/locks/<snapshot>.build.lock`): a second one, from another worker
  or a caller that retried after its HTTP client timed out, is refused at once with "already building" (HTTP 409),
  and a site publish shows that as a waiting publish (`building: true`);
- the adapter's pruning keeps every held snapshot (`prune_snapshots`);
- a hold older than 14 days is a job that died and protects nothing.

**Batched publish on `main`.** Site set-up decisions (a fact confirmed, a code mapped) on the hospital's lake used to
rebuild the current snapshot at every tap. Now a decision within `TB_SITE_PUBLISH_BATCH_SECONDS` (300 in the
production compose file; 0 = every decision publishes) of the last publish waits, and the waiting decisions are
published together when the window closes (the orchestrator checks every minute and after each job) or when a person
presses Publish. Nothing is published while a running job holds the snapshot, even on Publish: the batch follows when
the job ends. What waits is the difference between the stored facts and the last publish, so a restart loses nothing.
