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
2. **An instance that holds, on any of its fields, a value TrialBox did not write there is another person's entry
   or another event.** "TrialBox wrote it" means the field's last `sent` value, in REDCap's form, equals what REDCap
   holds. A ticked checkbox column counts as another's (TrialBox never writes a checkbox, EDC-003).
3. **Every value of TrialBox's for such an instance is held**: the field that differs is a `conflict` as before,
   every other value is `instance_taken`, with the reason in the trail ("choose another instance"). Nothing is
   written into the instance, and it stays so on every later send until a person moves TrialBox's values to
   another instance.
4. **An empty instance, and one whose every value TrialBox wrote, are written as before.**
5. **A visit's base row is unchanged**: judged field by field, as the row is one subject's visit, not one of several
   events.
6. The console names the new result in its three languages (`edc.result.instance_taken`; lane C2's file).

## Not in this card

- Offering "the next free instance" (EDC-014): the person still types the visit; the reason says to choose another.
- A person saving a value between TrialBox's read and its import (EDC-011, narrow window): unchanged.

## Evidence

`tests/unit/test_edc_repeat_instance_whole.py`: the review's case 8a (each failed before); a person's instance
holding only a field TrialBox has no value for (before: everything merged in, with no conflict at all); an empty
instance and TrialBox's own instance written; a base row still judged field by field. In
`tests/unit/test_edc_t302b.py` the acceptance round trip asserted the merge: it now asserts the instance is held,
and the "holding one value back hides another" case moved to a base row, with the repeat-instance case beside it.
