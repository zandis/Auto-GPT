# D-691 The attempt is ledgered before the import

- **Task:** NEW-EDC-8 (deep-review finding EDC-008, **High**: an audit gap on what is written to the EDC of record)
- **PR:** this branch (`agent/NEW-EDC-8-attempt-ledger`), cut from NEW-EDC-2 (D-690, #597): the same function
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-690 (a repeat instance is judged on TrialBox's own writes), the append-only `sent` table (EDC-009,
  D-582), the send's read-back (E-06, D-160)

## Context

The send wrote its ledger lines (`sent`) only after REDCap answered the import and the values were read back. When
REDCap applied the import and the answer never came back (a read timeout, the rate limit met on the read-back), the
ledger held nothing for those values and the audit line said "refused". The next send found the values in REDCap
and booked them `already_there` under whoever retried: the trail could not say who wrote the value into the EDC of
record, nor when. With D-690 it was worse on a repeat instance: a value with no `sent` line is "someone else's", so
TrialBox's own instance was held for good. Shown by tests before the change.

## Decision

1. **Before each import, one `attempt` line per value about to be written**, with the person and the time of the
   send. The `sent` table is append-only, so an attempt is never removed; it is closed by a later line.
2. **An attempt is open** while the item has no later line that read REDCap back (`sent`, `readback`, `erased`,
   `already_there`, `conflict`, `instance_taken`). A line that never read REDCap (opted out, no record, hidden,
   changed) leaves it open.
3. **On a later send, an open attempt whose value REDCap holds is TrialBox's write**: it is booked `sent` under the
   person and time of the attempt (when REDCap took it), and the line names who read it back, and when. It is not
   `already_there`, and it is not a value TrialBox did not write.
4. **An open attempt REDCap does not hold** (the import was refused before it applied) is written again by the new
   send, under its own person, as before.
5. **If the value was changed in TrialBox since** (re-authenticated, corrected, signed again) and REDCap holds the
   attempt's value, TrialBox cannot tell its own lost write from a person's equal entry typed after a "refused":
   it is a `conflict`, never overwritten, and not booked as TrialBox's write (a repeat instance is held whole). A
   person looks at REDCap. The value that did not change is booked as in point 3.
6. **D-690**: a repeat instance's field holding the value of an open attempt counts as TrialBox's write. When the
   instance is held all the same (a person changed another field since), each landed attempt is still booked
   under its writer before the held line.
7. The `sent` line of a landed attempt names the attempt's draft; the draft signed again since with the same value
   gets an `already_there` line.
8. The refused send's audit line counts the attempts (`attempted`). The console's trail names the new line in its
   three languages (`edc.result.attempt`; lane C2's file).

## Known limits

- A refused import that did not apply, then a person typing the very same value into REDCap before the next send
  with the value unchanged in TrialBox, is booked as TrialBox's write of that attempt. The value is the one
  TrialBox signed; only the hand that put it there cannot be told apart. A person's equal value with no attempt is
  `already_there`, as before (pinned by a test).
- An attempt stays open until a line reads the item back; lines that never read REDCap do not close it. With point 5
  failing closed, the open window can no longer overwrite; on a repeat instance, a person filling a field with an
  old refused attempt's value makes that field count as TrialBox's (the same limit as the first).
- "Erase hidden values" writes no attempt line: an erase that applies and whose answer is lost leaves the item as
  TrialBox last wrote it, and its instance held until a person looks (fail closed). Not in this card.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| A refused attempt left open, a person's equal entry, a correction in TrialBox: the person's value was booked as TrialBox's and overwritten | high | fixed, test first: point 5 holds it as a conflict |
| A landed attempt on an instance a person changed since was closed by `instance_taken` without being booked | medium | fixed, test first: point 6 |
| A landed attempt for an earlier draft was booked under the current draft | low | fixed: point 7 |
| Attempts never expire | low | kept, harmless with point 5 (known limits) |
| `erase_hidden` writes no attempt | low | not in this card (known limits) |

## Evidence

`tests/unit/test_edc_attempt_ledger.py`: the import applied and the answer lost (review case 5a); the import applied
and the read-back refused (case 12); a lost answer on a repeat instance (held for good before, with D-690); a value
changed after a lost answer, held as a conflict; the review's two findings (a person's value equal to a refused
attempt never overwritten; a landed attempt booked on an instance held since); and, unchanged, a refused import
written again by the next person and a person's equal value still `already_there`. The first four failed before
the change; the review's two failed before its fixes.
