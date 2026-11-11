# D-389 Job cancel, the SCREEN breaker, the declared settings list and the log caps

- **Task:** T-108d, operations in code, part d (`docs/plan/28-master-plan-v6.md` §6.2.5; the T-108 row of
  TB-ASSESS-01)
- **PR:** this branch (`agent/T-108d-ops-d`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** OPS-034, OPS-037; the cancel, breaker and declared-list parts of T-108 (review R-39 / A-08, MR-076)
- **Builds on:** D-360 (T-108a, compose limits and log options), D-377 (T-108b, systemd units), D-315 (no default
  zone), D-138 (log retention)

## Context

A cancel set a flag that was read only when a job changed state. A SCREEN changes state twice, so the cascade ran to
its end and the work was then thrown away. A hung model server (up, answering `/health`, never generating) cost up to
600 s a call, so a night could take days to fail, and the next nights queued behind it.

About 290 `TB_*` settings were read across the code with no single list, so nobody could tell what a box can be set
to, and a misspelt name was silently ignored.

The containers kept 5 × 50 MB of log each. The review estimates the busiest service writes about 300 MB on a
50,000-patient night, so the start of the day could rotate away before the 00:20 collection (OPS-034). The two host
log files of the cron jobs had no rotation (OPS-037).

## Decision

1. **Cancel reaches the model calls.** Each job's judge and verifier clients are wrapped
   (`services/orchestrator/jobs.py`, `GuardedLlm`). Before every model call the job's cancel flag is read; a set
   flag stops the job there, within the pair it is on. The job ends as before: state `failed`, step `cancelled`.
   Cancelling twice, or cancelling a finished job, changes nothing. Every job type gets this check.
2. **A breaker for SCREEN.** After `TB_SCREEN_BREAKER_FAILURES` model failures in a row (default 5; 0 turns it off)
   the breaker of that model client opens and the SCREEN fails at once, with a message that says the model stopped
   answering and nothing was sent. While it is open, a new SCREEN fails without a call. After
   `TB_SCREEN_BREAKER_WINDOW_S` (default 300 s) one trial call goes through: an answer closes it, a failure opens it
   for another window. A prompt that does not fit or is not qualified does not count. The breaker is shared by the
   orchestrator's jobs, one per model client. Other job types keep only their end-of-run failure share.
3. **One declared list.** `tb_common.config.DECLARED` names every `TB_*` setting the Python of `libs`, `services`,
   `tools` and `deploy` reads, with its kind, its default and one doc line. Names built at run time are families
   (`TB_EP_`, `TB_MEM_`). `tests/unit/test_config_declared.py` fails on a read name that is not declared and on a
   declared name nothing reads. A new setting adds its row in the same PR.
4. **Provisional log caps, marked unmeasured.** Each container keeps `TB_LOG_MAX_SIZE` × `TB_LOG_MAX_FILE`, default
   100 MB × 10 = 1 GB, in the main compose file and the four tier files' model servers. These were to be sized from
   G1, which is parked, so they are **not measured**. They rest on the review's estimate: about 2.8 times the busiest
   night, and about 1.4 times a day whose daytime traffic equals the night.
5. **Gap detection is the measurement.** `trialbox logs collect` (and `daily`) writes `COVERAGE.json` for each
   collected day. For each service it records the bytes, the lines and the share of the cap used. It also records a
   gap when docker had already deleted its oldest file and the oldest kept line is later than the day's start. A gap
   exits 1 and names what to raise. Over three quarters of the cap gives a warning. The first full night's
   `COVERAGE.json` replaces the estimate.
6. **Host log rotation.** `deploy/logrotate/trialbox` rotates `/var/log/trialbox-*.log` weekly and keeps 53.
   `install.sh` installs it as `/etc/logrotate.d/trialbox`.

## Consequences

- An admin's Cancel now stops a SCREEN in seconds, not at the end of the run. The partial S3/S4 answers of a
  cancelled run are not kept as a result. The gateway's audit lines of the calls made stay.
- A hung model fails a night after 5 failed calls (each still waits for its own timeout), not after every patient.
  The failure mail says so.
- A box can use up to 1 GB of disk per container for logs (the model servers included).
- `cancelled` is not a new job state: that would change the job contract and every reader. A cancelled job is
  `failed` with the error step `cancelled`, as before.

## Not done here

- `trialbox cancel <job>` from the host shell. The orchestrator's cancel endpoint needs a signed user assertion. The
  console's Cancel button and the `CANCEL` mail command already reach it.
- Keeping the partial S3/S4 answers of a cancelled SCREEN. That needs the cascade (`scenarios/`, outside this card).
- Measured caps: after the first full night (G1 or a site's first week).

## Tests

`tests/unit/test_job_cancel_breaker.py`, `tests/unit/test_config_declared.py`, `tests/unit/test_log_caps.py`.
