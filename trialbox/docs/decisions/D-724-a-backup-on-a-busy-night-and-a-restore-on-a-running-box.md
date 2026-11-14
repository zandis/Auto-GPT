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
   `flock` every `tb_common.audit` write takes) the backup reads `HEAD.json`'s bytes and the length of every day
   file, then lets go; it copies `HEAD.json` from the bytes read and each day file up to that length. The lock is
   held for those reads, not for the copy, so the box's writers wait microseconds, not the backup. The backup
   never makes the lock file (it runs as root; a lock file it made would be root's, which the writer could not
   open): a box with no lock file has never written its chain.
2. **A restore gives the owners back.** The owner of each file is read from its member of the backup (the `data`
   filter still guards the paths and modes) and given back after the folder is put in place; each folder gets the
   owner of the folder it replaced (else of the files' first owner). Files the restore writes itself (its own
   audit events, the writer's lock file) get the folder's owner, after its last audit event. Only as root: a user
   who is not root cannot give a file away, and the files are then its own.
3. **A restore of a box refuses while services other than the database run.** `trialbox restore` asks compose
   (`docker compose ps --status running --services`) and refuses, before anything is read or changed, while any
   service but `db` runs, with the command that stops them. Where compose cannot answer, the restore refuses
   unless the operator says the services are stopped (`--services-stopped`). In-process callers (the drills, the
   update's rollback) pass no question and are not asked. The runbook (sections 5 and 22) says to stop them.

## Test

`tests/unit/test_backup_busy_night.py`: an event written between the copies of the day file and of the head
anchor, in either order, leaves a backup whose chain verifies (before: "the chain ends at event 3, the head anchor
says event 4"); the backup never makes the lock file; a restore gives every file the owner its member had and
every folder the folder's owner, including the files it wrote itself (as root; not as another user); a restore is
refused while other services run, or while compose cannot say, and nothing changes; the command asks compose, and
`--services-stopped` is the operator's word. Five existing tests that drive `trialbox restore` where there is no
compose now pass `--services-stopped`; their assertions are unchanged.

## Not covered

- A failed restore (`backup.restore_failed`) after the folders were placed: the owners are given back when each
  folder is placed, but the failure's own audit event is written as root afterwards.
- The platform's restore job (`tools/trialbox/platform_day2.py`): it does not ask which pods run.
- Not run on a box: the owners are given back through `os.chown`, tested by recording the calls (no second user
  in this session); the compose question is tested with a stand-in.
