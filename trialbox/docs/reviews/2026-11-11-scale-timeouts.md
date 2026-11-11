# Fixed limits that break at production scale: review after the G1 drain failure

Date: 2026-11-11. Owner: Changfu. Scope: `trialbox/` on `master` at `a1d13cb`, and the run path of branch
`g1/rehearsed-2026-11-11` at `986d91c9`. Review by code reading; two findings were fixed on this branch with a test
that failed first (F-03, F-06). Nothing was run on GCP. Synthetic data only.

Paths are relative to `trialbox/`. Line numbers are those of `master` at `a1d13cb` unless a finding says "G1 branch".

## 1. Answer to the owner's question

**Yes. The drain failure is one case of a product bug class, not a test-driver accident.** The class has three forms,
and each was found in the product, not only in the driver:

1. **A fixed wall-clock limit around work whose duration grows with the hospital.** The drain's 600 s was one. The
   same shape is in the lake client (330 s around a rebuild measured at 805 s for 50,000 patients, F-01), the ingest
   chain (7,200 s, F-08), the nightly backup (7,200 s per step with every service paused, F-02), the update path
   (3 h, F-09) and the gateway's read limit (180 s, F-13) and the lake's query limit (300 s, F-29).
2. **Whole-hospital data held in one process, one query or one command line.** The night's ingest and the lake
   rebuild (F-05), the validator's sample (F-06, fixed), the cascade's note query (F-07, F-36), the OMOP load (F-17), the
   audit writer (F-12).
3. **A fixed count that silently cuts a result.** The newest 500 jobs of the whole box used as "this study's latest
   job" (F-14), the 2,500-token excerpt budget (F-11), the 20,000-pair and 10 M-token model budgets (F-16), the newest 200
   break-glass grants (F-21).

The reason none was seen is the same as for the drain: development and CI ran 500 to 5,000 synthetic patients on the
stub model, in one process, without the compose memory caps. Section 6 proposes the test that closes this gap as a
class (T-687), rather than finding by finding.

Counts: 3 Blocker, 9 Critical, 10 High, 14 Medium, Low items listed together. Two fixed here (F-03, F-06).

## 2. What threatens the G1 run now in progress

Branch `g1/rehearsed-2026-11-11`, parts hospital-zh-TW, the scenarios, embed and profile. No second certain breaker
like `drain()` was found in these parts. Four things can still lose a part; none can be changed while the run is up.

| Id | Part | What | Severity for G1 |
| --- | --- | --- | --- |
| G1-1 | hospital-zh-TW | The cloud hard cap is `ceil(estimate x 1.3)` and the estimate of a hospital part is already known to be low | High for a bounded `--only` run; Low for the full plan |
| G1-2 | hospital-zh-TW | A part is the unit of resume: a cap stop or a spot pre-emption loses the whole part | High |
| G1-3 | hospital-zh-TW | The "more than 10 % of note checks unanswered" rule is applied only after the whole screening job | Medium |
| G1-4 | embed | The in-run heartbeat does not see work done in a container | Medium |

### G1-1. The hard cap comes from an estimate that is low for the hospital part

- **Where (G1 branch):** `tools/complete_run.py:1129-1213` (`estimate`), `:1210` (`cap = math.ceil(hours * 1.3)`),
  `:1232`, `:1266`; used by `deploy/gcp/complete-run.sh` (`--max-run-duration="${CAP_H}h"`, `tb-max-minutes`).
- **The limit:** hospital part = 920 note-stage patients x 6.3 s + 300 s canary + 161 s x (50,000 / 5,000)
  = 7,706 s = **2.14 h**. `S3_SHARE` (92 of 5,000), the 6.3 s and the 161 s were all measured at 5,000 patients.
  `prepare` (the 50,000-patient synthetic hospital) has no row.
- **At 50k:** the failed attempt was still inside this part at 2.6 h, so the real part is at least 1.21 x the
  estimate, and stages 10 to 16 and the screenshots follow the drain. The full plan (`g1,embed,profile`) is 9.45 h,
  cap 13 h: 3.5 h of room, enough. A bounded run is tight: `--only hospital-zh-TW` is 2.64 h, cap 4 h, against
  0.5 h start and setup + prepare + at least 2.6 h.
- **At 500k:** the non-model term alone is 161 s x 100 = 4.5 h and the model term 16 h; whether the estimate holds
  at all is unmeasured.
- **Reproduce:** `python -m tools.complete_run --estimate --patients 50000 --only hospital-zh-TW` prints 2.64 h and
  cap 4 h. Compare with the run log of the failed attempt.
- **Fix:** take the hospital rows from the newest measured run at the same size (`--estimate-from`), give `prepare`
  a row, and refuse a cap smaller than the longest single part x 1.5. Until then pass `--hours` by hand. Card T-688.

### G1-2. A part restarts from zero

- **Where (G1 branch):** `tools/complete_run.py:325-331` (`part_hospital` removes its work folder), `:855-866`
  (`drop_stale_parts`: `--resume` keeps finished parts only).
- **At 50k:** a pre-emption or a cap stop at hour 2.5 of a 3 h part costs 2.5 h and the part starts again. With the
  cap of G1-1 a part longer than its cap can never finish, however often it is restarted.
- **At 500k:** one screening job of about 26 h (2.6 h x 10) on a spot VM does not finish in practice.
- **Fix:** checkpoint inside the screening job (judged pairs kept, see F-04); a run of 500k on spot is not planned
  before that. Card T-689.

### G1-3. The failure share is checked after the job, not during it

- **Where (G1 branch):** `services/orchestrator/scenarios/screen_cascade.py:111-123` (`check_failures`),
  `MAX_JUDGE_FAILURE_SHARE = 0.1`.
