# D-1062 A preview VM in steps mode: demo mode off, and a person may be administrator or steward

- **Task:** an owner's ruling, numbered by the integrator; the integrator's own card (the demo VM's driver, taken
  over from lane G on 2026-11-16)
- **Date:** 2026-11-17
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-17)

## Ruling

1. The owner and his testers walk a study from its first step on a small VM built from current master. The frozen
   PoC-1 demo VM (`tb-demo-vm`) is not changed.
2. `deploy/gcp/demo-vm.sh` gets a second mode, `TB_DEMO_VM_MODE=steps`. In it the boot leaves the audited flag
   `demo.mode` off, so a protocol can be pasted and uploaded, and `TB_DEMO_VM_PEOPLE` may also name the roles
   `admin` and `steward`. Everything else is as in demo mode: the stub model only, the synthetic hospital, tcp:443
   only, no SSH, one-time enrolment links, the hard stop.
3. The default stays `demo`: demo mode on before the door opens, and neither role offered.
4. Steps mode is for synthetic or public text only (rule 1 of the hand-over). The people are told so with their
   links; the console's first sign-in acknowledgement says the same.

## Where the wording comes from

The owner's messages of 2026-11-17 in the integrator's session: the preview should show current master; it should
be testable from the first step; all four roles for each of four people.

## Used by

`deploy/gcp/demo_vm.py`, `deploy/gcp/demo-vm.sh`, `deploy/gcp/demo-vm-boot.sh`, `tests/unit/test_g1_demo_vm.py`,
`docs/runbook/11-cloud-runs.md`.
