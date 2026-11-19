# 20. Close-out and decommissioning

**Reader:** the box owner, with the trial team.

*T-628, D-413. Closes LIFE-028 and OPS-075. What to do when a site's last study using the box closes, or the box is
retired: freeze the logs, archive the records with checksums, hand the archive to the trial office, then destroy the
keys and purge every store by NIST SP 800-88 Rev. 1, with one certificate per medium. A study that closes while
others go on uses steps 1 to 5 only, for that study.*

**Drill (T-213b):** `test_runbook_20_decommission` (in process, on a synthetic audit chain: step 2's four commands,
step 3's audit copy, plan and `SHA256SUMS`, step 4's checks on a second folder, which fail on a one-line change). Not
rehearsed by a test: the final backup and `backup-verify`, the export ledger, steps 1 and 5 to 8 (people, keys, media).

## The plan of this box

```sh
python3 -m tools.trialbox decommission-plan          # the steps and every store, on and off the box; changes nothing
python3 -m tools.trialbox decommission-plan --json   # the same, for the site's own record
```

It reads `deploy/.env` and the compose file: the volumes, `TB_BACKUP_TARGETS`, `TB_BACKUP_OFFBOX`,
`TB_PGBACKREST_REPO`, `TB_AUDIT_ARCHIVE_DIR`, `TB_AUDIT_ANCHOR_TARGETS`, the log and model folders. Each store is
**keep** (a record kept for its retention time), **purge** (steps 6 to 8) or **ask** (no setting names it: USB disks,
the backup private key, the KEK shares, platform volumes, paper). Print it, and go through the **ask** rows with
hospital IT before step 1. The copy of the plan, filled in, is the site's close-out record
(`docs/plan/sites/close-out-record.md`).

## The steps

**Step 1, announce.** The PI and the trial office set the close date. Tell the coordinators; from that date nobody starts new
screening for the study. A switch that stops one study's runs on the box is not built yet. On the close date the administrator disables every
study account that is not needed for steps 2 to 5 (`console.cli disable NAME`, §3; never delete: the audit names
them), and ends the delegation-log entries (§25).

**Step 2, freeze.** The final freeze of the logs by the audit chain (SPEC §10.2, D-272, D-355). Stop the services so
nothing writes (`systemctl stop trialbox`, or scale the deployment to zero on a platform, §17), then:

```sh
python tools/audit_verify.py /data/audit --json                   # the chain is whole and ends at HEAD.json
python tools/audit_verify.py /data/audit --sign-head --to ANCHOR  # a signed head, written once, off the box
python tools/audit_verify.py /data/audit --heads ANCHOR           # the chain matches every signed head
python tools/audit_verify.py /data/audit --foreign                # no event came from a role that does not write it (D-488)
```

Write down the head (sequence and hash) on the close-out record as `audit_verify.py /data/audit --json` prints it after
all four (`--sign-head` adds one event). From here the chain does not change: a later event on this box is a finding.

**Step 3, archive.** Into one new folder on the hospital's store (never only on the box):

| Part | How | Its checksum |
| --- | --- | --- |
| the final backup (databases, volumes, keys wrapped) | `trialbox backup --to ARCHIVE/backup` (§5) | stream hashes inside (D-187) |
| the audit chain as frozen, with `HEAD.json` and the signed heads | copy `/data/audit` and the anchor folder to `ARCHIVE/audit` | `MANIFEST.sha256` of the audit archive, and step 3's sums |
| the audit archive of earlier days | copy `TB_AUDIT_ARCHIVE_DIR` to `ARCHIVE/audit-archive` | its `MANIFEST.sha256` |
| the export ledger: every file that left the box | `trialbox exports --audit /data/audit --days 100000 --json > ARCHIVE/exports.json` | step 3's sums |
| the decommissioning plan | `decommission-plan --json > ARCHIVE/plan.json` | step 3's sums |

Then the sums of the whole folder: `cd ARCHIVE && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0
sha256sum > SHA256SUMS`, and the sum of `SHA256SUMS` itself on the close-out record. A study's own exports
(screening log, EDC prefill, statistics) are made before step 2 by the study team, through the console, and are
listed in the export ledger.

