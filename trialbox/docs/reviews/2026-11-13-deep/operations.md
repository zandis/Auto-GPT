# Deep review 2026-11-13: the box and its operation

| Field | Value |
| --- | --- |
| Document ID | TB-DR3-OPS |
| Date | 2026-11-13 |
| Tree | master `c7dcd5e7`; fixes on branch `claude/deep-review-operations` |
| Area | Install and first start (Linux and WSL2), compose files and images, model serving and the gateway, the night run and its scheduler, watchdog and health, updates and rollback, time, logs, resource limits, failure modes (power loss, full disk, dead GPU, dead database, clock jump) |
| Not in this file | Lane G's cloud-run files (`deploy/gcp/*`, `tools/complete_run.py`, `tools/run_metrics.py`, `tools/g_probes.py`, `tests/rehearsal/*`): findings on them are listed for lane G, not fixed |
| Run | The unit tests of every area below (about 1,550 tests, all pass on master except where a finding says so). New failing tests for each fix. `python -m tools.limits_lint`. `docker compose config`-equivalent rendering of the rtxpro6000, gb10 and rtx5090 forms by YAML. Repro scripts for the findings marked "confirmed by running". |
| Could not run | Anything that needs Docker, a GPU, a real power cut or a full disk. `tests/integration/test_e2e_simple.py` stops at its first compile here: the CQL translator's jars could not be fetched through this machine's proxy (`make jvm-deps`: Maven gets "not found" for artefacts that `curl` fetches). No `shellcheck`, no PowerShell. |

## 1. Terms

| Term | Meaning here |
| --- | --- |
| Night | The timed ingest (02:00 by default) and the chain that follows it: micro-batch, NAV, retention (T-726) |
| Timer's ingest | The ingest the scheduler starts, with options `timer=1`, `chain=1` |
| Slot | One call the gateway lets through to a model server at once (D-445) |
| Breaker | The gateway's per-endpoint circuit breaker: closed, open, half-open (one probe call) |
| Canary gate | The rule that a note answer may exclude a patient only after a recent passing model self-test (D-117) |
| Unfinished update | `deploy/updates/IN_PROGRESS.json` exists (D-210) |
| Confirmed by running | Reproduced with a command or a failing test; "by reading" means from the code only |

## 2. Summary

Ten things matter most. Five are fixed on this branch, each with a test that failed before.

| # | Finding | Severity | State |
| --- | --- | --- | --- |
| 1 | A power cut during an update booted the half-applied release; the later rollback discards every row written since boot | High | **Fixed** (OPS13-01) |
| 2 | One request the model server always answers with an error is resent every few seconds until the job's whole outage allowance is spent; then the whole job stops and every other patient of the night is left unscreened | High | Open, lane A2 (OPS13-20) |
| 3 | The gateway let 16 calls through per endpoint on every form: 4 times the rtx5090 server's sequences, twice the GB10's | High | **Fixed** (OPS13-02) |
| 4 | Model-guard keeps a request running on vLLM for up to 900 s after the gateway gave up at 180 s, so vLLM holds more requests than the gateway's slots | High | Open, lane D (OPS13-11) |
| 5 | A timer's ingest missed while the box was down never ran, though F-14 / D-130 say it does | Medium | **Fixed** (OPS13-03) |
| 6 | Three clock-step faults: the canary gate stayed open on a pass dated in the future; the night chain stuck on an ingest received while the clock ran ahead; `publish._recover` judges a finished build by a file's mtime | Medium | Two **fixed** (OPS13-04, -05), one open (OPS13-12) |
| 7 | The night-window arithmetic: the pass rule counts model time only, the default schedule gives 5 hours not 8, and the measured figures disagree with each other | Medium | Open, lanes B2 and G (OPS13-13) |
| 8 | The 2,000-patient night budget is not derived, and it starves excluded patients more than capacity does | Medium | Open, owner's decision (OPS13-14) |
| 9 | A crash-looping service is never acted on or reported; the watchdog's "gave up" is in the audit only | Medium | Open, lane D (OPS13-15) |
| 10 | The nightly end-to-end workflow is red on every scheduled run and tells nobody; its update and backup drills pass with their real cases skipped | Medium | Open, lane D (OPS13-16) |

