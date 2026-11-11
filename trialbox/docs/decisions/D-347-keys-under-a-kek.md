# D-347 The site keys under a KEK: wrapped files, three back ends, the unseal, the key inventory

- **Task:** T-210b (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-210b-kek`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-041 (second third: keys under a KEK and the unseal), OPS-058 (the key inventory; rotation code for
  the KEK and `pid_map.key`)

## Context

`site_hmac.key` and `pid_map.key` were plain files in the secrets volume (CR-041, OPS-061, OPS-043). Whoever copies
the volume or the disk has every pseudonym and every chart number of the pid map. The KEK must live outside the
data volume, and a box whose KEK is not available must refuse instead of making new keys. OPS-058 found no rotation
rule for most keys.

## Decision

1. **Wrapped files.** A protected key is `<name>.wrapped` (format `tb-wrapped-key/1`, JSON): AES-256-GCM under the
   KEK, with associated data that binds the format, the key's file name and the KEK's id, plus the key's fingerprint
   (`tb_common.crypto.key_fingerprint`). `libs/tb_common/kek.py` does the wrapping; `crypto.load_key` opens a wrapped
   key when there is one and `crypto.create_key` never makes a key beside a wrapped one. A plain copy beside a
   wrapped key is refused.
2. **`kek.json`** beside the keys holds the KEK's id, its back end and public parameters, never the KEK.
3. **Three back ends.** `passphrase` (scrypt; the passphrase typed or in `TB_KEK_PASSPHRASE`), `shamir` (k of n
   shares over GF(256), one file per steward, a set id so a share of another split is refused, a share given twice
   refused), `file` (a random KEK sealed by the host: a TPM-bound systemd credential or Windows DPAPI). A KMS back end
   is T-319's.
4. **The unseal.** `python -m tools.keys unseal` writes the KEK to `/run/trialbox/kek` (tmpfs, 0600; `TB_KEK_FILE`).
   Services look there, then at `$CREDENTIALS_DIRECTORY/trialbox-kek`, then at `TB_KEK_PASSPHRASE`. A KEK file in the
   secrets folder, readable by others, or with another id is refused. With no KEK the load fails closed.
5. **No auto-created keys on a real box.** `pid_map.key` is never made on first use when `TB_ENV` is VALIDATION
   or PRODUCTION (`install.sh` writes it). Tools that set no `TB_ENV` (the demo walks, fixtures) still make it.
6. **Checks.** `doctor` check `key_custody` FAILs a plain site key in VALIDATION and PRODUCTION (WARN in DEV/TEST) and
   every custody problem; `tools/apply_update.sh` runs `tools.keys check --for-update` first and refuses an update
   when the keys are wrapped and the KEK is not unsealed.
7. **Inventory and rotation.** `python -m tools.keys inventory` lists every key with where, holder, rotation rule,
   what breaks and the compromise action. `rotate-kek` re-wraps every key; `rotate pid_map` re-encrypts the pid map in
   one transaction. `site_hmac.key` is never rotated (T-612).

## Consequences

- The backup format does not change: the wrapped files are backed up as before, and are useless without the KEK.
- The compose wiring of the runtime KEK file into the containers, `totp.key` under the KEK and the `phi` outputs
  (T-210c) come later.
