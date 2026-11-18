# The failure drill under compose, 2026-11-18 (card H-31)

**Reader:** the integrator; lane B2 (the scheduler and the job queue); lane D (the nightly under compose, the
runbook); lane C2b (operations).

**Verdict.** The drill ran on the compose test stack (Docker, the stub model), not in process. Twelve services were
each killed during a night's work, then the database, then the disk that holds the database's volume was filled. Every
killed service came back by Docker's restart policy in 12 to 55 seconds, and no mail went twice in any night. The
audit chain verified after every kill, with no journal row missing from it. Jobs were lost when **the database went
away while a job was in its run step**: that job stays `running` with the orchestrator healthy, nobody is told, and it
ends only when the orchestrator is restarted (H31-01, High, B2). It happened in 2 of 3 database nights (a mailed
SCREEN) and in 1 of 2 full-disk nights (the night's own INGEST, so the night's RETENTION never ran). No runbook page
says to restart the orchestrator (H31-02, Medium, D). In a full-disk night the adapter's `ingest.failed` event could
not be audited and is not in the chain (H31-03, High, C2b). A kill of the adapter or the lake during the night's
ingest makes the INGEST fail with a reason, and the night's chain then waits for a person's retry, as the runbook says.
With the disk full, PostgreSQL could not stay up (10 restarts in 90 s) and came back by itself once space was freed.

## What ran, and what did not

