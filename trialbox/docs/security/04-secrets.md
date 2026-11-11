# 4. Secrets

| Secret | Where | Protection |
| --- | --- | --- |
| service tokens, operator token | `deploy/secrets/services/` | 0600, one per service, mounted into that service only; rotated with `trialbox secrets rotate` |
| database, mail and cloud passwords | `deploy/.env` | 0600, root; cleared in the containers that do not need them |
| `site_hmac.key` (pseudonyms), `pid_map.key` (AES-GCM key of the pid map) | volume `tb-secrets` | 0600 until sealed; at install `deploy/hardening/seal_keys.sh` wraps them under the KEK (`<name>.wrapped`, D-347), see below |
| backup public key | `deploy/secrets/backup.pub` | the private key is on a USB stick with hospital IT, never on the box |
| vendor update key | `deploy/keys/vendor_ed25519.pub` | public key only |

**The KEK (D-347, D-408).** In VALIDATION and PRODUCTION `install.sh` wraps `site_hmac.key`, `pid_map.key` and the other
site keys under a key-encryption key (KEK) right after it makes them and before any service starts. The KEK is not on
the data volume and is never in the backup. Back ends (`KEK_BACKEND`): `tpm` (the default; a random KEK sealed with
`systemd-creds encrypt --with-key=host+tpm2` to `/etc/credstore.encrypted/trialbox-kek`, opened at boot by
`trialbox-unseal.service`), `shamir` (stewards' shares) and `passphrase`. `python -m tools.keys unseal` writes the KEK to
`/run/trialbox/kek` (tmpfs); with no KEK the services refuse instead of making new keys. `python -m tools.keys
inventory` lists every key with its holder, rotation rule and compromise action; RUNBOOK §23 has the lost-box list and
`rotate-kek`. Details: the host section (§1) of this document.

Losing the site key changes every pseudonym: keep a sealed copy with the LUKS recovery material (and the KEK's shares or passphrase). No secret value is
ever printed, logged or put in the audit; `secrets status` shows names, modes and ages only.
