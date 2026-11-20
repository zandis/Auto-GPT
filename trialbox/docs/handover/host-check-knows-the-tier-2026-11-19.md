# The host check knows the tier (2026-11-19)

**Reader:** the people who build TrialBox: lane H and the integrator. For builders, so in one language.

Card 10G-11 (plan 10, track G; review 16 row 16-20, section 2.8), decision D-1342. New findings in the register's
`--add-from` form: `host-check-knows-the-tier-2026-11-19/findings.json`.

## What was there

`deploy/hardening/luks_policy.py` already FAILed a TPM-only unlock on every box. `deploy/check_host.sh` did not know
the tier, and under the poc host profile (D-837) it turned that FAIL into a WARN on a VALIDATION box: the gap the
review names ("nothing stops an installer from choosing TPM-only on a VALIDATION box").

## What changed

- `deploy/hardening/host_tier.py` reads `TB_PROFILE` from the env file and `desk_side` through
  `libs/tb_common/tier_value.py`. It prints the class (`desk-side`, `server-room`, `unknown`) and one line.
- `deploy/check_host.sh --baseline` prints that line. On a desk-side or unknown tier, in VALIDATION and PRODUCTION,
  a TPM-only line of `luks_policy.py` gets the reason and what to do, and stays a FAIL under the poc profile.
- Desk-side, from review 16 section 2.8: the RTX 5090 and RTX PRO 6000 workstations (`rtx5090`, `rtxpro6000`; both
  records declare `desk_side: true`). Unknown: no label, `P-GB10` (no record), a missing or malformed record.
- Tests: `tests/unit/test_host_check_tier.py`, 34 cases; 21 of them fail on master's `check_host.sh`.

## Findings

| Id | Severity | Claim | Basis |
| --- | --- | --- | --- |
| H10G11-01 | Low | BitLocker on WSL2 is judged without the tier | shown |
| H10G11-02 | Low | no record marks a server-room box; a no-GPU install is labelled `P-GB10` and reads as unknown | shown |
| H10G11-03 | Low | the Spark's rule in the review (TPM and PIN, no unattended unlock) is not built; a Tang binding passes there | shown |
| H10G11-04 | Low | run only against the fake host; no box with a real LUKS volume and TPM was used | hypothesis |
