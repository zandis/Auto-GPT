# D-666 A re-run of a merge rebuilds the alliance tables as the earlier merges left them, or says it cannot

- **Task:** NEW-B-25 (a finding of lane A2's review of the one upload decoder, #479; placed by the integrator on
  2026-11-13)
- **PR:** this branch (`agent/NEW-B-25-replay-gives-what-the-first-run-gave`), cut from lane A2's #479
  (`7de26651`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** the re-run of a job from its immutable objects (`orchestrator.rerun`), UX-004 / #479 (one reader
  for uploaded tables: UTF-8, Shift_JIS, Big5, or a refusal)

## Context

A re-run of a `COHORT MERGE` first rebuilds the alliance tables as they stood when that merge ran: it goes through
the earlier COHORT jobs in order and stores what each one stored (`_replay_alliance_tables`). It did so by parsing
every table of every earlier job, `done` or `failed`, with **today's** reader.

Before #479 a table in Big5 or Shift_JIS made the merge fail with a Python error: the job stopped at that table,
with the tables before it stored and nothing after. With #479 the same bytes parse. Confirmed by a test on #479's
head: the replay of such a failed job stored the Big5 table and the table after it, which the first run never
did. The merged table of a re-run then differs from the original's, or agrees with it for the wrong reason.

## Decision

`_stored_then(job)` says which tables an earlier merge stored, from **where** the job ended. A merge stores each
table as it reads it, while the job is `running`; `reporting` comes after the last table.

1. **`done`**: every table that parses and is not refused, as before. A job from before the one decoder ended
   `done` only with UTF-8 tables (anything else raised), and the one decoder reads UTF-8 as UTF-8; since then the
   same decoder reads a table now as then.
2. **Failed before a table was read** (refused at the start; cancelled before it ran, "Cancelled by ..."; "No
   valid alliance table"): none.
3. **Failed while `running` with the old reader's `UnicodeDecodeError`** (the job's recorded detail): the tables
   before the first one that is not UTF-8. That is where the job stopped.
4. **Failed after the tables** (in `reporting`; the output's routing refused): all, as `done`.
5. **Anything else**: an internal error, a restart or a service's failure while `running`, a cancel the job
   itself took ("Cancelled on request."), or no error recorded at all. Where it stopped is recorded nowhere. The
   replay does not guess: the re-run answers "this job cannot be re-run", names the earlier job, and runs
   nothing.

## Consequences

- One merge stopped in its run (case 5) makes **every** later merge's re-run answer "cannot", for good: nothing
  in the box clears it, and it is not per disease or quarter (a site's sender is bound across all of them).
  Before, such a re-run ran on tables that may not have been the ones of the time and said nothing. The way out
  is the record named below, which a later card can add; until then an operator reads the merged tables of the
  jobs themselves. **Since D-670 (the record is D-648): this cost remains only for a merge that read
  before the record began; every merge that reads after it is re-run from the record.**
- A cancelled merge: "Cancelled by ..." (a person cancelled a job that had not started) stored nothing, and is
  replayed as nothing. The job's own "Cancelled on request." can be before or after the tables and is case 5.
  Found by the reviewer by running: before this change such a re-run was not identical to its original.
- The rule reads the job's recorded error (step, message, detail), which is the orchestrator's own text
  (`core._error`); a change of those texts has to keep this in mind.
- If the one decoder changes what it reads, a `done` job's table could read differently later than at its run.
  That is a property of replaying from bytes with today's reader, as before this change; a record of what each
  merge stored (the site and the table's hash, per job) would end it.

## Not decided here

- Recording, at the merge, which tables it stored (see above): it would make case 5 answerable and remove the
  dependence on the reader.
