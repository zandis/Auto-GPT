# H99: the box's own update path updates a PoC box

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-99, a red from the MVP walk on the bench host (the integrator, comment 7105785224). It blocked the
  walk's update step (card 1, run 3, with `--no-backup`).
- **Date:** 2026-11-23
- **Decision:** D-1091 (on a PoC box the install, start and update paths stop for five things only), through
  `tools/trialbox/stops.py`.
- **Findings:** [`update-on-a-poc-box-h99-2026-11-23/findings.json`](update-on-a-poc-box-h99-2026-11-23/findings.json)
  (H99-01 to H99-05)
- **Files:** `tools/trialbox/update.py` (the preflight's size reads and its backup check), the new test
  `tests/unit/test_update_poc_box_h99.py`.

## 1. The size of `hapi`

The red named lines 1238 and 1281 of `tools/trialbox/update.py` (`db_bytes`, for the whole update's limit and the
backup's step limits). Those two already read the size on the `hapi` database as `hapi`, and a read that fails there
gives "no size, so no limit" (D-455), never a stop. The read that stops the update is the preflight's space check,
`ComposeBox.space_needs` (line 1374 on master): it asked `SELECT pg_database_size('hapi')` as `trialbox` on
`trialbox_wf`. The real role script (`deploy/docker/db-init/30-service-roles.sh`, D-541) makes `tb_fhir_store` the
owner of `hapi` and takes every right on it from PUBLIC, so `trialbox` may not connect to `hapi`, and
`pg_database_size` of a database needs that right: `permission denied for database hapi`, on every run, with or
without `--no-backup`.

**The fix.** `space_needs` reads each size on its own database, as the role that dumps it (`_dump`, `db_bytes`):
`trialbox` on `trialbox_wf`, `hapi` (the db image's superuser, `POSTGRES_USER`) on `hapi`, with
`pg_database_size(current_database())`. `_psql` takes the role and the database, with the defaults of before.

**The test on the real roles.** A throwaway cluster of its own, with `hapi` as its superuser and a `hapi` database
(as the db image makes them), and the real role script applied. The site box's own command lines
(`compose exec -T db psql ...`) are run by the update's real runner against the cluster's socket. It shows the red
(the master form of the read is refused with the walk's words) and that `space_needs` and both `db_bytes` reads now
return sizes. Run locally against PostgreSQL 16; the test skips only where no PostgreSQL binaries are found (as
`tests/unit/test_db_roles.py` does), and the unit job has them.

## 2. No backup key on a PoC box

No backup key is not one of the five stops. The preflight's backup check (`backup_ready`: the key, and at least one
`TB_BACKUP_TARGETS`) now goes through `stops.stop_or_warn` (the existing helper, no second copy):

- **On a PoC box** (the box's own state, `stops.poc_box(deploy)`: `TB_ENV` in `deploy/.env`, the rehearsal mark;
  never a caller's variable): one warning on stderr, one line `update.backup` in `deploy/site/poc-stops.jsonl`
  (`doctor` shows it), and the update goes on **without the backup**. The skip is audited as
  `update.backup_skipped` (the event `--no-backup-reason` uses) and written in the history as
  `backup skipped (PoC box, H-99: deploy/site/poc-stops.jsonl)`.
- **On PRODUCTION** (and a box that cannot be told): the refusal of before, the same words and the same exit code.

**Which way back.** The simpler of the two: no snapshot of its own. The update already takes its rollback point
before it changes anything: both databases dumped locally (0600 under `deploy/updates/<bundle>/rollback/`, sealed),
the images tagged, the models copied aside, the host tree's release kept. That is what an automatic rollback uses
on every box (the encrypted backup needs the hospital's private key, which the box does not hold, D-126). So on a
PoC box without a key the way back is the rollback point, said plainly in the warning's "skipped" text. What is
lost is the off-box encrypted copy, and the quiet-box stop the backup does before its dumps: the rollback point's
dumps are then taken with the services running, as `--no-backup` takes them today (H99-03).

**The tests, on the real entry.** `trialbox update` through the command line's `main` (as `tools/apply_update.sh`
runs `python -m tools.trialbox update`), on an installed, running site box whose commands the update tests' fake
runner answers (no Docker in a session):

- test_h99_a_poc_box_without_a_backup_key_updates_and_lists_it, for DEV, TEST and VALIDATION: exit 0, the warning,
  no backup container, the rollback point's dumps, one line on the list, the history's step.
- test_h99_production_keeps_its_refusal_whatever_the_caller_exports (the twin), with no caller variable and with
  `TB_ENV=DEV` exported: exit 1, master's line word for word, no list, no dump, nothing loaded. It passes on master
  too.
- test_h99_production_with_the_key_still_backs_up_first.

All four PoC cases and the real-roles test fail on master's `update.py`.

## Changed assertions

None. No existing test asserted the refusal without a backup key on a box whose `deploy/.env` names DEV, TEST or
VALIDATION (the update tests' boxes name no environment: PRODUCTION), and every update test passes unchanged.

## What was not run

- The bench host, Docker, a real update bundle: not run. The size reads ran against the real role script on a local
  PostgreSQL 16 cluster, not the db image.
- The container rehearsal: not run.
