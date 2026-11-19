# D-1321 `--no-backup` needs a reason on a PRODUCTION box (10G-3)

- **Task:** lane H, plan 10 row 10G-3 (review 16, item 16-18): correct the stale security page and refuse
  `--no-backup` in PRODUCTION without a reason. · **Date:** 2026-11-18
- **Decision:**
  - `tools/apply_update.sh` and `python -m tools.trialbox update` take a new option, `--no-backup-reason REASON`,
    beside `--no-backup` (which is unchanged). On a PRODUCTION box `--no-backup` without a reason is refused before
    anything is read or changed, exit 2. A reason alone, without `--no-backup`, is a usage error (exit 2).
  - The box's environment is read as the update path reads it (D-633): the last `TB_ENV` line of `deploy/.env`; with
    none, the rehearsal mark `deploy/site/rehearsal.json` makes it TEST; otherwise, and for any name that is not DEV,
    TEST or VALIDATION, it is PRODUCTION. Never the process environment. The demo target is DEV, as before.
  - DEV, TEST and VALIDATION take `--no-backup` as before, with or without a reason.
  - A given reason is audited as `update.backup_skipped` (`bundle_id`, `reason`, at most 500 characters) where the
    backup step would run, and written in `deploy/updates/history.jsonl` on the "backup skipped" line, as
    `--allow-downgrade REASON` is audited as `update.downgrade` (D-210). `update.applied` keeps `backup: false`.
  - The guard sits at the two command-line entries, not in `Updater.run` or `main_apply`: the update path's Python
    callers (tests, drills) keep their signatures and behaviour.
- **Held by:** `tests/unit/test_no_backup_needs_a_reason.py`.
