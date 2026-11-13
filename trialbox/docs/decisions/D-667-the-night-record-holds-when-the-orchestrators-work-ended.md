# D-667 The night record also holds when the orchestrator's nightly work ended

- **Task:** NEW-B-26 (asked by lane W for the update window, placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-26-night-record-orchestrator-end`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-661 (the adapter's record of a night and its copy on the host), D-492 / T-726 (the night's
  chain: screen, NAV, retention follow the timed ingest), D-474 (an administrator's retry of a scheduler job),
  D-606 (the update window is placed outside the night)

## Context

D-661 measures a night from the adapter's start to the moment the lake is published. The box's night does not end
there. The orchestrator's timed ingest job then derives and builds the twins, and the night's chain follows it:
one micro-batch per study, NAV on its day, retention. On a box with many studies that work can be the longer part.
An update window placed just after the adapter's `end` falls into it.

The orchestrator's container, like the adapter's, has no writable host folder; its data folder (`TB_ORCH_DIR`) is
the volume `orch-data`, which the host's backup already reads.

## Decision

1. **The orchestrator records each night's work**: `<TB_ORCH_DIR>/night_work.json` (`orchestrator.night_work`),
   one entry per night: `day` (the snapshot's date, the adapter's `snapshot`), `start`, `end` (the site's time with
   its offset), `finished`, `run`.
2. **The times are read from the jobs, and the entry is written once.** `start` is when the timer's ingest job was
   received; `end` is the latest end among that ingest job and the jobs of the night's chain. The entry is written
   when the night's retention job has ended and no job of the chain is open (`night.advance`, which runs at every
   job's end and at the orchestrator's start). Because the times are the jobs', a process that died before the
   write records the same times at its next start. The first finished entry of a night stays.
3. **`run` is 1 when the timer's own ingest passed, 2 when the night passed only as an administrator's retry**
   (D-474). The reader takes only `run` 1, as for the adapter's record: a daytime retry is not the night's length.
4. **Not measured, never a guess**: a night whose ingest failed; a night with no retention job (the scenario is
   not on the box, or retention is held); a night whose chain was cut short by the next night's ingest; a box
   whose scheduler does not run.
5. **No new count.** An entry goes when the job store no longer holds a retention job of its night: the box's
   own retention of jobs decides how many nights are kept.
6. **The same file and the same function on the host.** The nightly backup's copy step
   (`backup_schedule.copy_night_length`) puts the orchestrator's entries into `deploy/site/night-length.json`
   under the key `work`, beside the adapter's `nights`. `tools.night_length.night_runs(deploy)` answers each night
   as before (`start`, `end`), and adds `work_start` and `work_end` when the orchestrator measured the same day.
   **A night without the two keys: its work was not measured**, never "no work after the publish".
7. **The record never fails what it measures.** `night_work.note` never raises (a full disk, a damaged file); the
   copy step keeps the adapter's part whole when the orchestrator's part cannot be read, and keeps the earlier
   copy of that part.

## What this does not do

- It does not change the doctor's `update_window` line (lane W): the reader gives it two more keys.
- The monthly jobs (cohort, calibration) keep their own clock time and are not part of a night's entry.
- A night that ran past the next night's ingest is not measured (item 4). The adapter's entry of that night is
  still answered.

## Tests

`tests/unit/test_night_work_record.py`: a real orchestrator and job store with the T-726 stand-in scenarios (the
entry's times equal the jobs'; nothing is written before retention has ended; a failed ingest, a missing retention
job; a retry is `run` 2 and the reader passes it over; the first measure stays and the file is not written again;
**interrupt**: a write that fails does not fail the chain, and a new process writes the same times from the jobs;
a damaged file; pruning by the job store), the host's copy (both parts in one file; an unreadable orchestrator
part leaves the adapter's part whole) and the reader (entries it cannot use are "not measured"; a copy made before
this card reads as before).
