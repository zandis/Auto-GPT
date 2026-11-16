# D-897 the box plan asks for a usable TPM

- **Task:** PLAN-TPM, lane D backlog item 2 on #639 (2026-11-16); from lane G's 2026-11-16 installer audit
- **PR:** this branch (`agent/PLAN-TPM-the-plan-asks-systemd-creds`)
- **Date:** 2026-11-16
- **Status:** accepted

## Cause

The box plan (`tools/box/plan.py`, `detect`) decided "the board has a TPM" from the device node alone (`/dev/tpmrm0` or
`/dev/tpm0`). `seal_keys.sh`, `check_host.sh` and `install.sh` decide by asking `systemd-creds has-tpm2` (D-836).
A node that systemd-creds cannot use (a vTPM without its driver, a TPM 1.2) therefore gave a hardening.conf with
`KEK_BACKEND=tpm`, followed by a seal step that stopped.

## Decision

1. `tpm_usable(host_root, has_tpm2)` returns true only when there is a device node **and** `systemd-creds has-tpm2`
   succeeds. It is false when systemd-creds is missing, since the seal needs it.
2. `detect` uses it. Without a usable TPM the plan writes `KEK_BACKEND=passphrase`, as before for a board with no TPM,
   and its warning now reads "no usable TPM (systemd-creds has-tpm2): ...".

## Test

`tests/unit/test_box_plan.py`:

- No node: false. A node that systemd-creds accepts: true. A node it refuses: false, and the plan writes
  `KEK_BACKEND=passphrase` with the warning.
- A host without systemd-creds: false.
