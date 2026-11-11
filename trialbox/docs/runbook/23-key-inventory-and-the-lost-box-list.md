# 23. Key inventory and the lost-box list

*T-635, D-390. Closes OPS-044. The keys on the box, their holders and rotation rules are in code: `python -m
tools.keys inventory` (D-347) prints them, and SECURITY §4 says where each secret is kept. This page adds what that
list does not cover: what to revoke **outside** the box when the box, a disk or a backup is lost, and who does it.*

**Drill (T-213b):** `test_runbook_23_lost_box` (tabletop: the box is reported stolen at 10:00; every row of the
lost-box list is assigned, and the time each would take is written; Docker part: `python -m tools.keys inventory
--json` lists every key this page names).

## The inventory on the box

```sh
python -m tools.keys inventory          # every key: where, what it protects, holder, rotation, compromise action
python -m tools.keys inventory --json
python3 -m tools.trialbox secrets status  # tokens: file, mode, age; never a value
```

Check the printout with hospital IT at IQ and once a year. A key whose holder has left is rotated (§25).

## The lost-box list

Use it when the box, one of its disks, or an unencrypted copy of its secrets folder is lost or stolen. It applies too
when a backup file **and** the backup private key are lost together. Start within the hour; the clock is the
incident plan's (T-318). Change each secret at its source, not on the lost box.

| Secret outside the box | Where it is changed | Who | Within |
| --- | --- | --- | --- |
| AD or LDAP bind account (hospital sign-in, §12) | the hospital directory: disable the account, make a new one for the new box | hospital IT | 4 hours |
| OIDC client secret (Authelia or the hospital's provider) | the identity provider: delete the client, register a new one | hospital IT | 4 hours |
| SMTP and IMAP passwords of the box's mailbox | the hospital mail server | hospital IT | 4 hours |
| REDCap API tokens (one per CRF project, §2 EDC prefill) | REDCap: delete each project's token | the REDCap administrator | 4 hours |
| a cloud-model API key, if one is set | the cloud provider's console | the hospital account owner | 4 hours |
| the hospital's TLS certificate and key (§12, hospital mode) | the hospital CA: revoke, issue a new one | hospital IT | 1 working day |
| staff second-factor (TOTP) secrets | every account enrols again on the new box (`console.cli reset-totp NAME`, §12) | site administrator | before the new box opens |
| staff passwords of local accounts | reset on the new box; tell staff who used the same password elsewhere | site administrator | before the new box opens |
| the backup key pair | `trialbox backup-keygen` on the new box; old backups stay readable with the old private key | hospital IT | 1 working day |
| the KEK (steward shares, passphrase) | `python -m tools.keys rotate-kek` on the restored box; old shares stop working | key stewards | at the restore |
| `pid_map.key` | `python -m tools.keys rotate pid_map` on the restored box | site administrator | at the restore |
| vendor update key | not on the box (public key only): nothing to do | | |
| share credentials for the backup target (NAS, SMB) | the hospital file server | hospital IT | 4 hours |

**Not rotated:** `site_hmac.key`. A new key gives every patient a new pseudonym and loses the opt-outs (T-612). If it
may have been read, it is a breach under the incident plan, not a rotation.

**What makes a lost box less bad.** The site keys are wrapped under the KEK (D-347), and the KEK is not on the disk:
a stolen disk without the shares, the passphrase or the TPM does not open the pid map. Disk encryption that only
unlocks inside the hospital is T-408. Until it is on the box, assume a stolen box exposes `deploy/.env` and every
password in it: every row above applies.
