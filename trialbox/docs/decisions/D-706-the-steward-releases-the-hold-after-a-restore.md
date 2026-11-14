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

- **The steward can also set the flag to `held`, at any time**, not only after a restore: the same form. That
  stops the box's lists until somebody releases them. It is audited under the steward's name and it is the safe
  direction, but it is a new stop lever for a role that is not the IT operator. Accept, or limit the steward to
  `released`: the owner's to say.
- **The page does not show what must be re-applied before a release.** It shows the restore's reason and the
  flag's description; the events are in the audit trail (`backup.restore_reapply`), which the steward's menu has,
  and the runbook says so. Nothing checks that they were re-applied, which was so for the administrator too.
  Whether the page should link that event, or a release should require it, is the owner's to say.

## What the adversarial review changed

One review by a fresh reviewer, who tried as the steward to read or change any other flag (another name, an
undeclared one, an empty one, two names, other spellings, the confirmation sheet, the query string) and found no
way; a refusal comes before the page says whether a flag of that name exists. Verdict: fix first, small.

- **No test posted the hold's own name as an account without the right**, so a gate that let anybody release it
  would have passed. A coordinator, an investigator, the privacy office and a viewer are refused now, by test,
  and the flag stays held.
- **Two texts still sent a blocked person to the administrator only**: the message of every held list job and
  the runbook's step. Both name the data steward too.
- The refusal's audit event says which flag was tried.
- By reading: the steward's own audit page shows other flags' changes with their reasons (it did before this
  card). So "no other flag is listed" is true of the flags page; what this card holds for other flags is that the
  steward cannot change them.

## What it does not do

- The list of events to re-apply is in the restore's report and its audit event; the page does not show it as a
  list (D-522 left that too; it is not this card).
- The steward can set the flag to `held` as well as to `released`: the same form. Holding the lists is the safe
  direction.

## Reuse check

The flags page, the matrix and the confirmation sheet, as they are; nothing is added.

## Dropped (D-311)

No sign-off step.
