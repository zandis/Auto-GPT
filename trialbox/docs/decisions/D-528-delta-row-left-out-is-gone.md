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

1. **On a delta night, what a row of the feed gave before and does not give tonight leaves the snapshot.** For
   every row that mapped, each `(type, id)` the row can give (`Mapper.tombstones`: the mapping's own ids, `where`
   not evaluated, never a Patient) that is not among the records the row gave tonight is left out
   (`write_snapshot(left_out=...)`).
2. **The last row of a key decides** (DATA-017). A later row of the same run that gives the record again keeps it;
   a later row that does not give it removes the record an earlier row of the run gave.
3. **It is not a tombstone.** The source did not delete the row. The ids are not written to `tombstones.json`, the
   night's `tombstoned` count does not include them, and the OMOP record event says "left the feed", not "deleted
   at the source". The night logs how many records left, per record type.
4. **A full night is unchanged**: it has no night before to merge with.
5. **A rejected row removes nothing** (STD-025, D-527): the box could not read it, so it does not know what the
   row gives; the record of the night before stays and the row is counted.

## Consequences

- The record goes everywhere the snapshot goes: the lake is built from the snapshot, the FHIR store deletes what
  the snapshot no longer has, OMOP tombstones what left its batch.
- The night's drop limit (feedguard) sees these removals: a night in which most bookings turn unknown is held
  ("removes Appointment: 200 of 200"), where before the records stayed, stale, and nothing was said.
- **Bound (OD-10):** the set of ids kept in memory during a delta night is at most (resources of the table that
  have a `where`) x (rows read tonight), each a 32-character id; it is linear in the night's rows, as the
  tombstone set is. Rows that never pass a `where` (a vitals row with no height) add an id every night that
  matches nothing.
- The rule is per row of the feed. A record whose id several rows or tables share (an `id` from a column that is
  not the row's key, or a second table's resource with the same type and id) is removed when tonight's row does
  not give it and the row that does is not in tonight's delta. No shipped mapping does that (checked by loading
  `tw_core/demo_his`, `jp_core/ssmix2_site` and the rehearsal sites: every resource with a `where` is keyed by its
  row); `Mapper.tombstones` has had the same reach for deleted rows since P0-1.
- A person is never removed this way (the opt-out path's job).

## Not decided here

- Whether a row left out for an unknown code should hold the night above some share: D-580 counts them.
