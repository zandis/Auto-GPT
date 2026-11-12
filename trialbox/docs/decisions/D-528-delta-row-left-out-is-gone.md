# D-528 On a delta night, a row the mapping now leaves out takes its earlier record with it

- **Task:** NEW-B-7 (a finding sent to the night and capacity lane on 2026-11-12, confirmed by running)
- **PR:** this branch (`agent/NEW-B-7-delta-row-left-out-is-gone`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** dataflow review P0-1 (a row deleted at the source is a tombstone), D-587 (a booking whose status
  the map does not know is left out and counted, never shown as booked), D-580 (the counter of unknown codes)

## Context

A delta night's snapshot is the snapshot of the night before with tonight's records written over it by id, minus
the tombstones (rows the source marked deleted). A resource of the mapping can have a `where`: a row that does not
pass it gives no record. When a row passed the `where` on an earlier night and does not tonight, nothing was
written for it and nothing was removed: the record of the night before stayed in the snapshot and in the lake until
the next full load. Run on train 4: a booking with status `B` on the full night; the next night its status is `Z`
(not in the map). D-587 says it is never shown as booked. The lake showed it as `booked`.

The same holds for every `where`: a height taken out of a vitals row, a lab row whose code left the look-up.

## Decision

1. **On a delta night, what a row of the feed gave before and does not give tonight is removed.** For every row
   that mapped, each `(type, id)` the row can give (`Mapper.tombstones`: the mapping's own ids, `where` not
   evaluated, never a Patient) that is not among the records the row gave tonight is a tombstone.
2. **A record sent in the same run wins over its tombstone** (`write_snapshot`, unchanged): two resources of one
   table that share an id and differ by their `where`, or a later row with the same key, are not removed.
3. **A full night is unchanged**: it has no night before to merge with, and no tombstone is written.
4. **A rejected row removes nothing** (STD-025, D-527): the box could not read it, so it does not know what the
   row gives; the record of the night before stays and the row is counted.

## Consequences

- `tombstones.json` and the night's `tombstoned` count now include records removed this way; the completeness
  gate already reads them as "removed on purpose".
- The rule is per row of the feed. A record whose id two **tables** share (one table makes it, another table's
  resource with a `where` has the same type and id) would be removed when the second table's row does not pass and
  the first table's row is not in tonight's delta. No shipped mapping does that (checked: `tw_core`, `jp_core`,
  `mimic`); `Mapper.tombstones` has had the same reach for deleted rows since P0-1.
- A person is never removed this way (the opt-out path's job).

## Not decided here

- Whether a row left out for an unknown code should hold the night above some share: D-580 counts them.
