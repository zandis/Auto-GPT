# D-541 The FHIR store has a database role of its own

- **Task:** NEW-TRUST-1 (the owner's ruling of 2026-11-12 on a finding left open by the review of T-712, #308;
  `docs/plan/33-plan-v7.md` section 5, wave 1, lane C)
- **PR:** this branch (`agent/NEW-TRUST-1-fhir-store-role`), stacked on T-718 (#337): it uses that card's
  `ComposeBox.ensure_fhir_password` and lane D's `db-up` steps (the update runs the role script)
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
4. **An installed box, updated in place.** The steps are the new release's own, run from its tree by lane D's
   two commands (`tools/trialbox/prestart.py`; UPDATE-PRESTART and UPDATE-DBUP, D-624):
   - `pre-start`, step `FHIR store password`: the password is written to `deploy/.env` (0600) if it is not
     there, or is still the example file's (`ComposeBox.ensure_fhir_password`);
   - `db-up`, step `database`: the database container is put on this release's settings, so it holds the
     password in its own environment and mounts this release's role script;
   - `db-up`, step `service roles`: the role script runs in that container. Nothing is handed over on the
     command: psql reads the password from the container's environment (`\getenv`). It makes the role, sets
     the password, gives it the database, and inside `hapi` moves what HAPI made as the superuser: tables with
     their indexes, sequences, views, the schema `public`, and the large objects in committed batches of 1,000;
   - the services start; the FHIR store signs in as its own role.
   Every step can be repeated: a run that stops after the file and before the script, or in the script, is run
   again with the same password and moves what is left. **The window:** the database step recreates the
   database container, so the FHIR store loses its connections there and is recreated by the final start with
   the new sign-in (D-624 says the same of every service still running).
   **The first version** ran the script from the updater itself, on standard input and with the password handed
   over by name, because the running container was the previous release's. Its review found that the update
   which BRINGS this release is run by the release before it, whose steps knew none of this. Lane D's two
   commands are the answer; a box must be on a release that has `db-up` before it takes this one
   (`min_installed_version`, lane D's rule). A new box is not affected. No box is in the field.
5. **After a restore** the dump is loaded by the superuser, so the tables are the superuser's again: the role
   script is run after a restore (as D-378 already asks) and moves them.
6. `ADMIN_HOLDERS["POSTGRES_PASSWORD"]` is the database server alone. The unit test over every compose file set
   and `trialbox doctor` (`db_passwords`) fail when the FHIR store holds an administrator's password.

## What it does not do

- The Kubernetes form gives every pod the administrator's URL, and its FHIR store still signs in as the
  superuser: it waits with the frozen server form.
- `trialbox secrets rotate --service db` does not rotate this role's password yet, and still restarts the FHIR
  store when it rotates the superuser's (the review of T-712 named the rotation: its own card).
- A stack started by hand from an older `deploy/.env` (not through `install.sh` or `trialbox update`) has no
  `TB_DB_PW_FHIR_STORE`: add one and run the role script. `.env.example` carries a placeholder; `poc.sh` and
  `poc.ps1` replace it. A run of the script without the variable leaves a password that is set as it is.
- The update's one-off backup container still gets the superuser's URL for `hapi` (it dumps the database).
- `tb_fhir_store` can connect to `postgres` and `template1` (PostgreSQL's default for every role) and, as the
  owner, could drop its own database from there. It reaches no other data.
- As the owner of `hapi` the role may create the extensions the image marks trusted (`vector`, `pgroonga`).
  Whether PGroonga's command function reaches server files was not run (no such image here): to be checked on
  the image, and the trusted mark narrowed to `trialbox_wf` if it does (lane D's `db.Dockerfile`).
- Only what HAPI is known to make is moved: relations and large objects. A function, a type or a schema other
  than `public` made by the superuser would stay the superuser's.
- `trialbox doctor` reports the example password and a value equal to the superuser's, not a missing
  `TB_DB_PW_FHIR_STORE`.
- The support bundle's redaction of `TB_DB_PW_*` is OPS-002 (#324, lane D).
- The server's superuser is still named `hapi`. Renaming it would need a new volume.

## Dropped (D-311)

No sign-off or owner review step beyond the ruling that asked for the card.
