# D-529 A night dated after the site's today is refused

- **Task:** NEW-PERF-3 (deep review of 2026-11-12, PERF-009)
- **PR:** this branch (`agent/NEW-PERF-3-no-future-snapshot`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** DATA-007 (the box never moves back in time: a night older than the served one is built, not
  served), D-383 (a job pins the served snapshot and checks its age once), D-489 (T-723: a night that was built
  and not served is reported as not published)

## Context

PERF-009, run by the review: a night named `2027-01-01` was ingested and served. Every later night (`2026-10-07`,
`2026-10-08`) is older than it, so by DATA-007 it is never served; before T-723 each still reported `passed`. The
lake's age check read a snapshot dated after today as "0 days old", so the staleness limit never fired either. One
wrong date (a host clock wrong for one night, a re-run typed with a wrong date) made the box serve that night for
weeks with no sign.

T-723 (D-489), on master since train 3, closed one half: a night that is built and not served is "not published:
a newer night is already served", an error of the night. What was left is the cause.

## Decision

1. **The adapter refuses a night dated after the site's today** (`adapter.pipeline.refuse_future_night`), in the
   nightly ingest and in the first load, before a data-operations row, a folder or a lake build exists for it.
   "Today" is the site's (`TB_TZ`), read once at the start of the run, as the night's default name is.
2. **No day of grace.** The nightly names its snapshot after the site's today; a snapshot named by hand names a
   night that has happened. A box whose clock is behind refuses the night and says which date it believes: the
   clock is what must be corrected.
3. **The pin refuses a served night dated after today** (`lake.store.check_snapshot_age`): `LAKE-STALE`, with the
   reason, whatever `TB_LAKE_MAX_SNAPSHOT_AGE_DAYS` is (0 switches the age limit off; this is not an age). A box
   that already serves such a night builds no list from it.
4. **A snapshot whose name is not a date is not judged** (a tool's, a test's): it has no place in time. The lake
   itself does not refuse a future name: it has no clock of its own to trust over its caller's, and its callers
   are the adapter (point 1) and the site set-up, which rebuilds the served date.

5. **The publish refuses it too** (`adapter.publish.publish_night`): a steward's accept of a night held under a
   future name (left on disk from before this rule) ends "not published", nothing built or served.
6. **The refusal is recorded.** The ingest writes the audit event `ingest.failed` with `refused: future_night`
   and the reason, as a refused site key does; the command line prints the reason and ends with 2.
7. **A box whose day is pinned is not judged at the pin.** `TB_TODAY` (the test stack) pins the orchestrator's
   day behind the feed on purpose; there a served night after that day is 0 days old, as before.

## What this does not prevent

A host clock that is **ahead** names tonight's night after its own wrong today and accepts it: the adapter has no
second clock to ask. The night is served. When the clock is corrected the pin refuses it (point 3) and every later
night says "not published: a newer night is already served" (D-489): loud, and stuck. **There is no command that
takes one served night back** (the lake, the FHIR store, the OMOP store and the pid map all hold it); the runbook
says to restore from the last backup before that night. Such a command is a card of its own.

## Consequences

- A re-run with a mistyped future date ends at once with a plain message instead of being served.
- A box that already serves a future night stops building lists (`LAKE-STALE`) until the night is removed; nights
  ingested meanwhile say "not published: a newer night is already served" (D-489). Removing a served night is a
  runbook action, not built here.
- Tests that ingest under a date after the real today must give the run a date that has happened.

## Not decided here

- `trialbox doctor` and the health page naming a served night dated after today (PERF-009's last clause): the
  refusal at the pin and the night's own error say it; a doctor check is a small follow-up.
