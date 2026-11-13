# D-538 After an outage of the reference data, the next delta night reads that table whole

- **Task:** NEW-B-18 (D-530's "not decided here": a full load started by the box itself after an outage)
- **PR:** this branch (`agent/NEW-B-18-full-load-after-refdata-outage`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-530 (an outage does not hold the night; the night says what it could not map), D-593 (the
  counter's `<map>:unavailable`), D-580 (`unmapped_codes.json`), D-271 (the night a delta merges over)

## Context

When the reference data does not answer during a night, a row keeps its source code only and is counted under
`<map>:unavailable` (D-593, D-530). A delta night reads only rows that changed, so such a row kept its unmapped
code until it changed at the source or a person ran a full load. Nobody is told to do that anywhere but in a log
line, and a criterion on the mapped code answers "unknown" for those patients until then.

## Decision

1. **A delta night reads whole every table for which the reference data did not answer on the night it merges
   over** (`adapter.pipeline.reread_whole`). The night merged over is D-271's (`merge_base`: the newest earlier
   night that passed); what it could not ask is in its own `unmapped_codes.json`. The table is read as on a full
   night (no "since"); every other table is read as a delta, and the snapshot is merged as on any delta night.
2. **Nothing new is kept.** The answer is read from the night merged over each time. A night that reads the
   table whole while the reference data answers counts nothing under `:unavailable`, so the night after is a
   delta again. While the outage lasts, the table is read whole every delta night.
3. **The night says it**: one log line per table, with the table and the night that said so; never a code.
4. A `unmapped_codes.json` that cannot be read asks for nothing: the night goes on as a delta.

## Consequences

- A delta night after an outage costs a whole read of each table the outage touched (one table for the ICD-9-CM
  map: diagnosis), every night until the reference data answers. The rows go to disk as they are read (T-692),
  so memory does not grow with the table; with the data contracts on (`TB_DATA_CONTRACTS`) the table's raw rows
  are held in memory, as on a full night. A database that is configured and never answers means a whole read
  every delta night for as long as that lasts.
- A held night is not merged over, so it is not asked: the next night asks the last night that passed, which is
  the night whose records are in the lake.
- **Only what the source can give again is healed.** The CSV, `cgrd_sql` and SS-MIX2 sources filter by "since"
  themselves and give every row they hold when it is not set (read in their code). A feed whose files hold only
  the changed rows has nothing more to give: for it D-530's line still stands and a person runs the full load. A
  FHIR bulk export does not go through the mapper, so it has no such rows.
- On that night the table's row count in the night's facts is the whole table's, not a delta's. The completeness
  gate does not judge row counts on a delta night, so it is not affected.
- **The outage night's log line changes**: it said the codes "stay so until the row is sent again or the next
  full load"; it now says the next delta night reads the table whole (the expected sentence of NEW-B-8's wording
  test is changed with it: the old sentence is no longer true).
- **The back-fill's file asks too.** The back-fill writes the same `unmapped_codes.json` with the same keys, so
  the first delta night after a first load that met an outage reads those tables whole. Where the nightly source
  holds less than the history that was loaded, that read heals only what the source holds, writes a clean file,
  and the older history rows stay unmapped with nothing saying so any more: there a person loads the history
  again.
- Rows the healing night sets aside (a contract's quarantine, a row the mapper rejects) are not mapped that
  night and are not asked for again.
- Rows that are no longer at the source are not removed by this read: the night is still a delta night
  (deletions come by the source's own marks, as before).

## Not decided here

- Telling a person when an outage has lasted several nights (D-530: the doctor check of the reference data).
- A back-fill that heals its own history after an outage (see the consequence above).
