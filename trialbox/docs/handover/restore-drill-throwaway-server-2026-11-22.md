# The restore drill runs in a throwaway server (2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer. For builders, so in
one language.

Card H-84 (high-risk: a restore of the box's data). The integrator's option (d): the drill restores into a separate
throwaway database server, so that no role in it can reach the live one, and D-892's one command is kept.

## Pull request body (draft)

**What changes for a box.** `sudo python3 -m tools.trialbox restore-drill <file> --key <key>` is typed as before.
It no longer connects to the box's database at all. It starts a one-off container of the box's own database image
(`POSTGRES_IMAGE`, else `deploy/images.lock`; `--pull never`), named `tb-restore-drill-<id>`, labelled
`tb.restore-drill=<id>`, with `--network none`, no published port, `--read-only`, `--cap-drop ALL`,
`no-new-privileges`, `--user 999:999`, 1 GB of memory (no swap), 256 processes, 256 MB of shared memory, and exactly
three mounts: its data folder (under `--db-dir`, default `--work`) and its socket folder (at
`/var/run/postgresql` and at its own path). `initdb` runs first in a one-off container of the same kind with the
password in a 0400 file that is removed when it exits; the server then listens on the socket only
(`listen_addresses=`), scram-sha-256 locally and `reject` for any host. The scratch databases are made there; the
restore is `docker exec -i -e PGPASSWORD <throwaway> pg_restore` with the very flags of `backup.restore_db`
(`TB_PG_RESTORE_CMD` is replaced for the drill: on a box it is an exec into the live `db`); the comparison with the
manifest is unchanged. Everything is removed at the end, after a failure, Ctrl-C and SIGTERM too (exit 130). What a
drill makes is written to `deploy/site/restore-drill/<id>.json` before it is made; the next drill sweeps what a
crashed one left: containers by the label (and the record), folders only when they carry the drill's mark. New
refusals (exit 2, nothing started): Docker not available, the image not on the box, too little memory, a drill
still running (a lock). No refusal was removed. Space: the unpacked backup and the throwaway's data are added when
they are on one file system. `--db-dir` now means the throwaway's data folder (was: the folder for the space check,
default Docker's root).

**The invariant test:** `test_a_drill_never_touches_the_live_server_or_any_object_of_the_box` in
`tests/unit/test_restore_drill.py` (four cases:
pass, a failed restore, a manifest mismatch, a server that never started), with the same assertions after SIGTERM and
after a `kill -9` followed by the next drill's sweep
(`test_sigterm_cleans_up_and_a_crash_is_swept_by_the_next_drill`). The live URL points at a planted TCP listener that
counts connection attempts (zero), `TB_PG_RESTORE_CMD` is the box's exec into the live `db` (never called), and the
stand-in `docker` holds the box's own container, volumes and networks plus look-alikes (unchanged after).

**What is not verified.** No real Docker run: the unit tier has no daemon, so the container argv, the double
socket mount, `initdb` in the image, the readiness wait and the chown to 999 are shown on a stand-in only. The
restore, the comparison and the drops run on a real PostgreSQL (pglocal) through the drill's own socket folder. To
prove it on the bench, see "Bench check" below. The drill still cannot run on an installed box for reasons outside
this card (H84-03, H84-04).

## Why (d) and not (a)

A decision record would be lane H's; its number block is used up (question: a decision number).

- **Decision.** The restore drill restores into a throwaway database server of its own (a one-off container of the
  box's database image with no network), never into the box's server.
- **Why not (a)** (revoke CONNECT from PUBLIC on the live databases with a migration): it changes live grants on
  every box to make a drill safe, it has to keep holding for every future database, role and default privilege (the
  failure that started this card was a default nobody had looked at), and the drill would still need a role that can
  create databases on the live server, which the box takes away on purpose (`ALTER ROLE trialbox NOCREATEDB`, D-378).
  With (d) the question cannot arise: the throwaway has no route to the live server (no network, no shared volume, no
  shared socket), and nothing of the live server's roles or grants changes.
- **Cost.** The drill needs Docker, the image and 1 GB of memory on the host; it can no longer run where there is no
  Docker (the dev/CI drill is `tools/backup_drill.py` on pglocal, unchanged).

## How the throwaway is reached, and why a socket folder

Through a Unix socket folder of the drill's own, bind-mounted into the throwaway at `/var/run/postgresql` (the image's
default, so its entrypoint works unchanged) and at its own host path (so one libpq DSN, `host=<folder>`, works both
in the throwaway and here). Why not `docker exec` for everything: the row counts, the content hashes, the schema drop
before the restore and the copy of the hospital's reference rows are libpq calls of `backup.py`
(`row_counts`, `site_row_counts`, `_drop_schemas`, `_copy_in`); through the socket they run unchanged, so the drill
compares exactly as `trialbox restore` does. `pg_restore` itself runs inside the throwaway (`docker exec`): the host
has no PostgreSQL tools, and the image's `pg_restore` is of the backup's major. The socket folder sits in a 0700
folder of root's, so on the host only root can reach it.

**The password.** Random per drill. Not in any argv (checked on every call), not in the containers' configuration
(no `-e` on `docker run`), not in the record, the result or the audit. Unavoidable: it is in the drill process's
environment (`PGPASSWORD`, for libpq) and in the `docker exec` client's environment (`-e PGPASSWORD` takes it by name)
for the drill's length; `/proc/<pid>/environ` is readable by root and the same user only. It is on disk, 0400 and the
database user's, in 0700 folders, while `initdb` runs, and removed when it exits (checked: absent when the server
starts).

