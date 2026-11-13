# D-706 The data steward sees and releases the hold after a restore

- **Task:** NEW-FLAG-1 (the item D-522 left to the console: "who may release")
- **PR:** this branch (`agent/NEW-FLAG-1-screening-after-restore`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-522 (a restore that is not complete holds the box's lists by the flag
  `screening.after_restore`), D-455 (a steward re-applies what a restore lost), D-207 (`/ops/flags`), D-380 (the
  steward keeps the opt-out register)

## The problem

After a restore that is not complete the box makes no patient list until a person releases the hold, on
`/ops/flags`, with a reason, once the events recorded after the backup (opt-outs, erasures, consent changes) were
re-applied. `/ops/flags` was the administrator's page alone. D-455 names the data steward as the person who
re-applies those events, and the steward keeps the opt-out register; so the person who knows whether the hold can
be released could not release it, and the person who could (the IT administrator) is not the one who knows.

## The decision

- A row of the permission matrix, **`restore.release`**: the administrator (as before) and the data steward.
- **An account with that row that is not an administrator sees `/ops/flags` as this one flag's page**: its
  value, when and by whom and why it last changed, its own history, and the change form. No other flag is listed
  or named; a change of any other flag is refused (403) and the refusal is audited (`console.denied`).
- A change is what it was: a reason, one confirmation sheet, one `flag.set` audit event with the steward's own
  account as the actor.
- The steward's menu has the page ("Hold after a restore"), in three languages; the role descriptions say the
  right.

## Open with the owner

- **Should the administrator keep the right?** The administrator can change every flag today, this one too, and
  this card takes nothing away. D-455 names the steward only. Leaving the release to the steward alone would be a
  cell of the matrix to change (`restore.release`, administrator: false) and a special case on the flags page;
  it is the owner's to say. Sent to the integrator.
- The privacy office keeps the opt-out register too (D-380) and does not get the right here: D-455 names the
  steward.

## What it does not do

- The list of events to re-apply is in the restore's report and its audit event; the page does not show it as a
  list (D-522 left that too; it is not this card).
- The steward can set the flag to `held` as well as to `released`: the same form. Holding the lists is the safe
  direction.

## Reuse check

The flags page, the matrix and the confirmation sheet, as they are; nothing is added.

## Dropped (D-311)

No sign-off step.
