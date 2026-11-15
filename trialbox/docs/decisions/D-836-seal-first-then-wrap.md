# D-836 the KEK is sealed before any key is wrapped under it

- **Task:** I-5 of the independent examination of the bundle and installer path (2026-11-15, #639)
- **PR:** this branch (`agent/I-5-seal-first-then-wrap`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-408 (T-634, seal_keys.sh), D-347 (the KEK)

## Decision

1. `seal_keys.sh` (tpm): make the KEK, seal it with `systemd-creds encrypt` to `trialbox-kek.new`, then wrap the keys
   under it (`tools.keys init --kek-in`, new), then move the credential into place. A failed seal changes nothing;
   before, the keys were wrapped and kek.json written first and the trap shredded the only plain copy.
2. Up front it asks `systemd-creds has-tpm2` (the TPM and its TSS2 libraries), not only a /dev/tpm* node; so does
   `check_host.sh` on the running host. Every failure names the fix: `TB_KEK_BACKEND=passphrase` with
   `TB_KEK_PASSPHRASE`.
3. `TB_KEK_BACKEND` (declared) chooses the KEK back end from the installer's environment, over hardening.conf's
   `KEK_BACKEND`: a fresh box needs no hardening.conf for it, which also ran `hardening/apply.sh all`.
4. The passphrase path runs end to end in a test.

## Test

`tests/unit/test_seal_keys_order.py` runs the script on a test host root with a stand-in systemd-creds: before, a
failed seal left the keys wrapped and no message named the fix; after, all pass. `test_host_baseline.py`'s stand-in
systemd-creds also answers `has-tpm2`.
