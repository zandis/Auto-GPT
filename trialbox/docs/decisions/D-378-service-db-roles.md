# D-378 One PostgreSQL role per service

- **Task:** T-212c, boundary part c (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-212c-db-roles`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-037 (one PostgreSQL role for every service)
- **Builds on:** D-126 (one trial database, one schema per store), D-204 (db image, db-init), D-360 (compose limits)

## Context

Every service signed in to `trialbox_wf` as `trialbox`, the owner of the database, with `CREATEDB`. So the mail
gateway, the model gateway, the lake, the compiler and the adapter could read and change `auth` (sessions, password
hashes), `edc` (signatures) and the pseudonym map (CR-037).

## Decision

1. **A role per service.** `deploy/docker/db-init/30-service-roles.sh` makes `tb_lake`, `tb_criteria_compiler`,
   `tb_adapter`, `tb_orchestrator`, `tb_mail_gateway`, `tb_gateway` and `tb_console`: LOGIN, no superuser,
   `CREATEDB`, `CREATEROLE`, replication or `BYPASSRLS`. Its list says which schemas each one reaches; that list is
   the only place for it.
2. **A group per schema.** Each store schema is owned by a NOLOGIN group `tbs_<schema>`. A service role is a member
   of the groups in its list and of no other. `tb_common.db` sets the role to the group when it opens such a schema,
   so a migration's tables belong to the group, whichever service starts first.
3. **`trialbox` stays the admin of the host tools** (backup, update, doctor). It keeps the database, is a member of
   every group and every service role, and loses `CREATEDB`.
4. **Passwords from the environment.** `TB_DB_PW_<SERVICE>` in `deploy/.env`; `deploy/install.sh` makes a random one
   for each. Compose gives each service its own `TB_DB_URL`. Unset, a password falls back to the workflow password
   (a dev or test stack only).
5. **The FHIR database is closed.** No role but its owner connects to `hapi`; only `trialbox` and the service roles
   connect to `trialbox_wf`.
6. **Existing boxes.** The script is idempotent. `install.sh` runs it on every install and upgrade, after the db is
   up and before the services start. It moves schemas and tables an older release made as `trialbox` to the groups.
7. **Who reaches what.** The list is the schemas each service's code opens, taken from its imports. The core
   services (orchestrator, console) reach most stores; the edge services reach only their own and the flags (`app`).
   No edge service reaches `auth`, `edc`, `pidmap`, `sae`, `team` or `breakglass`.

## Consequences

- `tests/unit/test_db_roles.py` runs the real script on a throwaway cluster, twice, and checks each role: its own
  schemas read, every other refused, no database made.
- A restore with `--no-owner` (backup, update rollback) makes its tables owned by `trialbox`; the services reach
  them again once the role script runs (`install.sh`, or `docker compose exec -T db
  /docker-entrypoint-initdb.d/30-service-roles.sh`). Wiring that into the restore paths is left to a later card.
- The platform (Kubernetes) form gets the script, but its services still sign in as `trialbox` until it has a
  secret per service.
- `tools/spark_e2e.sh` makes its scratch database as the superuser.

## Dropped (D-311)

No security sign-off or owner review step.