Also open and worth a card: a same-date lake rebuild skips the drop check and nothing on the night path is fsynced (OPS13-10, Medium).

Also fixed: the second model server's logs were filed as TrialBox's own scrubbed logs (OPS13-06); a half-open probe that raised an unexpected error shut its endpoint until a restart (OPS13-07); a job's outputs were not on disk when the job said done (OPS13-08).

Lane G's three asks are already on master: the gateway's audit records each call's `slot_wait_ms` (D-627, `services/gateway/core.py:184`, `:677`, `:910`); `Stage.check` keeps the whole detail and cuts only the printed line (D-628, `tools/e2e_simple.py:66-82`); `tools/serving_config.py` captures `structured_outputs_backend` (`:83-114`). The last is only half done: see OPS13-17.

## 3. Fixed on this branch

Each fix has a test that fails on master and passes here.

| Id | Defect | Root cause | Fix | Test |
| --- | --- | --- | --- | --- |
| OPS13-01 | After a power cut during an update, `trialbox.service` started the half-applied release (`deploy/systemd/trialbox.service:15`); Docker's `restart: unless-stopped` started recreated containers too. The night ran on half-migrated tables; the runbook's rollback then restores the pre-update dumps and discards every row written since. | `update_status check` was documented as the start guard (D-210; runbook §5 line 55) and called by nothing | `ExecStartPre` tests for the marker `update_status check` reads (a file test: a host without `python3` still starts); when it exists it stops the project's containers and the unit fails. Runbook §5 says so | `tests/unit/test_systemd_units.py::test_the_stack_does_not_start_on_an_unfinished_update` |
| OPS13-02 | The gateway's slots per endpoint were 16 on every form. The rtx5090 servers run 4 sequences, GB10 8, the base form 64 | `load.py:183-184` reads `TB_SERVING_RECORD`, else `TB_GATEWAY_SLOTS`, else 16; no compose file passed either | Each GPU overlay sets `TB_GATEWAY_SLOTS` to the judge server's `--max-num-seqs` expression | `tests/unit/test_gateway_slots_follow_the_server.py` |
| OPS13-03 | A timer's ingest missed while the orchestrator was down (a reboot across 02:00) never ran: no ingest, no chain, that night. On the fall-back night of a daylight-saving zone the timer fired twice | The job store is in memory: `misfire_grace_time` (`config.py:305`) covers a delay inside a live process only. The ingest job had no once-a-day rule | `scheduler.catch_up_ingest` at start, on a PRODUCTION or VALIDATION box only, runs an ingest whose time passed within the grace when the scheduler's ingest for that fire time does not exist; `timed_ingest` runs once per fire time, recorded on the job as the site's wall clock (option `fire`), so the two 02:30s of a fall-back night are one. An administrator's retry, which copies the options, does not count as the timer's run | `tests/unit/test_scheduler_missed_ingest.py` (6 tests) |
| OPS13-04 | The canary gate stayed open on a pass stamped while the clock ran ahead: its age read negative, so a note answer could exclude past `TB_CANARY_MAX_AGE_H` | `age = (time.time() - at) / 3600` (`canary_gate.py:115`) with no lower bound | A pass dated later than now (beyond the stamp's 0.1 s rounding) is `stale`: the gate closes, a note answer goes to review | `tests/unit/test_canary_gate.py::test_a_canary_stamped_in_the_future_does_not_hold_the_gate_open` |
| OPS13-05 | The night chain picked "the newest night" by the job's wall-clock `received_at`; one ingest received while the clock ran ahead stayed newest after the clock was put right: no micro-batch, NAV or retention, and no message | `JobDB.chained_ingest` ordered by `received_at` (`db.py:363-367`) | Order by the job store's `seq`; page back by job id | `tests/unit/test_night_order_not_clock.py` (2 tests, PostgreSQL) |
| OPS13-06 | The second model server (`llm-verifier`) and the rtx5090 swap helpers run the vLLM image, but their logs went into `services/`, the tree the support bundle copies. OPS-035 had come back in part | `THIRD_PARTY` in `tools/trialbox/logs.py:70` was a hand list | The set names every service on an image TrialBox does not build; the test reads the compose files, so a new one fails CI | `tests/unit/test_logs_third_party.py::test_every_service_on_an_image_trialbox_does_not_build_is_collected_apart` |
| OPS13-07 | A half-open probe whose call raised an error that is not an `httpx` error (a body the client cannot encode, a bug) left the probe flag set: every later call to that endpoint was refused until a restart, and `/readyz` did not show it | `_send` handles only `httpx` errors; nothing told the breaker | `except BaseException: breaker.cancel(); raise` around `_send` | `tests/unit/test_gateway_breaker_unexpected_error.py` |
| OPS13-08 | A job's outputs were renamed into place with no fsync while its `done` was durable at the database's commit: a power cut after a screening left a done job with no list | `FsStore.put` (`libs/tb_common/objstore.py:146-155`) | fsync of the file and of its folder | `tests/unit/test_objstore_sealed.py::test_a_put_is_on_disk_before_it_returns` |

What the fixes change for patients and the night (called out for the integrator):

- OPS13-04 closes the canary gate in one more case. A closed gate never excludes and never includes: a note answer that would exclude goes to review.
- OPS13-03 can start one ingest at start-up that did not start before. It runs only within the declared misfire grace and only when no timer's ingest of that night exists.
- OPS13-05 changes which ingest is "the night" only when the clock and the store's order disagree.

The adversarial review (a fresh reviewer, read the diff and ran the tests and its own scripts) passed fixes 01, 02, 04 to 08. It broke the first form of OPS13-03 in two cases, both fixed before the second push: a dedupe counted from site midnight let a late ingest time (23:30) caught up after midnight take the next night's run, and an administrator's retry before 02:00 blocked that night's timer; it also showed that a test stack started at night would ingest at start. Testing the reworked rule found a third: the first form's search for the last fire time added a second to an aware time, which Python does on the wall clock, so on a fall-back night the loop never ended (it would have hung the scheduler's thread); the search now runs in UTC. It asked for the guard of OPS13-01 not to need `python3`. Left as findings: on shared-quota the verifier's sequences are set apart from the judge's, so `TB_GATEWAY_SLOTS` (one number) can exceed the verifier's (OPS13-29); with the slots now equal to the screening's calls in flight (4 and 4 on rtx5090), an interactive call during a micro-batch hears `model_busy` after 0.5 s instead of queueing inside vLLM, which is D-445's intent but a change people will notice; a canary run at start before the time service corrected a fast clock closes the gate for about a day (availability, not safety), and the health mail shows `stale` as "too long ago"; an update marker left at step `finished` (only the clean-up was cut) also keeps the box down until `rollback` (OPS13-30).

## 4. Open findings

Severity: Critical is a wrong exclusion or inclusion of a patient, data loss, a secret or patient data exposed, or who may act broken. "Locked" means an open pull request touches the file, so this branch did not edit it.

### 4.1 Power loss, disk, database

**OPS13-10. A same-date lake rebuild is served unchecked; the night's files are not fsynced.** Medium (a wrong inclusion when it happens; the adversarial review lowered it from High: it needs a same-date rebuild over an NDJSON folder a power cut damaged, and ext4's `auto_da_alloc` covers a file renamed over an old one). Lane B2.

- Symptom: `Lake._check_drop` returns at once when the rebuilt snapshot is the current one (`services/lake/store.py:977-978`), which is the site publish's rebuild (`services/sitesetup/service.py:463`). The adapter and the lake fsync none of the night's NDJSON, `publish.json` or `passed.json`. A type file emptied by a power cut is then served, delta nights merge onto it, and the drop guard compares against it.
- Evidence: confirmed by running a test that builds a lake, empties `condition` and rebuilds the same date: before `{'patient': 10, 'condition': 10}`, after `{'patient': 10, 'condition': 0}`, served with no error. That ext4 leaves a zero-length file after a cut is inferred.
- Fix: check a same-date rebuild against the served DuckDB's own row counts; fsync the NDJSON and its folder before `passed.json`; record the folder's fingerprint in the build record and refuse a rebuild whose folder differs.

**OPS13-12. `publish._recover` judges a re-run by a file's mtime against the wall clock.** Medium. Lane B2.

- Symptom: `rec["swapped_ns"] = time.time_ns()` (`services/adapter/publish.py:486`) is compared with the served file's mtime (`:196-198`). A clock step back during a build reads a finished re-run as unfinished; the old folder is put back under a lake that serves the re-run, and FHIR is put back too.
- Evidence: confirmed by running (a stub clock).
- Fix: record the date's generation before the swap; "forward" means a newer generation record exists.

**OPS13-18. A database outage makes the watchdog restart the services that use it.** Medium, by reading. Lane D.

- The orchestrator's `/healthz` queries the job store (`services/orchestrator/app.py:161-164`). After about 150 s of database outage it is unhealthy and the watchdog restarts it, which cannot help. Each restart kills the running SCREEN and counts against `TB_JOB_MAX_RESTARTS` (3).
- Fix: do not restart a service whose dependency is unhealthy; report "dependency down" apart from "this service is hung".

**OPS13-19. A future-dated audit day file keeps later events out of the off-box archive.** Medium. Lane C2.

- The writer stays on the newest day file when its date is later than the event's (`libs/tb_common/audit.py:263-268`); `archive_audit` copies only days before today (`tools/trialbox/logs.py:372`). Confirmed by running. The chain still verifies; the archive copy is what is lost with the box.
- Fix: archive a file whose last line is more than a day old; a doctor FAIL for a day file named after today.

Low, by reading: `JobLease` is a session advisory lock that a database restart drops silently (`services/orchestrator/db.py:180-205`); lake holds expire by wall clock, 14 days (`services/lake/store.py:362-370`); runbook §4 "disk full" says `doctor` warns, but `doctor.py` has no disk check (the health mail has, `metrics.py`, 85 %).

What holds (do not change): a failed or timed-out model call becomes `unknown`, never an exclusion (`services/matching/cascade/judge.py:136-141`, `libs/tb_common/pair.py:71-72`, `engine.py:922-944`); the outage wait and kept answers after a restart (T-689) use the monotonic clock; the audit chain survives a torn last line; the backup writes `.part`, fsyncs and renames; the lake build goes into `.building` and promotes `CURRENT` last and atomically (`store.py:914-919`); a dead database fails the job rather than ending it done with partial results (`decision_context.py:145-164`).

### 4.2 Gateway and model serving

**OPS13-11. Model-guard keeps a request running after the gateway gave up.** High. Lane D.

- Symptom: on a read timeout (180 s batch, 30 s interactive) the gateway frees its slot and admits the next call. Model-guard's own upstream connection stays open up to `TB_GUARD_TIMEOUT_S` (900 s, `services/model_guard/__init__.py:189`) with a blocking `resp.read()` (`:142-151`). vLLM aborts a generation only when its client, the guard, disconnects. So vLLM holds more requests than the gateway's slots, and timeouts feed more timeouts.
- Evidence: confirmed by running that the guard's upstream socket stays open 3 s after the client left; vLLM's abort-on-disconnect is inferred.
- Fix: set the guard's timeout from `TB_GATEWAY_UPSTREAM_READ_S` plus a margin in compose; close the upstream when the downstream socket closes.

**OPS13-20. One request the server always fails is resent for the whole outage allowance, then the whole job stops.** High (raised by the adversarial review). Lane A2 (`libs/tb_llm`).

- Every 5xx after the gateway's own retry is `upstream_down`, a model fault (`libs/tb_llm/outage.py:28`); `wait_and_retry` resends it with no per-call cap (`:141-160`); while it waits, `_once` gives the job's breaker back instead of counting a failure (`services/orchestrator/jobs.py:553`). A simulation: 361 sends, 722 model calls in 1,800 s for one request, then `OutageExhausted`: the whole job stops with `ModelOutage` (`jobs.py:512`), saying the model did not answer, and every other patient of that night is left unscreened. Each resend also adds two gateway breaker failures; when the other calls drain, the endpoint opens for interactive users too.
- Fix: a per-call resend cap (a declared setting), then that pair is `unknown` (`upstream_failed`).

**OPS13-21. The rtx5090 swap puts a model to sleep with calls to it in flight.** Medium, by reading. Lane D.

- `swap.activate` does not look at `load.endpoints[other]` in-flight calls. A front-desk judge call outside a screening hold can sleep the verifier under a running batch.
- Fix: wait, bounded, for the other endpoint's calls, or answer `model_busy`.

Low: `failure()` while open moves `opened_at` forward and a stale `cancel()` lets a second half-open probe out (`services/gateway/load.py:99-118`; confirmed by running); a `ConnectTimeout` ends as final `upstream_failed` though nothing was sent (`core.py:790-798`), while `timeouts.dropped()` calls it safe to resend; the retry delay has no jitter; 429 and 408 reset the failure count (`core.py:819`); nothing checks that the caller's timeout (240 s) exceeds the call budget (210 s) and the read limit (180 s); a body with `NaN` is accepted and ends as HTTP 500 with no audit record (LLM-5). `TB_GATEWAY_SLOTS` is one number for both endpoints: right while both servers default to the same sequences (the new test holds that); a per-endpoint value needs a declared setting.

Known and still open, not repeated: F-13 / PERF-013 (T-698), a batch call's slot wait comes out of its call budget and its read timeout counts as a breaker failure.

**OPS13-29. One slot number for two servers.** Low. Lane D. `TB_GATEWAY_SLOTS` applies to every endpoint; on shared-quota `JUDGE_MAX_SEQS` and `VERIFIER_MAX_SEQS` are both required and may differ, so a verifier with fewer sequences gets the judge's count. Fix: per-endpoint slots (a declared setting, D-TBD), or the serving record mounted and `TB_SERVING_RECORD` set, as D-445 describes.

### 4.3 The night, its scheduler and capacity

**OPS13-13. The night-window arithmetic.** Medium. Lanes B2 and G.

The plan's thresholds (`33-plan-v7.md:478-479`, from `2026-11-12-deep-review/06-llm.md:146-150`) are `N × 0.0239 × 5.6 × K ÷ (W × 3600 × 0.7)` model calls per second: 2.39 % of patients reach the note stage, 5.6 calls each. With W = 8 hours the 1.66 and 3.32 are right. Against the measured 4.5 calls per second, with the non-model time of a 50,000-patient part (37.5 of its 50 minutes) growing with patients and studies:

| Patients × studies | Model calls | Calls/s needed, 8 h | Calls/s needed, 5 h | Model hours at 4.5/s | Whole night, hours | Fits 8 h × 0.7 | Fits 5 h × 0.7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 50,000 × 1 | 6,692 | 0.33 | 0.53 | 0.41 | 1.0 | yes | yes |
| 50,000 × 5 | 33,460 | 1.66 | 2.66 | 2.07 | 5.2 | yes, barely | no |
| 500,000 × 1 | 66,920 | 3.32 | 5.31 | 4.13 | 10.4 | no | no |
| 500,000 × 5 | 334,600 | 16.6 | 26.6 | 20.7 | 52 | no | no |

- The G-3 pass rule ("calls/s meets the window") counts model time only. At 500,000 × 1, 4.5 calls/s passes it, yet the night does not fit once three quarters of non-model time are counted. Only G-6 would show it.
- The measured figures disagree: G1 made 6,704 calls per 50,000-patient study; at 4.5/s that is 25 minutes, half of the 50-minute part, not a quarter. Either the part did not run at 4.5/s or it made about 3,400 calls. Lane G should say which before a capacity statement is written.
- The default schedule (ingest 02:00, `TB_NOTICE_N1_AT` 07:00) leaves 5 hours, not 8.
- The night window is in no setting and no derivation: the only figure is `tools/bench_profile.py:42` `NIGHT_HOURS = 8.0`. Nothing compares a night to it; nothing refuses with an estimate. `bench_profile.py` also has its own note-stage share (92/5000), which differs from 2.39 %: two capacity models.
- The nightly SCREEN the thresholds assume is never timed: the night runs micro-batches capped at 2,000 patients for all studies (about 268 calls, about a minute of model time).
- Fix: declare the window as a setting, or derive it from `schedule.ingest` and `TB_NOTICE_N1_AT`; judge G-3 and G-6 on whole-night time against it; have `scale_gate` report seconds per patient; one capacity model.

**OPS13-14. The night budget of 2,000 patients is not derived, and it, not capacity, starves excluded patients.** Medium. Owner's decision (D-TBD), lane B2.

- `TB_MICROBATCH_NIGHT_BUDGET` defaults to 2000 (`config.py:647`, `microbatch.py:115`) with no reason in D-397. `reserve()` splits it equally over the night's jobs (`microbatch.py:161-185`); D-646 keeps a quarter for excluded patients: about 100 per study per week with five studies. A whole-hospital scope of 50,000 takes about 500 weeks for one pass; a patient whose exclusion ended stays off the list for months.
- D-646's own measure (about 24 s and 20 to 40 calls per 1,000 excluded patients) puts 50,000 at about 27 minutes a week. The default uses about 0.3 % of an 8-hour night.
- Fix: derive the default from measured seconds per patient and the declared window, or declare it with a reason; print weeks-to-a-full-pass in the summary.

**OPS13-22. The box's record of its nights ends at the adapter's publish.** Medium, inferred. Lane B2 with W.

- `night_runs.json` (D-661) ends when the publish ends; micro-batch, NAV and retention run after it, and the Windows update window (D-606) is placed from this record, so an update can land on running screening jobs. D-661 lists this as not decided.
- Fix: the record ends at the night chain's last job.

Low: the night budget is keyed by calendar date, not by night (`microbatch.py:173-177`): an ingest moved before midnight gets two budgets; received jobs with no run date dilute the share.

What holds: chain job ids as the uniqueness key; the stateless chain recovered from the job rows (`night.py:214-252`); `night_left` and `excluded_kept` fixed at first run, so a resumed job makes the same list; the job lease with no time-to-live (a dead worker holds nothing); a newer night waits for an older chain (`night.py:224-232`); one site time zone throughout the scheduler (`config.py:288-298`).

### 4.4 Install, update, limits, logs, time

**OPS13-23. Memory caps add up to more than the host on the plain-Linux install, and nothing checks it.** Medium. Lane D. `deploy/install.sh` and `tools/trialbox/doctor.py` are locked.

| Form | Sum of `mem_limit` | Model servers alone | Host the overlay names |
| --- | --- | --- | --- |
| rtx5090 | 138.8 GiB | 96 GiB | 64 GB or more (`docker-compose.rtx5090.yml:20`) |
| rtxpro6000 | 138.0 GiB | 96 GiB | |
| gb10 | 115.5 GiB | 74 GiB | 128 GB unified |

Only the box form sizes caps from RAM (`tools/box/plan.py:314`); `install.sh` sizes the adapter and the lake only (`memcaps`, line 329); `check_wsl2_memory` passes on any non-WSL host (`doctor.py:1243`). The cgroup caps cannot bind before the host's OOM killer. Fix: one sizing path (`tools.box.plan.memory_caps`) for both installers, and the sum checked on every host.

**OPS13-24. `deploy/.env` can be left world-readable with fresh database passwords.** Medium (a secret exposed to local users). Lane D. Locked (`install.sh`).

- When `settings.yaml` exists and `.env` does not (a site that places its own settings; a power cut between the wizard's two writes, `settings_wizard.py:589`, `:593`), `install.sh:239` copies `.env.example` as 0644, appends the passwords (`:259-265`) and dies before the `chmod 600` at `:334` (the example has no `TB_SOURCE_DIR` or `TB_TLS_HOSTNAME`, `:288`, `:303`). Simulated by shell: 0644.
- Fix: `umask 077` at the top of `install.sh`; `chmod 600` after the copy; the wizard writes `.env` first, atomically.

**OPS13-25. `install.sh` can finish without the boot units.** Medium, by reading. Lane D. Locked.

- When `network.sh apply` fails or systemd is missing, `install.sh:539-558` only warns, even in PRODUCTION: the egress-at-boot, stack, watchdog, weights and ops units are not installed. The cron step dies in PRODUCTION (`:570`); this one does not. Doctor checks only `trialbox-ops.timer` (`doctor.py:1009`).
- Fix: die in PRODUCTION; doctor checks every unit.

**OPS13-26. With `TB_NTP_SERVER` set, the host check always fails the clock in PRODUCTION.** Medium. Lane D.

- `check_host.sh:314` runs the doctor with `docker run --network none`; `check_clock` then cannot reach the time server. Confirmed by running in a network namespace: `FAIL ... did not answer (gaierror)`. A permanent FAIL teaches operators to ignore the clock line. OPS-055 is closed in `doctor` only: `check_host.sh:240` still warns, the health line has no clock fact, and the box has no time source question (OPS-007).
- Fix: measure the offset on the host and pass it in, as D-621 does for `docker inspect`.

**OPS13-27. A power cut after the first-run wizard and before apply strands the box.** Medium, inferred. Lane D with W.

- `services/console/firstrun.py:211-223` creates the owner accounts, then writes the answers (with the key passphrase) to tmpfs `/run/trialbox-firstrun`. A reboot, `wsl --shutdown` or a Windows restart clears `/run`; the first-run pages answer 404 because accounts exist; `trialbox-firstrun.service` waits forever (`box-install.sh:143`). No runbook covers it.
- Fix: detect "accounts exist, no answers" and stop with a recovery instruction.

**OPS13-30. An update marker at step `finished` keeps the box down.** Low. Lane D. `update.py:823` writes step `finished` before the clean-up; a cut there leaves the marker, and the new start guard (OPS13-01) keeps the stack down until `rollback`, which would undo a completed update. Fix: `status` says a marker at `finished` needs only `clean`, and the guard lets that step through (`update_status check` and the unit's file test then differ: one rule in one place).

**OPS13-28. The rtx4090 verifier at boot** (the frozen finding, `box-install.sh:176`, `update.py:1365`) has a third place: `deploy/systemd/trialbox.service`'s `up -d` starts it on every reboot. Even with `--scale llm-verifier=0`, `model-swap-init` depends on a healthy verifier and `judge-wake-init` on it (`docker-compose.rtx5090.yml:151`, `:164`): the judge may never wake (inferred). Better: an rtx4090 overlay without the verifier and the swap helpers.

Low: no CPU limit on any service (a CPU-bound embed batch can starve the database); logrotate `weekly` with `maxsize 50M` keeps 53 files that can cover less than the 365 days claimed; no journald limits while two timers log every minute; `trialbox.service` hard-codes `--wait-timeout 900` instead of `TB_INSTALL_UP_TIMEOUT`; `tools/limits_lint.py` scans `services/` only, so the compose caps and `tools/` timeouts (`update.py` `timeout=900`) are outside the owner's limits rule; the watchdog's limits (3 restarts in 6 h) are command-line defaults, not declared settings, and it times them by `time.time()` (`watchdog.py:191`), so a clock step restarts too early or not at all.

What holds: the update's rollback point (images retagged, model files recorded before they are overwritten, dumps sealed, the restore in one transaction, `recover()` from any step); the backup's time limit from the database's size (D-455); every long-running service has a JSON log cap, `pids_limit`, a restart policy and a health check in every rendered form; `TB_TZ` is required and the doctor compares site, mapping and host zones; Windows sleep is off and WSL2 runs systemd.

### 4.5 Watchdog, health and the nightly

**OPS13-15. A crash-looping service is never acted on or reported.** Medium. Lane D.

- The watchdog acts only when `health == "unhealthy"` (`tools/trialbox/watchdog.py:316`). A service that exits at start (a failed migration, an OOM kill under its cap) is restarted for ever by `unless-stopped`; its health resets to `starting`, never `unhealthy`. Confirmed by running: 57 restarts over 30 passes, no audit event. When the watchdog does give up (3 restarts in 6 h, `:193-195`) it writes `ops.watchdog.gave_up` to the audit only; the health line (`libs/tb_common/metrics.py:318-331`) never reads container state, so the box stays green.
- Fix: track `RestartCount` per service across passes and audit a crash loop once; put unhealthy, crash-looping and given-up services on the health line in red.

**OPS13-16. The nightly workflow is red every night and tells nobody; its drills prove less than they say.** Medium. Lane D.

- `.github/workflows/trialbox-e2e.yml` was red on 2026-11-10, -11 and -12; it has `permissions: contents: read` and no failure step. The update drill always skips its real database-image case in CI and still prints PASSED (`tools/update_drill.py:249-258`, `:530-533`). The backup drill runs without `--require-extensions` on stock PostgreSQL, so its pgvector and PGroonga checks pass with nothing to check (`tools/backup_drill.py:272`, `:291`, `:500`). The scale job has not yet run on a schedule.
- Fix: an `if: failure()` job that opens or updates one "nightly red" issue; build the database image in the drill job and pass `--require-extensions`; a skip fails on schedule.

**OPS-074 is closed on paper only.** 13 of the 14 `test_runbook_*` drills it cites do not exist; only `test_model_hold::test_runbook_19_model_hold` does. Runbook §19's printed command (`python -m`, line 31) fails on the host.

### 4.6 For lane G

| Id | Finding | Ask |
| --- | --- | --- |
| OPS13-17 | No committed serving record names its structured-output backend or image digests (`deploy/measured/serving_config.rtxpro6000.json` and the five older records); `tools/serving_config.py validate` does not require them and prints "complete". There is no record for rtx5090, gb10 or shared-quota | Re-capture the PRO 6000 record with the current tool on the next GPU run; then lane D adds the backend to the validator's required fields (doing it now would fail every committed record) |
| OPS13-13 | The two measured figures disagree (6,704 calls per study at 4.5/s is half the 50-minute part, not a quarter) | Say which held in the 50-minute part: calls made, calls/s, slots |
| OPS13-11 | vLLM's abort on client disconnect is inferred | On the next run, time out a call at the gateway and read vLLM's `num_requests_running` |
| OPS13-02 | The new `TB_GATEWAY_SLOTS` on the PRO 6000 is 16, as measured | No change expected; the record's `max_num_seqs` should match |

## 5. Needless weight

- Two capacity models: `tools/bench_profile.py` (its own `NIGHT_HOURS` and note-stage share) and the review's formula; `tools/gpu_sizing.py` estimates throughput from bandwidth × 0.35 and nothing compares it with the measured 4.5 calls/s.
- Two memory sizing paths: `install.sh memcaps` and `tools/box/plan.memory_caps`.
- `tools/limits_lint.py` passes while covering none of the limits this area depends on.
- The rtx4090 rule as a command-line flag repeated at four call sites instead of one overlay.

## 6. Decisions for the owner

| Question | Recommendation |
| --- | --- |
| The night window: a declared setting, or derived from the ingest time and `TB_NOTICE_N1_AT`? (D-TBD) | Derived: 02:00 to 07:00 by default, so 5 hours; the capacity statement is restated against it |
| The night budget `TB_MICROBATCH_NIGHT_BUDGET` (2,000): derive it from measured seconds per patient and the window? (D-TBD) | Yes; until measured, state the reason for 2,000 in the declaration |
| A per-endpoint slot setting for the gateway, for a form whose two servers run different sequences (D-TBD) | Not needed while both default the same; the new test fails if they part |
| A failed nightly opens a GitHub issue (needs `issues: write` on the workflow) | Yes |
