# Architecture review, seam `lifecycle`: the night and the data lifecycle across stores

Reviewer: seam `lifecycle`. Date 2026-11-12. Code: `origin/master` at `f8ceaa7d` (worktree `/home/user/wt-arch-lifecycle`),
read-only. Open branches read with `git show` only: `origin/agent/T-207-derived-data-rest` (PR #262),
`origin/agent/T-203b-s2b-vector-store`, `origin/agent/T-206b-optout-erasure-retention` (holds only the D-452 claim, no code).
Paths are under `trialbox/`. "CONFIRMED" = a throwaway test ran and asserted it
(`/tmp/arch-lifecycle-t/test_seam_lifecycle.py`, 4 tests, all passed); "READ" = from the code only; "GUESS" is marked.

## 0. Summary

There is no identity for "tonight's data". The only name is the snapshot's **date** (`pipeline.py:398`), and a date is
not a content identity: the same date is rebuilt in place by a site publish (`sitesetup/service.py:403-414`), by a
second ingest on the same day and by a re-run (`pipeline.py:593`). Of the downstream stores only the lake file and the
job's pin carry that date; FHIR, OMOP, derived rows, the vector store, twins, the pool and the data-operations row are
each "the newest", advanced by different triggers, with different (or no) guards against moving backwards and
different (or no) completeness marks. Every step of the night is a side effect inside one function
(`adapter.pipeline._run_ingest`, then `orchestrator.scenarios.admin.ingest`), in a fixed order with "never fails the
ingest" wrappers, so a failure in the middle leaves the stores at different nights and nothing records which.
Erasure is a list of three stores in one module (`optout_worker.py:108-114`); six more stores hold the patient and no
test enumerates them.

## 1. The seam as it is

### 1.1 Who calls whom

| # | Caller → callee | What the caller assumes | What the callee does | Anchor |
| --- | --- | --- | --- | --- |
| 1 | scheduler (clock 02:00) → orchestrator job INGEST → adapter `POST /run` (7,200 s, no retry) | one call = one night; the reply says passed / held | names the night by the wall-clock date; one ingest at a time (409 otherwise) | `scheduler.py:270`, `clients.py:125-133`, `adapter/app.py:35-58`, `pipeline.py:398` |
| 2 | adapter → OMOP dual write | "never holds the night" | loads before FHIR and the lake; refuses an older batch | `pipeline.py:694-699`, `omop/load.py:662-667` |
| 3 | adapter → fhir-store `sync_snapshot` | failure is an error, not a hold | makes HAPI "hold exactly the snapshot"; no guard against an older night | `pipeline.py:701-710`, `load_fhir.py:160-187` |
| 4 | adapter → lake `rebuild(snap, dir)` | a refusal (409) = held night; any other failure = failed | builds, promotes unless older than CURRENT or held by a job (checked once, at the start) | `pipeline.py:711-720`, `lake/store.py:513-521`, `:624`, `:633` |
| 5 | adapter → `dataops.record_night` | one row at the END of the run | `PUBLISHED` iff `passed`; `HELD` iff `held`; else `FAILED` | `pipeline.py:834-856`, `dataops.py:135-140`, `:256` |
| 6 | INGEST job → `scheduler.after_ingest` → MICROBATCH per pool study | the ingest passed, so CURRENT is tonight | the micro-batch pins whatever CURRENT is when a worker takes it | `admin.py:85-89`, `scheduler.py:161-183`, `microbatch.py:182` |
| 7 | INGEST job → `twins_after_ingest(report.snapshot)` | the passed night is the newest | builds from the named snapshot, supersedes whatever twin is current | `admin.py:58-70`, `:90`, `twin.py:375-413`, `:431-447` |
| 8 | (PR #262) INGEST job → `derive.after_ingest(report.snapshot)` | the same | recomputes every patient from that snapshot; rows keyed (pid, score, anchor), batch_run keyed by snapshot | branch `orchestrator/derive.py`, `derived_store.py` (branch) |
| 9 | job → `PinnedLake.pin()` → lake `hold` | "my snapshot does not change until I end" | pin = read CURRENT, then write a hold file; the lake checks holds only when a rebuild starts | `jobs.py:85-117`, `lake/store.py:377-387`, `:513` |
| 10 | sitesetup `publish("main")` (60 s tick, after each job) → lake `put_site` + `rebuild(CURRENT)` | rebuilding the served snapshot in place is safe when no job holds it | same date, new bytes; nothing downstream is told | `sitesetup/service.py:396-424`, `orchestrator/app.py:131-132`, `:557` |
| 11 | opt-out worker (every 5 min) → register, pool, candidate registry, OMOP | "one tick takes every opted-out patient out of the stores it knows" | three stores; reads the lake's CURRENT for the registry | `optout_worker.py:108-114`, `:124-141` |
| 12 | every screening path → `opted_out(as_of=job.received_at)` and `opted_out()` at publish | the register is an event log that only grows | true until a restore | `optout.py:257-292`, `screen.py:179`, `:198` |
| 13 | steward `/data-ops` decide → `DataOps.decide(promote=...)` | accept publishes the held night | no promoter exists: accept is refused | `dataops.py:302-320`, `console/dataops_page.py:74`, `:173` |
| 14 | cron 04:45 → backup (pauses every writer but `db`) | nothing important is running | a job crossing 04:45 is frozen | `backup_schedule.py:700-714`, `deploy/backup/trialbox-backup.cron` |
| 15 | restore → `pg_restore` + directories moved aside | the backup is the box | register, jobs, dataops, derived, twins, vec and audit all go back to T | `backup.py:878-1006` |
| 16 | orchestrator start → `interrupted()` → requeue | "scenarios are idempotent" | every non-terminal job runs again from zero, INGEST included | `core.py:522-528`, `db.py:235-241` |

Two callers, two contracts for the same thing:

* **"The night passed."** The adapter means "no error in any step". The lake means "this file is CURRENT". The
  data-operations row means "PUBLISHED". They disagree when a step after the gate fails (F-2).
* **"The snapshot."** The job (T-305a) means "these bytes". The lake, the site publish and the adapter's re-run mean
  "this date" (F-1, F-3, F-5).
* **"Not older than what is served."** The lake (`store.py:519`) and OMOP (`load.py:662`) refuse to go back. FHIR, the
  twin build and (PR #262) the derive batch do not (F-4).
* **"Complete."** The lake: `.building` renamed + sha sidecar. OMOP: one transaction + `tb_load` row. NDJSON night:
  `passed.json` / `held.json`. Dataops: the final state only. Derived (PR #262): `batch_run.finished_at`. Twin, vec,
  pool, FHIR: nothing.

### 1.2 The timeline matrix

Keys: **D** = the snapshot date; **–** = no key (one live state). "Newest" = the reader takes whatever is there.

| Artefact | Written by / when | Keyed by | Read by; specific or newest | Complete when | Held night | Failed step | Restart mid-step | Re-run of an old job | Restore | Opt-out / source delete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NDJSON night `lake/ndjson/D` | adapter, 02:00 (`pipeline.py:590-603`) | D (wall-clock date, or `snapshot=`) | next delta night (`merge_base`, `:1049`), lake rebuild, OMOP load, backup (CURRENT + 2 newest) | `passed.json` (`:724`) | stays, `held.json` (`:750`); never a merge base | no marker at all; folder stays | a re-run of a promoted night goes to `ndjson-rerun/D`, moved in when it passes the gate, **before** the loads (`:685-692`) | n/a | CURRENT's + 2 newest only | opt-out: stays (3 nightly + 36 month-ends). Source delete: `tombstones.json`, dropped from the next night |
| FHIR store (HAPI) | adapter `sync_snapshot`, after OMOP, before the lake (`:701-710`) | – (ledger `lake/fhir_ledger`) | compile-time CQL gate; `FhirEvaluator`; newest | none (ledger written twice, `load_fhir.py:177`, `:186`) | not loaded | error, night "failed"; the lake is still rebuilt and promoted | ledger makes it resumable | n/a | `hapi` dump at T; ledger from the lake dir at T | opt-out: **stays** (no path deletes). Source delete: DELETE at the next sync. An older night re-run moves it **back** (READ) |
| Lake `db/D.duckdb` + Parquet | lake `rebuild`: adapter (night), sitesetup publish (60 s tick), backfill, CLI | D | jobs (pinned D), console pages / worker / EDC prefill (CURRENT) | `.building` → rename, `.sha256`, `lake_meta.built_at` | not built | CURRENT unchanged | `.building` left; rebuilt | reads D if it still exists (3 nightly + 36 month-ends), **as it is now** (rebuilt in place) | every DuckDB and Parquet at T | opt-out: stays in every kept snapshot (legacy source); with `lake.source=omop` left out of later rebuilds, consent rows kept. Source delete: gone from the next snapshot, stays in older ones |
| `CURRENT` | `Lake.promote` (`store.py:414-419`) | → D | every unpinned reader; a job's first lake call | atomic rename | unchanged | **moves even when the night ends "failed"** (F-2) | – | not read (pin recorded) | at T | – |
| Lake holds `lake/holds/<job>.json` | job's first lake call; released at job end | job id → D, 14-day TTL | `rebuild` (start only), `prune_snapshots`, sitesetup | – | – | – | file stays; a re-queued job re-holds | "not held" is only logged (`jobs.py:107-116`) | at T (jobs at T) | – |
| `embed_cache.duckdb` (lake vectors) | lake `_embed` in every rebuild | chunk sha + model | `chunks_search` | per batch | – | – | – | read by sha | at T | **never deleted** (no DELETE in `store.py`): vectors of an opted-out or deleted patient's notes stay |
| OMOP (`omop.*`, `tb_record`, `tb_record_event`, `tb_load`, `tb_withheld`) | adapter dual write (flag) and/or lake rebuild with `lake.source=omop` (`source.py:142-170`) | batch = D; one live state + event log | lake rebuild (`export_rows()` = now); `export_rows(as_of=)` (T-202; T-627 will call it) | one transaction + `tb_load` row | not loaded | rolled back; refusal row `feed-refused` | all or nothing | n/a | at T | opt-out: tombstoned + `tb_withheld`; **before-images kept** (`load.py:1473-1477`), `tb_consent` kept. Source delete: tombstone "deleted at the source". An as-of export winds the tombstones back (F-9) |
| `dataops.batch` / `batch_step` | adapter `night_event`, **end of run only** (`pipeline.py:834`) | (source, D, attempt) | `/data-ops`, readiness lights (newest night) | the final state; all step rows written at once | `HELD`; left only by `decide`; accept refused (no promoter) | `FAILED` (also when CURRENT moved, F-2); nothing when the adapter is killed | no row (the doc says "no row while a night is running", `dataops.py:29-30`) | – | at T: nights after T have no row | holds tables and counts only |
| Derived `score_row`, `conflict` (+ `batch_run` in PR #262) | master: **nobody on the production path** (`run_batch` has no caller); PR #262: `derive.after_ingest` inside the INGEST job | rows: (pid, score, anchor oid), "current" = `superseded_at IS NULL`; batch_run: D | master: twin build (`twin.py:407`); PR #262: screening (`stored_scores`), newest rows + `batch(D)` | PR #262: `finished_at` | not run | PR #262: no finished batch → every stored-score answer is "needs information" | INGEST re-runs from zero | PR #262: reads **today's** rows under an old D's finished batch (F-6) | at T | opt-out: **stays**. Source delete of a patient: not visited by the batch, rows stay current |
| Vector store `vec.note_chunk`, `vec.embedding` | master: nothing on the production path (only `tools/backup_drill.py`); T-203b: `index_snapshot` after the rebuild | (did, chunk_no), sha+model; no D | T-203b S2b: verifies each window note of the pinned snapshot against the stored chunks, else falls back (`vec/s2b.py` on the branch); T-203c: whole store | none; verified on read by content | – | – | idempotent by sha | verify-or-fall-back | at T | opt-out: `delete_patient` exists (`vec/store.py:248`), **nobody calls it**; skipped at index time only. Source delete of a note: chunks stay |
| Twins `profile.tb_patient_profile` | INGEST job, last step (`admin.py:90`) | (pid, version); `snapshot`, `checked_snapshot` recorded | console twin API: `current(pid)` = newest | none; per-patient transaction | not built | "never fails the ingest": the old twin stays, nothing says it is stale | built again | – | at T | opt-out: erased **only at the next build** (`twin.py:394-397`), not by the worker (CONFIRMED). Patient gone from the feed: `missing += 1`, the stored twin stays (`:402-404`) |
| Candidate pool `orch.pool` | SCREEN / MICROBATCH `persist_pool` | (ruleset, pid) + version, job_id, last_eval | MICROBATCH, twin `study_pids`, console | none | not touched | – | `pool_as_received` reconstructs (`microbatch.py:156-167`) | re-run copies the **live** pool (`rerun.py:111`) | at T | opt-out: removed by the worker; re-read at publish. Source delete: stays |
| Candidate registry | console / lifecycle | (ruleset, pid) | console | – | – | – | – | – | at T | open → withdrawn; consented / enrolled kept (OD-8) |
| Job outputs (object store) | each job `ctx.publish` | job id | MICROBATCH `seen_from` (the last SCREEN's lists), not-matched sample, console, mails already sent | job state `done` | INGEST report published either way | job `failed` | job re-runs from zero and publishes again | compared by sha | at T | opt-out: **stay** (365 days): `candidate_list_*.json`, `excluded_*.json`, micro-batch `pids`; readers filter at read time. Mails already sent cannot be recalled |
| Jobs `orch.jobs` (`snapshot_date`) | orchestrator | job id; pin = D only (no content hash) | rerun, console "data as of" | terminal state | INGEST job gets `snapshot_date` = the held night (`admin.py:81`) | – | re-queued; pin kept | – | at T: jobs running at T run again (F-11) | – |
| Audit chain | every service | day file, hash chain | verify, readiness fallback | per line | `ingest.held` | `ingest.failed` | – | NullAudit | directory replaced by T's; later lines only in `audit.pre-restore-*` | counts only, never who |
| Opt-out register `optout.optout_events` | office / steward; worker (registry) | event log (pid, at) | every list path; as-of for re-runs | per row | registry sync reads CURRENT (the previous night) | tick retried | tick at start | as-of `received_at` | **at T: later opt-outs are gone** (F-8) | the record of the refusal itself; kept |
| Pid map `pidmap.pid_map`, `pid_alias` | adapter at ingest (`pipeline.py:581-588`), **before** the gate | pid; alias append-only | reveal, opt-out `with_survivors` | – | **written for a held night too** | – | upsert | – | at T | opt-out: stays (the chart number is needed to honour the opt-out at the door). No path removes a pid |
| EDC drafts | `edc.prefill` on demand | draft id; citation carries `row@snapshot` | console, send | – | – | – | – | – | at T | refused at draft / sign / send (`edc/service.py:93-96`); stored drafts stay |

## 2. Findings

### HIGH

**F-1. A hold taken while a rebuild is running does not protect the snapshot (CONFIRMED, test C1).**
`Lake.rebuild` reads the holds once, at its start (`store.py:513`), and replaces the file at its end (`:624`). A job
pins CURRENT and then writes its hold (`jobs.py:85-104`); the site publish checks `_held_by` and then rebuilds
(`sitesetup/service.py:406-414`). Sequence: publish tick starts a rebuild of CURRENT (805 s at 50k by the scale
review) → a SCREEN starts, pins and holds the same date → its first queries read the old file → the rename lands →
its later queries read the new one. The test: count of patients read by the same pin went 3 → 5 with the hold in
place and the rebuild not refused. The job's list mixes two contents under one `snapshot_date`; this is exactly what
T-305a/b (D-383, D-403) say cannot happen. The same window exists for the adapter's re-run of the served night.

**F-2. A night can end "failed" with CURRENT moved; the stores are then at three different nights and nothing
downstream runs (CONFIRMED, test C2).** After the gate, `_run_ingest` loads OMOP, then FHIR, then rebuilds the lake
(`pipeline.py:694-720`). A fhir-store failure appends an error but the lake is still rebuilt and promoted; `passed` is
false, so: no `passed.json` (`:724`), dataops state `FAILED` ("the run stopped"), the INGEST job fails
(`admin.py:84-85`), and the micro-batch, the twin build and (PR #262) the derive batch are skipped. The box serves a
night its own data-operations page says never published. The mirror case (READ): the lake rebuild fails with an
ordinary error → FHIR and OMOP hold the new night, the lake the old one. The scale review's F-08 is the same end
state reached by a timeout. With PR #262 this becomes user-visible: no finished derive batch for the served
snapshot, so every stored-score criterion (eGFR, DAS28 ...) reads "needs information" for every job until the next
good night.

**F-3. A second run of the served night while any job reads it marks the served night HELD and replaces its NDJSON
(CONFIRMED, test C3).** A re-run of a promoted night is written beside it and moved into `ndjson/D` as soon as it
passes the gate (`pipeline.py:685-692`), before the loads. If a job holds D, the lake refuses (`SnapshotHeld` is in
`REFUSALS`, `:1021`): the night is `held`, `held.json` is written into the folder CURRENT was built from,
`passed.json` is gone, dataops shows attempt 2 `HELD`, OMOP (dual write) already took the new content, FHIR too. In
the test the folder holds 2 conditions and the DuckDB built "from it" holds 1. How it happens without anyone asking:
`core.py:522-528` re-queues an interrupted INGEST after any restart, and the first run's follow-up micro-batches
(`admin.py:89`) are re-queued with it and hold D. Also a manual "Ingest" on the same day as the timer's.

**F-4. Three stores can move back in time on a late re-run of an earlier night (twin CONFIRMED, test C4; FHIR and
derive READ).** The lake builds an older night without promoting it (`store.py:519-521`) and OMOP refuses it
(`load.py:662-667`), but the night still "passes", so: `sync_snapshot` makes HAPI hold exactly the older night
(`load_fhir.py:160-187`, no guard); `twins_after_ingest` builds from `report.snapshot` and supersedes the newer twin
(test: current twin went from `2026-10-02` v1 to `2026-10-01` v2 while CURRENT stayed `2026-10-02`); on PR #262
`derive.after_ingest(report.snapshot)` supersedes the newer derived rows while `batch_run` of the newer night still
says finished. Plan §7.4 "Idempotence: re-running an older night never moves the served date backwards" holds for
two of five stores.

**F-5. The snapshot date is not an identity; a finished job's pin names bytes that change (READ).** The job records
`snapshot_date` only (`jobs.py:157-160`); no sha, no `built_at`. The site publish rebuilds CURRENT under the same
date every time a fact is confirmed (batched to 300 s in compose). After that, `orchestrator.rerun` of a job that ran
before the publish reads different rows and reports "not identical"; the console's "data as of D" is true by date
only; the twin's `basis.snapshot` and an EDC citation `row@D` point at a file that has since been replaced. The lake
already has the identity (the DuckDB's `.sha256` sidecar, `lake_meta.built_at`); nobody carries it.

**F-6. (PR #262, READ on the branch) The derive batch is recorded per snapshot but its rows are not.**
`batch_run(snapshot, finished_at)` says "the rows are this snapshot's"; `latest_many` reads `superseded_at IS NULL`,
i.e. the rows of the last batch that ran, whatever its snapshot. Cases: (a) a long SCREEN pinned to N that crosses
the night, a job resumed after an approval, a restart-requeued job and every re-run read N+1's rows under N's
finished batch; (b) a site publish rebuilds N in place (a confirmed lab value) and no derive batch follows, so the
"finished" batch of N is stale for N; (c) F-4. The reader's anchor check (`row.anchor_oid not in oids`) turns most
mismatches into "needs information", so this fails towards unknown, not towards a wrong exclusion, but a decided
answer silently becomes undecided and a re-run is not reproducible. Contrast T-203b, which solved the same problem
correctly: it verifies each stored chunk against the pinned snapshot's text by content hash and falls back.

**F-7. Erasure is three stores out of at least ten, and the two erase functions that exist are not called
(CONFIRMED for the twin, test C5; the rest READ).** `STORES` = pool, candidate registry, OMOP
(`optout_worker.py:108-114`); `register_store` has no caller. After an opt-out and a tick the patient is still in:
every kept lake snapshot (DuckDB, Parquet, NDJSON; up to 36 month-ends), `embed_cache.duckdb` (never pruned), HAPI,
OMOP before-images and `tb_record_event`, derived rows, `vec.note_chunk` (`delete_patient` exists, `vec/store.py:248`,
uncalled), the twin (`ProfileStore.erase`, `twin.py:357`, called only by the next build, and only if an ingest
passes), job outputs for 365 days, EDC drafts, the pid map, every backup. T-206b owns this; its branch has no code
yet. What is missing structurally is not the nine `clear` functions but anything that makes a tenth store impossible
to add without one.

**F-8. A restore silently undoes opt-outs typed since the backup (READ).** `restore` replaces `trialbox_wf` (the
register) and the audit directory with the backup's (`backup.py:936-999`); the default accepts a backup up to 14 days
old (`:827`). Registry refusals come back by themselves (the worker copies them from the lake's consent table);
opt-outs typed by the office or the steward do not. They cannot be replayed from the audit (the events hold counts,
never who, by design) nor from the "box as it was" copy (encrypted to the hospital's key). Nothing in the restore
output says "opt-outs recorded after <T> must be entered again". The patient is back on lists the next morning.

**F-9. An as-of export brings an opted-out patient back (READ; no production caller yet, T-627 will be one).**
`withhold` tombstones with before-images kept (`load.py:1473-1551`); `_wind_back` restores the before-image of every
record changed after `as_of` (`export.py:120-212`) and does not read `tb_withheld`. An as-of lake built for a date
before the opt-out contains the patient in full. The same holds for a SCREEN re-run pinned to a kept month-end
snapshot (the register is read as of `received_at` by decision D-441, the publish-time read then drops them: lists
are safe, the snapshot itself is not).

### MED

**F-10. The steward cannot ACCEPT a held night because "publish" is not a function (READ).** Everything after the
gate (OMOP load, FHIR sync, lake rebuild, `passed.json`, removing `held.json`, pruning, micro-batch, twins, derive,
vector index) is inline in `_run_ingest:694-753` and `admin.ingest:85-90`. `DataOps.decide` takes a `promote`
callable and the console passes none (`dataops_page.py:74`, `:173`). Two traps for whoever wires it: a held night
older than CURRENT is built and not promoted (`store.py:519`), so the row would say PUBLISHED while nothing is
served; and an old `HELD` attempt stays decidable after a later attempt of the same night published
(`dataops.py:1-6`: "a held night stays on the list").

**F-11. Restore + restart recovery replays jobs (READ; GUESS on the mail).** After a restore, `orch.jobs` is as at T.
With the backup's pause a job mid-run at 04:45 is in the dump as `running`; `core.py:522-528` runs it again from
zero. If it had finished and mailed after T, it mails again: the outbox's "never twice" record is in the same
restored database. GUESS: I did not read the mail gateway's dedupe store.

**F-12. The pid map is written before the gate (READ).** `pm.upsert_many` / `upsert_identity` run at
`pipeline.py:581-588`; the gate is decided at `:683`. A night held for a wrong extract (another site's file passes the
site-key check but not completeness) has already added its chart numbers to the reverse map, and nothing removes them
when the steward rejects the night.

**F-13. The order of the night is five clocks and two completions (READ; overlaps F-33 of the scale review).**
Clock: INGEST 02:00, MICROBATCH MON 03:00, NAV MON 03:30, COHORT 1st 04:00, backup 04:45 (cron, outside the
scheduler), RETENTION 05:00, CALIBRATION 1st 05:30, not-matched sample, opt-out worker every 5 min, site publish every
60 s. Completion: micro-batch and twins after an ingest that passed. Pairs that overlap or invert:
(a) Monday's 03:00 micro-batch and 03:30 NAV pin CURRENT at their first lake call; if the ingest is still running they
screen last night with no notice (the age check is 3 days); (b) Monday has two micro-batches per study (clock and
after-ingest) racing on one pool; (c) the backup pauses the orchestrator under any job crossing 04:45; (d) a site
publish tick can start a rebuild of CURRENT at any second, including between an ingest's promote and the follow-up
jobs' pins (F-1); (e) the opt-out worker's registry sync reads CURRENT, so on a held night a refusal that arrived
tonight is not copied until a night passes; (f) retention at 05:00 deletes outputs a micro-batch still reads (F-34);
(g) the after-ingest micro-batch is submitted before the twin build and (on master) nothing orders them.

**F-14. A patient who leaves the feed stays in the derived rows, the twin, the vector store and the pool (READ).**
`run_batch` visits only patients in the snapshot; `twin.build` counts `missing` and keeps the stored twin
(`twin.py:402-404`); `index_snapshot` never deletes a note that is gone. T-206b names "source delete has an erase
path" for OMOP; the other stores have none.

### LOW

* `rerun.PinnedLake.chunks_search` passes straight through (`rerun.py:42-43`): a re-run's note search is on CURRENT
  unless the caller names the snapshot.
* The INGEST job sets `snapshot_date` to a held night's date (`admin.py:81`), a snapshot that has no DuckDB.
* `dataops.batch` states `LANDED → … → PUBLISHED` are all written in one transaction at the end (`dataops.py:271-275`):
  they are a label, not progress; a killed adapter leaves no row.
* Pruning keeps 3 nightly snapshots: a re-run of a job older than three nights fails with "no lake snapshot" unless
  it was a month-end. Loud, not silent; but "byte-identical re-run" (ARCHITECTURE §9) is a three-day promise.

## 3. Answers to the six questions

**(1) One identity?** No. Readers that take "the newest" of something a job is not pinned to: the derive rows
(PR #262 `latest_many`); the twin's derived layer (`twin.py:407`) and the twin itself (`current(pid)`); the pool in a
re-run (`rerun.py:111`); `opted_out()` at publish (by decision); the FHIR store (`FhirEvaluator`, the CQL gate);
OMOP `export_rows()` in a rebuild; the opt-out worker's registry read, EDC prefill, the death check and the console
pages (CURRENT, by design: they are not jobs); `rerun`'s `chunks_search`; MICROBATCH's `seen_from` (the newest SCREEN,
fixed on first run: correct pattern); study state `require_open` (live). Readers that do it right: SQL through
`PinnedLake`; T-203b's verify-by-content; the register read as-of; `notmatched_sample` (reads the run's own stored
list).

**(2) Order.** §2 F-13. Only two steps are chained by completion and both are chained by *the INGEST job's reply*,
so a timeout (F-08), a restart (F-3) or a failed side step (F-2) breaks the chain while the data has moved.

**(3) Completeness markers.** Lake: good (rename + sha), except F-1. NDJSON: good (`passed.json`), except F-3 removes
it from a served night. OMOP: good (transaction). FHIR: none; a reader sees a half-synced store; only the CQL gate
reads it. Dataops: marker written after the work, never before; a crash = no row; readiness then falls back to the
audit chain. Derived (PR #262): `finished_at` NULL → reader treats as "no batch" → unknown (fails safe, silently).
Twin: none; a failed build leaves the old twin, the API shows it with its old `snapshot` (visible if the page prints
it). Vec: verified on read. Pool: none; `pool_as_received` reconstructs. Job outputs: the job state.

**(4) Erasure and withholding.** After an opt-out + tick: see F-7 for where the patient remains. What brings them
back: a rebuild in `legacy` mode (the default) always includes them (lists filter at read time; counts and exports
depend on each path reading the register); an as-of export (F-9); a restore (F-8, and it also restores twins, vec
rows and OMOP rows erased after T, which the worker then clears again only for opt-outs it still knows); a back-fill
(`backfill._publish` writes a snapshot from the source: legacy lake includes them); a re-run on a kept snapshot
(lists drop them at publish; the engine evaluates them). A lift restores nothing by design. Source delete: handled in
NDJSON, lake (next snapshot), OMOP, FHIR; not in derived, twin, vec, pool, embed cache, older snapshots (F-14).

**(5) Reproducibility.** Only within three nights, only if no site publish rebuilt the date (F-5), and not for what
is read live (question 1). Retention removes the snapshot after 3 nights (month-ends 36 months) and outputs after 365
days; the judge's answers are not stored (T-689 would store them). For T-627 ("an as-of SCREEN equals a SCREEN on a
snapshot built to that date") the as-of read exists for the register and OMOP, could exist for derived rows
(`computed_at` / `superseded_at`) and twins (versions), and does not exist for vec; and F-9 must be decided first.

**(6) Scale cards.**

| Card | Duration only | Fixes ordering / consistency | Interaction |
| --- | --- | --- | --- |
| T-689 (replay judged pairs, attempts) | mostly | the attempts count stops F-3's restart loop | the replay key must include the generation (content), or a rebuilt date replays answers about other text |
| T-690 (rebuild and ingest as polled jobs; one rebuild per snapshot) | F-01, F-08 timeouts | **yes**: two rebuilds of one snapshot; and it is the natural place to fix F-1 (hold check and rename under one lock) and F-2 (the night's state is polled, not inferred from an HTTP reply) | should be built as the generation record's writer, not a second state store |
| T-691 (backup without pause) | the pause length | yes: backup vs running job, watchdog restart → F-3 / F-28 | "the backup waits while a job runs" needs the same record |
| T-692 (streams) | **only duration / memory** | no | none; but do not stream the derive batch into the INGEST job (PR #262 loads every observation of the hospital into the orchestrator: `rows_from_lake(lake, None, snapshot)`) |
| T-704 (night as a chain, allowance reserved, retention keeps what is read) | – | **yes**: F-13 a, b, f; F-32 | must chain on the generation's state, not on the INGEST job's end; its "nightly deltas" (D-451) need "since = the last PUBLISHED generation", else a held delta night is lost |

## 4. Architecture verdict

* **R1 (F-1, F-3, F-5, F-6, F-13d): a snapshot is named by date and rebuilt in place.** Structural: T-305a pinned a
  name, not a content, and three writers may rewrite the name.
* **R2 (F-2, F-3, F-4, F-10, F-13, F-08): the night is not an object.** Its state is implied by files
  (`CURRENT`, `passed.json`, `held.json`), a ledger, a `tb_load` row, an end-of-run dataops row and the INGEST job's
  HTTP reply; each store has its own rule for "newer", "complete" and "held". Structural.
* **R3 (F-4, F-6, F-14, question 1): derived artefacts are "the newest", with no record of what they were built
  from and no guard.** Structural for derived rows and twins (their schema has no such column or check); T-203b
  shows the alternative inside the same codebase.
* **R4 (F-7, F-8, F-9, F-12, F-14): erasure is an opt-in list, and the stores' own history features (before-images,
  kept snapshots, backups, the cache) are not part of it.** Structural: a new store is erasure-exempt by default.
* F-11 is an accident of implementation (restart recovery predates restore).

## 5. Proposed change

**The generation.** One row per build of servable data, in schema `dataops` (it already has the night, its attempts,
the append-only trail and the steward's decision):

```
dataops.generation (gen_id BIGINT PK, snapshot DATE, seq INT,            -- 2026-11-12#3
                    cause TEXT,          -- ingest | site_publish | backfill | rerun | accept | restore
                    batch BIGINT NULL REFERENCES batch(id),
                    lake_sha TEXT NULL, state TEXT, opened_at, closed_at,
                    UNIQUE (snapshot, seq))
dataops.generation_step (gen_id, step TEXT, state TEXT, started_at, finished_at, detail,
                    PRIMARY KEY (gen_id, step))
   -- steps: ndjson, omop, fhir, lake, derive, vec, twins, followup  (state: pending|running|done|failed|skipped)
dataops.served (one row: gen_id)        -- replaces the meaning of CURRENT for jobs
```

Rules: a generation is immutable once `lake` is done (a site publish makes generation `D#n+1`, a new file
`db/D.n+1.duckdb`; `D` stays a readable alias for "the newest generation of D"); `served` moves only forward and only
to a generation whose required steps are done; each step is started by the previous step's `done`, by one runner;
every derived artefact records the generation it was built from; one function answers what a job may read.

Cards (ids are placeholders, the plan's next free numbers are taken by the scale review up to T-704):

| Card | Goal | Files | Acceptance test | Size | Depends on | Changes / absorbs |
| --- | --- | --- | --- | --- | --- | --- |
| **G-1** Lake: build-then-swap under one lock; holds checked at the swap | closes F-1 and the two-rebuilds race without any schema change | `services/lake/store.py` (`rebuild`, `hold`: one file lock `lake/.rebuild.lock`; `hold` takes it; the held check repeated just before `tmp.replace`) | test C1 turned round: a hold taken during a rebuild makes the rebuild end `SnapshotHeld`, file unchanged; two concurrent rebuilds: the second waits or is refused | S | – | first half of T-690; do it now |
| **G-2** `publish(night)` as one function with a step record | closes F-2, F-3, F-10, F-12; lets the steward accept | new `services/adapter/publish.py` (the code of `pipeline.py:685-753` moved, order: lake build → OMOP → FHIR → **promote last** → `passed.json`; the pid-map upsert moved after the gate); `dataops.py` (`generation`, `generation_step`; `record_night` opens the row at the START); `console/dataops_page.py` (promoter = `publish`) | C2 turned round: a failing FHIR step leaves `served` on the previous generation and the row at `fhir: failed`, and a second call resumes from that step; C3 turned round: a re-run of the served night makes generation #2 and never touches #1's folder; accept of a held night runs the same function; accept of an attempt that is not the newest is refused | L | G-1; T-112a/b on master | **T-112b's missing ACCEPT**; T-690 (the polled state is this row); T-305b's `ndjson-rerun` folder goes away |
| **G-3** Generations are immutable; jobs pin a generation | closes F-5, F-1 for good | `lake/store.py` (file per generation, `lake_meta.gen_id`, alias), `sitesetup/service.py` (publish = new generation, no hold check needed), `orchestrator/jobs.py` + job schema (`generation` beside `snapshot_date`), `pipeline.prune_snapshots` (by generation; holds keep a generation) | a job that started before a site publish finishes byte-identical to a run with no publish; `rerun` after a publish is identical | M | G-2 | **T-305a** (pin field becomes a generation), **T-305b** (holds stop blocking the site publish: the batch window stays only to limit rebuilds), **T-627** (the frozen record names generations) |
| **G-4** One reader gate: `tb_common/generation.py: readable(gen, artefact) -> Ok | Unknown(reason)` | every downstream store answers "built from which generation, finished?"; a job reads derived rows, vectors, twins only through it | new lib; `derived_store` (`score_row.built_gen`, `superseded_gen`; `latest_many(gen)` = rows with `built_gen <= gen < superseded_gen`), `patient_profile/twin.py` (`gen` column; `put` refuses an older generation), `adapter/load_fhir.py` (refuse older), `matching/stored_scores.py`, `vec/s2b.py` (keeps verify-by-content; registers itself) | property test: for any interleaving of {ingest N, site publish, ingest N+1, re-run N, restart}, a job pinned to G reads only rows `readable(G)` or unknown; C4 turned round | M | G-3 | **T-207 / PR #262**: land it with `built_gen` on the rows, not `batch_run` alone (else F-6 ships); **T-204** (twin guard); **T-203b** unchanged, registers; **T-627** as-of derived read comes free |
| **G-5** The night runner: steps chained by completion | closes F-13, F-33 | `orchestrator/scheduler.py` (only INGEST and the monthly jobs keep a clock; MICROBATCH, NAV, derive, vec index, twins, retention start on `generation_step` done; one run per study and generation), `admin.py` (the INGEST job only starts the adapter and returns; a `night` runner polls the row) | Monday with a 90-minute ingest: the weekly micro-batch runs once, on tonight's generation; a restart mid-step resumes that step, no second ingest (F-3's trigger gone); a held night: no follow-up, the previous generation's artefacts stay readable | M | G-2 | **T-704** (this is its chain; keep its allowance and retention parts), **T-624**, T-689's attempts count, T-691 ("the backup is a step of the night, after the follow-ups") |
| **G-6** Erasure as a registered obligation | closes F-7, F-14; frames F-9 | `tb_common/erasure.py`: `STORES: dict[schema.table, Obligation]` where an obligation is `erase(pids)`, `kept(reason, decision)` or `no_patient_data`; `datacore/optout_worker.py` runs it; each store module registers (twin, vec, derived, lake snapshots + embed cache via "rebuild without" or a tombstone list applied at read, OMOP before-images, job outputs, EDC drafts, HAPI) | **the enumerating test**: collect every `CREATE TABLE` from every `MIGRATIONS` tuple (as `tests/unit/test_record_inventory.py` already does for the record inventory) and every top-level folder of the lake layout; fail on one with no obligation. Second test: seed a patient in every store, opt out, tick, assert no row holds the pid except those registered `kept` | M (+ the per-store clears, which are T-206b) | T-206a on master | **T-206b / PR #278**: build it on this registry; **T-203a** (`delete_patient` gets a caller); **T-204** (`erase` called by the worker) |
| **G-7** As-of and restore honour the register | closes F-8, F-9 | `omop/export.py` (`_wind_back` leaves `opted out` tombstones in place: one WHERE on the event reason, plus `tb_withheld` filtered in `_export`); `tools/trialbox/backup.py` (restore prints and audits "opt-outs recorded after <T>: re-enter them; N events were in the box before the restore" — the count is readable before the database is emptied; and marks jobs non-terminal at T as `failed: interrupted by restore` instead of re-queuing, F-11) | an as-of export for a date before an opt-out has no row of the patient but the consent row; a restore over a box with a later opt-out says so and leaves a `backup.restored` detail `optouts_after_backup: n` | S | – | **T-627** (must not ship before the export half), T-117b (restore audit), T-206b |

**What breaks.** (i) Disk: a site publish that makes a new DuckDB per generation costs a full copy; mitigate by
keeping one generation per date except while a job holds an older one (prune in G-3), and by T-692's Parquet reuse.
(ii) Every caller that passes `snapshot: str` (a date) to the lake: keep the date as an alias so SQL callers do not
change; only `PinnedLake` resolves to a generation. (iii) `CURRENT` file readers (adapter, backup, tools): keep the
file, written from `served`. (iv) PR #262's goldens are unaffected (the flag-off path reads SQL alone); its schema
gains two columns. (v) The legacy lake source cannot "rebuild without" an opted-out patient unless the rebuild reads
the register: G-6 forces the decision the plan has postponed (filter at build for both sources, or register kept
snapshots as `kept` with a retention bound and a decision number).

**Staging.** Week 1: G-1 and G-7 (small, independent, each closes a confirmed or legal defect). Then G-2, because
T-112b's accept, T-690 and T-704 all need it and each would otherwise invent its own state. PR #262 and PR #278 should
not merge in their present shape and then be reworked: #262 needs `built_gen` (or, as a stop-gap that needs no new
table, the batch_run id on each row and `latest_many(run_id)`), #278 needs the registry and the enumerating test
first, then its clears. G-3 before T-203b's flag is turned on anywhere and before T-627. G-4 and G-5 after G-3;
T-689 and T-691 can run beside them. T-692 is independent.

## 6. What I did not read

`services/adapter/backfill.py` beyond its outline and `_publish`'s existence; `services/adapter/governance.py` beyond
the gate record; `services/omop/load.py` `_write` / `_derive` bodies; `tools/trialbox/update.py` and
`backup_schedule.py` beyond the pause and the rollback outline (the update's rollback restores database dumps taken at
its start: the same class as F-8 for the length of an update, not verified); the mail gateway's outbox store (F-11's
mail half is a guess); `services/datacore/lifecycle.py`, `sync.py`, `export.py`; the cascade engine; `canary_gate.py`;
the console pages except `dataops_page.py`; decisions other than D-441's first section; PR #275 and the actual heads
of PR #262 / #278 on GitHub (I read the local remote-tracking branches, which may be behind). The pid-alias case
(a hospital merge moves records to the surviving pid; rows keyed by the old pid in derived, twin, vec and pool) is
suspected and not verified. Nothing was run against a real box; the four confirmations ran in-process with synthetic
rows and a per-test PostgreSQL.
