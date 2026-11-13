# D-661 The box keeps how long its nights took, where the host's doctor can read it

- **Task:** NEW-B-20 (asked by lane W for the doctor line `update_window`, D-606; placed by the integrator on
  2026-11-13)
- **PR:** this branch (`agent/NEW-B-20-night-length-record`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-606 (the Windows update window is placed outside the night "from the night's measured
  length"; until a record exists its line is WARN), T-723 / D-489 (the publish record's step times), D-274 (the
  host's nightly backup and the box's records under `deploy/site`)

## Context

The doctor's `update_window` check runs on the host inside WSL2: standard library only, no docker call, no
database. It sees the deploy folder. What the box knew about a night's length was in places it cannot reach (the
night's batch row in the database; the publish record in the lake's volume), and nowhere as one start and one
end. The adapter's container has no writable host folder: its lake is a docker volume.

## Decision

1. **The adapter records each night in its lake**: `<lake>/night_runs.json` (`adapter.night_runs`), written when
   the night's run ends: the snapshot's date, the run's start and end in the site's time with its offset,
   `finished` (the night ended published: the whole of a night), and when each publish step ended. Times and
   step names only: no patient data.
2. **How many nights are kept is the lake's own retention**, not a new number: an entry goes when its snapshot
   is no longer in the lake.
3. **The first finished run of a night is the night's measure and stays.** A night run again (a steward's re-run
   by day, a held re-run of the served night) does not replace it: a daytime interval, or "not finished", in the
   place of the night's own times would move the update window. An entry that is not finished is replaced by the
   next run, and each entry says which run of the night it was (`run`). The reader gives only nights that
   finished on their first run: a night that was held and passed when run again measures the re-run.
4. **The host's nightly backup copies the file** to `deploy/site/night-length.json`
   (`backup_schedule.copy_night_length`, at the start of every backup run): it already runs on the host, as
   root, every night, and reads the volumes there. A host that cannot read the volume, or a box that has not run
   a night, leaves the earlier copy as it was; the backup goes on either way. The copy is readable by every user
   of the host (0644: times only), because the doctor may run as the host's user.
5. **`tools.night_length.night_runs(deploy)`** (standard library only) reads the copy: the finished nights,
   oldest first, each `{"start", "end"}`. **An empty list means "not measured"**, never "no time": a file that
   is missing or cannot be used, or holds no finished night. An entry without an offset or with its end before
   its start is left out.
6. **Nothing here can fail a night or a backup.** A record that cannot be written, a damaged record, a publish
   record of an unexpected shape: the night goes on and the log says the length was not recorded. A file in the
   volume that cannot be read or is not a record of nights is not copied over a good copy; the backup goes on and
   the nightly run prints why.

## Consequences

- The copy the doctor reads is as old as the last backup run: a night that ends after the nightly backup is seen
  the next day. For placing a weekly update window that is enough.
- The end of a night is the end of its run in the adapter (ingest, validation, and the publish steps the run
  made: pid map, OMOP, the FHIR store, the lake). What the orchestrator does after the night (derive, twins,
  screening jobs) is not in it. A held night that a steward accepts later is recorded by its own run as not
  finished; the accept's publish is not added to it.
- A night run by a tool without the lake or FHIR steps is recorded with what ran; on a box the night runs with
  both.
- A run that ends in an error before its report (the night failed, not held) writes no entry; the back-fill
  writes none (it is not a night); a steward's accept of a held night writes none, so that night stays "not
  finished".
- The file in the lake is in every backup (the lake's root is taken); the copy is in the backup's host part
  (`deploy/site`).
- A cluster (`doctor --platform`) has no host backup run: nothing copies the file there, and the reader answers
  "not measured".

## Not decided here

- The length of what follows the night in the orchestrator, if the update window must stay clear of that too.
- Showing the nights' lengths on the console's data-operations page.
