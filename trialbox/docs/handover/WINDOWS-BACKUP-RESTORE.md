# Backup and restore on a Windows workstation (NEW-WIN-7, D-608)

**Reader:** the box owner, with hospital IT.

For the box owner and the hospital's IT. The backup itself is the same as on any box (RUNBOOK §5: one encrypted
file per night, `trialbox backup-nightly`, written to every folder of `TB_BACKUP_TARGETS`). What is different on
Windows is where those folders may be, how fast they are, and what a restore on another machine starts with.
Nothing on this page has been run on Windows yet; the rehearsal is P-0 lines 63 to 70.

## Where the backup must go

TrialBox lives in WSL2's virtual disk (one file, `ext4.vhdx`, on the data drive). A backup that stays in that
file, on the data drive, or on the system drive is lost with the PC. A target counts as off-box only when it is:

- **the hospital's share**, mounted inside WSL2 (`/mnt/share`, from `\\server\share`); or
- **an outside drive** (a USB disk with BitLocker), mounted inside WSL2 under its letter (`/mnt/e`). It counts
  once the installer has checked it with Windows and marked it. With the disk plugged in, in an administrator
  PowerShell: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<media>\windows\box-install.ps1" -BackupDrive E:`. Only a disk attached by USB that is none of the
  PC's own drives is marked; the mark is a small file on the disk, so it goes with the disk. A disk on
  Thunderbolt, eSATA or a card reader is refused (Windows does not say it is outside): use the share.

After any change of disks in the PC (a disk added, removed, or a drive letter changed), start the installer once
more: it tells TrialBox again which drives are the PC's own.

`trialbox doctor`'s `backup` line says for each target what it is; in PRODUCTION it fails when no target is
off-box. `/mnt/c`, `/mnt/d` (the data drive), any folder inside WSL2, a share of the PC itself (`\\localhost`)
and a drive letter made with `subst` are "this box".

The backup file is encrypted to the hospital's backup key whatever the target; BitLocker on an outside drive
protects the drive when it is carried.

## How fast the path is

A path through Windows is expected to be much slower than WSL2's own disk (not measured yet; P-0 line 66). A backup step is stopped as hung when it runs below
`TB_BACKUP_MIN_MBPS` (5 MB/s by default, a tenth of a box disk; D-455). Measure each target once, and again when
the share or the drive changes:

```
wsl -d TrialBox -u root -- bash /opt/trialbox/deploy/windows/wsl-setup.sh backup-speed /mnt/e/trialbox 1024
```

It writes 1024 MiB there, waits until they are on the disk, removes them and records the speed. It needs twice
that much free space, and less than 1024 MiB does not count (Windows' write cache hides the real speed). Then
`trialbox doctor`'s `backup_speed` line says whether `TB_BACKUP_MIN_MBPS` is at most a tenth of it, and which
value to set in `deploy/.env` when it is not.

## An export of the WSL2 distribution is not a backup

`wsl --export` copies the whole virtual disk as it is at that moment, with the databases running: it is not a
consistent copy of them, it is not encrypted, it holds the site's keys in the clear, and nothing checks it. Do
not make one "to be safe", and never store one on a share. The backup is the nightly encrypted file.

## Restore on a second machine

1. On the new PC: the offline media and `Install-TrialBox.cmd`, to the end (the same release as the backup's).
2. Attach the backup target (the share, or the outside drive) and bring the private backup key (hospital IT holds
   it; it is never on the box).
3. Inside WSL2: `trialbox restore <file> --key <private key> --yes` (RUNBOOK §5 for every step and for what is
   checked first). Do not copy `deploy/site/box/` back from the backup's host part: it holds the old PC's drive
   letters and speed measurements; the new PC's installer wrote its own. Measure the backup path again.
4. `trialbox doctor`, then the first night.

The BitLocker recovery keys of the new PC are new: the owner confirms them at the install, as the first time.
