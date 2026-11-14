# D-693 A value TrialBox found already there is not TrialBox's

- **Task:** NEW-EDC-8b (deep-review finding EDC-012, Medium, assigned by the review to the NEW-EDC-8 change; found
  on the way to be worse: "erase hidden values" erased a person's value)
- **PR:** this branch (`agent/NEW-EDC-8b-own-only-what-was-sent`), cut from NEW-EDC-7 (#606): the same function
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-690 (`last_written`: TrialBox's own writes), D-691, the send's rule that it never overwrites a value
  someone else wrote in REDCap (E-06, D-160), T-302b's "erase hidden values" (D-414)

## Context

`last_sent` counted an `already_there` line as TrialBox's write. A value a person typed in REDCap that happened to
equal TrialBox's was then TrialBox's from that send on. Three paths read it:

- the send: a later correction in TrialBox overwrote the person's value with no conflict line (review case 1c);
- "erase hidden values": the person's value, hidden by REDCap's branching logic, was erased as TrialBox's own;
- the send's list of values REDCap hides marked the person's value as TrialBox's.

Shown by tests before the change.

## Decision

1. **Who owns a value in REDCap is read from TrialBox's own writes only**: its last `sent` (written and read back)
   or `erased` line for the item (`last_written`, D-690). An `already_there` line is the person's value.
2. The send's conflict check, "erase hidden values" and the hidden-value list use it. After an `already_there`, a
   different value in REDCap, or a correction in TrialBox, is a conflict; the person's value is never erased.
3. `last_sent` had no other reader and is removed.
4. `already_there` still marks the draft as delivered (`sent_value`), so it is not sent again; that is unchanged.

## Known limits (fail safe)

- A value TrialBox delivered as `already_there` (a person had typed TrialBox's correction first) is the person's: a
  later correction is a conflict until someone looks in REDCap.
- Before D-691, a retried send whose first import landed with its answer lost was booked `already_there`. Those
  values were TrialBox's writes; they are now held on correction and kept by "erase hidden values".
- D-691's residual stays: an attempt that did not apply, then a person typing the very same value, is booked as
  TrialBox's write, so "erase hidden values" would erase it if REDCap later hides it.

## The adversarial review (by running)

Nothing serious. Its low findings are the known limits above. Also confirmed: a value erased, then retyped by a
person, then hidden again, is now kept (`last_sent` ignored `erased` lines and would have erased it); an erased
draft still counts as delivered when REDCap shows the field again (unchanged, older behaviour).

## Not in this card

- EDC-011 (a person saving between TrialBox's read and its import): REDCap's API has no conditional write; narrowed
  only, a later card.

## Evidence

`tests/unit/test_edc_own_only_what_was_sent.py`: case 1c (a correction holds as a conflict, the person's value
stays); erase hidden values keeps a person's value found already there; the hidden-value list does not call it
TrialBox's. All three failed before the change.
