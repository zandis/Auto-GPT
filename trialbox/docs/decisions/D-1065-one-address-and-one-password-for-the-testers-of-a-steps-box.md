# D-1065 One address and one password for the testers of a steps-mode box

- **Task:** an owner's ruling, numbered by the integrator; the integrator's own card (the demo VM's driver)
- **Date:** 2026-11-17
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-17)

## Ruling

1. On a steps-mode demo VM (D-1062) the owner's testers sign in at the one address with their own user name and one
   password that all of them share. Each account holds the roles it may act in (D-1063).
2. `TB_DEMO_VM_SHARED_LOGIN=1`, in steps mode only: the boot makes the password, redeems each person's one-time code
   with it through the product's own first sign-in, and writes it to the private hand-off object only. It is never
   in the metadata, the serial console, a log or a file left on the VM.
3. This is weaker than a password each person chooses, and is accepted for a test box with synthetic data only. It
   is refused outside steps mode, and steps mode's acting role is refused on a VALIDATION or PRODUCTION box.
4. The default is unchanged: each person chooses their own password with a one-time link.

## Where the wording comes from

The owner's message of 2026-11-17 in the integrator's session: one link for all four people, the same password, four
roles each.

## Used by

`deploy/gcp/demo_vm.py`, `deploy/gcp/demo-vm.sh`, `deploy/gcp/demo-vm-boot.sh`, `tests/unit/test_g1_demo_vm.py`,
`docs/runbook/11-cloud-runs.md`.
