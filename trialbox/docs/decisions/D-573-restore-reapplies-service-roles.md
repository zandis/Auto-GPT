# D-573 A restore puts every store back under its service's role, functions included

- **Task:** RESTORE-ROLES (given to lane D by the integrator on 2026-11-12; read by T-213b)
- **PR:** this branch (`agent/RESTORE-roles-functions`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-378 (one PostgreSQL role per service; `deploy/docker/db-init/30-service-roles.sh` and its
  platform copy; a schema and what is in it belong to the group `tbs_<schema>`; a service works as that group),
  D-274 (the restore: each database is emptied and restored with `pg_restore --no-owner`), D-394 (the audit journal's
  roles, in the same script)
- **Read by:** T-213b (the restore drill on a rented workstation and a Spark)

## Context

`pg_restore --no-owner` makes every restored schema, table, view, sequence and function the property of the role
that restores: `trialbox`. A service signs in as its own role and works as the schema's group, which then owns
nothing: it cannot alter its tables or run a migration, and where a later migration replaces a function it is
refused. Until now the runbook told the operator to run the roles script by hand after a restore. The script
itself moved tables, views and sequences to their groups, and not functions.

## Decision

1. **The roles script moves functions, procedures and aggregates of a store schema to its group**, as it moves
   tables. What an extension owns is left to the extension. Both copies of the script (the box's and the
   platform's) stay identical.
2. **The restore runs the roles script itself, after the trial database is restored, its rows are checked, the
   jobs that were running at the backup are failed and the opt-outs recorded after it are put back** (those are
   rows, written as `trialbox`; a failure of the roles step leaves neither undone).
   The command is the setting `TB_DB_ROLES_CMD` (on a box:
   `docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh`).
   A command that fails stops the restore with its output: the databases are restored, no directory was touched
   yet, and the message says not to start the services and to run the restore again.
3. **With no command set, the restore says so.** In PRODUCTION and VALIDATION the restore is then not complete:
   its result says `service_roles: not_configured`, the command prints the line to run, and the exit code is 4, as
   for the other "not complete" cases. In DEV and TEST it is a line in the result only.
4. **The restore's audit event names the outcome** (`service_roles`), so the record of a restore says whether the
   stores went back to their roles.
5. **The restore drill proves it**: after the restore every service role opens each store on its list as the
   store's group and may alter a table there, and reaches no store off its list.

## Consequences

- The hand step becomes a setting. **Nothing on a box sets `TB_DB_ROLES_CMD` yet** (the installer does not write
  it, as it writes neither of the restore's other commands): the runbook's restore step names it, and a PRODUCTION
  restore without it ends "not complete" with the line to run. Open: a default on a box.
- The platform's restore job passes `not-needed`: its services sign in as `trialbox`.
- Run from the host without the `TB_DB_PW_*` variables, the script clears the service roles' passwords (D-378's
  rule for an empty variable); the runbook says to run it through the `db` container.
- Types, domains, collations and text search objects in a store schema are not moved; the product makes none.
- One new setting, `TB_DB_ROLES_CMD`, declared. No limit, no new store, no new audit event (one more field of
  `backup.restored`).
