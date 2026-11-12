# TB-DR2-07 Performance, scale and robustness at 50,000 and 500,000 patients

| Field | Value |
| --- | --- |
| Document ID | TB-DR2-07 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (the deep-review branch of 2026-11-12, the same tree as master) |
| Area | Memory, time windows, fixed limits, database, restarts, partial failure, backups, upgrade and rollback |
| Prefix | PERF |
| Run | Synthetic nights at 1,000 / 2,000 / 4,000 / 8,000 patients through the real adapter and lake (phase times, peak memory, bytes on disk); a held-feed experiment (4 cases); a wrong-clock experiment (3 nights); an orchestrator-restart experiment against the adapter's `/run`; the lake lock held as the backup holds it; a lake query beside a rebuild thread; the audit chain's append cost at 7 / 70 / 350 MB day files; the not-matched page's load at 29,746 and 297,460 rows; `EXPLAIN (ANALYZE, BUFFERS)` on a local PostgreSQL 16 for the job list, the pool and the audit journal; `tests/unit/test_polled_jobs.py`, `test_admin_retry_scheduled.py`, `test_ops_backup_resumes.py`, `test_validator_large_sample.py` (55 passed) |
| Read only | The cascade, the orchestrator's scenarios, the gateway, the update path, the backup container, the OMOP load, the vector store, the console pages; the G1 result files; the repository's own scale results (`eval/hospital_sim/results/scale.json`, `docs/plan/measurements/backfill-2026-11-11.md`) |
| Not run | Anything on a GPU, in Docker, on HAPI FHIR, or above 8,000 patients. The machine was shared (load average 9 to 22 on 4 cores during the runs), so every wall time measured here is an upper bound; bytes and memory are not affected |
| Data | Synthetic only (`tools/synth`). The local PostgreSQL cluster ran under `/var/tmp/trialbox-0/PERF-dr2` because the `postgres` user cannot enter the session scratchpad; removed at the end |

Paths are relative to `trialbox/`. "Scale review" means `docs/reviews/2026-11-11-scale-timeouts.md` (findings F-01 to F-36).

## 1. Reading in ten lines

1. Of the 36 findings of the scale review, 4 are fixed on this tree (F-01, F-02, F-03, F-08), 3 are partly fixed (F-06, F-09, F-26), 27 are open and 2 were not re-checked. The three merged cards (T-690, T-691, T-746) do what they say; their tests pass here.
2. **A 50,000-patient site still cannot run its night under the shipped memory caps.** The adapter and the lake each hold the whole hospital as Python objects: 0.33 MB of peak memory per synthetic patient, measured again here (546 MB at 1,000, 2,852 MB at 8,000). That is 16.7 GB at 50,000 against caps of 6 GB and 8 GB.
3. **The synthetic hospital is about 16 times thinner than a real one.** It has 31 records and 1.8 notes per patient. Every "50,000 patients" measurement in the repository is about 1.55 million records. A real 50,000-patient history is 25 to 50 million. Memory and time scale with records, not patients.
4. The night reloads everything every night: the timer's ingest passes no `since`. Time is linear (exponent 0.93 from 2,000 to 50,000 patients): 13 minutes at 50,000 synthetic patients, about 3.6 hours at real density, about 36 hours at 500,000. A nightly full reload does not fit at 500,000 at all.
5. **The only model throughput number was measured one call at a time.** G1's hospital part never sets `TB_SCREEN_LLM_CONCURRENCY`, whose default is 1: 6,704 calls in 8,584 s is 1.28 s per call in sequence. The production setting (16 in flight) has never run, so the capacity statement and the Japan hardware note have no base, and the gateway's queue limits (F-13) are untested.
6. Restarts: a killed screening job starts again from zero with no count (F-28, open). New: after an orchestrator restart during the ingest, the night's job fails with "an ingest is already running" while the adapter finishes and publishes; the follow-up screening never runs (reproduced).
7. New: one night with a future date pins `CURRENT`; every later night reports "passed" and is never promoted (reproduced). The age check counts a future snapshot as fresh.
8. Backups are consistent without a pause now (D-455), but each night copies everything: up to 39 full lake snapshots, a full uncompressed `pg_dump`, and a hash of every table row. At real density that is 100 to 430 GB a night at 50,000 patients and 1 to 4 TB at 500,000. While it reads the lake it holds the lake lock, and a job that starts or ends then waits (reproduced).
9. PostgreSQL is not the bottleneck for the product's own tables (plans checked; milliseconds at years of rows). The whole hospital is also mirrored into HAPI FHIR every night although screening reads SQL only; that store was never sized or timed.
10. No scale gate exists (T-687 is not built). CI measures 5,000 synthetic patients on the stub model in one process without memory caps: the same blind spot that hid the G1 drain failure.

Counts: 2 Blocker, 4 Critical, 17 High, 10 Medium, 3 Low (36 findings; about 14 of them new, the others are open findings of the scale review, re-verified on this tree and several now measured).

## 2. Status of the previous findings

Verified in the code and, where a test exists, by running it. "Open" means the cited lines still hold on `514ae9b`.

| Old ID | Severity then | Status | Evidence on this tree |
| --- | --- | --- | --- |
| F-01 publish times a rebuild at 330 s | Blocker | **fixed** (T-690) | `services/lake/client.py:109-115` (`follow_rebuild`), `services/lake/store.py:698-760` (job state, build lock); `tests/unit/test_polled_jobs.py::test_a_publish_whose_rebuild_takes_400_s_rebuilds_once_and_is_recorded` passes |
| F-02 backup pauses every service, 7,200 s per step | Blocker | **fixed** (T-691) | `tools/trialbox/backup_schedule.py:76-92`, `:182-188` (`step_timeout` from bytes), `:928-960` (waits for jobs, pause off by default); watchdog skips paused (`watchdog.py:312`). New problems of the new design: PERF-009, PERF-010, PERF-028 |
| F-05 ingest and rebuild hold the hospital in memory | Blocker | **open** | `services/adapter/pipeline.py:472` (`list(src.rows(...))`), `services/adapter/ndjson.py:73-80` (whole type in a dict), `services/lake/store.py:810-812` (`json.loads` of every line), `:886`, `:893-908`; measured here, PERF-001 |
| F-03 console backup never restarts services | Critical | **fixed** | `tools/trialbox/ops.py:344-355` (`:351` refuses while jobs run); `tests/unit/test_ops_backup_resumes.py` passes; the stop under a running job is refused |
| F-04 a short model outage turns pairs into unknown | Critical | **open** | `services/gateway/load.py:27-29`, `services/orchestrator/scenarios/evaluate.py:424-431`, `screen_cascade.py:158`, `:395` (checked after the whole cascade) |
| F-06 validation sample on one command line | Critical | **partly** | batches of 5,000 (`services/adapter/validate/validator.py:103`, `:135`); the 1 % sample has no absolute cap and each batch has a fixed 1,800 s (`:168`) (T-693 open) |
| F-07 note query for every survivor in one answer | Critical | **open** | `services/matching/cascade/engine.py:282-286`, `:574` |
| F-08 ingest timed at 7,200 s / 1,800 s | Critical | **fixed** (T-690) | `services/orchestrator/clients.py:125-158`, `services/adapter/cli.py:55-79`, `services/console/backend.py:256`; tests pass. A restart is not handled: PERF-007 |
| F-09 update stops services under a job, 3 h cap | Critical | **partly** | dump limits now from size (`tools/trialbox/update.py:1069`); still no job check before `stop` (`:1066`), still 3 h for the whole apply (`tools/trialbox/ops.py:455`) |
| F-10 no service has time to stop | Critical | **open** | no `stop_grace_period` in any compose file; `deploy/systemd/trialbox.service:17` |
| F-28 a restart re-runs every job from zero, no count | Critical | **open** | `services/orchestrator/core.py:602-608`; no `attempts` column on `jobs` (`services/orchestrator/db.py:18-33`) |
| F-29 every lake query has 300 s | Critical | **open** | `services/lake/store.py:1073-1080`; `services/lake/client.py:38-45` sends no other value |
| F-11 excerpt budget 2,500 tokens | High | **open** | `services/matching/cascade/engine.py:82`, `:604-605` (T-710) |
| F-12 audit writer reads the day file per event | High | **open**, measured | `libs/tb_common/audit.py:244-249`; PERF-015 |
| F-13 gateway counts queueing as failure | High | **open** | `libs/tb_llm/timeouts.py:23-26`, `services/gateway/load.py:25-31`, `services/gateway/app.py:86` |
| F-14 "latest job" in the newest 500 jobs | High | **open** | `services/console/home.py:268, 313, 328, 510, 560, 582, 766, 829, 979`; `screening_log.py:60, 387` |
| F-15 embedder on the CPU, one try | High | **open** | `services/embed_service/embedder.py:129`, `:144` |
| F-16 budgets of 20,000 pairs and 10 M tokens | High | **open** | `services/orchestrator/scenarios/screen_cascade.py:315`; `services/matching/cascade/engine.py:117` |
| F-17 OMOP load whole-store diff (behind a flag) | High | **open** | `services/omop/load.py:664`, `:744`, `:798`, `:1012`; `services/omop/schema.py:327` |
| F-18 screening-log export degrades silently | High | **open** | `services/console/screening_log.py:153` (`except Exception`), `services/console/backend.py:253` (60 s, one retry) |
| F-19 PostgreSQL on defaults | High | **open** | `deploy/docker-compose.yml:58-74` (no `shared_buffers`, `max_wal_size`, `shm_size`) |
| F-30 the canary takes the model on the swap layout | High | not re-checked | read only in the scale review; nothing in the three merged cards touches it |
| F-20 excluded list read whole per page view | Medium | **open**, measured | `services/console/home.py:827-835`, `:908-921`; PERF-017 |
| F-21 newest 200 break-glass grants | Medium | **open** | `services/console/breakglass.py:213-215` |
| F-22 audit page ends at 1,000 events | Medium | not re-checked | — |
| F-23 S2b with the hash embedder, one thread | Medium | **open** | `services/orchestrator/scenarios/screen_cascade.py:366`, `:390` (`HashEmbedder()`) |
| F-24 boot wait 900 s | Medium | **open** | `deploy/systemd/trialbox.service:15`; `tools/trialbox/update.py:1212` (now a setting, `TB_INSTALL_UP_TIMEOUT`, default 900) |
| F-25 platform restore deadline 6 h | Medium | **open** | `tools/trialbox/platform_day2.py:73` |
| F-26 14 full backups, 3 x free space | Medium | **partly** | kept by share of the target too (`backup_schedule.py:147-170`, `KEEP_SHARE`); still full copies every night, still 3 x on the deploy folder (`:562-577`) |
| F-27 equivalence sample over the whole lake; twin build swallows failure | Medium | **open** | `services/patient_profile/twin.py:447-449` |
| F-31 five failures in a row fail the job | Medium | **open** | `services/orchestrator/jobs.py:191-192`, `:265-271` |
| F-32 microbatch night budget read before others write | Medium | **open** | `services/orchestrator/scenarios/microbatch.py:76`, `:98-114` |
| F-33 the night is fixed clock times | Medium | **open** | `services/orchestrator/scheduler.py:185-198`, `:280` |
| F-34 retention deletes what a study still reads | Medium | **open** | `services/orchestrator/scenarios/retention.py:59-61` |
| F-35 death check capped at 20,000 | Medium | **open** | `services/orchestrator/app.py:727` |
| F-36 4 GB for four workers, a verdict list per scoped patient | Medium | **open** | `deploy/docker-compose.yml:245`; `services/orchestrator/scenarios/screen_cascade.py:397-400` |
| G1-1 / A4 cloud estimate too low | High | **fixed** | `tools/complete_run.py:1224`, `:1273` (the measured 17,960 s, scaled) |
| G1-2 / A3 a part restarts from zero | High | **partly** | an on-demand VM for hospital parts (D-468); the part itself still does not resume |
| G1-3 failure share checked after the job | Medium | **open** | same as F-04 |
| G1-4 heartbeat does not see container work | Medium | **open** | `tools/complete_run.py:841-853` (process tree only) |
| DATA-001 no completeness gate | Critical | **fixed**, by a run | `services/adapter/pipeline.py:963-1017`; §4.6: a missing, an empty and a halved table each held the night and left `CURRENT` unchanged |
| OPS-021 rollback point leaves out the lake | Medium | **open** | `tools/trialbox/update.py:93`, `:683` (images, databases); PERF-029 |
| OPS-022 update stops services under a job | Medium | **open** | same as F-09 |
| OPS-029 an unhealthy container is not restarted | Medium | **fixed** | `tools/trialbox/watchdog.py` (restart on unhealthy, stops after 3 in 6 h) |
| OPS-031 disk watched only by the backup | Medium | **fixed** | `libs/tb_common/metrics.py:23`, `:67-68` (70 % warn, 85 % red, settings) |
| OPS-045 RPO and RTO never measured | High | **open** | `tools/backup_drill.py` runs `e2e_simple`'s small box in process; no size or duration at hospital scale; PERF-009 |
| OPS-048 point-in-time restore optional | Medium | **open** | `deploy/docker-compose.yml:65` (`archive_mode` default `off`) |

