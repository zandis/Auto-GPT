# 25. Leavers

**Reader:** the box owner.

*T-635, D-390. What to close when a person leaves the trial team, hospital IT, the key stewards or Aimedics. Do it
on the last working day, not after.*

**Drill (T-213b):** `test_runbook_25_leaver` (in process: step 1 on **Users** and with `console.cli disable`; neither
account signs in after or is deleted; both are audited). Steps 2 to 5 and a key steward's leaving are not rehearsed.

## A member of the trial team (coordinator, investigator, PI)

1. The administrator disables the account on **Users** (`/ops/users`), or `console.cli disable NAME` (§3). Never delete
   it: the audit and the signatures name it.
2. With the hospital sign-in (§12), the hospital disables the directory account too; the box then refuses the sign-in,
   but disable the TrialBox account as well.
3. The PI ends the person's delegation-log entry: their EDC signing stops (D-281).
4. Mails: remove the person from any study's recipients; a list sent to them before stays in the audit.
5. Hand-over: their open review items stay in the study; the PI gives them to another person.

Leavers nobody reported (T-209c, D-406): every local account other than an administrator has an end date at most 365
days ahead (an empty one is set to that limit). **Unused accounts** (`/admin/accounts`, linked from the Accounts tile
of `/admin`) lists accounts not used for 60 days, ending within 14 days, or with no end date; the administrators'
health mail carries the same list every Monday. Disable each one that belongs to a leaver.

## The site administrator

Everything above, and:

1. A second administrator exists before the first leaves (§3). The new one signs in and checks the Operations page.
2. Rotate the operator token: `python3 -m tools.trialbox secrets rotate --service operator` if the leaver used it in
   scripts, or a full `secrets rotate` (§5).
3. If the leaver knew the KEK passphrase or held a share: see the key stewards below.

## A key steward or the holder of the backup key

| What they held | Do | Command |
| --- | --- | --- |
| a KEK share or the KEK passphrase | rotate the KEK; the old shares stop working | `sudo python -m tools.keys rotate-kek` |
| the backup private key envelope | a new backup key pair; hand the old private key to the new holder for the old backups | `python -m tools.trialbox backup-keygen` |
| the pgBackRest cipher copy | hand it over; rotate it only with Aimedics (§5) | |

## Hospital IT staff who ran the box

Change the passwords they knew at their source (the lost-box list of §23 names them: the AD bind account, the mail
passwords, the share credentials), and remove their host accounts and SSH keys.

## An Aimedics person

1. Remove them from the support rota and the support sheet (§21); the site gets the new names.
2. The hospital closes the visitor badge and any hospital account it gave them (IT pack A.8a).
3. If they could sign update bundles: the vendor key is changed by a signed rotation bundle (§5, "Vendor keys").
4. Their access to the repository and to the owner's machines ends the same day (outside the box; the owner does
   it).

**Check.** Once a quarter the administrator lists the accounts (`console.cli list-users`) with the PI and disables
any that is not needed. An automatic unused-account report is T-209.
