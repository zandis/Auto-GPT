# D-800 An erase is ledgered before the import

- **Task:** NEW-EDC-8c (D-691's known limit: "erase hidden values" wrote no attempt line)
- **PR:** this branch (`agent/NEW-EDC-8c-erase-attempt`), cut from NEW-EDC-5b (#636), the EDC chain's head
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-691 (the attempt ledger), D-692 (`refused`), D-690 (a repeat instance judged on TrialBox's own
  writes), D-414 (erase hidden values)
- **Number:** lane E's block (renumbered from D-614, lane W's block)

## Context

"Erase hidden values" wrote its ledger line only after REDCap's answer. An erase that REDCap applied with its answer
lost left no line at all: the trail could not say TrialBox had asked REDCap to blank the field. Shown by tests before
the change.

## Decision

1. **An erase writes an `attempt` line (a blank value) per field before the import**, as the send does (D-691), with
   the person and the time.
2. **A refused erase** (REDCap answered no, D-692) gets a `refused` line per field: nothing was erased.
3. **A lost erase is never booked as TrialBox's.** REDCap blank afterwards may be TrialBox's erase or a person who
   cleared the field: TrialBox cannot tell them apart (the ambiguity D-691 point 5 fails closed on). So nothing books
   it: on a repeat instance the instance stays held (D-690) and a reconcile lists the change (D-695), for a person to
   look at; the trail shows the attempt.
4. **An erase attempt is never a landed write** (D-691 point 3): only an attempt of a value that REDCap reads back
   equal is taken as TrialBox's write. A blank attempt read back blank made the send book a `sent` line with a blank
   value and set the draft's sent value to blank (found by the review).

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| Booking a lost erase on a later read booked a person's clearing as TrialBox's erase, and the send then wrote into a person's instance | high | fixed, test first: nothing is booked (point 3) |
| The same booking put a wrong person and time in the trail | medium | fixed with it |
| A blank attempt read back blank was taken as a landed write: a `sent` line with a blank value, the draft's sent value set to blank | medium | fixed, test first (point 4) |
| The first test's second send had nothing to send | low | rewritten |
| The erase's audit line names only the refusal's code | low | kept: the attempt lines are in the ledger |

## Evidence

`tests/unit/test_edc_erase_attempt.py`: an erase is in the ledger before REDCap answers; a lost erase is never booked
(the next send and a reconcile write no `erased` line, and the change is listed); an erase attempt is never taken for
a landed write (no blank `sent` line, the draft's sent value kept, the instance held); a refused erase is ledgered
`refused`. The first and the last failed before the change; the review's two failed before its fixes.
