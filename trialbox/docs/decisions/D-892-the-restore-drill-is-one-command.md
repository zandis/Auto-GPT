# D-892 the restore drill is one command, and the health page shows its result

- **Task:** T-730d, the integrator's answer on #639 (2026-11-16): the conservative shape
- **PR:** this branch (`agent/T-730d-the-restore-check-runs-from-the-health-page`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

D-126 stands: the box cannot open its own backups; only the private key, kept by hospital IT, does. So the restore
drill of T-730 ("the restore drill runs from the health page") is not started from a web page and no web request
names a key or its path. Instead:

1. `trialbox restore-drill <backup file> --key <key>` (`tools/trialbox/restore_drill.py`) is the whole proof, typed
   on the host with the key in hand: free space first (the unpacked backup, four times the file, in the work folder;
   the scratch databases, twice the file, in the database's folder; short of either it starts nothing and says how
   many GB it needs), `backup.unpack` (every file against the signed manifest), each database restored into a
   scratch database `tb_drill_<id>_<name>` on the same server, rows and content hashes compared with the manifest as
   `trialbox restore` compares them, and the scratch databases and the unpacked files dropped at the end, after a
   failure too. A scratch name that is not a drill's own, or that is the live or the admin database, is refused
   before CREATE, and DROP refuses any name that is not a drill's. Exit 0 pass, 1 fail, 2 nothing started.
2. The result is the box's key-check record (`deploy/site/backup-verified.json`, `tb_common.metrics.record_drill`): a
   pass is a key check with what was compared; a fail keeps the last good check and adds `drill_failed_at` and
   `drill_error`; and an audit event `backup.restore_drill`. Neither holds the key or its path.
3. The health check `backup_verified` (OPS-047) reads it: red after `TB_HEALTH_VERIFIED_DAYS` (100 days, warn after
   90, as before) without a key check or drill, and red at once after a failed drill until one passes. The site's
   interval is that existing setting; no second one is added. A failed drill is also a problem in `backup-status`
   (`backup_schedule.drill_failure`), so it goes through the box's alert route: mail, or the health page (D-735).
4. The Operations page's backups tile shows "Last restore drill: <date>, passed/failed" (red on a fail or past the
   interval), and the backups tab gives the exact command, with the newest backup file's path filled in.

## Test

`tests/unit/test_restore_drill.py` (11): a drill against the test's real database restores into scratch, compares,
drops everything and leaves the live database as the box changed it; the scratch database is never the live one
(refused names, the guard before DROP, a drill whose name would be live fails and changes nothing); a failure part
way still drops the scratch database and the unpacked files; differing rows fail; short space starts nothing; a
wrong key fails with nothing left; the record turns red on a fail until the next pass and red after the interval;
a failed drill is a backup-status problem; neither the key nor its path is in the record or the audit; the command's
exit codes. `tests/console/test_ops_pages.py`: the tile and the tab show the last drill and the command, never a key
path. All new; before this card there was no such command.