- **What happens:** a model call that fails is recorded `unknown` / `model_down` and the job goes on at full speed.
  If a model server restarts in the middle of the note stage, the remaining pairs fail in seconds, and the job ends
  hours later with "The model did not answer N of M note checks": the part is lost. Under 10 % the run passes with
  those pairs unjudged. On master this is F-04, and worse, because the gateway's breaker makes refusals instant.
- **For the run:** the two vLLM containers have `--restart unless-stopped`; a restart reloads the model for minutes.
  If the hospital part ends with that message, look at `docker ps` restart counts in the serving logs first.

### G1-4. The heartbeat counts only the part's own process tree

- **Where (G1 branch):** `tools/complete_run.py:797-846` (`_tree_cpu`, `Heartbeat`), `deploy/gcp/complete-run-vm.sh`
  (`tb-idle-minutes`, default 20; the watchdog's `run)` case).
- **What happens:** the heartbeat file is touched when the part's process tree used CPU in the last 30 s. The embed
  part does its work in a container (`TB_BENCH_EMBED_CMD=/usr/local/sbin/tb-embed-py`, a `docker run`): the
  container's processes are children of the container runtime, not of the part, and `tools/bench_embed.py` prints
  nothing until its end. The heartbeat is touched at the part's start, so embed is safe while it ends within 20
  minutes. Its estimate is 15 minutes (`EMBED_SECONDS = 900`, "no card measurement yet") and includes the download
  of two embedding models that the pre-flight does not check.
- **Evidence the hospital part is safe:** the 2.6 h screening job did not trip this watchdog in the failed attempt.
- **For the run:** a power-off during embed with "TB-WATCHDOG no heartbeat for 20 minutes in the run (a stuck part)"
  is this. Run embed again with `tb-idle-minutes` raised.
- **Fix:** the part touches the heartbeat itself while its child process is alive and the container is running;
  add the embedding weights to the pre-flight. In card T-688.

Checked for the run and found right: the job claim has no lease and no expiry, so a long job is not claimed twice
(`services/orchestrator/db.py:213`); the model client and the gateway allow 600 s per call and nginx 900 s; the
scenario sizes are capped at 5,000 patients (`tools/scenarios.py:107`), the rehearsed size; the pair's budget check
for the hospital part is 8 h; the 20,000-pair model budget is not reached, and the hidden 10 M-token budget (F-16) is
not either: 920 note-stage patients x 2 note criteria = 1,840 pairs, at most 5.2 M tokens.

## 3. Findings on master

Severity: Blocker = a 50,000-patient site cannot run its nightly path; Critical = a 50k site loses a night, a job or
a backup under conditions that will occur; High = a wrong or cut result, or a break at 500k; Medium = a bounded or
conditional risk. "Certain" means the call path was read end to end; durations and memory are arithmetic from the
repository's own measurements unless a line says "measured".

Calibration used below, all from the repository: the 50,000-patient synthetic lake rebuild took 805 s and 17 GB
(`docs/plan/design/02-architecture.md`, QS-13); `run_ingest` holds 0.33 GB per 1,000 patients
(`services/adapter/backfill.py:3`); one 50k screening job on the real pair ran 2.6 h (G1, 2026-11-11); compose
memory caps are adapter 6 GB, lake 8 GB, orchestrator 4 GB, console 2 GB, database 4 GB (`deploy/docker-compose.yml`).

### Blocker

#### F-01. Site-publish times a full lake rebuild against 330 s and tries again every minute

- **Where:** `services/lake/client.py:31` (`LakeHttp(timeout=330)`), `:76-80` (`rebuild`); caller
  `services/sitesetup/service.py:412-414` inside `publish("main")`; `:424` `set_published` is reached only after the
  rebuild returns; the tick `services/orchestrator/app.py:134` (every 60 s) and `:557` (after every job).
- **The limit:** 330 s for a call whose work is the whole hospital snapshot.
- **At 50k:** rebuild 805 s > 330 s. The client times out, the digest is never stored, the next tick publishes
  again: a new full rebuild about every 6.5 minutes while the last still runs. The lake has two workers and no
  rebuild lock; both write the same `<snapshot>.building` file (`services/lake/store.py:581-583`). A fresh box does
  this with no site facts at all (`last is None`, `service.py:399-402`).
- **At 500k:** rebuild about 8,050 s: about 20 overlapping rebuilds per rebuild.
- **Reproduce:** a stub lake whose `/rebuild` sleeps 400 s; call `SiteSetup.flush("main")` twice. Expected: one
  rebuild and `store.published("main")` set. Today: two rebuilds and `None`.
- **Fix:** `/rebuild` answers 202 and is polled for its state; one rebuild per snapshot at a time in the lake; the
  publish row records "in progress"; no rebuild when there are no site facts. Card T-690. Certain.

#### F-02. The nightly backup pauses every service for the whole dump, with a 7,200 s limit per step

- **Where:** `tools/trialbox/backup_schedule.py:711-722` (`docker compose pause` of every writer but `db`), `:653`,
  `:654` (7,200 s per snapshot and copy), `tools/trialbox/update.py:1075` (7,200 s for the backup container);
  schedule `deploy/backup/trialbox-backup.cron:10` (04:45); the other schedules `deploy/settings.example.yaml:32`
  (ingest 02:00, microbatch 03:00, retention 05:00).
- **At 50k:** a database of 20 to 50 GB at 30 to 50 MB/s is a pause of 30 to 75 minutes every night. A job that
  crosses 04:45 is frozen for that long; its open HTTP calls time out on thaw (the clocks run during a freeze). A
  2.6 h job started at 03:00 is always caught.
- **At 500k:** 200 to 500 GB: the dump of one database passes 7,200 s, the step is killed, **no backup ever
  completes**, and the box is frozen from 04:45 for two hours every night. The first sign is the 36 h age alert.
- **And the watchdog (suspected, Docker behaviour not run here):** `tools/trialbox/watchdog.py:232-260` acts on
  `unhealthy` and does not look at `Paused`. A paused container's health probe times out: a Python service is
  unhealthy after about 170 s, and the watchdog restarts it 2 minutes later, in the middle of the backup. A restart
  runs the interrupted job again from its start (`services/orchestrator/core.py:523`).
- **Reproduce:** a fake runner whose snapshot step takes longer than 7,200 s: the nightly ends "failed". On a box:
  `docker compose pause orchestrator`, wait 6 minutes, `python3 -m tools.trialbox watchdog --dry-run`.
- **Fix:** no pause: the repeatable-read snapshot already makes each database consistent (`TB_BACKUP_QUIESCE=off`
  as the default, or a pause for the snapshot export only); step limits from the database size; the backup waits
  while a job runs; the watchdog skips a paused container and honours a maintenance flag. Card T-691, decision
  D-448 (the backup's point-in-time promise changes). Certain on the pause, the limits and the schedule.

#### F-05. The night's ingest and the lake rebuild hold the whole hospital in memory

- **Where:** `services/adapter/ndjson.py:73` (the whole previous snapshot of a type in a dict, every delta night);
  `services/adapter/pipeline.py:443`, `:472` and `sources/csv/source.py:75` (whole files read, the delta filter
  applied after); `sources/ssmix2/source.py:320-336` (every file of the storage tree listed each night);
  `services/adapter/load_fhir.py:166` (a hash of every resource each night); `services/lake/store.py:525-529`, `:557`
  (`json.loads` of every line, then one Arrow table).
- **At 50k:** 0.33 GB x 50 = 16.5 GB in an adapter with about 3 GB left after the validator's heap; 17 GB measured
  for the lake against 8 GB. The container is OOM-killed in the night: no `ingest.*` audit event, no report, CURRENT
  unchanged, no microbatch.
- **At 500k:** 165 to 192 GB by the project's own extrapolation.
- **Reproduce:** the 50,000-patient synthetic set under compose with the default `TB_MEM_*` caps (the existing
  `tools/hospital_sim.py` run is in one process without caps, which is why it passed).
- **Fix:** stream the merge (`backfill._merged` already does); read CSV in rows; build Parquet with DuckDB
  `read_json` or Arrow batches; size `mem_limit` from the patient count in `install.sh`, with a `doctor` check.
  Card T-692. Certain on the code paths; the memory figures are the repository's.

### Critical

#### F-03. The console's Backup stops the services and never starts them — fixed here

- **Where:** `tools/trialbox/ops.py:351` called `ComposeBox.backup` (`tools/trialbox/update.py:1024-1038`), which
  stops every Python service and starts them again only when the backup fails. The update path starts them in its
  restart step; the operations runner had no later step.
- **At 50k / 500k:** the outage was not the dump's length (tens of minutes, hours) but for ever: the orchestrator,
  the gateway and the console stayed down after a successful backup, and a running job was killed with 10 s notice.
- **Test:** `tests/unit/test_ops_backup_resumes.py`; before the fix `['stop'] != ['stop', 'start']`.
- **Fix made:** the runner resumes the services after the backup. **Still open (card T-691):** the button stops
  the services under a running job without asking, and the two dumps have no limit and no progress.

#### F-04. A model outage of seconds turns the rest of a screening job into "unknown"

- **Where:** `libs/tb_llm/client.py:204-216` (a 503 raises at once; `Retry-After` is not read);
  `libs/tb_llm/timeouts.py:51-62` (one retry, on a dropped connection only); `services/gateway/load.py:27-28`
  (`BREAKER_FAILURES = 5`, `BREAKER_OPEN_S = 30.0`); `services/orchestrator/scenarios/evaluate.py:356-358`
  (`unknown`, `model_down`, no wait); `services/orchestrator/scenarios/screen_cascade.py` `check_failures`, after the
  whole cascade; `evaluate.py:424` (`MAX_JUDGE_FAILURE_SHARE = 0.1`).
- **The limit:** a 30 s breaker window and a 10 % share, against a job of hours.
- **At 50k:** a refused call costs 5 to 10 ms. At 16 calls at a time the job consumes 1,600 to 3,200 pairs per
  second while the breaker is open: one 30 s window is 48,000 to 96,000 pairs, more than the whole budget of 20,000.
  Above 10 % the job of hours is discarded ("send the request again"); under 10 %, up to 2,000 pairs are quietly
  `unknown` and their patients go to review.
- **At 500k:** the same, on a job ten times longer: the chance of one vLLM restart in the job goes up with it.
- **Reproduce:** a stub upstream that answers 502 for 40 s in the middle of 5,000 pairs. Expected: no `model_down`
  and 40 s more wall time. Today: thousands of `model_down`.
- **Fix:** batch roles wait and retry on `model_busy`, `model_unavailable` and `model_asleep` (bounded per job, not
  per call); the share is checked while the job runs and the job pauses; judged pairs are kept so a failed job
  resumes. Card T-689, decision D-449 (what a batch call does on a refusal). Certain.

#### F-06. The validation sample did not fit one command line — fixed here

- **Where:** `services/adapter/validate/validator.py` (`validate`: every sampled file an argument of one `java`,
  `timeout=1800`); the sample is 1 % of the load (`services/adapter/pipeline.py:48`, `:649`; `backfill.py:509`).
- **At 50k:** 50,000 x 500 resources = 25 M, a sample of 250,000 files. The kernel refuses a command over 2 MiB,
  about 65,000 names: `OSError: Argument list too long` (reproduced at 100,000 files). The pipeline catches it as
  "validation failed to run" and **holds the night**: the first load could never be published.
- **At 500k:** a sample of 2.5 M files.
- **Test:** `tests/unit/test_validator_large_sample.py`; fails before the fix with the `OSError`.
- **Fix made:** one `java` run per 5,000 files, each file's index kept; an index past five digits is read (it was
  dropped). **Still open (card T-693):** a 1 % sample of 25 M resources is 50 runs; the sample needs an absolute
  cap per type, which is a rule of the ingest gate (decision D-450).

#### F-07. The cascade reads every surviving patient's notes in one query into a 4 GB process

- **Where:** `services/matching/cascade/engine.py:274-278` (`NOTES_SQL`, `list_contains` over the patient list),
  `:558-577` (`notes()`: one query, then three copies of each note's text); the same list pattern at `:419`,
  `services/matching/coverage.py:40-45`, `proposed.py:44`, `coded_values.py:36-59`;
  `services/patient_profile/twin.py:124-143`.
- **Measured (DuckDB 1.5.5, 4 cores):** 1 M document rows x a 50,000-patient list = 28 s; the cost is rows x list
  length.
- **At 50k:** the query is about a minute, but 2 M notes x 2 KB is 4 GB in one answer and three to four times that
  in Python, in an orchestrator capped at 4 GB: OOM unless the coded stage removes far more than 80 % of patients.
- **At 500k:** 20 M documents x 500,000 patients is about 93 minutes for one query, against the lake client's 330 s.
  The job fails.
- **Reproduce:** 50,000 synthetic patients with 20 notes of 2 KB under a 4 GB cgroup.
- **Fix:** a join against a temporary table instead of `list_contains`; the note stage in batches of about 1,000
  patients, the text dropped once the excerpts are made. Card T-694. Certain on the code and the measurement.

#### F-08. The ingest chain is timed against 7,200 s, and the console's against 1,800 s

- **Where:** `services/adapter/cli.py:87` (lake rebuild, 7,200 s); `services/orchestrator/clients.py:127` (the whole
  `/run`, 7,200 s, no retry); `services/console/backend.py:253` and `app.py:959` (the Ingest button, 1,800 s, a
  synchronous request).
- **At 50k:** the 7,200 s windows probably hold on synthetic density with no margin (the validator alone may take
  1,800 s per run). The console's 1,800 s is passed by any full run: the administrator sees "Unavailable", a second
  click gets 409, and the console's `ingest.done` audit line is never written.
- **At 500k:** the rebuild alone is about 8,050 s. The adapter reports "lake rebuild failed" and audits
  `ingest.failed` while the lake finishes and moves CURRENT anyway; the orchestrator then skips the microbatch, so
  the night's new patients are not screened.
- **Reproduce:** a lake stub whose rebuild takes 7,300 s (time-mocked): the night is "failed" and CURRENT has moved.
- **Fix:** `/run` and `/rebuild` as jobs with a state that is polled; progress, not wall time. With F-01 in card
  T-690.

#### F-09. The update path stops services under a running job and cannot finish inside its own limits

- **Where:** `tools/trialbox/update.py:1027`, `:1271` (stop, no check for a running job); `tools/trialbox/ops.py:425`
  (3 h for the whole apply) around two dumps with no limit, a 7,200 s backup container, a 3,600 s image load, a
  3,600 s weights check and a 7,200 s reference-data load; `update.py:1180` (`up --wait --wait-timeout 900`);
  `ops.py:63` (`MAX_AGE_MIN = 60`).
- **At 50k:** a migration that runs past about 170 s at service start makes the service unhealthy, `--wait` fails
  and the update rolls back, restoring the database. A request queued behind a backup of over an hour expires.
- **At 500k:** the dump alone passes 3 h. `subprocess.run` kills the shell wrapper, the updater goes on as an
  orphan, and the console reports a failure while the update is still changing the box.
- **Reproduce:** a fake runner with a 4 h dump; a migration with `pg_sleep(600)` before `up --wait`.
- **Fix:** refuse or wait on a running job; limits from the database size; migrations as their own step before the
  health-gated start; the whole process group killed on a limit. Card T-695.

#### F-10. No service has time to stop

- **Where:** `deploy/systemd/trialbox.service:17` (`docker compose stop`, 10 s by default); no `stop_grace_period`
  in any compose file; `deploy/hardening/ospatch.py:231` (no job check before the reboot);
  `deploy/docker-compose.yml:102-106` (the database's health check: no `start_period`, 100 s).
- **At 50k / 500k:** a reboot, an OS patch or an update kills the orchestrator 10 s after SIGTERM and the job of
  hours starts again from zero; PostgreSQL gets the same 10 s for its shutdown checkpoint and may need crash
  recovery, which at this size passes the 100 s of its health check and fails `up`.
- **Fix:** `stop_grace_period` of 120 s or more for the database; a stop that waits for the running job or
  checkpoints it; a job check in the patch path. In card T-695. Certain on the settings.

### High

#### F-11. The cascade's excerpt budget is 2,500 tokens whatever the model's context

- **Where:** `services/matching/cascade/engine.py:74` (`EXCERPT_TOKENS = 2500`), used at `:594-595` (1,250 per note).
- **At 50k and 500k alike:** 2,500 tokens is one or two real progress notes. A pair with three or more notes that
  hit the lexicon has `left_out > 0`: "not met" becomes `unknown` ("N evidence note(s) did not fit", `:853-857`) and
  "met" is never `strong`. On real charts of 10 to 50 notes a year the note stage excludes and confirms almost
  nobody; the review list is nearly every survivor of the coded stage. It is counted, and the job passes.
- **Why unseen:** synthetic patients have a few short notes. The RTX PRO 6000 profile serves 32,768 tokens.
- **Test:** a patient with five notes of 1,500 characters that each hit; expect a decided verdict on a 32k build.
- **Fix:** the budget from `tb_llm.budget.text_budget` and the smaller context of the pair. Card T-696.

#### F-12. The audit writer reads the whole day file for every event, inside 256 MB

- **Where:** `deploy/docker-compose.yml:227` (256 MB), `:236` (heartbeat under 60 s);
  `libs/tb_common/audit.py:351` (`_repair_torn`) reads the newest day file whole (`:249`) on each append; the
  gateway audits every model call.
- **At 50k:** about 20 calls per patient is 1 M events, a day file of about 700 MB: over the cap after about
  300,000 events (15,000 patients), then an OOM loop; the audit chain stops while the journal grows. The work is
  quadratic: about 3.5 x 10^14 bytes read for one day.
- **At 500k:** a hundred times that.
- **Fix:** check the file's tail only (as `_last_line` does), a heartbeat per event, a larger cap. Card T-697.
  Certain on the code; the events per patient are the repository's own estimate.

#### F-13. The gateway's limits count queueing as failure

- **Where:** `services/gateway/core.py:663-664` (a batch call may wait for a slot for the whole budget), `:768`
  (read limit `min(180, left)`), `:783` (a batch read timeout counts toward the breaker);
  `libs/tb_llm/timeouts.py:22-24` (180 / 210 / 240 s); `services/gateway/load.py:25` (`SLOTS = 16`, not tied to
  `--max-num-seqs` in the rtxpro6000, gb10 and rtx5090 compose files), `:29-31` (`STALL_S = 40`, one 3 s probe);
  `services/gateway/app.py:85-86`, `:411-412` (the 57th batch call at once gets `model_busy` with no wait).
- **At production load:** a call that queued 90 s has 120 s left to read; with long-context requests of 30 to 120 s
  those time out, five in a row open the breaker, and F-04 follows. "Calls in flight and none finished for 40 s" is
  the normal state when 16 long calls start together, and one missed 3 s probe then opens the breaker. With
  `TB_SCREEN_LLM_CONCURRENCY=64`, 8 of 64 calls (12.5 %) are refused at once: over the 10 % share, the job fails
  after it has finished. A read of 180 s also needs 22.8 tokens/s per stream for the judge's 4,096-token retry, and
  91 tokens/s for the 16,384-token protocol extraction: likely not met on a DGX Spark with all sequences busy.
- **Test:** 32 callers, 16 slots, a stub that answers in 100 s; all must succeed. Today the second wave times out.
- **Fix:** a queue allowance of its own for batch roles, the read clock from the moment a slot is taken; a read
  timeout is not "server dead" while other calls finish; slots from the same variable as `--max-num-seqs`; the read
  limit from `max_tokens` and the measured rate in the serving record. Card T-698, with D-449. Certain on the code;
  the triggers are suspected until measured on the pair.

#### F-14. "This study's latest job" is looked for in the newest 500 jobs of the box

- **Where:** `bk.list_jobs(limit=500)` at `services/console/home.py:267, 312, 327, 509, 559, 581, 765, 828, 977`,
  `screening_log.py:60, 381`, `step4.py:272` (200), `:363` (300); the orchestrator caps at 500
  (`services/orchestrator/app.py:329`) and already filters by study and type, which the console does not use.
- **Arithmetic:** every passed ingest makes one microbatch job per pooled study. 20 studies fill 500 jobs in 25
  nights; 50 studies in 10.
- **What the user loses, with no notice:** the feasibility report (the home card goes back to "request
  feasibility"); a paused or closed study's candidate list, week page and patient pages (404); criteria waiting for
  the PI's approval leave the approvals list; the administrator's job filter covers the newest 300 only.
- **Test:** one FEAS job and 501 others; `GET /studies/X/feasibility` shows no report.
- **Fix:** ask per study and type (`/jobs?ruleset=&type=&state=done&limit=1`). Card T-700. Certain. This one is
  small; it is not fixed here only because it touches thirteen call sites of the console under other open PRs.

#### F-15. Embedding for the lake runs on the CPU with one try per batch

- **Where:** `services/embed_service/embedder.py:129` (`TB_EMBED_DEVICE` default `cpu`; only the gb10 compose file
  sets `cuda`), `:144`, `:156-158` (300 s, 64 texts, no retry); the lake rebuild embeds every chunk
  (`services/lake/store.py:579`).
- **At 50k:** the repository's own figure of 18 GB of vectors is about 4.4 M chunks: at about 10 chunks/s on a CPU,
  five days; on a GPU at about 500/s, 2.4 h. No snapshot exists until it ends. One failed batch of about 69,000
  stops the rebuild (it resumes from the cache).
- **At 500k:** 51 days on a CPU, 24 h on a GPU.
- **Fix:** the embedder on the GPU in the production profiles; retry with backoff; progress. Card T-701. Certain on
  the code; the throughput is an estimate that G1's embed part will replace.

#### F-16. The model budget of 20,000 pairs is far under a hospital-wide screen

- **Where:** `services/orchestrator/scenarios/screen_cascade.py:265` (`SCREEN_MAX_PAIRS = 20000`);
  `services/matching/cascade/engine.py:105` (default 2,000).
- **At 50k:** survivors x note criteria: 50,000 x 20 % x 5 = 50,000 pairs; 60 % are "unprocessed (budget)" and go
  to review. **At 500k:** 96 %. It is reported (`budget.hit`), not silent. 20,000 pairs are about 12 h on 16 slots.
- **Fix:** the budget from the population and the night's length, or a refusal at the start with an estimate.
  With T-689.

#### F-17. The OMOP load is a nightly whole-store diff in memory, in one transaction (behind a flag)

- **Where:** `services/adapter/dual_write.py:109`; `services/omop/load.py:598-629`, `:744`, `:798`, `:1012` (three
  `fetchall` of every row), `:663` (one transaction under an advisory lock), `:1482` (the opt-out worker takes the
  same lock); `services/omop/schema.py:327` (`tb_row_seq MAXVALUE 2,147,483,647`).
- **At 50k:** 5 to 25 M rows: tens of GB in a 6 GB container; the opt-out worker waits for the whole load and its
  health line goes red after 15 minutes. **At 500k:** 4,300 rows per patient exhaust the row sequence.
- **Fix:** stage with COPY and diff in SQL; `bigint` ids; a lock of its own for the worker. Card T-702. Certain.

#### F-18. The screening-log export degrades without saying so when the orchestrator is slow

- **Where:** `services/console/screening_log.py:150-154`, `:156-180` (`except Exception: return {}`);
  `services/console/backend.py:251` (60 s, one retry, and the retry re-sends POSTs).
- **What the user gets:** an XLSX in which every row is "candidate" with no reason, record id or dates, audited as a
  normal export. The trigger is an orchestrator that answers slower than 60 s, which a job of hours makes likely.
- **Fix:** the export fails with 503; no POST is re-sent. Card T-700. Certain on the code.

#### F-19. PostgreSQL runs on its defaults

- **Where:** `deploy/docker-compose.yml:58-74`, `:99` (4 GB); no `shm_size`. Effective: `shared_buffers` 128 MB,
  `max_wal_size` 1 GB, `maintenance_work_mem` 64 MB, 64 MB `/dev/shm`, no `idle_in_transaction_session_timeout`.
- **At 50k to 500k:** the night's ingest forces a checkpoint every few seconds; the vector index and the FHIR
  store's indexes are tens of GB against 128 MB of buffers.
- **Fix:** sizes from the host's memory in `install.sh`, `shm_size` with them. Card T-703. Certain on the settings.

### Medium

| Id | Where | The limit | What happens at scale | Fix |
| --- | --- | --- | --- | --- |
| F-20 | `services/console/home.py:826-857`, `notmatched_pages.py:62-68` | the whole excluded list read on each page view | 15 to 50 MB of JSON per request at 50k; 1 to 5 GB of objects in a 2 GB console at 500k | a table, paged in the store (T-700) |
| F-21 | `services/console/breakglass.py:213-215` | newest 200 grants | an unreviewed grant older than that leaves the steward's list | unreviewed grants without a limit (T-700) |
| F-22 | `services/console/backend.py:190-221`, `app.py:976-986`, `step4.py:306`, `:274`, `:162` | newest 1,000 / 5,000 / 2,000 audit events; every file read per call | the audit page ends at 1,000 events with no notice; the Sources row goes amber "stale"; 24 h counters under-count | read by date and by event type (T-700) |
| F-23 | `services/matching/cascade/s2b_semantic.py:93-101`, `screen_cascade.py:338` | `k = 5`; the CI hash embedder, one thread | 2.9 h of one core at 50k with no progress; a fixed five sentences whatever the chart | embed once per patient; the pinned embedder (T-696) |
| F-24 | `deploy/systemd/trialbox.service:15`, `deploy/docker-compose.gb10.yml:111`, `update.py:1176` | wait 900 s = the verifier's start period | a cold load the compose file allows fails the boot and the update, then the rollback | wait = start period + retries (T-695) |
| F-25 | `deploy/platform/base/day2.yaml:63`, `:197`; `platform_day2.py:73` | 6 h for a backup or restore job | a restore of 200 to 500 GB does not finish | from the database size (T-691) |
| F-26 | `backup_schedule.py:339`, `:413-417`; `deploy/pgbackrest/pgbackrest.conf:16` | 14 full backups; 3 x free space | 2 to 4 TB per target at 500k on a 4 TB box | keep by size; incremental (T-691) |
| F-27 | `services/criteria_compiler/equivalence/gate.py:148`, `services/patient_profile/twin.py:447-449` | whole lake evaluated to sample 200; twin build swallows its failure | 5 GB in a 3 GB compiler at 500k; twins stay stale with a log line | sample in SQL; batches; show the failure (T-694) |

### Low

- `deploy/docker-compose.yml:15`: 1 GB of logs per container; 3 GB a night at 500k by the repository's estimate.
- `libs/tb_common/metrics.py:177`: the opt-out line is red after 15 minutes without a tick; any long freeze does it.
- `services/doc_parser/parser.py:353-355`: `secs[:60]`, `text[:4000]` cut a long protocol with no warning
  (document size, not patients).
- `services/vec/index.py:87`, `store.py:179-198`: the index is made before the load, one INSERT per vector; not on
  the production path yet.
- `services/deliverables/analytics.py:315`: 10^8 or more random draws per pack at 500k.
- `services/console/app.py:970`, `team.py:788`, `:1063`: newest 100 / 50 / 30 with no "more".
- `tools/complete_run.py:336` (`BUDGET_S = 8 h` for the pair): the hospital part's own check fails at 500k (26 h).

## 4. The orchestrator: jobs, the night and the model budget

No job lease, heartbeat or reaper exists on the production path, so the precise failure the owner asked about (a long
job claimed again and run twice, or marked dead while it runs) **does not exist today**. The opposite problems do:
nothing limits how often a job starts again, and nothing orders the night.

### Critical

#### F-28. A restart runs every interrupted job again from zero, without a count

- **Where:** `services/orchestrator/core.py:522-528` (`start()`: "restart recovery: re-run from the beginning"),
  `services/orchestrator/db.py:235-241` (`interrupted()`); the cascade's cache and the two-phase memo are in memory
  only (`services/orchestrator/twophase.py:65`, `services/matching/cascade/engine.py:329`).
- **The limit:** none, and no attempts counter.
- **At 50k:** any restart (an update, F-02's watchdog, F-10's 10 s stop, an OOM kill of F-07) throws away up to
  2.6 h of model work per job and starts it again.
- **At 500k:** a job of about 26 h never ends if the box restarts more often than that. With an OOM as the cause it
  is a loop: the compose policy is `restart: unless-stopped`, and the job that caused the kill is first in the queue.
- **Reproduce:** a SCREEN on a slow stub; `docker restart orchestrator` three times: the job runs three times and
  `llm_calls` starts at 0 each time.
- **Fix:** the judge's answers kept in PostgreSQL by (job, prompt, variables hash) and replayed; an attempts column
  and a failed job with a clear message after N restarts. Card T-689. Certain.

#### F-29. Every lake query has 300 s, and feasibility is one query

- **Where:** `services/lake/store.py:750-757` (`timeout_s: int = 300`, a timer that interrupts the query);
  `libs/tb_contracts/generated/models.py:620`; `services/lake/client.py:38-45` never sends another value; callers
  `services/orchestrator/scenarios/feas_compute.py:294`, `cohort.py:104`.
- **At 50k:** about 107 s by the repository's bench (100,200 patients x 36 month-ends in 215 s,
  `docs/VALIDATION.md:118`): right.
- **At 500k:** the limit is crossed at about 140,000 patients; at 500k the query needs about 1,070 s and the job
  fails with "Internal error". The product's own target (300k in 30 minutes) cannot be met through this path.
- **The patient-list form of the same limit (F-07):** `coded_values.attach` scans seven tables against the listed
  patients; when its read fails or times out it returns 0 (`services/matching/coded_values.py:142`, "display
  only"), and the candidate list silently loses every coded value, unit and date. Suspected to be near the limit
  at 50k hospital-wide; certain at 500k.
- **Reproduce:** `Lake.query(..., timeout_s=1)` on the FEAS funnel at 5,000 patients; a test that `attach` returns
  more than 0 on a 50k hospital-wide run.
- **Fix:** the limit per job type from the orchestrator (the job's own target), the HTTP read limit from it;
  `attach` says in the run's `judging` record when it could not read. Card T-694.

### High

#### F-16 (addition). The budget that really stops a screen is a hidden 10,000,000 tokens

- **Where:** `services/orchestrator/scenarios/screen_cascade.py:318-334` builds the cascade's settings without
  `max_tokens`, so `services/matching/cascade/engine.py:109` (`max_tokens: int = 10_000_000`) applies (enforced at
  `:901`). A pair reserves 300 + up to 2,500 tokens, so this stops the job between 3,571 and 10,000 pairs whatever
  `TB_SCREEN_MAX_PAIRS` says, and the message names the wrong limit ("limit of 20000 model calls").
- **At 50k (the G1 hospital):** 920 note-stage patients x 2 note criteria = 1,840 pairs, at most 5.2 M tokens: under
  the limit, with a factor of two. A ruleset with five note criteria would reach it at 50k.
- **At 500k:** 18,400 pairs or more: about two thirds are "unprocessed (budget)" and go to the coordinator's review
  list unjudged.
- **Test:** 5,000 pairs with 2,500-token excerpts and `max_pairs=20000`; expect none unprocessed.
- **Fix:** `max_tokens` from the settings, scaled with `max_pairs`; the message names the budget that stopped it.
  This part is small; it waits for D-449 only because the right number is a decision. Card T-689. Certain.

#### F-30. On the one-card swap layout another job or the night's canary takes the model away

- **Where:** `services/orchestrator/twophase.py:170-189`, `:238-274`; `services/orchestrator/selftest.py:134-144`;
  `services/orchestrator/scheduler.py:142-158`; `services/gateway/swap.py:122-145` (the hold names the service, not
  the job). Layout: `TB_MODEL_SWAP=sleep` (`deploy/docker-compose.rtx5090.yml:166`); layouts with both models
  resident are not affected.
- **At scale:** a job of 2.6 h overlaps the 02:00 night as a matter of course; the canary swaps the models under it
  and drops its hold; calls in flight get `model_asleep`, five in a row fail the job (F-31), and F-28 starts it
  again. Also the last round of a swap run does no model call for hours, so the 3,600 s hold lapses.
- **Fix:** one lease of the card for the whole process; the canary waits for it. Card T-698. Suspected (read, not
  run).

### Medium

| Id | Where | The limit | What happens at scale | Fix |
| --- | --- | --- | --- | --- |
| F-31 | `services/orchestrator/jobs.py:191`, `:265-271` | 5 failures in a row fail the job; calls run 4 to 16 at a time | one blip fails every call in flight together: five "in a row" at once, and the job of hours is lost | a share over a window, or a multiple of the concurrency (T-689) |
| F-32 | `services/orchestrator/scenarios/microbatch.py:75`, `:95-114`; `scheduler.py:174`, `:247` | 2,000 patients a night, read before the other jobs have written their use | four jobs that start together each take 2,000; later studies, in alphabetical order, get 0 every night; at 500k the backlog grows and a patient booked for Friday is screened after the visit | reserve the allowance in the database at the job's start; share by nearest appointment (T-704) |
| F-33 | `services/orchestrator/scheduler.py:192-197`, `:274`; `core.py:543-553` | fixed times (02:00, 03:00, 03:30, 04:00, 05:00) and four workers; the nightly ingest is a full load (no `since`) | once ingest passes an hour the 03:00 jobs use last night's snapshot with no notice; two microbatches of one study overlap and both mail; four long jobs make the next ingest wait into clinic hours; a failed ingest leaves the canary stale after 36 h, and screens then run with note exclusions off | the weekly jobs follow the ingest's end; one run per study; a worker kept for INGEST; nightly deltas (T-704, D-451) |
| F-34 | `services/orchestrator/scenarios/retention.py:28`, `:59-74`; `microbatch.py:124-131` | outputs deleted after 365 days | a study whose last SCREEN is over a year old: every microbatch fails with `KeyError` (time, not patients) | keep the last SCREEN's lists of an open study (T-704) |
| F-35 | `services/orchestrator/app.py:640`; `services/console/backend.py:409-416` | 20,000 patients per death check | a list over 20,000 gets 422; the console reads "unchecked" and nobody on it can be approached | chunks, or the list by job id (T-700) |
| F-36 | `deploy/docker-compose.yml:245`; `services/orchestrator/scenarios/screen_cascade.py:345-348`, `screen.py:609-633`, `microbatch.py:144-153` | 4 GB for four workers; a verdict list for every scoped patient | about 30 KB per scoped patient (measured on synthetic objects): 1.5 GB at 50k per job before notes (F-07), 9 to 15 GB at 500k; every microbatch reads the last screen's excluded list again (85 MB at 50k, 850 MB at 500k) | excluded patients as JSONL in the store; full verdicts for listed patients only (T-694) |

### Low

- `services/orchestrator/scenarios/evaluate.py:47` (`FULL_RECORD_MAX_CANDIDATES = 100`): the full-record second
  try runs in every test and almost never in production; nothing in the run record says it was skipped.
- `services/orchestrator/db_pg.py:251` (`lease_ms=60_000`), `outbox.py:115-117`: a 60 s lease with no renewal.
  Nothing on the production path uses it today. **If a real step is ever put behind it, this is the drain bug in
  its purest form:** a step longer than 60 s is claimed by a second worker and run twice. A renewal is needed first.

## 5. Checked and found right at scale

- The job claim: `FOR UPDATE SKIP LOCKED`, no lease, no expiry (`services/orchestrator/db.py`); a long job is not
  claimed twice. The scheduler: `misfire_grace_time` 6 h, coalesce, one instance (`libs/tb_common/config.py:296`).
- No systemd `WatchdogSec` or `RuntimeMaxSec`; Kubernetes probes are readiness only; the database is `report`-only
  for the watchdog; the watchdog stops after 3 restarts in 6 h.
- The gateway's start check has no deadline; connect 5 s; the order read < budget < caller holds by default.
- Worklists are paged with counts; the screening log is built from uncut queries; the screening number widens past
  9,999; the data-operations history is paged by cursor; upload and ODM limits refuse loudly.
- Ingest gates are percentages; back-fill spool, sort and merge are streaming and resumable.
- The mail gateway's limits follow jobs and staff, and over-limit mail waits.
- Alert rules: disk 85 %, certificate 30 days, backup age 36 h; none is "job running longer than N".

## 6. Proposed cards

Numbers are the next free in `docs/plan/28-master-plan-v6.md` (T-687 on; T-699 is taken) and
`docs/decisions/REGISTRY.md` (D-448 on) at the time of writing. No row is reserved by this review.

| Card | What | Findings | Decision |
| --- | --- | --- | --- |
| T-687 | **The scale gate.** One nightly CI run of ingest, rebuild, screen, backup at 50,000 synthetic patients under the compose memory caps, with a slow model stand-in (seconds per call, a 40 s outage, a restart); a lint that lists every `timeout=` over 60 s and every `LIMIT`/`limit=` literal in `services/` against an allow-list with a reason | the class | — |
| T-688 | The cloud run's estimate and heartbeat: hospital rows from a measured run, a row for prepare, a cap never under the longest part x 1.5, the heartbeat for container work, embedding weights in the pre-flight | G1-1, G1-4 | — |
| T-689 | The screening job survives an outage and a restart: wait and retry for batch roles, the failure share checked while it runs, judged pairs kept and replayed, an attempts count, the pair and token budgets from the population | G1-2, G1-3, F-04, F-16, F-28, F-31 | D-449 |
| T-690 | Rebuild and ingest as polled jobs; one rebuild per snapshot | F-01, F-08 | — |
| T-691 | The backup without a pause; limits from size; no stop under a job; the watchdog and maintenance | F-02, F-03 (rest), F-25, F-26 | D-448 |
| T-692 | The ingest and the rebuild in streams; memory caps from the patient count | F-05 | — |
| T-693 | The validation sample: an absolute cap per type | F-06 (rest) | D-450 |
| T-694 | The cascade's note stage in batches; joins, not patient lists; the lake's query limit per job type; excluded patients streamed | F-07, F-27, F-29, F-36 | — |
| T-695 | Update, stop and boot at scale | F-09, F-10, F-24 | — |
| T-696 | The excerpt budget from the context; S2b with the pinned embedder | F-11, F-23 | — |
| T-697 | The audit writer at a million events a day | F-12 | — |
| T-698 | The gateway's queue and read limits for batch roles; one lease of the card on the swap layout | F-13, F-30 | D-449 |
| T-700 | The console's fixed counts: jobs per study, the export that fails loudly, the excluded list, break-glass, audit reads | F-14, F-18, F-20, F-21, F-22, F-35 | — |
| T-701 | The embedder on the GPU, with retry | F-15 | — |
| T-702 | The OMOP load at scale | F-17 | — |
| T-703 | PostgreSQL sized from the host | F-19 | — |
| T-704 | The night as a chain: weekly jobs after the ingest, one run per study, the microbatch allowance reserved and shared, retention that keeps what a study still reads | F-32, F-33, F-34 | D-451 |

## 7. Fixed on this branch

| Finding | Commit subject | Test (failed first) |
| --- | --- | --- |
| F-03 | The console's backup starts the services it stopped | `tests/unit/test_ops_backup_resumes.py` |
| F-06 | The HL7 validator takes a sample of any size, in batches | `tests/unit/test_validator_large_sample.py` |
