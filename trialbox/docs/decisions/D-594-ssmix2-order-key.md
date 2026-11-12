# D-594 Whether an SS-MIX2 order number is used again on another day is declared by the site, and counted either way

- **Task:** NEW-DIN-4 (finding DIN-004 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan v7.2 section 5, lane E, wave 2)
- **PR:** this branch (`agent/NEW-DIN-4-ssmix2-key-with-day`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-615a (the SS-MIX2 reader on what vendor files hold), dataflow review P0-1 (a delete at the
  hospital is a tombstone)

## Context

The reader chose the current version of a stored file per (patient, type, order number), whatever the day folder.
The finding: a hospital whose order numbers repeat (per day, per year) loses the earlier order when the number
comes back. The first repair of this card put the day in the key. Its review showed the other half: a vendor that
files an amendment, a late result or a delete under the day it was sent, not the order's day, then gets two
records, a record that cannot be deleted, and a stale version winning. The standard keeps an order under its day
of care; nobody has seen the Japan site's storage. The two faults cannot both be excluded by one fixed rule.

## Decision

1. **The site declares it**: `TB_SSMIX2_ORDER_NUMBERS`.
   - `unique` (the default, the behaviour until now): one order number of a patient and type is one record
     whatever its day folder; the newest version wins, a delete removes it. Right for a storage that never
     reuses a number; tolerant of amendments filed under another day.
   - `per_day`: the day folder is part of the key. An order number used again on another day is another
     order. Right for a storage whose numbers repeat; it requires what the standard says, that every version of
     one order (amendment, delete) is filed under the order's own day.
2. **Counted either way**, so the site check shows which storage it is before anybody decides:
   `<type>:order number on several days` in the reader's statistics (`reader.json`), once per patient, type and
   order number, over live versions of the record types only (not the change messages, which name an earlier
   order on a later day by design).
3. **Ids in `per_day`**: a lab result with no id of its own always carries its day (`O1@20261015-1`), on
   the first day too, so an id never changes meaning when an earlier or later day's file appears. Changing the
   setting is therefore a one-time new set of ids for such results: one full load.
4. Nothing is detected from the storage: a count is shown, a person sets the key.

## Not in this card

- Telling "the same order amended" from "the number used again" by the content of the messages (OBR-2/3, OBR-7):
  possible for labs only, and wrong the day a vendor differs. Not done.
- Prescriptions and diagnoses take their row keys from the message (ORC-2, PRB-4): in `per_day` two orders
  with one number are both read and still merged by that key further on; the count shows the case.
