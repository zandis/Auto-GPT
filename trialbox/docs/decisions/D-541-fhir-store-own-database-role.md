# D-541 The FHIR store has a database role of its own

- **Task:** NEW-TRUST-1 (the owner's ruling of 2026-11-12 on a finding left open by the review of T-712, #308;
  `docs/plan/33-plan-v7.md` section 5, wave 1, lane C)
- **PR:** this branch (`agent/NEW-TRUST-1-fhir-store-role`), stacked on T-718 (#337): it uses that card's
  `ComposeBox.set_roles` (the update runs the role script)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-378 (one role per service), D-481 (a service holds its own role's password only), D-121 (one
  PostgreSQL server, two databases)

## The problem

The database server's first user is `hapi` (`POSTGRES_USER`), which makes it the cluster's superuser. The FHIR
store signed in as that user with `POSTGRES_PASSWORD`. A superuser reads and changes every database of the
server, the trial database `trialbox_wf` included, and can give itself any role: no rule of D-378 or D-481 held
against the one container that runs a third-party server and takes hospital data in. `ADMIN_HOLDERS` listed it as
an allowed holder.

## The decision

1. **The role.** `tb_fhir_store`: LOGIN, not a superuser, no CREATEDB, CREATEROLE, REPLICATION or BYPASSRLS, a
   member of no other role. It owns the database `hapi`, its schema `public` and what is in it. It has no right
   to connect to `trialbox_wf` (only `trialbox` and the service roles do), and no service role connects to
   `hapi`. The cluster keeps one superuser, the server's own, which no service holds.
2. **Its password** is `TB_DB_PW_FHIR_STORE` in `deploy/.env`. There is no fallback to an administrator's
   password in the compose file: without it the role has no password and the FHIR store does not start. The role
   script reads it with psql's `\getenv`, from the environment, not as a `-v name=value` argument (the review of
   T-712 left the other roles' passwords on the command line: its own card).
3. **A new box**: `install.sh` makes the password with the others; the role script makes the role before HAPI
   first starts, so HAPI makes its tables as their owner.
4. **An installed box, updated in place** (`trialbox update`, or `install.sh` run again). In this order:
   - the password is written to `deploy/.env` (0600) if it is not there;
   - the role script runs. It makes the role, sets the password, gives it the database, and inside `hapi` moves
     what HAPI made as the superuser: tables with their indexes, sequences, views, the schema, large objects. The
     running database container was started before the variable existed, so the update hands it over by name for
     that one command (`exec -e TB_DB_PW_FHIR_STORE`; the value is in the environment, never an argument);
   - the services start; the FHIR store signs in as its own role.
   Every step can be repeated: a run that stops after the file and before the script, or in the script, is run
   again with the same password and moves what is left. **The window:** an update stops the services first, so
   the FHIR store is down for the update as before and for nothing longer. With `install.sh` on a running box,
   the old FHIR store container keeps working as the superuser until it is recreated with the new sign-in (a
   superuser may use tables it no longer owns); it cannot connect only if the role script failed, and then
   `docker compose logs fhir-store` says "password authentication failed for user tb_fhir_store".
5. **After a restore** the dump is loaded by the superuser, so the tables are the superuser's again: the role
   script is run after a restore (as D-378 already asks) and moves them.
6. `ADMIN_HOLDERS["POSTGRES_PASSWORD"]` is the database server alone. The unit test over every compose file set
   and `trialbox doctor` (`db_passwords`) fail when the FHIR store holds an administrator's password.

## What it does not do

- The Kubernetes form gives every pod the administrator's URL: it waits with the frozen server form.
- `trialbox secrets rotate --service db` does not rotate this role's password yet (it rotates two roles; the
  review of T-712 named that: its own card).
- A stack started by hand from an older `deploy/.env` (not through `install.sh` or `trialbox update`) has no
  `TB_DB_PW_FHIR_STORE`: add one and run the role script. `.env.example` carries a placeholder; `poc.sh` and
  `poc.ps1` replace it.
- The server's superuser is still named `hapi`. Renaming it would need a new volume.

## Dropped (D-311)

No sign-off or owner review step beyond the ruling that asked for the card.