## 3. Findings

Flags: PoC, Go-live TW, Go-live JP, Go-live both, Later. "(F-nn)" names the scale review's finding that this row re-verifies; rows without one are new.

### 3.1 Blocker and Critical

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PERF-001 | Blocker | The night's ingest and the lake rebuild hold the whole hospital as Python objects (F-05). | Run, §4.1: peak RSS 546 / 868 / 1,512 / 2,852 MB at 1,000 / 2,000 / 4,000 / 8,000 patients = 0.33 MB per patient; the repository's own 50,000 run: 12.3 GB RSS (`eval/hospital_sim/results/scale.json`), 17 GB with swap. Code: `services/adapter/pipeline.py:472`, `ndjson.py:73-80`, `services/lake/store.py:810-812`, `:886`, `:893-908`. Caps: adapter 6 GB, lake 8 GB (`deploy/docker-compose.yml:143`, `:202`). | At 50,000 synthetic patients the adapter or the lake is OOM-killed every night: no snapshot, no screening. At real record density (§4.2) the need is 90 GB or more at 50,000 patients. | Stream every step: rows from the source, the merge by id on disk (as `backfill._merged` does), Parquet written in Arrow batches or by DuckDB `read_json`, chunks made per batch. Then size the caps from the host. | T-692 | Go-live both |
| PERF-002 | Blocker | No test at production size exists. The scale gate (T-687) is not built; the performance gate is 5,000 synthetic patients on the stub, in one process, without memory caps; the synthetic hospital has 31 records and 1.8 notes per patient. | `.github/workflows/trialbox-e2e.yml:86-98`; `tools/bench_baseline.json` (`patients: 5000`); run, §4.1 (`counts`: 31,104 records for 1,000 patients, 1,754 notes). | Every limit and memory figure below was found by reading or by a small run. Nothing stops the next one from shipping. The G1 drain failure was this gap. A 50,000-patient synthetic run is the data volume of about 3,000 real patients. | Build T-687 first. Add a "dense" synthetic profile (500 records and 40 notes per patient, set from the first real feed profile) and run the gate at 50,000 dense patients under the compose caps with the slow model stand-in, a 40 s outage and one restart. | T-687 | Go-live both |
| PERF-003 | Critical | A restart runs every interrupted job again from zero, with no count (F-28). | `services/orchestrator/core.py:602-608`; the judged pairs live in memory only. | Any restart (update, OS patch, OOM) discards up to 2.4 h of model work per job at 50,000 patients (G1) and about 24 h at 500,000. A job that causes the OOM is requeued first: a crash loop under `restart: unless-stopped`. | Keep judged pairs in PostgreSQL by (job, generation, prompt, variables hash) and replay them; an `attempts` column; fail with a plain message after N restarts. | T-689 | Go-live both |
| PERF-004 | Critical | The cascade reads every survivor's notes in one lake answer and keeps a verdict list per scoped patient in a 4 GB process (F-07, F-36). | `services/matching/cascade/engine.py:282-286`, `:574`; `services/orchestrator/scenarios/screen_cascade.py:397-400`; `services/lake/client.py:45` (the whole Arrow answer in one response body). | At 50,000 real-density patients the note answer alone is several GB, three to four times that in Python. The orchestrator is killed, and PERF-003 restarts the job. | Note stage in batches of patients; a join against a temporary table, not `list_contains`; excluded patients written as JSON lines as they are decided. | T-694 | Go-live both |
| PERF-005 | Critical | A model outage of seconds turns the rest of a screening job into "unknown" or fails it after hours (F-04, F-31, G1-3). | `services/gateway/load.py:27-28` (5 failures, 30 s open); `services/orchestrator/jobs.py:191-192`; `services/orchestrator/scenarios/evaluate.py:424-431`; `screen_cascade.py:395`. | One vLLM restart during a job of hours loses the job or sends thousands of patients to review unjudged. | Batch roles wait and retry on a refusal; the failure share is checked while the job runs and the job pauses; with PERF-003's replay a failed job resumes. | T-689 | Go-live both |
| PERF-006 | Critical | The night reloads the whole hospital every night. The timer's ingest passes no `since`; every step is a full pass: read, map, write all NDJSON, hash every resource, rebuild the whole lake. | `services/orchestrator/scheduler.py:280` (options `{"timer": "1"}` only); `services/orchestrator/scenarios/admin.py:79`; `services/adapter/load_fhir.py:119-123`, `:167`. Time: linear, exponent 0.93 (`scale.json`: 40.3 s at 2,000, 804.6 s at 50,000). | 13 min at 50,000 synthetic patients; about 3.6 h at 50,000 real-density patients; about 36 h at 500,000 (§5.1). A full nightly reload cannot fit a night at 500,000 and leaves no room for screening at 50,000. | Nightly deltas "since the last published generation" with a weekly or monthly full reconcile; the lake build appends changed partitions instead of rebuilding. | T-726 (absorbs T-704) | Go-live both |