| What | How | Ran |
| --- | --- | --- |
| The box | The compose test stack, as `make up-test` builds it (`deploy/docker-compose.yml` with `deploy/docker-compose.test.yml`, profiles `stub` and `test`): fifteen containers, the stub model, GreenMail (mail into the box) and Mailpit (the hospital's mail server). Images from `make images` on this machine (4 cores, 15 GB). A fresh stack for every night (`down -v`, the object folder emptied, `up --wait`) | yes |
| A night's work | Yesterday's ingest at set-up (`tests.stack.ensure_ingested`); then the night: a FEAS and a SCREEN mailed in for GZQO and RA-JAK (through GreenMail, the mail gateway's intake and the orchestrator, to the result mails); the timer's INGEST at its clock time (the drill sets `schedule.ingest` seven minutes ahead before the stack starts) with the adapter's ingest, the lake's rebuild and publish, and the chain the orchestrator starts by itself; the morning notices (`python -m console.notify` in the console container) | yes |
| The control night | The same night with no kill, on a fresh stack: 6 units of work (FEAS and SCREEN for each study, INGEST, RETENTION), 16 messages, the chain verified | yes |
| A kill | `kill -9`, from the host, of the container's first process (`docker inspect` gives its pid): the container exits as on a crash or an out-of-memory kill and Docker's `restart: unless-stopped` acts. Not `docker kill`, which Docker counts as a person's stop | yes, 13 targets |
| The full disk | The database's volume (`db-pg`) bound by a compose override to a folder on a 1 GB ext4 file, loop-mounted on the host (root on this machine); during the night's ingest a file beside that folder fills the ext4 from the host (`dd` until no space: something else on the same disk grew; the runbook forbids deleting from the database volume), and the drill removes it 90 s later (a person's step, `docs/runbook/04-disk-full.md` step 3) | yes, twice |
| The checks | From the product's records, after the night: the orchestrator's jobs (`GET /jobs`), the gateway's outbox (`mail.send_keys`), the hospital's mailbox (Mailpit), the audit journal (`audit.journal`) and the chain (`tools/audit_verify.py /data/audit` in the orchestrator's container). D-1109 says how each is counted | yes |
| The real model's pair (`llm-service`, `model-guard`) | not in the test stack (the stub stands in); needs the GPU box | **not run here** |
| A hung service (the watchdog's case: running but unhealthy) | the drill kills; it does not hang a process. `tools.trialbox watchdog` restarts an unhealthy container after `--after-minutes`; Docker's restart policy did every recovery, so the watchdog never acted | **not run** |
| The lake's, the audit's and the host's disks full | only the database's volume was capped; the others are named volumes on the host's disk (30 GB free), which the drill does not fill | **not run** |
| The morning notices N1 and N2 | `console.notify` ran and exited 0 in every night, but the test stack has no marks, visits or serious AEs due, so it sent no notice: "no double notice" was not tested by a notice that went out | **not shown** |
| MICROBATCH and NAV in the night's chain | the test stack's pool is empty (`orch.pool`: 0 rows; a mailed SCREEN does not fill it) and NAV runs on its weekday (Monday; the drill ran on a Wednesday). The chain was INGEST then RETENTION | **not run** |
| The administrator's retry of a failed INGEST (the "can be retried" half of check 1) | `POST /jobs/{id}/retry` needs a signed-in administrator; the drill did not drive it | **not run** |
| The identity, monitoring, backup and platform stacks | other compose files; not in the test stack | **not run** |

GreenMail and Mailpit are the test stack's stand-ins for the hospital's mail servers and are not part of the box, so
they were not killed. `tests/unit/test_failure_drill.py::test_compose_services_are_all_targets` fails when a service
of the base compose file is neither a target nor named as left out.

## The table by target

The final run, on one tool version, `python -m tools.failure_drill report` of its records (in
`failure-drill-2026-11-18/records/`). "Recover s" is from the kill until every service of the stack is running and
healthy again. The database and the disk were run twice each: their results differ between runs (both runs are shown).

| Target | Killed (exactly) | Stage, when | Recovery | Recover s | Night finished | Lost jobs | Double mails | Audit chain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adapter | kill -9 of pid 26212 on the host: the first process (init) of container adapter (6acd69e98f6e) | ingest, the adapter's ingest run is running | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost, 1 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| lake | kill -9 of pid 5736 on the host: the first process (init) of container lake (683ba78c8caf) | ingest, the ingest has ended and the lake is rebuilding | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost, 1 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| criteria-compiler | kill -9 of pid 18964 on the host: the first process (init) of container criteria-compiler (c3b00b73b867) | mailed, a mailed FEAS is running | Docker's restart policy (restarts: 1) | 13 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| orchestrator | kill -9 of pid 32272 on the host: the first process (init) of container orchestrator (981dbba56878) | mailed, a mailed job is running | Docker's restart policy (restarts: 1) | 13 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| gateway | kill -9 of pid 13729 on the host: the first process (init) of container gateway (b5bd38f5ae28) | mailed, a mailed SCREEN is running (it asks the model) | Docker's restart policy (restarts: 1) | 13 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| llm-stub | kill -9 of pid 27047 on the host: the first process (init) of container llm-stub (b97a220d72f1) | mailed, a mailed SCREEN is running (it asks the model) | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| mail-gateway | kill -9 of pid 7778 on the host: the first process (init) of container mail-gateway (d46a30e49762) | mailed, the first result mail is in the outbox | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| audit-writer | kill -9 of pid 20399 on the host: the first process (init) of container audit-writer (6af7b8a00ac3) | mailed, a mailed job is running | Docker's restart policy (restarts: 1) | 13 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| doc-parser | kill -9 of pid 1642 on the host: the first process (init) of container doc-parser (225238c6fae0) | mailed, a mailed job is running | Docker's restart policy (restarts: 1) | 13 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| embed-service | kill -9 of pid 14946 on the host: the first process (init) of container embed-service (f546f97dea0a) | mailed, a mailed SCREEN is running | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| fhir-store | kill -9 of pid 28175 on the host: the first process (init) of container fhir-store (37a58a27328f) | ingest, the adapter's ingest run is running | Docker's restart policy (restarts: 1) | 55 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| console | kill -9 of pid 10340 on the host: the first process (init) of container console (0e5acf72f3c2) | notices, the morning notices are being sent | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| db | kill -9 of pid 23456 on the host: the first process (init) of container db (52ae5b3d2bfa) | mailed, a mailed job is running | Docker's restart policy (restarts: 1) | 19 | no | FAIL: 1 lost, 0 failed with a reason, 0 twice | pass: 0 double, 7 missing, 0 held | pass: verify exit 0 |
| db (run 2) | kill -9 of pid 26764 on the host: the first process (init) of container db (a0b2a7d6bd6c) | mailed, a mailed job is running | Docker's restart policy (restarts: 1) | 19 | yes | pass: 0 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| disk | the disk that holds the database's volume, filled from the host by a file beside the database's folder until no space was left: 559939584 bytes (560 MB, 534 MiB) copied, 0.881723 s, 635 MB/s; /dev/loop0 974M 958M 0 100% /root/.cache/tb-drill-pg | ingest, the adapter's ingest run is running | a person's step (the drill freed the space); the database's restarts: 10 | 150 | no | FAIL: 2 lost, 0 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |
| disk (run 2) | the disk that holds the database's volume, filled from the host by a file beside the database's folder until no space was left: 558891008 bytes (559 MB, 533 MiB) copied, 0.844702 s, 662 MB/s; /dev/loop0 974M 957M 0 100% /root/.cache/tb-drill-pg | ingest, the adapter's ingest run is running | a person's step (the drill freed the space); the database's restarts: 10 | 147 | yes | pass: 0 lost, 1 failed with a reason, 0 twice | pass: 0 double, 0 missing, 0 held | pass: verify exit 0 |

## The findings

| Id | Target | What happened | Expected, and its source | Severity | Lane |
| --- | --- | --- | --- | --- | --- |
| H31-01 | db, disk | Killed while the mailed SCREEN GZQO was in its run step: the database was back in 19 s, but the job stayed `running` for the rest of the night (past the 900 s window) with the orchestrator healthy; its 7 result mails were never sent and its requester was not told. The orchestrator's log has one `worker error on <job>`: in `_run`'s failure branch `self.db.get(job_id)` (`services/orchestrator/core.py:566`) raised `DatabaseError` because the database was down, the error left `_run`, and `_worker` (`core.py:791-793`) logged it and went on; nothing looks at the job again until the orchestrator starts. Seen in 2 of 3 database nights (the first full run and run 1 of the final; run 2 killed at 2 s, before a job was in its run step, and recovered), and in full-disk run 1 on the timer's INGEST (so RETENTION never started) | No lost job: an interrupted job is queued again or failed with a reason (T-689, D-456, D-532; plan 8 V12; D-1109) | High | B2 |
| H31-02 | db, disk | The step that ends the stuck job is a restart of the orchestrator (the drill took it after its checks: the job ended `done` 11 s later), and no page says so. `docs/runbook/04-troubleshooting.md` names restarts only for a job "interrupted by a restart of the box N times" | A recovery that needs a person has a runbook row (card H-31): the row belongs in `docs/runbook/04-troubleshooting.md` | Medium | D |
| H31-03 | disk | The adapter's ingest run ended while the database was down; its log says "ingest.failed could not be audited" (`AuditUnavailable`). The event is in no journal and no chain: the audit trail of that night has no record of the ingest's failure, though the chain verifies | Every state change of a night is audited (SPEC §10.2; D-394: events go through the audit journal); the register's rule: an audit trail that can be wrong is High | High | C2b |

## Each target, in words

- **adapter** (killed while the timer's INGEST ran the adapter's ingest). Back in 12 s. The night's INGEST failed
  with "the ingest's process ended without an answer (it was killed, or the box restarted); run it again", and its
  failure mail went to the site contact. RETENTION did not start: the chain never follows a failed ingest. The
  runbook's row "The night's ingest reads failed: the ingest's process ended without an answer" says what to do.
- **lake** (killed during the 3.5 s rebuild after the ingest). Back in 12 s. The INGEST failed with "The nightly
  ingest finished with 1 error(s): see ingest_report_<day>.json"; the chain waits as above. The runbook's rows on an
  interrupted rebuild and a failed night say what to do.
- **criteria-compiler, orchestrator, gateway, llm-stub, mail-gateway, audit-writer, doc-parser, embed-service**
  (each killed in the first seconds of the mailed jobs). Each back in 12 to 13 s; every job ended `done` once; the
  mail was the control's, per recipient and event. The orchestrator's own kill was recovered by its requeue at
  start (T-689). The mail gateway was killed after the first mail (a "received" notice) had left: no key was left
  `sending`, none `uncertain`. The audit writer's kill left 28 lines in the chain; the journal held the rest and
  the writer drained all of it on restart, with no journal row missing. For doc-parser and embed-service the drill
  did not measure whether a job was calling them at the instant of the kill.
- **fhir-store** (killed while the ingest ran). Back in 55 s (the FHIR server's start). The INGEST and the chain
  ended `done`; nothing lost.
- **console** (killed while `console.notify` ran). Back in 12 s; the notice run exited 137 and a second run (as the
  timer's next firing) exited 0. The test stack had no notice to send, so this shows no double notice only
  vacuously (see above).
- **db** (killed while a mailed job ran). Back in 19 s, with every service healthy. Then H31-01, in 2 of 3 nights.
  The audit chain stayed intact in every database night: the journal kept what was written after the database
  came back, and the writer drained it.
- **disk** (the ext4 that holds the database's volume filled during the ingest). PostgreSQL wrote "could not extend
  file ... No space left on device", then could not write its WAL and stopped; Docker restarted it 10 times in the
  90 s the disk stayed full, and it came up by itself once the drill had freed the space (all services healthy 147
  and 150 s after the fill). Run 1: the timer's INGEST was in its run step when the database went; it stayed
  `running` (H31-01, the same `worker error on <job>` in the orchestrator's log), so RETENTION never started; the
  person's step (restart the orchestrator) ended the INGEST `done` 46 s later. The adapter's log of that night has
  "ingest.failed could not be audited" (`AuditUnavailable`): the adapter's run ended with the database down and its
  failure event is in no store the chain reads (H31-03). Run 2: the INGEST failed with `DiskFull` and a reason, and
  the chain waits, as for the adapter; `docs/runbook/04-disk-full.md` step 6 says to run it again.

## How the drill changed while it was built (so that the records can be read)

- The first full run (the same targets) gave the same result for every target but the database. Its database night
  ended `done` only because the drill then restarted the orchestrator to load the timer's clock time: that restart
  is itself the recovery (the requeue at start, T-689) and hid the stuck job. The drill now sets the clock time
  before the stack starts and never restarts a service during a night. The orchestrator's log of that night showed
  the cause (below, H31-01).
- The first lake run waited for a field the lake does not have; the lake's rebuild lasts about 3.5 s and is now read
  from `GET /rebuild/<day>` every 0.25 s.
- The disk target was first a tmpfs volume filled from inside the container. In the first full run PostgreSQL
  kept running and the INGEST failed with `DiskFull`. In the final run's first try PostgreSQL stopped on its WAL, and a
  tmpfs volume does not survive its container's restart: the database came back empty (initdb ran again). A loop-
  mounted ext4 then refused initdb (`lost+found` in its root), and freeing the space with `docker exec` failed while
  the container was restarting. The disk target now binds a subfolder of the ext4 and fills and frees the disk from
  the host. Those three tries are not in the table; the tmpfs fallback stays for a host without root.
- "The chain grew after the kill" is asked only when a job ended after the kill: the console's night had nothing
  left to audit after its kill.

## For the nightly under compose (lane D)

request: add `make failure-drill` as its own nightly job beside `compose` (it brings its own stack up and down and
kills its parts, so it cannot share the `compose` job's stack): about 110 minutes on a 4-core runner (15 nights of
about 7 minutes, the database's night up to 25); `timeout-minutes: 150`; it needs `make images` and Docker only.
A shorter nightly set (orchestrator, db, mail-gateway, audit-writer, disk: about 45 minutes) is `--target` each.

## How to run it

```
make images                              # once
make failure-drill DRILL_OUT=build/drill # every target; the records in build/drill, the table printed at the end
TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m tools.failure_drill run --out build/drill --target db --run 2
TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m tools.failure_drill report build/drill
```
