# D-458 The night's shared limits: the micro-batch allowance is reserved, retention keeps what an open study reads, one worker is the ingest's

- **Task:** T-704 (`docs/plan/28-master-plan-v6.md` §6.2.10; `docs/plan/31-master-plan-v6.1-addendum.md` §3.4: its
  chain is absorbed by T-726, D-492)
- **PR:** this branch (`agent/T-704-night-allowance-retention`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-32, F-34 and the worker item of F-33 of `docs/reviews/2026-11-11-scale-timeouts.md`
- **Builds on:** D-397 (the micro-batch cadence and its night budget), D-386 (a list job runs only for an open
  study), D-492 (T-726: the night's chain starts the micro-batches of a night together), OD-10

## Context

- **The allowance** (`TB_MICROBATCH_NIGHT_BUDGET`, patients a night for every study together) was read by each
  micro-batch as "the budget less what the night's other micro-batches have written into their metrics". Jobs
  that start together have written nothing yet, so each took the whole budget: four jobs, four times the
  allowance; and when they ran one after another the first studies took it all and the later ones got nothing,
  every night, in the same order (F-32).
- **Retention** deletes job outputs after 365 days. The micro-batch reads the lists of the study's last SCREEN
  (who was listed, who was excluded) to know whom it has seen. A study whose last SCREEN is over a year old lost
  those files, and every micro-batch of it failed from then on, for a reason of time, not of data (F-34).
- **The workers**: four long jobs took all four, and the next night's ingest waited behind them into clinic hours
  (F-33).

## Decision

1. **The allowance is reserved in the database.** A micro-batch takes its allowance once, under a lock of the
   night (a PostgreSQL advisory lock): it reads what the night's other micro-batches have **reserved** (a running
   job) or **used** (a finished one), not what they happen to have written so far, and writes its own reservation
   into its job record (`options.night_reserved`) before the lock is released. The reservations of a night never
   add up to more than the allowance, however many jobs start at the same moment.
2. **Each study gets a share.** A job reserves an equal share of what is left among the night's micro-batches
   that have not reserved yet (itself included), so the order of the studies no longer decides who gets anything.
   When the job ends its reservation becomes what it used; what it did not use is there for the jobs after it.
   Within a study the allowance goes to the nearest appointments first, as before.
3. **Retention keeps what an open study still reads.** Before it deletes, retention asks the micro-batch's own
   function which stored lists the next micro-batch of each study with a candidate pool will read (the last
   SCREEN's candidate and excluded lists, the newest micro-batch record after it). For a study that is open
   (D-386) those objects are kept whatever their age; a study whose state cannot be read is treated as open. The
   retention report says how many objects were kept for that reason. Everything else is deleted as before, and
   when the study is closed or screened again the old lists go at the next retention.
4. **One worker is kept for the ingest.** With two or more workers, the first takes only INGEST jobs: the night's
   ingest starts at its time whatever the other workers are doing. A box with one worker is as before.

## Consequences

- Three micro-batches started together with an allowance of 100 evaluate at most 100 patients, and each study
  some.
- A box with four workers runs three other jobs at a time; the ingest never waits for them.

## Not decided here

- **Sharing by nearest appointment across studies** (the 100 nearest visits of the box, whichever study): the
  share here is equal between the studies that are waiting. It needs each study's due list before any of them
  reserves; the night's chain (D-492) is where that can be computed.
- **Nightly deltas** (the timer's ingest as "since the last published generation"): not built. A delta night
  depends on what each source can say about change and deletion; a wrong delta drops records silently, so it
  wants its own card and tests per source.
