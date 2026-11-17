# D-1063 One sign-in per person with an acting role, on test boxes only

- **Task:** an owner's ruling, numbered by the integrator and relayed by the integrator; built by lane C2
- **Date:** 2026-11-17
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-17)

## Ruling

1. On a test box (the demo VM's steps mode, D-1062) a person has one account and chooses the role they act in.
2. The acting role decides every permission exactly as an account's own role does today. It gives no power that
   role does not have, and D-280 holds per acting role.
3. It exists only while an audited flag is on. The flag cannot be set, and extra roles cannot be granted, on a
   VALIDATION or PRODUCTION box. Each switch is an audit event that names the real user.
4. The separation of duties on a real box is unchanged: one account, one role.

## Where the wording comes from

The owner's message of 2026-11-17 in the integrator's session, after four accounts a person proved too hard to use.

## Used by

Lane C2's card STEPS-ROLE; `deploy/gcp/demo-vm-boot.sh` once that card is on master.
