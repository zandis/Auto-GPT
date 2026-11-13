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
2. **A Windows drive counts as off-box only when Windows said it is an outside disk and the disk itself carries
   that statement.** Three things must hold:
   - the Windows installer recorded the PC's own drives on the box (`wsl-setup.sh windows-drives`, kept in
     `deploy/site/box/windows-drives`): every fixed drive Windows lists, less those on a disk attached by USB,
     and always the system drive and the data drive;
   - the drive's letter is none of them;
   - the drive's own root carries the mark `.trialbox-outside-drive`, which `box-install.ps1 -BackupDrive E:`
     writes after asking Windows what the drive is: only a disk attached by USB (`Get-Disk`, `BusType`) that is
     none of the PC's own is marked.
   The first form of this card took any letter outside the record as off-box. The review showed that is the
   wrong way round: a letter an internal volume gets after the install, a letter made with `subst`, or a record
   that lists too few drives would each have passed a PC's own drive as off-box. With the mark, an unknown letter
   is **not** off-box, and the mark goes where the disk goes: a letter that later names another volume has none.
   A mark on one of the PC's own drives changes nothing. **Without the record no Windows drive counts.**
   What is refused that a site might want: an outside disk on Thunderbolt, eSATA or a card reader (Windows does
   not list it as USB, so the installer cannot tell it from an internal one). Such a site uses the share, or
   states it itself with D-274's `.trialbox-offbox` file in the target folder, which still stands.
3. **A share is recognised in both forms WSL2 writes it** (the UNC path as the source, or in the options of a
   drvfs mount), and **a share of the PC itself is this box**: `\\localhost`, `\\127.0.0.1`, `\\wsl.localhost`,
   `\\wsl$`. A mount line is read as a Windows drive or share only when it is plainly one: the file system `9p`
   (`drvfs`), `aname=drvfs` where the path is taken from the options, and the source and the options agreeing.
   D-274's rule "a declared target on another device is off-box" is not applied to a Windows drive: under WSL2
   every Windows drive is another device than WSL2's own disk, the data drive too.
4. **The path's speed is measured, and the limit held against it.** `wsl-setup.sh backup-speed <folder> <MiB>`
   writes that much there, waits until it is on the disk, removes it and records MB/s and the MiB written, one
   line per path (`deploy/site/box/backup-speed`). It refuses to write more than half the free space, and it
   writes to a file it made itself under a name nobody can know beforehand, never through a link: it runs as
   root on a share or a disk that others can write to. `trialbox doctor`'s `backup_speed` (WSL2 only): FAIL when
   `TB_BACKUP_MIN_MBPS` is above the measured speed (every large step would be stopped as hung) or is not a
   speed; WARN when it is above a tenth of it (the margin D-455 chose), when a target was never measured, or when
   it was measured with less than `TB_BACKUP_SPEED_TEST_MIB` (declared, 1024: enough to get past Windows' write
   cache, which is a reason and not a measurement; here 1 MiB read 200 MB/s and 256 MiB read 1000 MB/s on the
   same folder). The line names the value to set, rounded down so that setting it clears the line. A measurement
   is keyed by the path: after a share or a disk is changed it must be taken again, and the line says so.
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

Proven here (`tests/unit/test_wsl2_backup_paths.py`; Pester for the installer's logic): the classification on
written mount lines in both forms, with and without the record and the mark; that a mark on an own drive, a
record with too few drives, a Linux mount, a line naming two drives, a folder of a drive and a share of the PC
itself are all "this box"; that the record and the mark reach the box's own check (`status`); the readers'
refusals, a record that is not text included; the measurement on a temporary folder (the file removed, one line
per path, no write through a planted link, no filling of the target); `backup_speed` at each threshold, with the
value it names clearing the line; the installer telling the drives once and marking only a USB disk that is not
the PC's own. `tests/unit/test_backup_schedule.py` is unchanged and passes.

Not proven, all on the P-0 sheet (Part 8): what WSL2 really prints in `/proc/mounts` for a drive and a share
(line 64); `Get-TbOwnDrives`, `Get-TbDriveBus` and the writing of the mark, which only Windows can run: that
`BusType` separates outside drives from the PC's own on real hardware (lines 63 and 64a); any speed (line 66);
that a backup to an outside drive runs with nobody signed in (line 69), and what a share does there (line 70).
That a path through Windows is slower than WSL2's own disk is expected from Microsoft's description of the 9p
path, not measured; that S4U carries no network credentials is Microsoft's documentation, tested by line 70.

## Consequences

- `tools/trialbox/backup_schedule.py` (shared with lane D): `target_kind` takes one more optional argument and
  `_mounts` returns the options too; behaviour without the record is unchanged. Named to the integrator.
- `TB_BACKUP_MIN_MBPS`'s default stays 5 until line 66 gives a figure for a path through Windows.
- RUNBOOK §5 (lane D's) can point to `docs/handover/WINDOWS-BACKUP-RESTORE.md` for the Windows form.
