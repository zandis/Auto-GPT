# D-670 A re-run of a merge reads the store's own record of what it stored

- **Task:** NEW-B-29 (the owner's ask that D-666's stated cost be remedied for good; lane A2 built the record,
  D-648; placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-29-rerun-reads-the-merges-store-record`), cut from lane A2's #508
  (`979f89d5`), which is stacked on #489
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-648 (the alliance store records each table it stores, and each merge's read, in the
  transaction that does it), D-666 (a replay gives what the first run gave, or says it cannot)

## Context

D-666 rebuilt the alliance tables of a merge's time from the earlier jobs' files and told what each earlier merge
had stored from how its job ended. Two costs, both stated or found since:

1. One merge stopped at a point nobody recorded made **every** later merge's re-run answer "cannot", for good.
2. A merge that was stopped and later run to its end reads as `done`, and was replayed whole, in job order,
   before the merges that had in fact read between its two runs. Confirmed by a test through `rerun()` on this
   card's base: the later merge's re-run published a table of a site its first run never saw.

D-648 gives the store a record: each table as it is stored (site, table, hash, order), and the point at which
each merge read the tables for its output.

## Decision

1. **`rerun()` asks the record once, for the merge being run again**: `cohort.replay_stored(orch.db, scratch,
   job_id)`. True: the scratch store holds the tables as the first run read them; the job is run on it.
2. **False (the merge has no recorded read) leaves D-666's way**, unchanged: `_replay_alliance_tables`, with its
   "cannot".
3. **`cohort.ReplayUnsure` and `cohort.RecordChanged` end the re-run like `ReplayUnknown`**: the scratch schema
   is dropped and the answer is `this job cannot be re-run: <the record's sentence>`. Unsure: between this
   merge's store of a site's table and its read, another job stored a table of the same site. Changed: a recorded
   table cannot be read or is not the table its hash was taken of.

4. **The scratch schema and the work folder go on every path**, also on an error nobody expected (one
   `finally` in `rerun()`). Before, a database error in the replay or an error in the run left the schema, and the
   work folder was never removed on any path.

## What is left of D-666's "cannot"

Of D-666's own: only a merge that **read before the record began** (a box updated in place, re-running a merge
from before the update). For such a merge the earlier jobs' endings are all there is, and an earlier merge
stopped at an unrecorded point still makes its re-run "cannot". No such job exists at a live site. Every merge
that reads after the update is re-run from the record, whatever happened to the merges before it: D-666's cost 1
no longer grows.

From the record itself (D-648's, in `scenarios/cohort.py`, lane A2's; found by this card's review by running, and
sent to the integrator, not changed here):

- **Unsure is asked per site, not per table.** Another job that stored a table of the same site for *another*
  quarter between this merge's store and its read makes the re-run "cannot", although the re-run's own store
  replaces only the merge's own (site, disease, quarter, definition) groups. On this card's base the same re-run
  was identical. Needs two jobs storing the same site's tables at the same time.
- **A merge that ended `done` through a race in its own check** (`merge_refusal` runs outside the store's lock:
  another sender stored the site between the check and the store) is re-run as `rerun failed: No valid alliance
  table ...`: the replay stores the other sender's table first, and the re-run's check then refuses. The first
  run's acceptance was the race; the re-run is the one that follows the rule.
- **A record that was changed** (`RecordChanged`).

## Tests

`tests/unit/test_rerun_reads_store_record.py`, through `rerun()` on a real orchestrator, job store and the real
COHORT scenario (lane A2's `_Box`): a later merge's re-run after a stopped merge that was then run to its end
gives the bytes of its first run, and so does the stopped merge's own re-run; a merge stopped for good at an
unrecorded point no longer makes a later merge's re-run "cannot"; an unsure record and a changed record are said
and the scratch schema is dropped; the record is asked once, for the merge being run again; a merge with no
recorded read is run again D-666's way, with its "cannot". Five of the six fail on the base. After the review:
the check for scratch schemas is itself checked (it sees one while a re-run runs; the first version looked for a
name the test run's prefix hides and proved nothing), and an error nobody expected at four places (the record,
the record after it stored a table, the old way, the run) leaves no scratch schema and no work folder. The test that goes
through every ending of a merge is lane A2's (`tests/unit/test_cohort_store_record.py`). No state change is
added: the re-run writes only its scratch schema and its work folder, and every path removes both.
