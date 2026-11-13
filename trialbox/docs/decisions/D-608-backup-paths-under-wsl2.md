# D-608 Backup paths under WSL2: what counts as off-box, and a limit that fits the path's speed

- **Task:** NEW-WIN-7 (`docs/plan/33-plan-v7.md` section 2.3; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-7-backup-paths`), stacked on NEW-WIN-6 (D-607)
- **Date:** 2026-11-13
- **Status:** accepted for the rules and their logic. No mount line and no speed in it was seen on Windows:
  rehearsed at P-0 (lines 63 to 70), which also decide which target works with nobody signed in
- **Owner decisions:** D-494 (the Windows form), OD-10 (no figure that is not measured or a declared setting)
- **Builds on:** D-274 and D-187 (the nightly backup and its off-box rule), D-455 (a step's time limit from
  `TB_BACKUP_MIN_MBPS`), D-600 and D-602 (the installer; the boot task's sign-in)

## Context

On a Windows workstation TrialBox's data is one file, WSL2's virtual disk, on the data drive. The backup check
(D-274) asks for a target "off the box" and knows network file systems and USB block devices. Under WSL2 it saw
neither: an outside USB drive appears as a Windows drive (`/mnt/e`, file system `9p`), which the check called
"this box", so a site that did the right thing failed the check and a site could only pass it with the share. And
the step limit of D-455 (5 MB/s, a tenth of a box disk) was never held against a path that goes through Windows.

## Decision

1. **A backup target must be outside the virtual disk and outside the PC**: the hospital's share mounted inside
   WSL2, or an outside drive. A folder inside WSL2, on the data drive or on the system drive is "this box".
2. **A Windows drive counts as off-box only when it is none of the PC's own drives.** The Windows installer tells
   the box the letters of its own drives (`wsl-setup.sh windows-drives`, kept in
   `deploy/site/box/windows-drives`): the system drive and the data drive always, and every other disk Windows
   does not list on USB (`Get-Disk`, `BusType`). It tells it once, and again when the letters change. The backup
   check reads the drive letter from the mount (the source `E:\`, or `path=E:\` in the options) and counts the
   target as off-box when the letter is not in the record. **Without the record no Windows drive counts**: an
   install made before this card, or a PC where Windows would not list its disks, stays on the strict side until
   the installer has run once more.
3. **A share is recognised in both forms WSL2 writes it** (the UNC path as the source, or in the options).
4. **The path's speed is measured, and the limit held against it.** `wsl-setup.sh backup-speed <folder> <MiB>`
   writes that much there, waits until it is on the disk, removes it and records MB/s
   (`deploy/site/box/backup-speed`). The amount to write is the caller's to name (1024 in the documents: large
   enough that Windows' write cache does not hide the speed; a reason, not a measurement). `trialbox doctor`'s
   `backup_speed` (WSL2 only): FAIL when `TB_BACKUP_MIN_MBPS` is above the measured speed (every large step
   would be stopped as hung), WARN when it is above a tenth of it (the margin D-455 chose) or a target was never
   measured; the line names the value to set. Nothing is changed for the owner.
5. **An export of the distribution is not a backup** (`wsl --export`): not consistent for running databases, not
   encrypted, carries the site's keys, checked by nothing. Said in the handover page; nothing makes one.
6. **Restore on a second machine is the installer, then the restore**: `Install-TrialBox.cmd` to the end, attach
   the target, `trialbox restore`. Written in `docs/handover/WINDOWS-BACKUP-RESTORE.md`.

**What is deliberately not built here.** Mounting the target. Whether a drive plugged in later is mounted by
itself, and whether a share can be reached from the boot task's sign-in at all (S4U carries no network
credentials, by Microsoft's documentation of the task scheduler), are exactly what P-0 lines 64, 69 and 70 find
out; a mount step written before that would be a guess. If the share fails unattended, mounting it by CIFS inside
WSL2 is a card of its own (it needs a credential kept on the box, which is an owner decision).

**Reuse check.** The existing backup, its off-box rule and its doctor line are used and widened; `dd` measures
the speed. `fio` would measure more and is not on the media; one sequential write is what a backup step does.

## What is proven here, and what is not

Proven here (`tests/unit/test_wsl2_backup_paths.py`; Pester for the installer's part): the classification on
written mount lines in both forms, with and without the record; that a Linux mount is never taken for a Windows
drive; the record's and the measurement's parsing and refusals; the measurement on a temporary folder (the file
is removed, the speed recorded); `backup_speed` at each threshold; the installer telling the drives once, the
system drive always among them, and going on when Windows lists no disks. `tests/unit/test_backup_schedule.py` is
unchanged and passes: without a record every Windows drive is judged as before.

Not proven, all on the P-0 sheet (Part 8): what WSL2 really prints in `/proc/mounts` for a drive and a share
(line 64); that `BusType` separates outside drives from the PC's own on real hardware (line 63); any speed (line
66); that a backup to an outside drive runs with nobody signed in (line 69), and what a share does there (line
70).

## Consequences

- `tools/trialbox/backup_schedule.py` (shared with lane D): `target_kind` takes one more optional argument and
  `_mounts` returns the options too; behaviour without the record is unchanged. Named to the integrator.
- `TB_BACKUP_MIN_MBPS`'s default stays 5 until line 66 gives a figure for a path through Windows.
- RUNBOOK §5 (lane D's) can point to `docs/handover/WINDOWS-BACKUP-RESTORE.md` for the Windows form.
