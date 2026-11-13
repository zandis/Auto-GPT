# D-660 A first load that met an outage of the reference data is held

- **Task:** NEW-B-19 (a finding of the review of NEW-B-18 / D-538, placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-19-backfill-outage-is-held`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-530 (a night is not held for an outage of the reference data), D-538 (the next delta night
  reads that table whole), D-535 (the first load's gate before it publishes; a held load reads its source again),
  D-593 (`<map>:unavailable`)

## Context

The back-fill (the first load of a hospital's history) gives the mapper the same reference data as a night
(D-593) and writes the same `unmapped_codes.json`. When the reference data does not answer during a first load,
the history's rows keep their source codes only.

For a night that is accepted (D-530) because it heals: the next delta night reads the table whole (D-538). For
the history it does not. The history is read once; the nightly source often holds less than the history that was
loaded; and the first delta night after the load, reading the table whole from the nightly source with the
reference data answering, writes a clean count over the one file that said the history was unmapped. From then on
a criterion on the mapped code answers "unknown" for those patients' history, and nothing says so.

D-530's reason for not holding (a hold withholds new results, bookings and withdrawals of consent for one code
system's sake) does not apply: a first load is started by a person, nothing is served from it yet, and running
it again costs time only.

## Decision

1. **A first load whose rows met an outage of the reference data is held before anything is published**
   (`adapter.backfill`, beside D-535's completeness gate). The reason names the table, the map and the count,
   never a code, and says what to do: run the back-fill again when the reference data answers.
2. **Run again, the source is read again.** The kept spool is of the same source and mapping (its fingerprint
   matches) and holds the rows without their codes: reused, the load would be held for ever. As for D-535's
   incomplete tables, a kept spool that met an outage is not reused.
3. **Only "could not be asked" holds.** A code the reference data has no entry for is counted (D-580) and
   published, as before. No database configured is "nothing to ask" (D-593), not an outage.

## Consequences

- A first load during an outage costs a second read of the source, once the reference data answers. While the
  outage lasts, every run reads the source and is held.
- A partial publish (the newest years first) happens only without errors, so nothing of a load that met an
  outage is served.
- A back-fill that is run on a box that already serves nights (to bring older history) is held the same way: its
  rows would be published once as well.
- **There is no override and no other way through**: the reference data has to answer. The reference data lives
  in the box's own database, which a back-fill needs anyway (the pid map), so "no database configured" (D-593's
  "nothing to ask") cannot be a back-fill's state.
- **A short outage holds the whole load.** After a failed question the reference data is not asked again for a
  minute (`tb_common.refdata`), and every row in that minute counts. The load is run again; the source is read
  again.
- A held load still sorts its years before it stops, and the next run sorts them again (as a load held by the
  completeness gate does).
- On a box that already serves an earlier, partial publish of the load, that publish stays served while the
  load is held.

## Not decided here

- Telling a person that the reference data is down before a long first load starts (a check at the start would
  save the read; the doctor check of the reference data is lane D's).
- **A first load started before the reference pack is loaded** is published, with the same lasting gap: the
  reference data answers "no entry" for every code, which is counted (D-580), not held (point 3). Run by the
  reviewer: published, 3 rows counted. A check at the start of a load that the maps the mapping names are there
  would close it; it needs to know which maps a mapping asks for (the mapping lane's).
