# D-690 A repeat instance is written whole or not at all

- **Task:** NEW-EDC-2 (deep-review finding EDC-002, **Critical**: wrong safety data in the EDC of record)
- **PR:** this branch (`agent/NEW-EDC-2-repeat-instance-whole`)
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-414 (T-302b: arms, events and repeating instruments; a visit names one row), the send's rule that
  it never overwrites a value someone else wrote in REDCap (E-06, D-160)

## Context

On a repeating instrument the send judged each field alone. A person had entered instance 2 of the adverse-event
instrument (`ae_term = Rash`). TrialBox's own instance 2 held another event (`Headache`, serious, hospitalised). The
send listed a conflict on `ae_term` and still wrote `ae_serious = 1` and `ae_sae_reason = hospitalised` into the
person's instance, with a "sent, read back equal" line. A human-entered adverse event became serious with another
event's reason. The acceptance test of T-302b asserted exactly that outcome. Shown by tests before the change.

## Decision

1. **A repeat instance is one unit.** Every field that lives on a repeat instance the send touches is read: the
   repeating instrument's fields, or every instrument designated for a repeating event.
2. **An instance that holds, on any field a person can enter, something other than what TrialBox itself last
   wrote there is another person's entry or another event**: a value TrialBox never wrote, a value changed since,
   or a value of TrialBox's that a person cleared. "TrialBox wrote it" means its last `sent` (or `erased`) line for
   that field; an `already_there` line is not a write (the value was someone's before TrialBox came). A
   calculated or descriptive field is REDCap's own and is not judged. A ticked checkbox column counts as another's
   (TrialBox never writes a checkbox, EDC-003). The instance is judged once, on REDCap's rows as read, before any
   value is taken as already there.
3. **Every value of TrialBox's for such an instance is held**: the field that differs is a `conflict` as before,
   every other value is `instance_taken`, with the reason in the trail ("choose another instance"). Nothing is
   written into the instance, and it stays so on every later send until a person moves TrialBox's values to
   another instance.
4. **An empty instance, and one whose every value TrialBox wrote, are written as before.**
5. **A visit's base row is unchanged**: judged field by field, as the row is one subject's visit, not one of several
   events.
6. The preview says when every value of a visit would be held (`instance_taken: true`).
7. The console names the new result in its three languages (`edc.result.instance_taken`) and its send page counts
   every result of the send (`console/edc_pages.py` lacked the placement results too; lane C2's files).
8. **"Erase hidden values" is unchanged**: it erases only a field TrialBox wrote, whose value nobody changed, that
   REDCap now hides, and only on a person's explicit action. The instance rule is about TrialBox adding values to
   someone's instance; an erase of TrialBox's own stale value is REDCap's own hygiene (the review asked otherwise;
   kept, and pinned by a test).

## Not in this card

- Offering "the next free instance" (EDC-014): the person still types the visit; the reason says to choose another.
- A person saving a value between TrialBox's read and its import (EDC-011, narrow window): unchanged.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| A person's value equal to TrialBox's was taken as "already there" (TrialBox's), and TrialBox's other values went into the person's instance | high | fixed, test first: judged on TrialBox's own writes, before "already there" |
| A calculated field REDCap computed on TrialBox's instance held every later correction for good | high | fixed, test first: calculated and descriptive fields are not judged |
| A value of TrialBox's that a person cleared let TrialBox write into the instance again | medium | fixed, test first |
| `erase_hidden` erased on an instance a person had changed | medium | kept (point 8), pinned by a test |
| No test of TrialBox correcting its own instance | medium | added (with a calculated field) |
| The preview did not say every value would be held | low | fixed, test first |
| The console's send page did not count the result | low | fixed, test first |

## Evidence

`tests/unit/test_edc_repeat_instance_whole.py`: the review's case 8a (each failed before); a person's instance
holding only a field TrialBox has no value for (before: everything merged in, with no conflict at all); an empty
instance and TrialBox's own instance written; a base row still judged field by field. In
`tests/unit/test_edc_t302b.py` the acceptance round trip asserted the merge: it now asserts the instance is held,
and the "holding one value back hides another" case moved to a base row, with the repeat-instance case beside it.
