# D-548 The opt-out desk takes a chart number typed in full-width characters

- **Task:** NEW-DIN-3d (left open by D-546; the integrator's word of 2026-11-13: one small commit after train 5)
- **PR:** this branch (`agent/NEW-DIN-3d-desk-full-width-digits`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-301 (`tb_common.chartno`), D-544 (the desk asks the box whether it knows the patient), D-546

## The problem

The desk checks the shape of a typed chart number (letters, digits or `-`) before it asks the box. The check ran
on the text as typed, so full-width digits and letters were refused with "chart numbers are letters, digits or
'-'", although the box writes them half-width before it hashes. A keeper with a Japanese or Chinese input method
on types them without noticing.

## The decision

`console.team.to_pid` writes the typed number half-width and without the blanks around it
(`chartno.normalise("asis", ...)`: no padding, no change of case; the site's rule stays the box's) and asks the
shape of that. That text is what goes to the box. What is not a chart number after it is refused as before, and
before the box is asked: other signs, a blank inside, other scripts; and a whole pseudonym, also typed
full-width, is still "a pseudonym, not a chart number".

## What it does not do

- It changes no pseudonym: the box normalised a full-width number the same way; the desk only stopped refusing it.
- The desk does not apply the site's rule (width, leading zeros, case): one place does, the box.

## Reuse check

`tb_common.chartno.normalise` covers it: one call.

## Dropped (D-311)

No sign-off step.