### 3.2 High

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PERF-007 | High | **The one measured model throughput is sequential.** G1's hospital part runs the orchestrator in process and nothing in that path sets `TB_SCREEN_LLM_CONCURRENCY`; its default is 1. | `services/orchestrator/scenarios/screen_cascade.py:329-334`; the variable is set only in the four GPU compose files (`deploy/docker-compose.rtxpro6000.yml:97` and three more), never in `tools/complete_run.py`, `tools/e2e_simple.py` or `deploy/gcp/`. G1: 6,704 calls, stage 8,584.1 s (`docs/plan/measurements/g1-2026-11-11/hospital-ja.json`): 6,704 x 1.28 s = 8,581 s, the whole stage. | "2.4 h per 50,000-patient screen" and "6.3 s per note-stage patient" are single-stream numbers on a card serving 16 sequences. The capacity statement (T-734), the Japan hardware note (T-667) and the cloud estimate rest on them. The production path (16 calls in flight through the gateway's slots, breaker and read limits, F-13) has never run once. | Set the concurrency in the cloud run from the profile's `max_num_seqs`; record calls per second at 1, 4, 8, 16 in flight in the serving record; the capacity statement reads that record. Test in §8. | NEW-PERF-1: the cloud run screens at the profile's concurrency and records the throughput curve (S) | PoC |
| PERF-008 | High | After an orchestrator restart during the ingest, the requeued INGEST job asks `POST /run` again, gets 409, and fails, while the adapter finishes the night and moves `CURRENT`. | Run, §4.4: `StepFailed: ingest | an ingest is already running | adapter HTTP 409`, the adapter's run still `running`. Code: `services/orchestrator/clients.py:138-141`; `services/adapter/app.py:56-58` (the 409 carries the run id in `X-TB-Run`, which nobody reads). | The night's data is published but the job is "failed": no ingest report stored, no micro-batch for new patients (`admin.py:86-90`), no twin build, a "failed" mail to the site. The reverse case (the adapter restarts) fails the job too, and its run record is in memory only (`app.py:40`). | On 409 follow the run named in `X-TB-Run` to its end. Keep the run's state in the batch row (`dataops.batch`), so a restarted adapter still answers for it. | NEW-PERF-2: a restarted orchestrator follows the running ingest (S) | Go-live both |
| PERF-009 | High | One night with a future date pins the lake. Every later night is "built, not promoted" and still reports `passed: True` with no error. A future snapshot counts as 0 days old, so the staleness check never fires. | Run, §4.5: night `2027-01-01` passed, then `2026-10-07` and `2026-10-08` both `passed: True`, `CURRENT: 2027-01-01`. Code: `services/lake/store.py:803-806`, `:853-856` (a log warning only), `:316-318` ("a snapshot named after a later day ... is 0 days old"). | A wrong host clock for one night, or a re-run with a wrong date, makes the box serve that night's data for weeks while every ingest says "passed". Lists miss every new record with no sign. | A night that is built and not promoted is a held night with a plain reason; refuse a snapshot dated after the site's today; the pin refuses a future snapshot; `doctor` and the health page name it. | NEW-PERF-3: a night that is not promoted is not "passed"; no future snapshot (S) | Go-live both |
| PERF-010 | High | The nightly backup copies everything every night: every kept lake snapshot (3 nightly and up to 36 month-ends, each a full Parquet and DuckDB copy), an uncompressed full `pg_dump` of both databases, and a hash of every row of every table inside the same snapshot transaction. | `tools/trialbox/backup.py:548-586` ("Every Parquet and DuckDB file ... are kept"); `services/adapter/pipeline.py:53-54` (3 nightly, 36 months); `tools/trialbox/backup_schedule.py:301-306` (`pg_dump -Fc -Z0`, then `_ROW` per table); `:562-577` (3 x the backup's size free on the deploy folder; no check on the first run, `est == 0`). Sizes: §5.3. | Synthetic density: 7 to 27 GB a night at 50,000 patients. Real density: 100 to 430 GB a night at 50,000, 1 to 4 TB at 500,000, times the backups kept. The repeatable-read snapshot is held for the whole dump and hash, so vacuum cannot clean what the night's ingest changes. RPO 24 h holds; RTO 4 h does not (§5.3). | The lake's old snapshots are immutable: copy a snapshot once and list it by hash in later manifests. pgBackRest (already in the image) as the database backup with weekly full and nightly incremental; the logical dump weekly. Count the bytes before the first run. | T-730 (rest of T-691); NEW-PERF-4: incremental lake and database backup (M) | Go-live both |
| PERF-011 | High | The backup reads the lake's served files while it holds the lake's one lock. A job's `hold` (at its start) and `release` (at its end) take the same lock and wait for the whole read. | Run, §4.7: `hold()` waited 5.5 s for a 6 s lock held through the backup's own helper. Code: `tools/trialbox/backup.py:680-715` (lock around every file of `db/` and `parquet/`); `services/lake/store.py:553-574`; the client gives up after 330 s (`services/lake/client.py:32`). | At synthetic density the read is a minute or two. At real density (100 GB or more of served files) every job that starts or ends during the read fails after 330 s or leaves its hold behind; an orphan hold blocks the rebuild of that snapshot for 14 days (`store.py:142`). | Take the lock only to list the files and hard-link them into a backup folder (as the reader links do, `store.py:237-270`), release it, then read the links. | NEW-PERF-5: the backup holds the lake lock for the listing only (S) | Go-live both |
| PERF-012 | High | The whole hospital is loaded into HAPI FHIR every night, but screening reads SQL only. The sync holds a hash of every resource and every batch of a type in memory. HAPI's load speed and database size were never measured. | `services/adapter/pipeline.py:702-710` (default `load_fhir=True`); `services/orchestrator/scenarios/evaluate.py:153` ("SQL is the only runtime engine (CQL is compile-time only)"); `services/adapter/load_fhir.py:63-72` (all batches listed before any is sent), `:119-123`; `tools/bench.py:142` ("fhir-store load not included"). | A second copy of all patient data in PostgreSQL (est. 5 to 10 KB per resource: 125 to 250 GB at 50,000 real-density patients, over 1 TB at 500,000), in every dump and every backup, for a store that only the compile-time equivalence check reads. First load est. 7 h at 50,000 and 3 days at 500,000 at 1,000 resources per second. | Load only the equivalence sample (a few hundred patients) into fhir-store, or load the store on demand before a compile. Measure HAPI before any decision to keep the full mirror. | NEW-PERF-6: fhir-store holds the equivalence sample, not the hospital (M) | Go-live both |
| PERF-013 | High | The gateway's limits count queueing as failure; slots are a constant, not the profile's `max_num_seqs` (F-13). | `libs/tb_llm/timeouts.py:24-26` (180 / 210 / 240 s); `services/gateway/load.py:25` (`SLOTS = 16`), `:29-31`; `services/gateway/app.py:86` (`MAX_INFLIGHT = 64`). | With 16 or more long calls in flight, calls that queued run out of read time, five in a row open the breaker, PERF-005 follows. Never exercised (PERF-007). | A queue allowance for batch roles; the read clock starts when a slot is taken; slots from the serving record; the read limit from `max_tokens` and the measured rate. | T-698 | Go-live both |
| PERF-014 | High | PostgreSQL runs on its defaults; no service has time to stop; the boot wait equals one model's start period (F-19, F-10, F-24). | `deploy/docker-compose.yml:58-74`, `:99-106`; no `stop_grace_period` anywhere; `deploy/systemd/trialbox.service:15-17`. | 128 MB of buffers and 1 GB of WAL under a nightly bulk load; a stop kills PostgreSQL after 10 s (crash recovery at the next start, past its 100 s health window at this size); the orchestrator gets 10 s and PERF-003 restarts its job. | Sizes from the host's memory in `install.sh` with a `doctor` check; `stop_grace_period`; the wait from the start periods. | T-703, T-695 | Go-live both |
| PERF-015 | High | The update stops the services without asking whether a job runs, and the whole apply has 3 h. It takes a full backup and then a second dump of both databases for the rollback point (F-09, OPS-022). | `tools/trialbox/update.py:1066` (stop), `:1069`, `:93`, `:683`; `tools/trialbox/ops.py:455` (`3 * 3600`). `running_jobs()` exists (`update.py:1048`) and is used by the backup only. | A screening job in flight is killed (PERF-003). With PERF-010's sizes the backup step alone passes 3 h at real density; the wrapper is killed and the updater runs on as an orphan. | Refuse or wait while a job runs (the query is there); the limit from the bytes as the backup does; one dump serves both the backup and the rollback point. | T-695 | Go-live both |
| PERF-016 | High | The audit chain's writer reads the whole day file for every event and makes three `fsync` calls per event (F-12). | Run, §4.8: the torn-line check alone costs 3.7 ms per event at a 7 MB day file, 60 ms at 70 MB (90,000 events), 216 ms at 350 MB, with peak memory equal to the file. Profile of 100 appends: 300 `fsync`, 14.6 ms per append. Code: `libs/tb_common/audit.py:244-249`, `:276`, `:180`; cap 256 MB (`deploy/docker-compose.yml:227`). | The single writer does at most about 60 events a second on an empty day and falls as the day grows. Past about 300,000 events in a day the writer is OOM-killed in a loop and the chain stops while the journal grows. A 500,000-patient screen (67,000 model calls per study, each audited) reaches that on a busy day. | Check the file's tail only (as `_last_line` does); one `fsync` per batch of the drain (it already reads 500 at a time); cap from the measured need. | T-697 | Go-live both |
| PERF-017 | High | The console looks for "this study's latest job" in the newest 500 jobs of the box, and the screening-log export degrades to "candidate" rows when the orchestrator is slow (F-14, F-18). | `services/console/home.py:268, 313, 328, 510, 560, 582, 766, 829, 979`; `services/console/screening_log.py:60`, `:153`, `:387`. Plan on a local PostgreSQL (§4.9): each such call is a sequential scan and a top-500 sort, 49 ms at 24,090 jobs, plus 500 job documents parsed twice. | With 20 studies the 500 jobs are 25 nights: older studies lose their list, report and approvals with no notice. A regulatory export can be wrong without an error. | Ask per study and type (`/jobs?ruleset=&type=&state=done&limit=1`; the index `jobs_ruleset` serves it, 0.7 ms); the export fails with 503. | T-700 | Go-live both |
| PERF-018 | High | The model budgets cut a large screen: 20,000 pairs, and a hidden 10,000,000 tokens that stops it first (F-16). | `services/orchestrator/scenarios/screen_cascade.py:315`; `services/matching/cascade/engine.py:117`. G1: 3,352 pairs per study at 50,000 patients. | At 500,000 patients one study needs about 33,500 pairs and 100 M tokens: nine in ten pairs are "unprocessed" and go to review unjudged. A ruleset with five note criteria hits the token limit at 50,000. | Budgets from the population and the measured throughput (T-734), or a refusal at the start with the estimate. | T-689 | Go-live both |
| PERF-019 | High | The excerpt budget is 2,500 tokens whatever the model's context (F-11). | `services/matching/cascade/engine.py:82`, `:604-605`. | On real charts most note pairs have evidence left out: "not met" becomes unknown, the review list is nearly every survivor. Synthetic patients have 1.8 short notes, so no run shows it. | The budget from the pair's smaller context (T-710's one excerpt builder). | T-710 | Go-live both |
| PERF-020 | High | A model self-test that fails at the scheduled minute drops that night's model jobs. They are not deferred; the weekly jobs are lost for a week. The result is cached for the day in memory. | `services/orchestrator/scheduler.py:249-252`, `:260-262`, `:272-274` (`log.error` and `return`); `:140-158` (`_gate[day]`). | A model that is reloading at 03:00 on Monday costs every study its weekly list. Nobody is told except by a log line and an admin tile (OPS-032). | The held jobs are queued with a reason and run when the next self-test passes; the test is repeated on a declared interval; the morning mail says what was held. | T-726 | Go-live both |
| PERF-021 | High | The night is clock times, not a chain (F-33, F-32, F-34). Ingest 02:00, jobs 03:00, backup 04:45, retention 05:00, four workers. | `services/orchestrator/scheduler.py:185-198`; `deploy/backup/trialbox-backup.cron:10`. | Once the ingest passes one hour (50,000 real-density patients, PERF-006) the 03:00 jobs read yesterday's snapshot with no notice; long jobs push the next ingest into clinic hours; the backup waits up to 6 h for jobs and then runs beside them (`backup_schedule.py:88`). | One chain: ingest, publish, model self-test, jobs by nearest appointment within the measured capacity, backup, each started by the end of the one before. | T-726 | Go-live both |
| PERF-022 | High | Embedding for the lake runs on the CPU with one try per batch (F-15). The first load's embedding time is not measured (G1's embed part did not run). | `services/embed_service/embedder.py:129`, `:144`; `services/lake/store.py:1009-1010` (64 texts, no retry). The 15 to 17 % embedding share measured here is the hash stand-in. | First load of 50,000 real-density patients (about 6 M chunks): days on a CPU, hours on a GPU (estimates); one failed batch stops the rebuild. | The embedder on the GPU in the production profiles; retry with backoff; progress in the rebuild job's state. | T-701 | Go-live both |
| PERF-023 | High | Every lake query has 300 s, and feasibility is one query (F-29). | `services/lake/store.py:1073-1080`; `services/lake/client.py:32`, `:38-45`. | Feasibility crosses 300 s at about 140,000 patients (the repository's bench: 215 s at 100,200); `coded_values.attach` then returns nothing and the list loses its coded values silently. | The limit per job type from the orchestrator; `attach` records a failed read in the run. | T-694 | Later (Go-live TW if the screened population passes 140,000) |

### 3.3 Medium and Low

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PERF-024 | Medium | The not-matched page loads the whole excluded list for each view and pages it in memory (F-20). | Run, §4.10: at G1's 29,746 excluded patients the file is 14.9 MB, and one view parses it and builds every row to show 25; at 297,460 rows 149 MB and 729 MB of objects per view. Code: `services/console/home.py:827-835`, `:908-921`. | Seconds per click at 50,000; at 500,000 two viewers pass the console's 2 GB cap. | The excluded list as a table, paged and counted in the store. | T-700 | Go-live both |
| PERF-025 | Medium | The lake rebuild runs as a thread inside one of the lake's two query workers; the adapter's ingest runs as a thread inside its API process and its state is a dict in memory. | `services/lake/app.py:190-192`; `deploy/docker-compose.yml:144`; `services/adapter/app.py:40-44`. Run, §4.7: a query beside a rebuild thread, median 180 → 297 ms, p95 633 ms, at 4,000 patients. | When the build is OOM-killed it takes the query worker and its queries with it. A restart of the adapter loses the run record (PERF-008). | The build as its own process (the lake's CLI in a one-shot container or a subprocess) with its own memory cap. | T-692 | Go-live both |
| PERF-026 | Medium | `audit.journal` in PostgreSQL can never be pruned: update, delete and truncate are refused by trigger, and it is not partitioned. Every event is kept twice for ever (journal and chain). | `libs/tb_common/audit_writer.py:91-114`. Run, §4.9: 673 MB per 1,000,000 events. | Grows with every model call; it is in every nightly dump and row hash (PERF-010). | Partition by month; a partition whose rows are all in the verified chain is detached and dropped by the audit owner under a logged rule. | NEW-PERF-7: the audit journal is partitioned and trimmed after the chain holds it (M) | Later |
| PERF-027 | Medium | The OMOP load is a whole-store diff in memory in one transaction, with 32-bit row ids (F-17; behind a flag). | `services/omop/load.py:664`, `:744`, `:798`, `:1012`; `services/omop/schema.py:327`. | Tens of GB at 50,000; the row sequence runs out at 500,000. | Stage with COPY, diff in SQL, `bigint`. | T-702 | Later |
| PERF-028 | Medium | With `TB_BACKUP_QUIESCE=pause` a backup process that is killed leaves every service paused, and the watchdog never restarts a paused container. | `tools/trialbox/backup_schedule.py:956-976` (unpause in a `finally`, not run on `kill -9` or a power cut during the hold); `:819-824` (`sweep` removes folders, unpauses nothing); `tools/trialbox/watchdog.py:312-314`. Not the default mode. | The box stays frozen until a person runs `docker compose unpause`. | `sweep` unpauses what a dead backup paused (the stale maintenance flag names it). | NEW-PERF-8: a killed backup's pause is undone by the next run and by the watchdog (S) | Later |
| PERF-029 | Medium | A rollback to an older release cannot read lake snapshots that the newer release built; the rollback point does not cover the lake (OPS-021). | `services/lake/store.py:386-390` ("built by a newer TrialBox"); `tools/trialbox/update.py:93`, `:683`. Read only. | After a lake schema change, a rollback leaves `CURRENT` unreadable until a rebuild from NDJSON (minutes to hours, PERF-006). The message is clear; the time is not planned. | The update notes when a release changes `LAKE_SCHEMA_VERSION`; a rollback of such a release rebuilds `CURRENT` from its NDJSON as a step. | T-695 | Later |
| PERF-030 | Medium | The twin build reads every study patient's whole timeline in one pass, and reads every pool row with its verdict document only to collect patient ids (F-27). | `services/patient_profile/twin.py:124-143`, `:421-428`, `:447-449`. | With 20 studies and real density, millions of rows as Python dictionaries in the orchestrator after every ingest; a failure is one log line. | Batches of patients; `SELECT pid` only; the failure shown on the data-operations page. | T-694 | Later |
| PERF-031 | Medium | Fixed limits that are not derived and not settings (OD-10): the list in §6. | §6. | Several fire falsely at 500,000; others cut a result. | Each becomes a setting with its reason, or is derived; T-687's lint keeps the list at zero. | T-687 | Go-live both |
| PERF-032 | Medium | The platform (Kubernetes) restore job has a fixed 6 h deadline (F-25). | `tools/trialbox/platform_day2.py:73`. | A restore at PERF-010's sizes does not finish. | From the backup's size, as the appliance's steps. | T-691 | Later |
| PERF-033 | Medium | The validation sample is 1 % of the load with no absolute cap, in batches of 5,000 files with 1,800 s each (F-06, rest). | `services/adapter/validate/validator.py:103`, `:168`; `services/adapter/pipeline.py:48` (`sample_fraction = 0.01`). | 250,000 files and 50 Java runs at 50,000 real-density patients: hours inside the ingest. | A cap per resource type, as a setting, named in the night's report. | T-693 | Go-live both |
| PERF-034 | Low | `pid_map.upsert_many` reads every stored pseudonym and updates `last_seen` row by row every night. | `services/adapter/pidmap.py:175-190`. | 500,000 single-row updates and as many dead rows a night at 500,000; minutes, not hours. | One `INSERT ... ON CONFLICT DO UPDATE` from a staged table. | T-692 | Later |
| PERF-035 | Low | The opt-out worker deletes pool rows by patient with no index on `pid`. | `services/orchestrator/db.py:57` (key `(ruleset, pid)`), `:358-368`. Run, §4.9: a parallel sequential scan, 35 ms at 200,000 rows. | Small at any plausible pool size. | An index on `pool (pid)`. | T-700 | Later |
| PERF-036 | Low | After a journal resync the audit drain's first read filters on `at` with no index. | `libs/tb_common/audit_writer.py:300-301`. Run, §4.9: 928 ms at 1,000,000 rows, once per resync. | Seconds to minutes once after a database restore. | An index on `journal (at)`, or read by `seq` from a stored bound. | NEW-PERF-7 | Later |

## 4. What was run

Scripts are in the session scratchpad (`PERF/scripts/`: `night.py`, `partial.py`, `clock.py`, `restart_ingest.py`, `explain.sql`); they import the product code and change nothing in the repository.

### 4.1 A synthetic night at four sizes (PERF-001, PERF-002, PERF-006)

`tools.synth.generator.generate` → `tools.ingest_local.run_local` (the adapter's `run_ingest` with data contracts and the structural validator, then `Lake.rebuild` with the hash embedder), one process per size.

| Patients | Records | Notes | Night, s | Adapter, s | Lake rebuild, s | of which embed (hash), s | Peak RSS, MB | NDJSON, MB | Parquet, MB | DuckDB, MB | Vector store, MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1,000 | 31,104 | 1,754 | 28.3 (includes the cluster's first start) | 19.9 | 8.4 | 2.4 | 546 | 30.4 | 2.7 | 12.9 | 3.2 |
| 2,000 | 63,043 | 3,534 | 28.0 | 14.2 | 13.8 | 4.3 | 868 | 61.7 | 5.4 | 19.4 | 5.8 |
| 4,000 | 124,172 | 7,140 | 71.0 | 41.5 | 29.5 | 10.6 | 1,512 | 121.5 | 10.5 | 34.4 | 16.5 |
| 8,000 | 248,787 | 14,287 | 200.6 | 108.7 | 91.9 | 35.1 | 2,852 | 243.7 | 20.6 | 69.0 | 36.7 |

- **Memory** is linear: (2,852 − 546) / 7,000 = 0.33 MB per patient, 10.6 KB per record. The repository's adapter-only figure is 3.7 KB per record (`docs/plan/measurements/backfill-2026-11-11.md`).
- **Bytes** per synthetic patient: NDJSON 30.4 KB, Parquet 2.6 KB, DuckDB 8.6 KB, vectors 4.1 to 4.6 KB; the source CSV is 9.4 KB.
- **Time**: these wall times rose with the machine's load (load average 9 to 22 on 4 cores) and are not used for the exponent. The repository's own unloaded series is used: 40.3 / 172.9 / 467.6 / 804.6 s at 2,000 / 10,000 / 25,000 / 50,000 patients, exponent ln(804.6 / 40.3) / ln(25) = **0.93**, 16 to 20 ms per patient. The split measured here: adapter 51 to 58 %, lake 42 to 49 %.

### 4.2 The density of the synthetic hospital

31.1 records and 1.79 notes per patient. The scale review and the plan assume 500 records per patient ("50,000 x 500 resources = 25 M") and 40 notes ("2 M notes x 2 KB"). The ratio is 16 for records and 22 for notes. "Real density" below means these two assumptions; the first real feed profile must replace them (§8, test 3).

### 4.3 The T-690, T-691 and T-746 tests

`pytest tests/unit/test_polled_jobs.py tests/unit/test_admin_retry_scheduled.py tests/unit/test_ops_backup_resumes.py tests/unit/test_validator_large_sample.py -q -n 0`: 55 passed in 92 s.

### 4.4 An orchestrator restart during the ingest (PERF-008)

The adapter's app with a blocked `run_ingest`; `POST /run` (the night); then `orchestrator.clients.AdapterHttp.run`, as the requeued job calls it after `Orchestrator.start()`:

```
first start: 202 running run f213545254607b60
requeued INGEST after the restart -> StepFailed: ingest | an ingest is already running | adapter HTTP 409
the adapter's own run is still: running
```

### 4.5 A night with a wrong date (PERF-009)

Three more nights on the 1,000-patient box (`CURRENT` was `2026-10-05`):

```
night 2027-01-01 | passed: True | errors: [] | CURRENT: 2027-01-01
lake snapshot 2026-10-07 is older than CURRENT 2027-01-01: built, not promoted (DATA-007)
night 2026-10-07 | passed: True | errors: [] | CURRENT: 2027-01-01
night 2026-10-08 | passed: True | errors: [] | CURRENT: 2027-01-01
```

### 4.6 A missing, an empty and a halved table (DATA-001: fixed)

Second night on the 1,000-patient box, with data contracts on:

| Case | Result | `CURRENT` |
| --- | --- | --- |
| `lab.csv` removed | HOLD: "lab: table missing (last good night 4753 rows)", "this night removes Observation: 4753 of 6894" | unchanged |
| `lab.csv` header only | HOLD: "lab: VOLUME_ZERO", "table empty (last good night 4753 rows)" | unchanged |
| `note.csv` cut in half | HOLD: "note: 876 rows, 50.1 % fewer than the last good night's 1754 (limit 10 %)" | unchanged |
| first night ever, `lab.csv` removed | HOLD by the data contract ("TABLE_MISSING") | none |

Limit of this check: on a first night without data contracts (`TB_DATA_CONTRACTS` unset) and with no `required_tables` in the settings (`services/adapter/cli.py:154`, default empty) a missing optional table has no baseline to be compared with. Not run.

### 4.7 The lake lock under the backup, and a query beside a rebuild (PERF-011, PERF-025)

`tools.trialbox.backup._lake_lock` held for 6 s in one thread; `Lake.hold` in another waited 5.5 s; without the backup, `release` took 0.00 s. A count query on the 4,000-patient lake: idle median 180 ms (max 306); beside a rebuild thread in the same process (36 s): median 297 ms, p95 633 ms, max 826 ms.

### 4.8 The audit chain's append (PERF-016)

`AuditLog._repair_torn` on a day file of 774-byte lines: 3.7 ms at 7 MB (9,043 events), 59.9 ms at 70 MB (90,439), 215.8 ms at 350 MB (452,196); peak RSS 25 / 91 / 358 MB. A profile of 100 real appends: 1.46 s, of which `fsync` 1.07 s (300 calls) and `replace` 0.26 s.

### 4.9 Plans on a local PostgreSQL 16 (PERF-017, PERF-026, PERF-035, PERF-036)

Tables made with the product's columns and indexes in a scratch schema, filled with generated rows.

| Query (source) | Rows | Plan | Time |
| --- | --- | --- | --- |
| newest 500 jobs (`orchestrator/db.py:231-234`) | 24,090 jobs of 3 KB | Seq Scan, top-N heapsort | 48.6 ms |
| one study's newest done SCREEN (the fix for F-14) | same | Bitmap Index Scan on `jobs_ruleset` | 0.7 ms |
| claim the next job (`db.py:240`) | same | Index Scan on `jobs_queued` | 0.02 ms |
| running jobs, as the backup asks (`backup_schedule.py:82`) | same | Seq Scan | 2.9 ms |
| pool rows of two patients (`db.py:364`) | 200,000 | Parallel Seq Scan | 34.5 ms |
| one study's pool (`db.py:333`) | 10,000 of 200,000 | Bitmap Heap Scan on the key | 21.1 ms |
| journal after a resync (`audit_writer.py:301`) | 1,000,000 | Index Scan on the key, filter on `at`, 987,840 rows removed | 928 ms |
| journal by `seq` (the normal drain) | same | Index Scan | 0.3 ms |

`audit.journal` with 1,000,000 events of this shape is 673 MB. The product's own tables are small per patient: `pid_map` and `identity` together are 0.63 KB per patient (measured on the four boxes): 315 MB at 500,000. There is no patient-sized table without a key for its list query. The patient-sized lists live in DuckDB and in JSON files in the object store (PERF-004, PERF-024), not in PostgreSQL.

### 4.10 The not-matched page's load (PERF-024)

A document of the shape `excluded_doc` writes (`services/orchestrator/scenarios/screen.py:639-664`), read as the page reads it (`json.loads`, one row per patient with its items, sort, slice 25):

| Excluded patients | File | Parse | Rows and sort | Python objects |
| --- | --- | --- | --- | --- |
| 29,746 (G1's count at 50,000) | 14.9 MB | 1.0 s | 0.75 s | 73 MB |
| 297,460 | 148.6 MB | 10.7 s | 10.7 s | 729 MB |

Times are under memory tracing on a loaded machine; expect a third to a fifth on a quiet box.

## 5. Arithmetic: memory, the night, backups

Every number is marked **M** (measured here or in the repository's result files), **E** (extrapolated from M by a stated rule) or **A** (rests on the density assumption of §4.2).

### 5.1 Memory by place

| Place | What is held | Per unit (M) | 50,000 synthetic (E) | 50,000 real density (A) | 500,000 real density (A) | Cap |
| --- | --- | --- | --- | --- | --- | --- |
| adapter, `run_ingest` (`pipeline.py:472`, `ndjson.py:73`) | every source row, every mapped resource, the previous snapshot of a type | 3.7 KB per record | 5.7 GB | 92 GB | 925 GB | 6 GB (3 GB of it the validator's heap) |
| adapter, fhir-store sync (`load_fhir.py:63-72`, `:119-123`) | a hash per resource; all batches of one type | about 150 B per id and hash; one type's resources whole | 0.25 GB + the largest type | 3.7 GB + the largest type (tens of GB) | 37 GB + | same 6 GB |
| lake rebuild (`store.py:810-812`, `:886`, `:893-908`) | every NDJSON line parsed, every flat row, every chunk row with text and tokens | about 7 KB per record (0.33 MB per patient less the adapter's share) | 10 to 12 GB (12.3 GB RSS measured in one process with the adapter) | 170 GB | 1.7 TB | 8 GB, shared with two DuckDB workers at 40 % each |
| orchestrator, note stage (`engine.py:574`) | every survivor's notes of a year, three copies | 2 KB per note x 3 to 4 | 20 MB (1,193 patients x 1.8 notes) | 1,193 x 40 x 8 KB = 0.4 GB per study; all 50,000 in scope: 16 GB | 4 GB per study; hospital-wide: 160 GB | 4 GB for four workers |
| orchestrator, verdicts (`screen_cascade.py:397`) | a verdict list per scoped patient | about 30 KB per scoped patient (scale review, on synthetic objects) | 1.5 GB per job | 1.5 GB per job | 15 GB per job | same 4 GB |
| orchestrator, twins (`twin.py:124-143`) | every study patient's timeline | about 1 KB per row as a dictionary | small | 12,000 study patients x 500 rows = 6 GB | same order | same 4 GB |
| console, not-matched page (`home.py:827`) | the excluded list per view | 2.45 KB of objects per excluded patient | 73 MB per view (M) | same | 729 MB per view (M) | 2 GB |
| audit writer (`audit.py:249`) | the day file per event | file size | 5 MB per 6,704 calls | same | 52 MB per study-screen; 1 GB at 1.3 M events | 256 MB |
| OMOP load (flag) (`omop/load.py`) | three `fetchall` of every row | not measured | tens of GB (scale review) | — | — | 6 GB |
| lake `/query` answer (`client.py:45`) | the whole Arrow table in one HTTP body, then as Python lists | result size x 3 | per query | per query | per query | 8 GB / 4 GB |

Where the patient set is listed whole and it is fine: `pid_map` (0.63 KB per patient), the job claim, the worklist counts.

### 5.2 The night

**Ingest to published snapshot (no model).**

| Size | Basis | Adapter + lake |
| --- | --- | --- |
| 50,000 synthetic | M (`scale.json`, 2026-11-05) | 805 s (13 min) |
| 500,000 synthetic | E, exponent 0.93 to 1.0 | 1.9 to 2.3 h, if the memory existed |
| 50,000 real density | A: 25 M records at 0.52 ms per record (805 s / 1.555 M) | 3.6 h (range 2 to 7 h: the record mix is unknown, notes cost more than labs) |
| 500,000 real density | A | 36 h (range 20 to 70 h) |

Not in these figures: real embeddings (PERF-022; first load est. 6 M chunks: 3.3 h on a GPU at 500 chunks per second, 7 days on a CPU at 10; later nights embed only new text), the HAPI load (PERF-012; not measured), the 1 % validation sample (PERF-033).

**The model.** Measured (G1, RTX PRO 6000, 50,000 synthetic patients, one synthetic study, judge and verifier): 1,193 of 50,000 patients reach the note stage (2.4 %); 6,704 model calls; 8,584 s; one call at a time (PERF-007). So 1.28 s per call, 5.6 calls and 7.2 s per note-stage patient, 0.134 calls per hospital patient per study.

| Hardware | Calls per hour | Basis | One study, 50,000 patients (6,704 calls) | One study, 500,000 (67,040 calls) | 20 studies a week, 500,000, spread over 7 nights |
| --- | --- | --- | --- | --- | --- |
| RTX PRO 6000, 1 in flight | 2,810 | **M** (G1) | 2.4 h | 23.8 h | 27 h a night: impossible |
| RTX PRO 6000, 16 in flight (the shipped setting) | 14,000 to 28,000 | **E**: 5 to 10 x the single stream; not measured | 14 to 29 min | 2.4 to 4.8 h | 7 to 14 h a night: over the night |
| DGX Spark (GB10), 8 in flight | 1,100 to 2,200 | **E**: the sizing tool's 43 against 280 tokens per second per stream, half the sequences ("about 13 times slower", deep review LLM-025); not measured | 3 to 6 h | 30 to 60 h | not feasible |
| RTX 5090, one card, swap layout, 4 in flight | unknown | not measured; two passes with a model swap | — | — | — |
| B200 under MIG (CGMH) | unknown | G1b not run (`docs/plan/measurements/b200-g1b/G1b.md`) | — | — | — |

The night's window for the model is about 4.5 h: jobs start at 03:00 at the earliest, lists are due at about 07:30. Reading the table:

- At 50,000 patients the RTX PRO 6000 carries one hospital-wide screen a night even at one call at a time, and probably ten or more at 16 in flight. Twenty studies on one Monday at 03:00 (today's schedule) need 48 h in sequence or 5 to 10 h at 16 in flight: the schedule, not the card, breaks first (PERF-021).
- At 500,000 patients no option carries 20 hospital-wide screens a week inside the night. Screening must be incremental (new and changed patients, patients with a coming appointment), which the micro-batch already is; the hospital-wide screen becomes a first-load job that runs for days and must survive restarts (PERF-003).
- The nightly micro-batch at its budget of 2,000 patients, if each reaches the note stage: 11,200 calls: 4 h in sequence, 24 to 48 min at 16 in flight.
- The funnel (2.4 %, 2.8 note pairs per survivor) is one synthetic trial. A real trial with broad coded criteria can be ten times that. The capacity statement must take the funnel of each study from its feasibility run.

**The chain as scheduled today (50,000 real-density patients, A):** ingest 02:00 → about 05:40; the 03:00 jobs have already started on yesterday's snapshot; the backup at 04:45 waits for them up to 6 h; retention at 05:00 runs beside the ingest. Lists are built from data a day older than the page says.

### 5.3 Backups

What one nightly backup reads (`tools/trialbox/backup.py:548-586`): both databases as `pg_dump -Fc -Z0`; the lake's `db/` and `parquet/` of every kept snapshot; NDJSON of `CURRENT` and the two newest; the vector store; objects, audit, rulesets, mail, secrets, console.

| Part | Per patient (M, synthetic) | 50,000 synthetic (E) | 50,000 real density (A) | 500,000 real density (A) |
| --- | --- | --- | --- | --- |
| one lake snapshot (Parquet + DuckDB) | 11.2 KB | 0.56 GB | 9 GB | 90 GB |
| kept snapshots: 3 at first, up to 39 after three years | — | 1.7 to 22 GB | 27 to 350 GB | 0.27 to 3.5 TB |
| NDJSON, 3 kept | 30.4 KB each | 4.6 GB | 73 GB | 730 GB |
| vector store | 4.6 KB (hash vectors) | 0.23 GB | 24 GB (6 M chunks x 4 KB) | 240 GB |
| `trialbox_wf` without the journal | under 1 KB | under 0.1 GB | under 1 GB | under 5 GB |
| `audit.journal` | 673 MB per million events (M) | grows for ever | same | same |
| `hapi` (if the mirror stays, PERF-012) | not measured; est. 5 to 10 KB per resource | 8 to 16 GB | 125 to 250 GB | 1.2 to 2.5 TB |
| **one night, before zstd** | | **7 to 27 GB** (+ hapi) | **100 to 430 GB** (+ hapi) | **1 to 4.5 TB** (+ hapi) |

- **Duration** at 100 MB/s to a NAS over 1 GbE (compressed bytes; zstd −3 on notes and JSON is about 3 to 5 x, on Parquet and DuckDB near 1 x): 50,000 real density 20 to 70 min plus the dump and the row hash; 500,000: 3 to 12 h. The step limits now follow the bytes (5 MB/s floor), so they do not fire falsely.
- **Consistency without a pause (D-455)**: each database is one repeatable-read snapshot; the lake's served files are read under the lake lock and checked against their sidecars; the record names the window. Correct by reading and by the unit tests. The cost is PERF-011 (the lock) and a long-lived snapshot transaction under the ingest (PERF-010).
- **Disk on the box**: the dump is written inside the `db` container, copied to the deploy folder and then streamed to the target, so the box needs about twice the dump free beside the data; the pre-flight asks for 3 x the last backup on the deploy folder and nothing on the first run.
- **Kept backups**: 14 by count, cut to half the target by size, never under one. At real density one backup can pass half of a 4 TB target; the note says so and keeps it.
- **Restore time (RTO)**: read and decrypt the same bytes, `pg_restore` (indexes rebuilt: usually 2 to 3 x the dump time), the lake's own check (a hash of every file, `backup.py:727`), then start. Estimate: 1 to 3 h at 50,000 real density, 10 to 30 h at 500,000. The IT pack's 4 h is not met at 500,000 and is unproven at 50,000. Nothing here was measured (OPS-045 open).
- **RPO** is 24 h unless WAL archiving is turned on by hand (`archive_mode` default `off`): a signed EDC value or an SAE entry made after 04:45 is lost with the disk (OPS-048 open).

### 5.4 Restarts: what happens to work in flight

| Killed | During | Result | Resumed? | Evidence |
| --- | --- | --- | --- | --- |
| orchestrator | a screening job | requeued at start, run again from zero; no count | from zero | `core.py:602-608` (read) |
| orchestrator | the ingest (adapter alive) | the job fails with 409; the adapter finishes and publishes; follow-ups lost | no; the night's follow-ups never run | run, §4.4 |
| adapter | the ingest | the poller gets 404: "the adapter no longer knows ingest run"; job failed; `CURRENT` unchanged | no; next night or the administrator's retry (T-746) | `clients.py:144-150`; `test_a_lost_or_refused_night_is_a_plain_step_failure` passes |
| lake worker | a rebuild | the build lock is released by the kernel; the job's state reads `interrupted`; the adapter fails the night; leftovers removed by the next build | no; from zero | `store.py:762-774`, `:793-796`; `test_a_rebuild_whose_process_died_reads_interrupted` passes |
| backup | any step | the `flock` is released; the next run sweeps the dump folders and `.part` files and starts again | from zero (right for a backup) | `backup_schedule.py:1031-1039`, `:819-824` |
| backup | while paused (`QUIESCE=pause`) | services stay paused | **stuck** | PERF-028 (read) |
| update | any step | `IN_PROGRESS.json` stays; `status`, then `rollback` | by a person | `tools/apply_update.sh:76-80` (read) |
| mail gateway | a send | idempotency key per (job, kind, recipients, subject, files) | no second mail | `core.py:556` (read) |

The lake's lock (D-462) is a kernel `flock`: no stale lock survives a dead process. A hold is a file with a 14-day life (`store.py:142`): a job that dies and never runs again blocks the rebuild of its snapshot for 14 days; the next night builds a new snapshot, so the night goes on, but a site publish on the held snapshot waits.

### 5.5 Partial failure

| Case | Behaviour | Checked |
| --- | --- | --- |
| a feed table missing, empty or halved | the night is held, `CURRENT` unchanged, a plain reason | run, §4.6 |
| judge model down | no fallback to the verifier on patient routes (D-276); calls fail; the job ends unknown or failed (PERF-005) | read |
| verifier down | the same share rule; a note can never exclude alone | read |
| model down at the scheduled minute | the night's model jobs are dropped (PERF-020) | read |
| audit volume under 64 MB free | every audited action is refused (`audit.py:238-242`): fail closed | read |
| lake spill over its limit | the query stops with "LAKE-LIMIT" before the disk fills (`store.py:515-520`) | read |
| disk full during a rebuild | the build file and stage are removed, the job's state is `failed`, `CURRENT` unchanged (`store.py:820-825`) | read |
| disk full under PostgreSQL | not handled by the product; the disk alert is 85 % (`metrics.py:68`); with WAL archiving on and a failing archive command the disk fills (the compose file warns) | read |
| wrong clock, future date | PERF-009 | run, §4.5 |
| wrong clock, past date | the night is "built, not promoted" and reports passed: the same silent case in the other direction | read (`store.py:803-806`) |
| daylight saving | not applicable in Taiwan or Japan | — |

### 5.6 Upgrade and rollback

- **Forward**: every store migrates itself at service start under an advisory lock (`tb_common.db.migrate`, append-only versions, checksummed). A migration longer than the health wait (900 s) fails the update and triggers the rollback (F-09, open). There is no backward migration: rollback is the restore of the rollback point's dumps, so its time is the restore time of §5.3.
- **A running nightly job**: killed at the stop with 10 s of grace, then run again from zero after the start (PERF-003, PERF-015).
- **Lake format**: `LAKE_SCHEMA_VERSION = 4`, readable from 1 (`store.py:79-80`); older snapshots are read through compatibility views. A newer snapshot under older code is refused with a clear message (PERF-029). The backup format reads every older layout (`backup.py:39-41`).
- **The rollback point** holds images, models, rulesets and both databases, not the lake, the objects or the audit volume (OPS-021 open).

## 6. Fixed limits (OD-10)

Not derived from hardware, measured speed or data size, and not a declared setting with a reason. "False at 500k" means the limit stops correct work at that size.

| # | Where | The limit | A setting? | False at 500k? |
| --- | --- | --- | --- | --- |
| 1 | `services/lake/store.py:1074`, `services/lake/client.py:32` | 300 s per lake query; 330 s per HTTP call (also `hold` and `release`) | no (the request field exists; no caller sets it) | yes (feasibility; a hold during a backup) |
| 2 | `services/matching/cascade/engine.py:82` | 2,500 excerpt tokens | no | wrong at any size on real notes |
| 3 | `services/matching/cascade/engine.py:117` | 10,000,000 tokens per screen | no | yes |
| 4 | `services/orchestrator/scenarios/screen_cascade.py:315` | 20,000 pairs | yes (`TB_SCREEN_MAX_PAIRS`), no reason, not derived | yes |
| 5 | `services/orchestrator/scenarios/screen_cascade.py:332` | concurrency default 1, cap 64 | yes | no; hides the real throughput (PERF-007) |
| 6 | `services/orchestrator/scenarios/evaluate.py:47`, `:424` | 100 candidates for the full-record second try; 10 % failure share | no | the share is checked too late at any size |
| 7 | `services/orchestrator/jobs.py:191-192` | 5 failures in a row; 300 s window | yes, no reason | yes with 16 calls in flight |
| 8 | `services/gateway/load.py:25-31` | 16 slots; 5 failures; 30 s open; 40 s stall; 3 s probe | partly (`TB_GATEWAY_BREAKER_FAILURES`) | yes under long calls |
| 9 | `libs/tb_llm/timeouts.py:24-26` | 180 / 210 / 240 s | no | yes for long outputs on a slow card |
| 10 | `services/gateway/app.py:86` | 64 calls in flight | no | refuses the 65th at once |
| 11 | `services/orchestrator/scenarios/microbatch.py:76` | 2,000 patients a night | yes, not derived from throughput | cuts, with a notice |
| 12 | `services/orchestrator/app.py:727` | 20,000 patients per death check | no | yes (422) |
| 13 | `services/console/home.py` (9 places), `screening_log.py:60, 387` | newest 500 jobs | no | wrong after 25 nights at 20 studies |
| 14 | `services/console/breakglass.py:213` | newest 200 grants | no | time, not patients |
| 15 | `services/adapter/validate/validator.py:168` | 1,800 s per validator batch | no | possible on a slow box |
| 16 | `services/adapter/load_fhir.py:63`, `:149` | 600 s per FHIR batch of 500, 4 workers | no | no |
| 17 | `services/orchestrator/clients.py:76`, `:87`, `:116` | 900 s parse, 3,600 s compile, 300 s mail | no | document size, not patients |
| 18 | `services/orchestrator/twophase.py:161`, `services/gateway/swap.py:60` | 600 s and 120 s around a model swap | no | card load time, not patients |
| 19 | `services/embed_service/embedder.py:144`; `services/lake/store.py:1009` | 300 s per embed call; 64 texts | no | no; one failure stops the rebuild |
| 20 | `services/lake/store.py:142` | a hold lives 14 days | no | a job longer than 14 days loses its hold |
| 21 | `services/lake/store.py:954-962` | 30 s to open the vector store | no | possible while a rebuild writes vectors |
| 22 | `tools/trialbox/ops.py:455`, `:63` | 3 h for an update; a request older than 60 min is dropped | no | yes |
| 23 | `tools/trialbox/update.py:953`, `:1243`, `:1268`, `:1282` | 3,600 s image load, 3,600 s weights check, 7,200 s reference data, 300 s healthy | no | image and model size, not patients |
| 24 | `deploy/systemd/trialbox.service:15`, `tools/trialbox/update.py:1212` | 900 s for every service healthy | yes (`TB_INSTALL_UP_TIMEOUT`), equals one model's start period | fails a cold model load |
| 25 | `tools/trialbox/platform_day2.py:73` | 6 h restore job | no | yes |
| 26 | `services/adapter/pipeline.py:53-54` | 3 nightly and 36 month-end snapshots | yes | disk: 39 full copies (PERF-010) |
| 27 | `deploy/docker-compose.yml` | memory caps 6 / 8 / 4 / 2 GB, 256 MB | yes (`TB_MEM_*`), not sized from the host or the patient count | yes |

Declared and reasoned, found right: the job poll (`TB_JOB_POLL_SECONDS`, `TB_JOB_LOST_SECONDS`, `libs/tb_common/jobpoll.py`), the backup's step limits and waits (`backup_schedule.py:76-92`), the feed-drop percentages (`feedguard.py`), the disk thresholds.

## 7. What to drop or simplify

1. **The nightly mirror of the hospital into HAPI FHIR** (PERF-012). Screening is SQL only. Keep the store for the compile-time equivalence sample. This removes the largest database, most of the dump and a nightly hash of every resource.
2. **39 full lake snapshots.** Reproducibility needs the NDJSON generation and the build inputs, not 36 monthly copies of Parquet and DuckDB that every backup reads again. Keep the pinned snapshots that a signed report cites, and rebuild an old month on demand.
3. **Two audit stores for ever** (PERF-026). The journal is a queue for the chain; trim it once the chain holds the rows.
4. **The logical dump every night plus a row hash of every table.** With pgBackRest in the image, the logical dump is the weekly verification artefact, not the nightly backup.
5. **The in-process rebuild and ingest threads** (PERF-025). One-shot processes with their own caps are simpler to kill, time and resume than threads inside API workers with their state in a dict.
6. **Three places that decide "the night"**: the orchestrator's clock times, the host's cron for the backup, the retention job. One chain (T-726).

## 8. What the plan must change

| Order | Task | Size | Depends on | Why |
| --- | --- | --- | --- | --- |
| 1 | **NEW-PERF-1**: G1 screens at the profile's concurrency and records calls per second at 1, 4, 8, 16 in flight | S | T-688 | Every capacity number today is single-stream. Do this before the next paid run |
| 2 | **T-687** with a dense synthetic profile (500 records and 40 notes per patient) | M | — | Without it nothing below can be shown fixed |
| 3 | **T-692** (streams) with PERF-025 (the build as its own process) and **T-726** nightly deltas | L | T-687 | The night at 50,000 real-density patients |
| 4 | **T-689** (replay, attempts, outage) and **T-694** (batches) | L | T-724 | A screen that survives a restart; needed before any 500,000 run |
| 5 | **NEW-PERF-2, -3, -5** (three small fixes, §10) | S each | — | Reproduced defects with small fixes |
| 6 | **NEW-PERF-6** (fhir-store holds the sample) and **NEW-PERF-4** (incremental backup) | M each | T-691 | Cuts the database and the nightly backup by an order of magnitude |
| 7 | **T-734** (capacity statement) after 1 and after the first real feed profile | S | NEW-PERF-1 | It needs the throughput curve and each study's funnel |
| 8 | T-698, T-700, T-697, T-703, T-695, T-701, T-693 | as planned | — | Open findings of the scale review |

Changes to existing cards: T-667 (Japan hardware note) must not be written from the G1 figure as it stands (PERF-007). T-691's "done" leaves PERF-010, PERF-011 and PERF-028. T-690's "done" leaves PERF-008. The plan's "500,000 patients" target needs a statement of what runs nightly at that size (deltas and appointment-driven screening) and what is a first-load job of days.

## 9. Needs GCP / owner hardware

| # | Test | Command and inputs | Record | Pass |
| --- | --- | --- | --- | --- |
| 1 | Throughput curve of the pair | On the RTX PRO 6000 VM with the rtxpro6000 compose stack up: `TB_SCREEN_LLM_CONCURRENCY=N python -m tools.complete_run --only hospital-ja --patients 50000` for N = 1, 4, 8, 16 (the last through the gateway, not in process) | model calls, stage seconds, calls per second, `model_busy` / `model_unavailable` counts, breaker openings, pairs unknown | at N = 16: at least 5 x the N = 1 rate, 0 breaker openings, under 0.1 % failed calls; else F-13 is confirmed |
| 2 | The night under the caps | The compose stack with default `TB_MEM_*`; `python -m tools.synth_hospital --sites jp-a:JP:50000 --out /data/synth`; one timed INGEST through the orchestrator | adapter and lake peak memory (`docker stats`), seconds per step, OOM kills | no OOM kill; ingest under 1 h; today's expectation: OOM (PERF-001) |
| 3 | Density | On the first real or site-shaped feed: records and notes per patient, bytes per note, per table | the two ratios of §4.2 | replaces assumption A; rerun §5 with them |
| 4 | Restart in a screen | Test 1 at N = 16; `docker restart trialbox-orchestrator-1` at 50 % of the pairs | calls before and after, total wall time | after T-689: calls after the restart ≤ 55 % of the total; today: 100 % again |
| 5 | Model outage | Test 1 at N = 16; `docker restart` the judge's vLLM once | pairs `model_down`, job state | 0 pairs unknown for the outage; job done |
| 6 | Backup and restore at size | After test 2 (and with 39 copies of the snapshot made by re-running with dates): `trialbox backup-now`, wipe, `trialbox restore` | bytes, seconds per step, the lake-lock hold time, restore seconds | restore under the 4 h the IT pack states, or the pack changes |
| 7 | HAPI load | `python -m adapter.cli run` with fhir-store on, 50,000 synthetic patients | resources per second, `pg_database_size('hapi')` | a number exists; decide PERF-012 from it |
| 8 | Real embeddings | `python tools/bench_embed.py` on the card and on the CPU, 100,000 chunks | chunks per second | first-load time for 6 M chunks under 8 h on the chosen device |
| 9 | Spark and B200 | Test 1 (N = 1 and the profile's `max_num_seqs`) on a DGX Spark and on the owner's B200 in both MIG layouts (G1b) | calls per second | fills the two "unknown" rows of §5.2 |
| 10 | Update with a job in flight | Start test 1; `tools/apply_update.sh` with a same-version bundle | whether the job is killed; update seconds | after T-695: the update waits or refuses |

## 10. Small certain fixes

1. **PERF-008** — `services/orchestrator/clients.py:138-141`. On a `ServiceError` with status 409 from `POST /run`, read the running run (`GET /run`, or the `X-TB-Run` header once `ServiceError` carries headers) and follow that id instead of raising. Test that fails first: in `tests/unit/test_polled_jobs.py`, start a run on the adapter app, call `AdapterHttp.run` again, release the first run, expect the report (today: `StepFailed("an ingest is already running")`).
2. **PERF-009** — `services/lake/store.py:803-806` and `:853-856`: return `promoted=False` with a reason; `services/adapter/pipeline.py` (after `cfg.rebuild`, about `:712-730`): when the result was not promoted, append "snapshot S was built but not published: CURRENT is the later night C" to `errors` (so `passed` is false and the night is held). `services/lake/store.py:316-318`: a snapshot more than one day after `today` raises `StaleSnapshotError` ("dated in the future"). Test that fails first: two nights, `2027-01-01` then `2026-10-07`; expect the second `passed is False` (today: `True`, §4.5).
3. **PERF-011** — `tools/trialbox/backup.py:680-715`: under the lock, list `db/` and `parquet/` and hard-link each file into `lake/.backup-<pid>/` (same volume), release the lock, then read the links and remove the folder; the sidecar comparison stays. Test that fails first: hold the backup's read open on a slow file object and assert `Lake.hold` returns within a second (today: it waits, §4.7).
4. **PERF-017 (F-14)** — the nine `bk.list_jobs(limit=500)` calls in `services/console/home.py`: call the orchestrator's existing filter (`ruleset`, `type`, `state`, `limit=1`). The scale review's test stands: one FEAS job and 501 others; `GET /studies/X/feasibility` must show the report.

## 11. What is good

- T-690 is right in shape: a short start, a state that is read, no wall-clock limit on the work, a bound on silence only, both declared as settings with reasons. The rebuild's lock and state survive a dead process without a stale lock.
- T-691: limits from bytes, no pause by default, the wait for jobs with a stated bound, the watchdog's handling of paused containers and the maintenance flag.
- The completeness and drop gates hold a partial feed in every case tried, with messages a person can act on, and never move `CURRENT`.
- The back-fill path is streaming and resumable and its memory was measured (0.6 KB per record).
- Time through the adapter and the lake is linear; nothing quadratic was found on the data path. The one quadratic path is the audit chain's append.
- The product's PostgreSQL tables have keys for their queries; the job claim is `FOR UPDATE SKIP LOCKED` with no lease to expire.
- Mail is idempotent by key, so a re-run job does not mail twice.

## 12. What was not checked

- Nothing on a GPU: every figure for 16 calls in flight, the Spark, the RTX 5090 and the B200 is an estimate.
- Nothing in Docker: memory caps, `stop_grace_period`, the watchdog, pause and unpause, the update path and the backup container were read, not run.
- HAPI FHIR was not started: its load speed and size are estimates from general experience, not from this stack.
- No run above 8,000 patients here; 50,000 figures are the repository's result files. Wall times here were taken on a machine under load.
- The real-density assumption (500 records and 40 notes per patient) is the plan's own, not a measured hospital profile.
- The OMOP load and the vector store (both behind flags) were read only; F-22 and F-30 of the scale review were not re-checked.
- The Kubernetes platform form (`tools/trialbox/platform*.py`) was read for its one fixed deadline only.
- REDCap, EDC and data-core paths were not reviewed for scale: their tables grow with enrolled subjects (hundreds), not with the hospital.
- A first night without data contracts and without `required_tables` (§4.6) was not run.
