# D-1342 The host check knows the tier: a desk-side box may not open its disk by the TPM alone

- **Task:** lane H, plan 10 row 10G-11 (review 16 row 16-20, section 2.8).
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-1320 (the tier record), D-408 and T-634 (the host baseline, `luks_policy.py`), D-837 (the poc
  host profile)

## Context

Review 16 section 2.8 places each box: the no-GPU box in a server room; the RTX 5090 and RTX PRO 6000 workstations
under a desk, the riskiest physically; the DGX Spark small enough to carry away. Its threat table (section 1) says
`luks_policy.py` already FAILs a TPM-only unlock, but nothing stops an installer from choosing it on a VALIDATION
box: under the poc host profile (D-837) `check_host.sh` turned that FAIL into a WARN. The host check did not know
the tier at all.

## Decision

1. **The tier comes from the installer's label.** `deploy/hardening/host_tier.py` reads `TB_PROFILE` from the env
   file (`deploy/install.sh` writes it) and the field `desk_side` of the box's record through
   `libs/tb_common/tier_value.py` (never raises). `check_host.sh --baseline` prints the tier as its first host line.
2. **Desk-side boxes.** The records of `rtx5090` and `rtxpro6000` declare `desk_side: true` from review 16. The
   placement is a declared fact, not a figure, so this reader takes the declared value (D-1322 is about figures).
3. **Unknown is the stricter case.** No label, a label with no record (`P-GB10`: the Spark and today's no-GPU
   install), a missing or malformed record, or no `desk_side`: the line is a WARN that says the box is taken as
   desk-side. Only a record that states `desk_side: false` is a server-room box.
4. **The rule.** On a desk-side or unknown tier, in VALIDATION and PRODUCTION, a TPM-only way into a LUKS volume
   (a `systemd-tpm2` token without a PIN; a clevis binding that opens without a Tang server) is a FAIL with the
   reason and what to do: add a Tang server (`deploy/hardening/disk-unlock.sh bind`), or a PIN to the TPM, or keep
   the passphrase alone. The poc profile does not relax it. DEV and TEST, and a server-room tier, are unchanged.
5. **Tests.** `tests/unit/test_host_check_tier.py`: fixtures per tier (the two shipped records, a server-room
   record and a malformed one in a test folder through `TB_TEST_TIERS_DIR`, `P-GB10`, no label) against the fake
   host of `test_host_baseline.py`.

## Not covered

- BitLocker on Windows with WSL2 is judged by `deploy/windows/wsl2_policy.py`, which does not read the tier.
- No record marks a server-room box yet; a no-GPU box reads as unknown and takes the stricter rule.
- The Spark's own rule in the review (TPM and PIN, no unattended unlock) is stricter than this one (a Tang binding
  passes); not built here.
