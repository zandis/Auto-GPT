# 22. Disaster recovery with measured RPO and RTO

**Reader:** the box owner, with Aimedics.

*T-635, D-390. The backup, the restore commands and point-in-time recovery are §5; this page is the plan around them:
what is lost, how long it takes, who brings what, and how the numbers are measured. Parts of this section: a planned
power cut, moving the box, replacing hardware.*

**Drill (T-213b):** none. The timed restore is not rehearsed by a test: it needs a real compose box with the
50,000-patient synthetic set (T-213b), and the table below stays empty until it is run. The restore itself is
checked in process by `tools/backup_drill.py` (correct, not timed).

## The numbers

**No restore has been measured yet.** The restore drill on master (`tools/backup_drill.py`, `make backup-drill`) runs
in process on a small synthetic set: it proves the restore is correct, not how long it takes. The numbers below are
**targets**. T-213b measures them on a real compose box with the 50,000-patient set and writes the measured value
into the last column and into the IT pack (A.8).

| | Target | How it is reached | Measured (T-213b) |
| --- | --- | --- | --- |
| RPO, nightly backup only | 24 hours | one `.tbbak` a night (§5, 04:45); the next night's feed replays the lost ingest; the audit chain lists the day's marks and entries to redo | not measured yet |
| RPO, WAL archiving on | 5 minutes (database) | pgBackRest archive timeout (§5, point-in-time restore); files outside the database still follow the nightly backup | not measured yet |
| RTO, software fault, same hardware | 4 hours | reinstall from the release media, restore from the hospital's share with the key holder present | not measured yet |
| RTO, hardware lost or dead | 5 working days | a loaner box from Aimedics, then the same restore | not measured yet |

*The last row is the default until the owner answers (TB-DR-09 Q5).* It assumes Aimedics keeps one loaner box (the
acceptance box, or the Spark if that form is not chosen) that can reach either site within five working days. If
there is no loaner, the hardware RTO is the supplier's lead time for a new GPU box, which can be weeks; the IT pack
must then say so. The older design baseline (TB-DS-00 N-15) wrote RTO 2 working days; the IT pack's 4 hours on the
same hardware is the stricter target and the one this page holds.

## What a restore needs (have it before the day)

| Item | Where it is | Who brings it |
| --- | --- | --- |
| the newest good `.tbbak` and its `.sha256` | the hospital's off-box share (`TB_BACKUP_TARGETS`) | hospital IT |
| the backup private key | the sealed envelope (§5, Backup) | hospital IT, the envelope holder |
| the pgBackRest cipher, if WAL archiving was on | with the backup key (§5) | hospital IT |
| the KEK: steward shares, the passphrase, or the TPM | §23; a TPM-sealed KEK only unseals on the same board | the key stewards |
| the release media (the signed bundle of the installed version) | the hospital's copy of the media, or Aimedics | site administrator |
| the vendor reference data pack the backup names | `deploy/refdata/loaded` copy beside the backups, the bundle, or Aimedics | site administrator |
| the site's network values (name, address, certificate) | the network sheet (`tools/network_sheet.py`) and §12 | hospital IT |

Check the list each quarter with the drill below. A missing item is the most likely reason a restore takes days.

## The restore, with the clock

Start the clock when the site decides to restore. Write the time at each step on the tabletop record of the site
(`docs/plan/sites/tabletop-record-japan.md`, `docs/plan/sites/tabletop-record-cgmh.md`).

1. Decide: software fault (same hardware) or hardware loss (go to "Replacing hardware" first).
2. Reinstall from the release media (§1). Unseal the KEK (`python -m tools.keys unseal`, §23).
3. `trialbox backup-verify <file> --key <private key>`: note the `refdata_packs` it names. A box whose nightly sent
   the lake to restic adds `--restic-from-box` (the KEK unsealed) or `--restic-share <file>` once per custodian's
   share, here and to the restore in step 4 (§5, "A box whose nightly sends the lake to restic").
4. `sudo trialbox restore --last --key <root-only copy of the private key> --yes --restart` (§5, "Restore over the
   live stack, one command"), or by hand: stop every service but `db`, then `trialbox restore <file> --key <private key> --yes
   --refdata <folder>` (§5; the restore refuses while another service runs). Add `--dir host=<folder>` to get the
   host part back (`deploy/.env`, settings, the site folder, the Caddy and Authelia volumes).
5. With WAL archiving: restore to the last second the archive holds (§5, step 5 of point-in-time restore).
6. `trialbox doctor --env-file deploy/.env`: no FAIL. Run the pair canary (`trialbox selftest` on the box).
7. Open the console from a clinic PC; sign in; the Operations page shows the restored backup.
8. Stop the clock. Tell the users what to redo: the audit lists the marks and EDC entries made after the backup.
9. Run `backup-nightly` by hand, so a new chain starts.

## The quarterly drill

Each quarter and at IQ, with hospital IT: steps 3 and 6 on a spare machine or the acceptance box (a full step 1 to 9
once a year), plus the check of the list above. `backup-verify` proves the key still reads the backups. Write the
times on the site's tabletop record; a step that took longer than the target is a ticket (§21).