## The two claims of the survey

- **`trialbox` cannot create a database: confirmed** from the code (`deploy/docker/db-init/30-service-roles.sh:48`,
  `ALTER ROLE trialbox NOCREATEDB`; `tests/unit/test_db_roles.py:236`). On master the drill's `CREATE DATABASE` runs as
  `trialbox` (the TB_DB_URL install.sh writes, `deploy/install.sh:468`). The drill's test passed because it runs as
  the pglocal superuser. H84-01.
- **The host cannot reach `db:5432`: confirmed** from the code: TB_DB_URL names `db`, a name of the compose network,
  and `deploy/docker-compose.yml` publishes no database port (as H33-04). H84-02.
- Both are gone with this card: the drill connects to no live server and creates nothing there.

## Bench check (what a person must run)

On a bench box with Docker, the image built (`make images`) and a backup with its key:

1. `docker ps -a --format '{{.Names}}' > before; docker volume ls -q >> before; docker network ls -q >> before`.
2. `sudo python3 -m tools.trialbox restore-drill <file> --key <key>`; in a second terminal while it runs:
   `docker inspect tb-restore-drill-<id> --format '{{.HostConfig.NetworkMode}} {{.HostConfig.PortBindings}}
   {{json .Mounts}} {{json .Config.Env}}'` (`none`, no ports, three bind mounts, no password),
   `docker exec tb-restore-drill-<id> getent hosts db` (nothing), and `ps -eo args | grep -c 'PGPASSWORD='`
   (0: the password is on no command line).
3. The live server's log (`docker compose --project-directory deploy logs db`) shows no connection during the drill.
4. After: the three lists equal `before`; no `tb-drill-*` folder in `/tmp`; exit 0 and `"ok": true`.
5. Again with `kill -TERM` during the restore (exit 130, nothing left) and with `kill -9` (the container and folders
   left; the next drill's result lists them under `swept`).

Until H84-03 and H84-04 are settled, step 2 needs the drill run where its Python has `psycopg`, `cryptography` and
`zstandard` and `TB_DB_URL` is set (for the database names only).

## Findings

| Id | Severity | Claim | Basis | State |
| --- | --- | --- | --- | --- |
| H84-01 | High | on master the drill runs CREATE DATABASE as `trialbox`, which the box makes NOCREATEDB: the drill cannot run on an installed box | shown | open (this card fixes it) |
| H84-02 | High | on master the drill connects to `db:5432` from the host, which neither resolves nor is published: the drill cannot run on an installed box | shown | open (this card fixes it) |
| H84-03 | High | the drill is typed with the host's `python3`, which install.sh gives only `python3-yaml`; `tools/trialbox/backup.py` imports `zstandard` and `cryptography` at the top and the drill needs `psycopg` | hypothesis | open (question) |
| H84-04 | Medium | `sudo` drops the operator's environment, so `TB_DB_URL` (read for the database names) is not set and the drill refuses at once | hypothesis | open (question) |
| H84-05 | Medium | a drill killed during its restore left the decrypted backup (`tb-drill-*` in `--work`) with no record: nothing cleaned it up | shown | open (this card fixes it) |

H84-03 rests on `deploy/install.sh:212-213` and the comment at `tools/trialbox/ops.py:573-574` ("the host's python3
has no zstandard or cryptography"); not run on a box. H84-04 rests on `tools/trialbox/__main__.py` reading
`os.environ` only; not run on a box. Either one means the drill still cannot be typed as the runbook says; the fix
(run the drill's Python in a one-off `trialbox-py` container with the socket folder mounted, or load `deploy/.env`
for the names) touches the host-tool runtime, outside this card. H84-05 was found by this card's own crash test.

## Mutation pass

22 mutants of `tools/trialbox/restore_drill.py`, each alone, against `tests/unit/test_restore_drill.py`: 21 caught.

Caught: `--network bridge`; a box volume mounted; the SIGTERM handler gone (no clean-up); the sweep's label check
dropped; a folder swept without the drill's mark; the live DSN used for CREATE DATABASE; the password on the
`docker exec` command line; the result naming the server before it started; the result listing databases that were
not dropped; the box's `TB_PG_RESTORE_CMD` kept; `--pull never` dropped; a port published; the password file kept
after initdb; the unpacked folder left out of the record; the memory check gone; the lock gone; a hard-coded image;
no memory limit; the clean-up skipped; a container removed without its label matching the record; `--user` dropped.

Survived (equivalent): `docker ps` filtered by name in place of the label. The per-container label check after it
still removes only labelled containers, so nothing unlabelled is touched (the look-alike stays); the label filter is
the first of two guards. Three mutants first survived on the sweep's layered guards; a test of each guard alone
(`test_the_sweep_removes_only_the_drills_own_containers_whatever_docker_lists`, with a `docker ps` that ignores its
filter) was added, and two of them are now caught.

## Questions

- A decision number for "the restore drill runs in a throwaway server; why not (a)" (lane H's block is used up).
- H84-03 / H84-04: the drill's Python on a box (no `psycopg`, `cryptography`, `zstandard` on the host; `sudo` drops
  `TB_DB_URL`). The fix touches the host-tool runtime (a one-off `trialbox-py` container for the drill, the socket
  folder and Docker's socket mounted, or the names read from the backup's manifest): which card, which lane.
