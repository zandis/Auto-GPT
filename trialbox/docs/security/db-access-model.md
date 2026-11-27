# The database's access model and posture

The box runs one PostgreSQL server (`db` in `deploy/docker-compose.yml`). This page states who may reach it, how, and
what is recorded. It answers finding P2-06 of the 2026-11-27 audit and items D3/D4 of its assessment addendum, as the
integrator ruled them that day.

## Access model: grants per role in 1.0, row-level security in R2

- **1.0 (this release).** Access is by schema and table grants. Each service connects with its own login role
  (`tb_lake`, `tb_adapter`, `tb_console`, …; `deploy/docker/db-init/30-service-roles.sh`), none a superuser, none with
  CREATEROLE, CREATEDB, REPLICATION or BYPASSRLS. The roles take their rights from per-concern group roles (`tbs_*`).
  A service holds its own role's password and no other (T-712). One box serves one site, and which study a person may
  see is decided by the console and the orchestrator, not by the database.
- **No row-level security policies in 1.0.** `row_security` is on (PostgreSQL's default) and no table has a policy.
- **R2.** Row-level security policies on the study-scoped tables, so that a role sees only the rows of the studies
  it serves, whatever the application asks.

## Who reaches the server, and how (`deploy/docker/pg_hba.conf`)

- The access file is the repository's. Compose mounts it read-only and names it with `hba_file` on every start, so a
  box made before this change takes it too. No line says `trust`.
- **The socket** lives in the db container's tmpfs, mode 0770, owner `postgres`. Only a process inside that container
  reaches it: the host's tools through `docker exec db …` (backup, update, secrets, doctor). Authentication is `peer`;
  the map (`deploy/docker/pg_ident.conf`) lets the container's own user (`postgres`, uid 999) name any role, and
  nothing else.
- **TCP** (the services, the FHIR store, the backup container): `hostssl` with `scram-sha-256` only. A client that
  does not use TLS is refused.
- **TLS.** Each start makes a new self-signed key and certificate in the db's `/tmp` (a tmpfs: outside the database
  volume, so never in a backup; memory, unless the host swaps it out; mode 0600). Clients use libpq's and pgjdbc's default `sslmode=prefer`: the traffic on the internal bridge
  is encrypted, the server's certificate is not checked. The internal docker network stays the trust boundary for
  the server's identity; a site CA and `verify-full` are an R2 item if the pentest asks for them.
- The cluster's superuser is `hapi`, made by the image's first start. The host's tools use it over the socket; the
  update's copy of the FHIR store's database also uses it over TCP (`TB_HAPI_DB_URL` in `tools/trialbox/update.py`),
  with TLS and its password like every TCP client. The FHIR store itself connects as `tb_fhir_store`, the owner of
  database `hapi` only.

## What is recorded

- **Connections.** `log_connections` and `log_disconnections` are on: one line per connection and per disconnection
  (role, database, client address), in the db container's log, kept with the other logs.
- **Statements.** Not logged (`log_statement=none`; T-209c keeps a failed statement's text and values out of the
  log). What was read and changed is recorded by the application's audit chain (the audit-writer).
- **pgaudit** is not in the db image (its extensions are pgvector and PGroonga, D-204), so it is not enabled. Adding it
  is an image change with its own release gates.

## Backups and WAL archiving

`trialbox backup-install` turns WAL archiving on (`setup_archiving` in `tools/trialbox/backup_schedule.py`) unless the
site wrote `TB_PG_ARCHIVE_MODE=off`: when the db image carries pgBackRest and its repository is off the box
(`TB_PGBACKREST_REPO`, else the first off-box backup target), it makes the cipher pass once, creates the stanza,
switches `archive_mode` on and keeps it on only if `pgbackrest check` archives a segment. A box with no off-box target
(the audited one) keeps archiving off, and says so; it then has no point-in-time restore, and its recovery point is
that of the last nightly backup, if one has run. This change does not alter that. Turning archiving on as part of the
backup key ceremony, and a red `backup-status` while it is off, belong to the P-01 work. Never turn `archive_mode` on
without a working `archive_command`: PostgreSQL would keep every WAL file until the disk is full.
