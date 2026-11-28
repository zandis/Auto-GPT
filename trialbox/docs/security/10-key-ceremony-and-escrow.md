# 10. Key ceremony and escrow (TB-SOP-03)

**Reader:** the box owner, hospital IT and the key custodians, at the install of a site box (VALIDATION or
PRODUCTION), before any real data. **Evidence:** the signed ceremony record is IQ-05's evidence in go-live acceptance
(RUNBOOK §6). Decisions: D-893 (the record), D-894 (the escrow copy of a TPM-sealed KEK). Background: §4 of this document set (secrets) and RUNBOOK §23 (the key inventory and
the lost-box list).

## 1. What is made, and who keeps it

| What | Made by | Kept by | On the box |
| --- | --- | --- | --- |
| backup key pair | `trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub` | hospital IT: the private key in a sealed envelope | the public key only |
| site keys (`site_hmac.key`, `pid_map.key`, later `objects.key`, `audit_sign.key`) | `adapter.cli keys-init` (install.sh runs it) | the box, wrapped under the KEK | wrapped only |
| the KEK (key-encryption key) | `python -m tools.keys init` (install.sh's seal step, `deploy/hardening/seal_keys.sh`) | the back end chosen below | never on the data disk |
| the escrow set (TPM back end) | `python -m tools.keys escrow-shares` | the escrow custodians, one share each, on removable media | `kek.json` names the set, its custodians and each share's fingerprint; never a share |
| the ceremony record | `python -m tools.keys ceremony-record` | printed and signed; a copy with the site's validation file | `deploy/site/key-ceremony-<time>.md` and `.json` |

No key, share or passphrase is ever printed (the backup key's paper sheet of §7 aside), logged, put in the audit or in this record.

## 2. Who attends

- **Hospital IT**: types the commands on the box's host as root, and takes the backup key's envelope.
- **The key custodians** (for steward shares: one person per share; the ceremony record names each one).
- **A witness**: a person who is none of the custodians (the box owner, or the hospital's security officer).

## 3. The back end: the box owner's and hospital IT's choice at the ceremony

Which back end a site uses is the box owner's and hospital IT's choice at the ceremony. Both are supported; the
record says which was chosen.

| Back end | What it is | After a power loss | When a custodian leaves |
| --- | --- | --- | --- |
| **TPM** (the default, D-836; `KEK_BACKEND=tpm`, recorded as `file`) | a random KEK sealed to this machine's TPM with `systemd-creds` (DPAPI on the Windows host); its recovery copy is an escrow set (§5) | the box unseals itself at boot (`trialbox-unseal.service`); nobody is needed | when an escrow custodian leaves: `rotate-kek --backend file ... --escrow-out <media>` (a new KEK and a new escrow set; the old shares open nothing) and a new ceremony record; review who holds the backup key's envelope |
| **Steward shares** (`KEK_BACKEND=shamir`, 2 of 3 by default) | the KEK split into shares on removable media, one per custodian | the box waits, with the services refusing, until 2 of the 3 custodians bring their shares: `python -m tools.keys unseal --share <file> --share <file>` | `python -m tools.keys rotate-kek --backend shamir --shares-out <media>`: a new KEK and new shares; the old shares stop working; a new ceremony record |

**The recovery copy.** With steward shares the shares are the KEK's recovery copy by themselves. With the TPM the KEK
is bound to this board: its recovery copy is an **escrow set** (§5), made at the ceremony. Without one, a dead board
means the wrapped site keys cannot be opened, and a lost `site_hmac.key` changes every pseudonym (RUNBOOK §23); the
ceremony record then says "Escrow: none".

A **passphrase** KEK (`KEK_BACKEND=passphrase`) is for a proof of concept or a validation run on a plain VM
(`TB_HOST_PROFILE=poc`). Its ceremony record is marked **not a site's key ceremony**; a site box is made again with
the TPM or steward shares before real data.

For a passphrase box, run `python -m tools.keys unseal` at a terminal and enter the current passphrase at the hidden prompt. To rotate it, then run `python -m tools.keys rotate-kek --backend passphrase` and enter the new passphrase twice.
在終端執行上述 unseal 指令，依隱藏提示輸入目前密語。更換密語時再執行 rotate-kek，輸入新密語兩次。
端末で上記の unseal を実行し、非表示のプロンプトに現在のパスフレーズを入力します。変更時は続けて rotate-kek を実行し、新しいパスフレーズを 2 回入力します。

To rotate an already unsealed KEK without a terminal prompt, put the new passphrase in a file only root can read
(type it after sudo's own password prompt, then Enter; nothing is shown). The file is removed once the KEK is
rotated. A passphrase in the environment is refused by `tools.keys` (H-96): sudo writes a variable it keeps, with
its value, to the system journal. RUNBOOK §23 ("Rotate the KEK passphrase") is the whole procedure.

```bash
sudo bash -c 'umask 077; IFS= read -rs TB_KEK_NEW_PASSPHRASE; printf "%s\n" "$TB_KEK_NEW_PASSPHRASE" > /root/trialbox-kek-new.pass'
sudo env PYTHONPATH=libs:services:. python3 -m tools.keys rotate-kek --backend passphrase --new-passphrase-file /root/trialbox-kek-new.pass --audit-dir "$(sudo docker volume inspect -f '{{.Mountpoint}}' trialbox_audit-data)"
```

## 4. The ceremony, in order

1. Hospital IT makes the backup key pair and puts the private key in the sealed envelope at once:
   `trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub`.
2. The install makes the site keys (`adapter.cli keys-init`, run by `deploy/install.sh`) and, in VALIDATION and
   PRODUCTION, seals them under the KEK with the chosen back end (`deploy/site/hardening.conf`: `KEK_BACKEND=tpm`, or
   `KEK_BACKEND=shamir` with `KEK_SHARES_OUT=<removable media>`). For steward shares: each custodian takes one share
   file away, and it is removed from the media.
3. `python -m tools.keys status` shows every key wrapped and the KEK; nothing may be plain (`python -m tools.keys
   wrap` if one is).
4. For the TPM back end, the escrow set (§5): `python -m tools.keys escrow-shares --threshold 2 --shares 3
   --escrow-out /media/usb --custodian "<name 1>" --custodian "<name 2>" --custodian "<name 3>"`. Each custodian
   takes their share file away on its own medium; nothing is left on the box.
5. The record: `python -m tools.keys ceremony-record --custodian "<name 1>" --custodian "<name 2>" --custodian
   "<name 3>" --witness "<name>" [--shares-dir <media>]`. For steward shares, name the custodians in the order of the
   share numbers (share 1 to the first name); with `--shares-dir` each share file's fingerprint goes on the record
   (read before the files are taken away). The command refuses before `keys init` and while a key is plain. It writes
   `deploy/site/key-ceremony-<time>.md` and `.json` and the audit event `keys.ceremony` (fingerprints and names only).
   On a TPM box it lists the escrow set; every escrow custodian is named with `--custodian` and signs.
6. Print the Markdown record. Each custodian and the witness sign it. File it with the site's validation documents;
   `trialbox doctor` (`key_ceremony`) WARNs on a site box whose KEK has no record, a record of an older KEK, an escrow
   set of an older KEK, or an escrow set the newest record does not list.

## 5. Escrow: where each thing is kept

**The escrow set of a TPM-sealed KEK** (D-894). `python -m tools.keys escrow-shares` splits the unsealed KEK into
shares, any `--threshold` of `--shares` giving it back. The tool refuses:

- a threshold under 2, or not under the share count (one person never opens the KEK; a lost share never loses it);
- a custodian count other than the share count, or a name given twice;
- a folder that is not already mounted, is inside the secrets folder, is on the secrets folder's or the system's disk,
  or is not removable media: shares are written only to removable media named on the command line, never to the
  box's disks, never printed or logged (only each share's fingerprint is);
- a second set for the same KEK (a lost or doubtful set is replaced by `rotate-kek ... --escrow-out`, which makes a
  new KEK so the old shares open nothing);
- a box without an audit folder: making a set is the audit event `keys.escrow` (fingerprints and custodian names).

**Who may hold a share.** Each share goes to another named person. The shares are spread so that **neither the box
owner alone nor hospital IT alone** holds the threshold: with 2 of 3, for example, one share with hospital IT, one
with the box owner's named deputy and one with the hospital's security officer, or the site's research office. No
person holds two shares; a custodian is never the witness.

**Using the shares is a witnessed event with its own record.** On a new board (the secrets volume restored from the
backup, RUNBOOK §5): `python -m tools.keys unseal --share <file> --share <file> --witness "<name>"`. It refuses
without a witness, with a witness who is an escrow custodian, with too few shares, with a share of another set, and
without an audit folder. It writes the KEK to the runtime file, the escrow-use record
`deploy/site/escrow-use-<time>.md` and `.json` (which custodian brought which share, and the witness; printed and
signed, filed with the site's validation documents) and the audit event `keys.escrow_unseal`. Then, at once:
`python -m tools.keys rotate-kek --backend file --kek-out <media> --escrow-out <media> --custodian ...` (seal the new
KEK to the new board's TPM, D-836) and a new ceremony record. A `rotate-kek` without `--escrow-out` keeps the old set
in `kek.json` only to say it is of the old KEK: `doctor` WARNs until `escrow-shares` makes a new one.

| Thing | Where | Who may open it |
| --- | --- | --- |
| backup private key | sealed envelope, hospital IT's safe | hospital IT, for a restore or a restore drill (`trialbox restore-drill`) |
| steward shares | each on its own medium, with its custodian, in separate places | its custodian, at an unseal or a rotation |
| escrow shares (TPM back end) | each on its own medium, with its custodian, in separate places | its custodian, only at a witnessed escrow unseal (a new board) |
| the signed ceremony record | the site's validation file | anyone who checks the site |

## 6. Rotation and compromise

From `python -m tools.keys inventory` (RUNBOOK §23):

- the KEK: yearly, when a custodian leaves, and at once on a suspected compromise: `python -m tools.keys rotate-kek`,
  then a new ceremony record (the old record names the old KEK; `doctor` says so);
- `pid_map.key`: yearly and on compromise: `python -m tools.keys rotate pid_map`;
- `site_hmac.key`: never rotated (a new key gives every patient a new pseudonym and loses their opt-outs);
- the backup key: a new pair with hospital IT when the envelope is lost or opened without a restore; every later
  backup uses the new public key.

## 7. The backup-key ceremony on the host (10K-13, D-1379)

On a box that has no `backup.pub` yet, hospital IT (as root on the box's host) and a witness who is another person
can make the backup key with one command instead of step 1 of §4:

    python -m tools.backup_key_ceremony --stick /media/usb --operator "<name>" --witness "<name>" [--lang ja]

Mount an empty stick first with `mount -o uid=0,gid=0,umask=077,nodev,nosuid,noexec <device> /media/usb`. The
command runs four steps: (1) it makes the key, records its fingerprint and public key on the box
(`deploy/secrets/backup-ceremony-<fingerprint>.pending`, never removed), and writes `trialbox-backup.key` and the
printable sheet `trialbox-backup-key-paper.txt` to the stick; (2) it reads both back after a sync and compares them;
(3) it records the event `backup.key_ceremony` (the fingerprint and both names, never the key) through the
orchestrator's audit journal, which must answer with the event's number; (4) only then it makes
`deploy/secrets/backup.pub`. It refuses on a box whose orchestrator journal does not answer, on a folder that is not
a removable stick of its own, on a stick holding a key file this box has no record of, while another run is going on,
and once `backup.pub` exists ("done already"). Nothing is ever undone or deleted. **A run cut short (an error,
Ctrl-C, a power cut) is finished by running the same command again with the same stick.** If the command is run again
with another, empty stick instead, it makes a new key there: **the key from the abandoned run stays on its stick,
never the box's key, until IT wipes that stick** (its record on the box stays too). A stick the command says cannot
finish a run is wiped by IT too, and the command is run with an empty stick. Then unmount the stick, print the sheet
from the stick on a printer that keeps no copy of the job (not through this host's print spool), and seal both in
hospital IT's envelope. To restore from the paper alone, type only the letters between the two bars of each numbered
line, one line per line, into a file and give that file to `restore --key` (the sheet says the same). Each file is
written under a hidden temporary name (`.<name>.<random>.part`) and renamed; a run cut short can leave such a file on
the stick: it is never removed or read again, and goes with the stick. The stick must be one plain removable device
(no btrfs, LVM, LUKS or md on it). The journal is asked only through this host's own Docker socket, whatever Docker
context the shell has. The command refuses before making the key when swap is on and its memory cannot be locked:
run it as root (which may lock memory) or turn swap off first. It refuses a stick folder that is a backup target
(`TB_BACKUP_TARGETS`), inside one, holds one or shares its filesystem, and asks only the compose project whose
orchestrator runs from this checkout's deploy folder. Not detected, so set the host up plainly: an ext4 stick whose
journal is external on an internal disk (use a plain removable stick), and swap switched on during the ceremony when
memory could not be locked (keep swap off, or allow the memory lock).
