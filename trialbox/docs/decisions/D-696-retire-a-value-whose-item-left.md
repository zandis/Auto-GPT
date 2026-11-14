# D-696 A value whose item an amendment removed is retired

- **Task:** NEW-EDC-6 (deep-review finding EDC-006, **High**: an amendment that removes a sent item blocks the
  study's ODM export for good)
- **PR:** this branch (`agent/NEW-EDC-6-retire-removed-item`), cut from NEW-EDC-5 (#624): the decision paths change
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-281 (signed values are locked), E-22 (never a silent gap in the copy of signed records), D-694

## Context

After a protocol amendment renamed or dropped a field that was signed and sent, the ODM export was refused
(`edc.odm_gap`); the value could not be rejected (`edc.sent`) nor edited (`edc.not_in_dictionary`). The site could no
longer produce its electronic copy of signed records (review case 13; shown by tests before the change).

## Decision

1. **A new decision, `retire`**, for a confirmed or changed value whose item left the study's map (an amendment is
   saved as a map; a dictionary gap alone may be a bad re-read: `edc.not_removed` otherwise). It needs a reason; a signed value needs the password again, as any
   change of a signed value (audited `unlocked`).
2. **The value and its signature are kept**: the draft's fate becomes `retired`, its value and the signature row are
   unchanged, and a `retire` line goes into the decisions. It is no longer signed-and-current, so it is not sent,
   not offered for copying, and not in the ODM file.
3. **The export lists what it leaves out**: its audit line names each retired value (record, visit, item), so the
   gap is never silent (E-22).
4. An open draft of a removed item is already set aside by the map change (`edc.superseded`); nothing to retire.
5. **Retired is final while the item is out**: no confirm, edit, reject or keep on it (`edc.retired`). **When the item
   is in the study again**, the next draft run (or an ODM file carrying it) sets the retired value aside with a
   `reopened` line and drafts the item again, so it has one current draft (two would stop every send and export,
   `edc.duplicate`).
6. The copy-assist sheet does not count a retired value as waiting. The review page offers "Retire" for such a value (with a reason and, signed, the password); the fate and the
   decision are named in three languages (lane C2's files).

## Not in this card

- Writing a retired value into the ODM file under the dictionary version it was signed under (the review's other
  option): left out and listed instead, which keeps one dictionary per file.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| An item back in the map: a second current draft beside the retired one stopped every send and export (`edc.duplicate`) | high | fixed, test first (point 5) |
| The ODM import had the same hole | medium | fixed (point 5) |
| A retired value could still be rejected (with no reason when unsigned) or edited | medium | fixed, test first: `edc.retired`; the review page hides the actions |
| Retire allowed during a dictionary gap with the item still mapped | low | fixed, test first: the map says |
| Copy-assist counted a retired value as waiting | low | fixed, test first |
| `FATES` did not list `retired` | low | fixed |

## Evidence

`tests/unit/test_edc_retire_removed_item.py`: case 13 (refused, then retired with the password and a reason, the
export works and lists it, the trail keeps the decision); a value still in the study is not retired; an open draft is
already set aside; a retired value is not sent, not copied, not retired twice; the review page and the three
languages; the review's four cases. The first five failed before the change; the review's failed before its fixes.
