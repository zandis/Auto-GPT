# The live restore starts from the host (2026-11-23)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-100 (the MVP walk's step 8 on the bench host, the integrator's red 7106858719). The backup, `backup-verify` and
the drill passed; the live restore was never run, because it could not start from the host. Three gaps, each fixed
and held by a test in `tests/unit/test_restore_from_the_host_h100.py`.

## Pull request body (draft)

**Gap 1: `backup-nightly --deploy deploy`.** The schedule's entries (`main_nightly`, `main_status`, `main_install`,
`run_backup`, `ComposeOps`) and the job's public key path are made absolute against the working folder, links kept
(`backup_schedule.absolute`). Resolve, not refuse: nothing in the code argues for refusing, and the cron line and the
runbook both type a relative folder. Before, the container engine read the bind source `deploy/secrets/backup.pub`
(and the dump folder `deploy/.backup-*`) as volume names. Test: `main_nightly(Path("deploy"))` from the install
folder on the real `ComposeOps` and `ComposeBox` with the repo's runtime stand-in; every bind source is absolute.

**Gap 2: `trialbox restore` on the host.** The installed command (or a host python without the libraries) now runs
the restore in one container of the release's backup image (`TB_BACKUP_IMAGE`), on the database network, as the
nightly's job runs (`tools/trialbox/box_restore.py`, standard library only on the host):

- what it reads is the box's own `deploy/.env`: the trial database's URL; the hapi database as the cluster's
  superuser (`POSTGRES_USER: hapi` in compose, `POSTGRES_PASSWORD`), the same URL the job builds, the password quoted
  for the URL; each service role's password as compose gives it to the `db` container; the image, the runtime and
  compose; the volume folder. A caller's exported `TB_DB_URL`, `TB_HAPI_DB_URL`, `TB_DB_ROLES_CMD`, `TB_DOCKER`,
  `TB_COMPOSE`, `TB_BACKUP_IMAGE`, `TB_BACKUP_PUBKEY` or `TB_RESTORE_KEEP_DIR` changes nothing (tested);
- the URLs and passwords go as `-e NAME` without a value; no password is on any command line (tested);
- each data volume's folder is bound read-write, so its `_data` moves aside within the volume as the restore always
  did on a host; the backup file's folder, the key, the public key, the reference packs and the role script read-only;
  `--dir name=path` (the host part) made absolute, its parent bound;
- the role script runs inside the container after the trial database is restored (`TB_DB_ROLES_CMD` is the
  container's own `python -m tools.trialbox.box_restore roles`): psql over the network as the superuser, its password
  in psql's environment only;
- the guards stay: `--yes`; the running services, asked of compose on the host, before anything (D-724; the refusal
  moved to `box_restore.py` with its text unchanged, `backup.py` re-exports it); the site, the age, the copy of a box
  that holds data, the rows checked before any folder moves, the hold (inside, unchanged);
- `--restart` (new, the person's word): stop every service but `db` first, ask compose again, and start the stack
  and wait until healthy (`up -d --wait`) only after a complete restore (exit 0) or a held one (exit 4, `hold: held`);
  any other end leaves the services stopped and says why;
- `--last` (new): the backup `backup-nightly` recorded good, still on a target with the same size and sha256.

The real path is held end to end: `sudo trialbox restore --last --key <key> --yes --restart` typed from sudo's bare
environment with the system python (the h88 bare box: install link, stand-in runtime, the test cluster's databases);
the container gets the box's URLs, not the caller's; the role step runs inside; the restored rows equal
`trialbox backup-verify`'s; the audit gets `backup.restored`; the services start again.

**Gap 3: the client tools.** `deploy/docker/backup.Dockerfile` installs the database client tools of the server's
major (16) from the db image's own base and package source (the same index digest as `deploy/images.lock`'s db base),
each package at an exact version, held, its installed version and each tool's major checked at build; the build
stops on a base that is not Debian 13; the image still runs as its own user. The superuser URL comes from the box (gap
2). The installed `trialbox restore-drill` already took the box's settings (`box_drill.py`) and runs `pg_restore` in
the `db` container; it is unchanged.

**The one documented command.** RUNBOOK §5, "Restore over the live stack, one command", at the end of the restore
section (the step-by-step path keeps its lines: H-33's findings quote them by number); §22 step 4 names it first.

    sudo trialbox restore --last --key /media/usb/trialbox-backup.key --yes --restart

**The rehearsal.** `tools/rehearse_box/box.sh live-restore`, the last step on the box: the nightly with
`--deploy deploy` to a rehearsal target under a throwaway key pair, `backup-verify`, the one command; the rows equal
`backup-verify`'s, every service that ran before runs again and is healthy; the box's own settings and records are put
back. It runs only in CI's rehearse jobs: this session has no container engine.

**Not run, not verified here.** The live restore on a real stack (17 services healthy, row counts): the rehearse jobs
and the bench prove it. The backup image was not built (the pinned versions, the base's package source and key path,
and the Python base's suite are read, not built). Shellcheck was not run in this session (the `checks` job runs it).

## Findings

**H100-05, on the restore's path.** A caller who exports `TB_BACKUP_PUBKEY`, `TB_BACKUP_TARGETS`, `TB_COMPOSE` or
`TB_DOCKER` steers none of them during `trialbox restore` typed on the host: the public key and the copy folder
(`__main__._restore_defaults` with the box file), the targets of `--last` (`last_good`, `process_env=False`), the
engine and compose (`BoxRestore`) all come from `deploy/.env`, and the container gets only the names it is given. They
are steered in `backup-nightly`, `backup-status`, `backup-install` (`backup_schedule.config`) and the update's backup
(`ComposeBox`), which this card does not change.

In `restore-from-the-host-h100-2026-11-23/findings.json` (the register's `--add-from` form).
