# D-842 A checkbox is written to REDCap one column per choice

- **Task:** NEW-EDC-3b (deep-review finding EDC-003, second half; the first half held the item at send)
- **PR:** this branch (`agent/NEW-EDC-3b-checkbox-columns`), cut from NEW-EDC-5c (#647)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-414 (branching logic and calculated fields on the row), D-584 (the local REDCap test instance and
  its list of where the simulator is laxer than REDCap), D-690, D-693 (who owns a value), D-800 (an erase attempt)

## Context

REDCap's flat import and export carry a checkbox `x` as one column per choice, `x___<code>`, `1` ticked and `0` not.
A bare `x` column makes REDCap refuse the whole import. The first half of EDC-003 held a signed checkbox item at send
(`format`, "a checkbox item is not sent yet"). The simulator took the bare column and refused the `___` columns, so
no test could see the real shape. The REDCap stand-in run listed R2 (checkbox) and R6 (logic) as places the simulator
was laxer than REDCap.

## Decision

1. **The send writes a checkbox as its choices' columns, named as REDCap names them**: `field___` and the code
   lowercased, `-` and `.` written `_` (`Unknown, -99` is `field____99`; `forms.checkbox_column`, one helper for the
   send, the read, the ODM files and the datacore export). Never a bare column. The `format` hold is removed.
2. **`1` for each code chosen, `0` only for a code REDCap held ticked when the row was read**; a code neither chosen
   nor held is not written. A box a person ticks between the read and the import stays, and the read-back differs:
   never booked `sent`.
3. **An erase ("erase hidden values") writes `0` for each code held**, never blanks: REDCap reads `0` as unticked
   whatever the overwrite setting. It is read back blank before it is booked `erased`; one that does not read back
   blank is not in the call's `erased` list but in `kept` (`erase_did_not_read_back`), and its ledger line says
   `readback`.
4. **What REDCap holds for a checkbox is the codes ticked, in the field's choice order** (`Rows.held`), read from the
   `___` columns. The send's conflict check, the read-back, "erase hidden values" and the check that a row holds
   nothing TrialBox did not write judge it as any other value: a box a person ticked or unticked is a change in
   REDCap, never overwritten.
5. **Branching logic reads a checkbox as the send lays it**, else as REDCap holds it (`[x(2)]`): a tick the send is
   clearing no longer shows a field the row will hide.
6. **TrialBox's value of a checkbox is its codes once each, in choice order** (`redcap_value`), so `3,1` and `1,3` are
   one value.
7. **The simulator is as strict as REDCap here**: it refuses a bare checkbox column, a `___` column with a code the
   field has no choice for (named as REDCap names it), and a value other than `1`, `0` or blank; it exports the
   `___` columns, and an ODM `x___code` item stays its own column. The stand-in's expected failures drop R2 and R6;
   R6 now compares each expression, with TrialBox's own logic standing in for REDCap's until a real instance runs it.
8. **The signed values' ODM file writes a checkbox as one boolean item per choice** (`ItemDef`, `ItemRef` and
   `ItemData`, each with the value's audit record and signature): REDCap refused the one bare item, and the whole
   file with it.

## Known limits

- A code the dictionary no longer has is not written; the dictionary-changed hold (the item's dictionary entry changed
  since it was signed) holds such a value first.
- REDCap's naming of a choice's column is from REDCap's own code as recalled, not yet from a run. R2 on our instance
  now writes and reads back the column of a `-99` choice (`joints____99`), so the first real run settles it. Until
  then, a different naming fails closed for TrialBox's writes (REDCap refuses the column), but a person's tick under
  another name would read as unticked.
- A box a person unticks between the read and the import, on a code TrialBox is writing `1`, is ticked again, as a
  scalar value typed in that moment would be overwritten; the read-back then equals TrialBox's value.
- R6 passing on the simulator says nothing about REDCap's own calculations: the simulator computes with TrialBox's
  logic. Only a run against a real instance compares them.

## The adversarial review (by running)

A fresh reviewer probed choice order, duplicates, spaces and unknown codes, a changed dictionary, a lost answer
followed by a person's tick, an extra tick after a send, the read-back and branching logic: each held. It found:

- **F1 (High if REDCap behaves so):** REDCap names a choice's column from the formatted code; TrialBox and the
  simulator used the raw code, so a person's `-99` tick read as unticked (an instance a person filled only so would
  read as untouched, and `_not_ours` would let TrialBox merge into it). Fixed (points 1 and 7); tests with `A`, `-99`
  and `1.5`, and the simulator with a negative and a letter code.
- **F2 (Medium):** `0` for every other code unticked a box a person ticked between the read and the import, and the
  read-back then matched: booked `sent`. The same on the erase. Fixed (points 2 and 3), each shown by a test that
  ticks the box inside the import.
- **F3 (Medium, fails closed):** the signed values' ODM file wrote one bare item; REDCap refuses it. Fixed (point 8).

Each fix was shown failing first (7 tests), then passing.
