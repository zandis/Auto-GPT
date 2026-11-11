# 4. Secrets

| Secret | Where | Protection |
| --- | --- | --- |
| service tokens, operator token | `deploy/secrets/services/` | 0600, one per service, mounted into that service only; rotated with `trialbox secrets rotate` |
| database, mail and cloud passwords | `deploy/.env` | 0600, root; cleared in the containers that do not need them |
| `site_hmac.key` (pseudonyms), `pid_map.key` (AES-GCM key of the pid map) | volume `tb-secrets` | 0600; seal at rest with the TPM (below) |
| backup public key | `deploy/secrets/backup.pub` | the private key is on a USB stick with hospital IT, never on the box |
| vendor update key | `deploy/keys/vendor_ed25519.pub` | public key only |

Seal the two site keys with the TPM and decrypt them into the secrets volume at start:

```sh
systemd-creds encrypt --with-key=tpm2 --name=pid_map.key /root/pid_map.key /etc/trialbox/creds/pid_map.key.cred
shred -u /root/pid_map.key
# trialbox.service: ExecStartPre=systemd-creds decrypt /etc/trialbox/creds/pid_map.key.cred <volume>/pid_map.key
```

Losing the site key changes every pseudonym: keep a sealed copy with the LUKS recovery material. No secret value is
ever printed, logged or put in the audit; `secrets status` shows names, modes and ages only.
