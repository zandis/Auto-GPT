# 10. Key ceremony and escrow (TB-SOP-03)

**Reader:** the box owner, hospital IT and the key custodians, at the install of a site box (VALIDATION or
PRODUCTION), before any real data. **Evidence:** the signed ceremony record is IQ-05's evidence in go-live acceptance
(RUNBOOK §6). Decision: D-893. Background: §4 of this document set (secrets) and RUNBOOK §23 (the key inventory and
the lost-box list).

## 1. What is made, and who keeps it

| What | Made by | Kept by | On the box |
| --- | --- | --- | --- |
| backup key pair | `trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub` | hospital IT: the private key in a sealed envelope | the public key only |
| site keys (`site_hmac.key`, `pid_map.key`, later `objects.key`, `audit_sign.key`) | `adapter.cli keys-init` (install.sh runs it) | the box, wrapped under the KEK | wrapped only |
| the KEK (key-encryption key) | `python -m tools.keys init` (install.sh's seal step, `deploy/hardening/seal_keys.sh`) | the back end chosen below | never on the data disk |
| the ceremony record | `python -m tools.keys ceremony-record` | printed and signed; a copy with the site's validation file | `deploy/site/key-ceremony-<time>.md` and `.json` |

No key, share or passphrase is ever printed, logged, put in the audit or in this record.

## 2. Who attends

- **Hospital IT**: types the commands on the box's host as root, and takes the backup key's envelope.
- **The key custodians** (for steward shares: one person per share; the ceremony record names each one).
- **A witness**: a person who is none of the custodians (the box owner, or the hospital's security officer).

## 3. The back end: the box owner's and hospital IT's choice at the ceremony

Which back end a site uses is the box owner's and hospital IT's choice at the ceremony. Both are supported; the
record says which was chosen.

| Back end | What it is | After a power loss | When a custodian leaves |
| --- | --- | --- | --- |
| **TPM** (the default, D-836; `KEK_BACKEND=tpm`, recorded as `file`) | a random KEK sealed to this machine's TPM with `systemd-creds` (DPAPI on the Windows host) | the box unseals itself at boot (`trialbox-unseal.service`); nobody is needed | nobody holds a part of the KEK; review who holds the backup key's envelope |
| **Steward shares** (`KEK_BACKEND=shamir`, 2 of 3 by default) | the KEK split into shares on removable media, one per custodian | the box waits, with the services refusing, until 2 of the 3 custodians bring their shares: `python -m tools.keys unseal --share <file> --share <file>` | `python -m tools.keys rotate-kek --backend shamir --shares-out <media>`: a new KEK and new shares; the old shares stop working; a new ceremony record |

**The recovery copy.** With steward shares the shares are the KEK's recovery copy by themselves. With the TPM the KEK
is bound to this board, and **the tooling does not yet make an escrow copy of a TPM-sealed KEK** (a follow-up card):
until it does, a dead board means the wrapped site keys cannot be opened, and a lost `site_hmac.key` changes every
pseudonym (RUNBOOK §23). A site that wants a recovery copy today chooses steward shares, or keeps the TPM and accepts
that a board replacement is a new box re-pseudonymised from its source.

A **passphrase** KEK (`KEK_BACKEND=passphrase`) is for a proof of concept or a validation run on a plain VM
(`TB_HOST_PROFILE=poc`). Its ceremony record is marked **not a site's key ceremony**; a site box is made again with
the TPM or steward shares before real data.

## 4. The ceremony, in order

1. Hospital IT makes the backup key pair and puts the private key in the sealed envelope at once:
   `trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub`.
2. The install makes the site keys (`adapter.cli keys-init`, run by `deploy/install.sh`) and, in VALIDATION and
   PRODUCTION, seals them under the KEK with the chosen back end (`deploy/site/hardening.conf`: `KEK_BACKEND=tpm`, or
   `KEK_BACKEND=shamir` with `KEK_SHARES_OUT=<removable media>`). For steward shares: each custodian takes one share
   file away, and it is removed from the media.
3. `python -m tools.keys status` shows every key wrapped and the KEK; nothing may be plain (`python -m tools.keys
   wrap` if one is).
4. The record: `python -m tools.keys ceremony-record --custodian "<name 1>" --custodian "<name 2>" --custodian
   "<name 3>" --witness "<name>" [--shares-dir <media>]`. For steward shares, name the custodians in the order of the
   share numbers (share 1 to the first name); with `--shares-dir` each share file's fingerprint goes on the record
   (read before the files are taken away). The command refuses before `keys init` and while a key is plain. It writes
   `deploy/site/key-ceremony-<time>.md` and `.json` and the audit event `keys.ceremony` (fingerprints and names only).
5. Print the Markdown record. Each custodian and the witness sign it. File it with the site's validation documents;
   `trialbox doctor` (`key_ceremony`) WARNs on a site box whose KEK has no record, or a record of an older KEK.

## 5. Escrow: where each thing is kept

| Thing | Where | Who may open it |
| --- | --- | --- |
| backup private key | sealed envelope, hospital IT's safe | hospital IT, for a restore or a restore drill (`trialbox restore-drill`) |
| steward shares | each on its own medium, with its custodian, in separate places | its custodian, at an unseal or a rotation |
| the signed ceremony record | the site's validation file | anyone who checks the site |

## 6. Rotation and compromise

From `python -m tools.keys inventory` (RUNBOOK §23):

- the KEK: yearly, when a custodian leaves, and at once on a suspected compromise: `python -m tools.keys rotate-kek`,
  then a new ceremony record (the old record names the old KEK; `doctor` says so);
- `pid_map.key`: yearly and on compromise: `python -m tools.keys rotate pid_map`;
- `site_hmac.key`: never rotated (a new key gives every patient a new pseudonym and loses their opt-outs);
- the backup key: a new pair with hospital IT when the envelope is lost or opened without a restore; every later
  backup uses the new public key.
