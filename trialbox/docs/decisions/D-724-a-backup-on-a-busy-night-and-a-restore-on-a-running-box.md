# D-724 A backup on a busy night, and a restore on a running box

- **Task:** BACKUP-RESTORE (lane G's data review of 2026-11-13: DATA-009, DATA-010, DATA-011; the owner's order
  through the integrator)
- **PR:** this branch (`agent/BACKUP-RESTORE-a-busy-night-and-a-running-box`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-126 (backup and restore), D-272 (the audit head anchor), D-455, D-522, D-573

## Context

1. **DATA-009.** The backup copied the audit day file (`audit/<day>.jsonl`) and then `HEAD.json` (the walk's
   order). One event written in between gave a copy whose head anchor says one event more than its chain:
   `verify` fails, and a restore of it raised `AuditAnchorBroken` after the databases and folders were already in
   place. The drill could not see it: its box is idle while it backs up.
2. **DATA-010.** The restore extracted with the `data` filter (no owners) and put each folder back with
   `shutil.copytree` and `mkdir` as root: every file and folder of a restored volume was root's, and the services,
   which run as their own user, could not write their volumes after it.
3. **DATA-011.** The restore renamed each volume's data aside while the services ran; a running service went on
   writing the renamed copy, and those writes were lost.

## Decision

1. **The audit chain is copied as it stood at one moment.** Under the writer's own lock (`audit/.lock`, the
   `flock` every `tb_common.audit` write takes) the backup lists the audit folder, reads `HEAD.json`'s bytes and
   takes each day file's length up to its last whole line; then it lets go. It copies `HEAD.json` from the bytes
   read and each day file up to that length, and every day file the moment saw, also one the writer started after
   an earlier listing (the day changed, or the first event ever). So the copy's chain ends where its head anchor
   says, even when the writer cuts a torn last line and writes on before the copy. The lock is held for those
   reads, not for the copy. The backup never makes the lock file (it runs as root; a lock file it made would be
   root's, which the writer could not open): a box with no lock file has never written its chain.
2. **A restore gives owners and modes back.** Each file gets the owner and mode of its backup member (the `data`
   filter still guards the paths; no set-id bit is given back). Each folder gets the owner and mode of the same
   folder it replaced, else of the volume's top folder. A file the restore writes itself gets the top folder's
   owner, after its last audit event. Every audit write of the restore (its events, the hold flag's, a failed
   restore's) gives what it made in the audit folder to the folder's owner. Owners only as root: a user who is not
   root cannot give a file away, and the files are then its own.
3. **A restore of a box refuses while services other than the database run.** `trialbox restore` asks compose
   (`docker compose ps` for services running, restarting or paused) and refuses, before anything is read or
   changed, while any service but `db` does, with the command that stops them. Where compose cannot answer, the
   restore refuses unless the operator says the services are stopped (`--services-stopped`). In-process callers
   (the drills, the update's rollback) pass no question and are not asked. The runbook (sections 5 and 22) says to
   stop them.

## Test

`tests/unit/test_backup_busy_night.py`: an event written between the copies of the day file and of the head anchor
(before: "the chain ends at event 3, the head anchor says event 4"); a new day file started after the folder was
listed, the first event ever written then, and a torn last line repaired between the moment and the copy (each
found by the review by running; each failed before its fix); the backup never makes the lock file; a restore gives
every file the owner its member had and every folder the folder's owner (by recording the calls); a restore keeps
the modes of folders (0700) and files (0660); a failed restore leaves no audit file only root can write; a restore
is refused while other services run, or while compose cannot say, and nothing changes; a restarting or paused
service counts as running; the command asks compose, and `--services-stopped` is the operator's word. Five
existing tests that drive `trialbox restore` where there is no compose now pass `--services-stopped`; their
assertions are unchanged. Run here once more by hand: a writer thread appending as fast as it could with the day
moving every 40 events, 20 backups in a row (661 events, 17 day files): every copy verifies.

## Not covered

- Empty folders, symbolic links and hard links are not in a backup (the walk takes files only; a hard link comes
  back as a separate file). Unchanged by this card.
- The platform's restore job (`tools/trialbox/platform_day2.py`): it does not ask which pods run.
- Host cron jobs (retention, backups) are not compose services and are not asked about.
- Not run on a box: owners are given back through `os.chown`, tested by recording the calls (no second user in a
  CI runner); the compose question is tested with a stand-in.