**Step 4, verify.** On the hospital's store, by hospital IT with the backup private key:
`sha256sum -c SHA256SUMS`; `trialbox backup-verify ARCHIVE/backup/<file> --key <private key>`;
`python tools/audit_verify.py ARCHIVE/audit --heads ARCHIVE/audit/anchor`. All three pass, or the archive is made
again. Keep a second copy on another medium the hospital chooses.

**Step 5, handover.** The trial office receives the archive, the close-out record and the sum of `SHA256SUMS`. It
keeps them as long as the protocol, the sponsor agreement and national GCP rules say, and at least the audit
retention of IT pack A.5 (10 years). The backup private key that opens the final backup goes with it, in the
envelope (§23); without it the backup cannot be read. Nothing in steps 6 to 8 starts before the trial office has the
archive and step 4 has passed.

**Step 6, crypto-erase.** Destroy the keys first, so every copy left anywhere is unreadable:

| Key | Do |
| --- | --- |
| the KEK (steward shares, passphrase, TPM seal) | the stewards destroy their shares; clear the TPM or the platform's KMS key (§23) |
| site keys in the secrets folder (`TB_SECRETS_DIR`) and the `tb-secrets` volume | removed with the volume in step 7; wrapped under the KEK, so already unreadable |
| BitLocker or LUKS keys of the host disks (appliance) | remove the protectors and the recovery keys held by hospital IT |
| the backup private key, other copies | every copy except the one in the archive envelope is destroyed |

Only backups in the archive stay readable. Every other backup (the 14 kept, the pgBackRest repository, copies on USB
disks) is then encrypted to a key nobody holds.

**Step 7, purge.** Each **purge** row of the plan, by medium (NIST SP 800-88 Rev. 1, §2.5 and Appendix A; a site that
follows Rev. 2 of 2025 uses the same three categories):

| Medium | Category | Method | Verify |
| --- | --- | --- | --- |
| NVMe SSD of the box | Purge | `nvme sanitize -a 4` (crypto erase) or `-a 2` (block erase); else `nvme format --ses=2` | `nvme sanitize-log` says done; read back a sample |
| SATA SSD | Purge | ATA SANITIZE (`hdparm --sanitize-crypto-scramble` or `--sanitize-block-erase`) | read back a sample |
| hard disk (NAS, USB disk) leaving the hospital | Purge | ATA SECURE ERASE or SANITIZE overwrite; or Destroy | read back a sample |
| hard disk the hospital reuses inside | Clear | one overwrite of the whole disk (`shred -n 1 -z` on the device) | read back a sample |
| USB flash stick, SD card | Destroy | most cannot be purged: shred or disintegrate | the destroyer's record |
| folders on a shared store (NAS share, pgBackRest repository, backup targets) | Clear (logical) | delete the folders; they hold only encrypted backups whose key step 6 destroyed | list the folder empty |
| volumes on a hospital platform (§17) | Purge by crypto erase, else Clear (logical) | the platform team deletes the volumes and their storage-class keys | the platform's deletion record |
| paper (printed lists) | Destroy | cross-cut shredding | the shredding record |

The host disks go last, after every other row. The audit archive and the anchor folders are **keep** rows: they are
in the archive and stay with the hospital for their retention; they are not purged.

**Step 8, certificate.** One certificate per medium or shared store, on the template
`docs/plan/sites/purge-certificate.md` (English, 日本語, 繁體中文; the fields of NIST SP 800-88 Rev. 1 Appendix G).
The person who did the purge fills it; the hospital keeps it with the close-out record. Report back to Aimedics only
the line of the close-out record's last section (date, media count, no names).

## Per site

| | Japan (appliance, §8 or §10) | CGMH (shared B200 server, §17) |
| --- | --- | --- |
| Step 2 stop | `systemctl stop trialbox` | the platform team scales the TrialBox deployment to zero |
| Step 3 store | the hospital share named in `TB_BACKUP_TARGETS` | the hospital store the 資訊室 names |
| Step 6 KEK | stewards' shares, the TPM is cleared | KMS key, or the 2-of-3 shares with the 資訊室 (IT pack A.6) |
| Step 7 disks | the box's NVMe disks are sanitized; the box may then be reused or returned | the platform team deletes the volumes and the MIG reservation; no disk leaves the hospital |
| Certificates | one per box disk, USB disk and share | one for the platform volumes (by the platform team), one per share and USB disk |
